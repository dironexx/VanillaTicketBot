import asyncio
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, TypeVar

import discord
from discord import ui, app_commands
from discord.ext import commands, tasks

from config import Config
from database import DatabaseManager, MSK, get_msk_now
from design import AG, Colors

logger = logging.getLogger("VanillaBot.Tickets")

T = TypeVar("T")

SPEC_ROLE_NAMES = ("спек", "спектатор", "spectator", "наблюдатель", "спек тикеты", "тикет спек")


def _is_sqlite_busy(err: BaseException) -> bool:
    if not isinstance(err, sqlite3.OperationalError):
        return False
    msg = str(err).lower()
    return "locked" in msg or "busy" in msg


def _db_call(func: Callable[..., T], *args: Any, retries: int = 3, delay: float = 0.04, **kwargs: Any) -> T:
    """Синхронный вызов БД с коротким backoff при конкурентной блокировке SQLite WAL."""
    attempt = 0
    while True:
        try:
            return func(*args, **kwargs)
        except sqlite3.OperationalError as err:
            if not _is_sqlite_busy(err) or attempt >= retries:
                raise
            attempt += 1
            time.sleep(delay * attempt)


async def _async_db_call(func: Callable[..., T], *args: Any, retries: int = 3, delay: float = 0.04, **kwargs: Any) -> T:
    """Неблокирующий event loop вызов БД через to_thread с backoff при занятости SQLite WAL."""
    attempt = 0
    while True:
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except sqlite3.OperationalError as err:
            if not _is_sqlite_busy(err) or attempt >= retries:
                raise
            attempt += 1
            await asyncio.sleep(delay * attempt)


async def _safe_defer(interaction: discord.Interaction, *, ephemeral: bool = True) -> bool:
    """Безопасный defer интеракции с защитой от повторных кликов и таймаутов."""
    if interaction.response.is_done():
        return True
    try:
        await interaction.response.defer(ephemeral=ephemeral)
        return True
    except discord.InteractionResponded:
        return True
    except (discord.NotFound, discord.HTTPException) as err:
        logger.debug("Не удалось выполнить defer интеракции %s: %s", interaction.id, err)
        return False


async def _safe_send_interaction(
    interaction: discord.Interaction,
    content: Optional[str] = None,
    *,
    embed: Optional[discord.Embed] = None,
    ephemeral: bool = True,
) -> bool:
    """Универсальная отправка ответа на интеракцию (response -> followup) без Unhandled Exceptions."""
    kwargs: dict[str, Any] = {"ephemeral": ephemeral}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed

    if not interaction.response.is_done():
        try:
            await interaction.response.send_message(**kwargs)
            return True
        except discord.InteractionResponded:
            pass
        except (discord.NotFound, discord.HTTPException) as err:
            logger.debug("Ошибка первичного ответа на интеракцию %s: %s", interaction.id, err)
            return False

    try:
        await interaction.followup.send(**kwargs)
        return True
    except (discord.NotFound, discord.HTTPException) as err:
        logger.debug("Ошибка followup-ответа на интеракцию %s: %s", interaction.id, err)
        return False


async def _safe_send_modal(interaction: discord.Interaction, modal: ui.Modal) -> bool:
    """Безопасный вызов модального окна с защитой от double-click."""
    if interaction.response.is_done():
        return False
    try:
        await interaction.response.send_modal(modal)
        return True
    except (discord.InteractionResponded, discord.NotFound, discord.HTTPException) as err:
        logger.debug("Не удалось открыть модальное окно для интеракции %s: %s", interaction.id, err)
        return False


def get_spec_role(guild: Optional[discord.Guild], db: Optional[DatabaseManager] = None) -> Optional[discord.Role]:
    """Возвращает роль спека (наблюдателя тикетов): поиск по имени -> база данных -> Config"""
    if not guild:
        return None

    # 1. Поиск по имени среди существующих ролей
    for role in guild.roles:
        if role.name.strip().lower() in SPEC_ROLE_NAMES:
            return role

    # 2. По сохраненному ID в базе данных
    if db:
        try:
            saved = _db_call(db.get_setting, "spec_role_id")
        except sqlite3.Error as err:
            logger.warning("Ошибка чтения spec_role_id из БД: %s", err)
            saved = None
        if saved and saved.isdigit() and int(saved) != 0:
            r = guild.get_role(int(saved))
            if r:
                return r

    # 3. Config
    if Config.SPEC_ROLE_ID:
        r = guild.get_role(Config.SPEC_ROLE_ID)
        if r:
            return r

    return None


async def get_or_create_spec_role(guild: Optional[discord.Guild], db: Optional[DatabaseManager] = None) -> Optional[discord.Role]:
    """Находит или автоматически создает роль 'Спек' для доступа к тикетам"""
    if not guild:
        return None

    role = get_spec_role(guild, db)
    if role:
        if db:
            await _async_db_call(db.set_setting, "spec_role_id", str(role.id))
        Config.SPEC_ROLE_ID = role.id
        return role

    if guild.me and guild.me.guild_permissions.manage_roles:
        try:
            role = await guild.create_role(
                name="Спек",
                color=discord.Color.from_rgb(0, 180, 216),
                mentionable=False,
                reason="Создание роли спека для доступа к тикетам",
            )
            logger.info("Создана роль спека: '%s' (%s)", role.name, role.id)
            if db:
                await _async_db_call(db.set_setting, "spec_role_id", str(role.id))
            Config.SPEC_ROLE_ID = role.id
            return role
        except discord.Forbidden:
            logger.error("Недостаточно прав (Forbidden) для создания роли 'Спек'")
        except Exception as e:
            logger.error(f"Ошибка при создании роли 'Спек': {e}")

    return None


async def sync_spec_role_to_tickets(guild: Optional[discord.Guild], spec_role: Optional[discord.Role], db: DatabaseManager):
    """Синхронизирует права роли спека во всех активных тикетах и категории тикетов"""
    if not guild or not spec_role or not guild.me.guild_permissions.manage_channels:
        return

    # 1. Права на категории тикетов
    cat_id = Config.TICKETS_CATEGORY_ID
    try:
        saved_cat = await _async_db_call(db.get_setting, "tickets_category_id")
        if saved_cat and str(saved_cat).isdigit():
            cat_id = int(saved_cat)
    except Exception:
        pass
    if cat_id:
        category = guild.get_channel(cat_id)
        if category and isinstance(category, discord.CategoryChannel):
            try:
                current_ow = category.overwrites_for(spec_role)
                if current_ow.view_channel is not True:
                    await category.set_permissions(
                        spec_role,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        attach_files=True,
                        embed_links=True,
                        reason="Выдача доступа роли Спек к категории тикетов",
                    )
            except Exception as e:
                logger.error(f"Ошибка настройки категории тикетов для спека: {e}")

    # 2. Права во всех активных тикет-каналах
    active_tickets = await _async_db_call(db.get_all_active_tickets)
    
    # Ограничиваем конкурентность для избежания рейтов
    sem = asyncio.Semaphore(5)

    async def _set_perm(ch):
        async with sem:
            try:
                current_ow = ch.overwrites_for(spec_role)
                if current_ow.view_channel is not True or current_ow.send_messages is not True:
                    await ch.set_permissions(
                        spec_role,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        attach_files=True,
                        embed_links=True,
                        reason="Выдача доступа роли Спек к активному тикету",
                    )
            except Exception as e:
                logger.error(f"Ошибка настройки канала тикета {ch.name} для спека: {e}")

    tasks = []
    for row in active_tickets:
        ch_id = row[0]
        channel = guild.get_channel(ch_id)
        if channel and isinstance(channel, discord.TextChannel):
            tasks.append(_set_perm(channel))

    if tasks:
        await asyncio.gather(*tasks)


def get_ticket_ping_role_ids(db: DatabaseManager) -> list[int]:
    """Роли, которые пингуются в тикетах.

    Приоритет: настройка в БД (ключ есть, может быть пустой) -> Config.TICKET_PING_ROLE_ID.
    Пустая строка в БД означает «не пинговать никого» (явно очищено командой).
    """
    try:
        saved = db.get_setting("ticket_ping_role_ids")
    except Exception:
        saved = None
    if saved is not None:
        return [int(x) for x in str(saved).split(",") if x.strip().isdigit()]
    if getattr(Config, "TICKET_PING_ROLE_ID", 0):
        return [int(Config.TICKET_PING_ROLE_ID)]
    return []


def is_mod_or_admin(interaction_or_ctx) -> bool:
    user = (
        interaction_or_ctx.user
        if hasattr(interaction_or_ctx, "user")
        else interaction_or_ctx.author
    )
    if not isinstance(user, discord.Member):
        return False
    guild = interaction_or_ctx.guild
    if user.guild_permissions.administrator or (guild and user.id == guild.owner_id):
        return True
    user_role_ids = {r.id for r in user.roles}
    if any(mod_role in user_role_ids for mod_role in Config.MOD_ROLE_IDS):
        return True
    if Config.SPEC_ROLE_ID and Config.SPEC_ROLE_ID in user_role_ids:
        return True
    for r in user.roles:
        if r.name.strip().lower() in SPEC_ROLE_NAMES:
            return True
    return False


def can_manage_ticket(ctx: commands.Context, db: DatabaseManager) -> bool:
    """Может ли пользователь управлять данным тикетом (модератор или автор тикета)"""
    if is_mod_or_admin(ctx):
        return True
    ticket_author_id = db.get_ticket_user_id(ctx.channel.id)
    return ticket_author_id is not None and ctx.author.id == ticket_author_id


async def save_transcript_to_file(channel: discord.TextChannel) -> str:
    file_time = get_msk_now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(Config.TRANSCRIPTS_DIR, f"{channel.name}_{file_time}.txt")

    lines = [
        "==================================================",
        f" ТРАНСКРИПТ ОБРАЩЕНИЯ: #{channel.name}",
        f" Сервер: {channel.guild.name}",
        f" Дата закрытия: {get_msk_now().strftime('%d.%m.%Y %H:%M:%S')} (МСК)",
        "==================================================\n",
    ]

    async for msg in channel.history(limit=None, oldest_first=True):
        msg_time = msg.created_at.astimezone(MSK).strftime("%d.%m %H:%M:%S")
        if msg.author.bot:
            if msg.embeds:
                for emb in msg.embeds:
                    title = f" [{emb.title}]" if emb.title else ""
                    desc = emb.description or ""
                    lines.append(f"[{msg_time}] [СИСТЕМА/БОТ]{title}: {desc}")
            elif msg.clean_content:
                lines.append(f"[{msg_time}] [БОТ] {msg.author.name}: {msg.clean_content}")
            continue

        content = msg.clean_content or ""
        if msg.attachments:
            att_urls = " ".join([a.url for a in msg.attachments])
            content = f"{content} [Вложения: {att_urls}]".strip()

        if content:
            lines.append(f"[{msg_time}] {msg.author.name} ({msg.author.id}): {content}")

    if len(lines) <= 5:
        lines.append("[В диалоге не было сообщений]")

    payload = "\n".join(lines)

    def _write_transcript() -> None:
        os.makedirs(Config.TRANSCRIPTS_DIR, exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(payload)

    await asyncio.to_thread(_write_transcript)
    return filename


# --- КАРТОЧКА НАРУШИТЕЛЯ (SUSPECT SUMMARY ДЛЯ ПЕРСОНАЛА) ---
def build_suspect_embed(bot: commands.Bot, db: DatabaseManager, suspect_nick: str) -> discord.Embed:
    summary = _db_call(db.get_suspect_summary, suspect_nick)
    player = summary["player_name"]
    alts = summary.get("alts", [])
    ips = summary.get("ips", [])
    alerts = summary.get("alerts", [])

    bridge_cog = bot.get_cog("Мост Minecraft")
    is_online = False
    if bridge_cog and hasattr(bridge_cog, "mc_players"):
        is_online = any(p.lower() == player.lower() for p in bridge_cog.mc_players)

    status_str = "В сети" if is_online else "Оффлайн"
    embed = AG.embed(
        title=f"Досье игрока • {player}",
        footer="Vanilla Land • Безопасность",
    )
    embed.add_field(name="Статус", value=status_str, inline=True)

    if ips:
        masked_ips = [f"`{ip[:ip.rfind('.')] + '.***' if '.' in ip else ip}`" for ip in ips[:3]]
        embed.add_field(name="Известные IP", value=", ".join(masked_ips), inline=True)
    else:
        embed.add_field(name="Известные IP", value="*Нет записей*", inline=True)

    if alts:
        alt_names = [f"• `{a['player_name']}` ({a['last_seen']})" for a in alts[:6]]
        embed.add_field(name=f"Обнаруженные твинки ({len(alts)})", value="\n".join(alt_names), inline=False)
    else:
        embed.add_field(name="Связанные аккаунты", value="*Твинков по IP не обнаружено*", inline=False)

    if alerts:
        alert_lines = [f"• Забаненный твинк `{al['banned_nick']}`: {al['reason']}" for al in alerts[:3]]
        embed.add_field(name="Алерты безопасности", value="\n".join(alert_lines), inline=False)

    try:
        from cogs.bridge_views import get_skin_avatar_url

        avatar_url = get_skin_avatar_url(player, None, db)
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)
    except Exception:
        pass

    return embed


_CLOSING_CHANNELS: set[int] = set()


async def close_ticket_process(
    bot: commands.Bot,
    db: DatabaseManager,
    channel: discord.TextChannel,
    closed_by_name: str,
    reason: str = "Не указана",
):
    if channel.id in _CLOSING_CHANNELS:
        return
    _CLOSING_CHANNELS.add(channel.id)
    try:
        user_id = await _async_db_call(db.get_ticket_user_id, channel.id)

        saved_file: Optional[str] = None
        channel_already_deleted = False
        try:
            saved_file = await save_transcript_to_file(channel)
        except discord.NotFound:
            channel_already_deleted = True
            logger.info("Канал тикета %s (%s) уже удален до сохранения транскрипта.", channel.name, channel.id)
        except Exception as e:
            logger.error("Ошибка создания txt-транскрипта %s: %s", channel.name, e)

        file_exists = bool(saved_file and await asyncio.to_thread(os.path.exists, saved_file))

        if user_id:
            try:
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                if user:
                    guild_icon = channel.guild.icon.url if channel.guild and channel.guild.icon else None
                    closed_ts = int(time.time())
                    file_note = (
                        "Текстовый лог переписки (`.txt`) прикреплён к этому сообщению."
                        if file_exists and saved_file
                        else "В этом обращении не было текстовых сообщений для архива."
                    )
                    embed = discord.Embed(
                        title=f"Обращение закрыто • #{channel.name}",
                        description=(
                            f"Сотрудник **{closed_by_name}** завершил рассмотрение вашего обращения.\n\n"
                            f"{file_note}"
                        ),
                        color=Colors.GREEN,
                        timestamp=datetime.now(timezone.utc),
                    )
                    if guild_icon:
                        embed.set_author(name="Vanilla Land • Служба поддержки", icon_url=guild_icon)
                        embed.set_thumbnail(url=guild_icon)
                    else:
                        embed.set_author(name="Vanilla Land • Служба поддержки")
                    embed.add_field(name="Обращение", value=f"`#{channel.name}`", inline=True)
                    embed.add_field(name="Закрыл", value=f"**{closed_by_name}**", inline=True)
                    embed.add_field(name="Закрыто", value=f"<t:{closed_ts}:f>", inline=True)
                    embed.add_field(name="Причина закрытия", value=f"```{reason}```", inline=False)
                    embed.set_footer(text="Vanilla Land • Если вопрос остался, создайте новое обращение.")
                    if file_exists and saved_file:
                        await user.send(embed=embed, file=discord.File(saved_file))
                    else:
                        await user.send(embed=embed)
            except (discord.Forbidden, discord.NotFound):
                logger.info("Не удалось отправить транскрипт в ЛС пользователю %s (закрыты ЛС или покинул сервер).", user_id)
            except Exception as e:
                logger.warning("Ошибка отправки ЛС %s: %s", user_id, e)

        # Отправка транскрипта в канал логов (приоритет: ticket_log_channel_id -> log_channel_id -> Config.LOG_CHANNEL_ID)
        log_ch = None
        for key_name in ("ticket_log_channel_id", "log_channel_id"):
            saved_log_id = await _async_db_call(db.get_setting, key_name)
            if saved_log_id and str(saved_log_id).isdigit():
                cand = bot.get_channel(int(saved_log_id))
                if isinstance(cand, discord.TextChannel):
                    log_ch = cand
                    break
        if not log_ch and Config.LOG_CHANNEL_ID:
            cand = bot.get_channel(Config.LOG_CHANNEL_ID)
            if isinstance(cand, discord.TextChannel):
                log_ch = cand

        if isinstance(log_ch, discord.TextChannel):
            user_display = f"<@{user_id}> (`{user_id}`)" if user_id else "*Неизвестен*"
            embed_log = discord.Embed(
                title=f"Архив обращения • #{channel.name}",
                color=Colors.INDIGO,
                timestamp=datetime.now(timezone.utc),
            )
            embed_log.add_field(name="Автор", value=user_display, inline=True)
            embed_log.add_field(name="Закрыл", value=f"**{closed_by_name}**", inline=True)
            embed_log.add_field(name="Причина", value=reason, inline=False)
            embed_log.set_footer(text="Vanilla Land • Архив тикетов")
            try:
                if file_exists and saved_file:
                    await log_ch.send(embed=embed_log, file=discord.File(saved_file))
                else:
                    await log_ch.send(embed=embed_log)
            except Exception as log_err:
                logger.warning("Не удалось отправить транскрипт в лог-канал: %s", log_err)

        # Сначала удаляем канал из Discord, и только после подтверждения удаления очищаем БД
        deleted = channel_already_deleted
        if not deleted:
            try:
                await channel.delete(reason=f"Тикет закрыт: {closed_by_name} ({reason})")
                deleted = True
            except discord.NotFound:
                deleted = True
            except discord.Forbidden:
                logger.error("Нет прав (Forbidden) на удаление канала тикета %s", channel.id)
            except Exception as e:
                logger.error("Ошибка удаления тикета %s: %s", channel.id, e)

        if deleted:
            await _async_db_call(db.close_ticket, channel.id, closed_by_name, reason, saved_file)
    finally:
        _CLOSING_CHANNELS.discard(channel.id)


class CloseReasonModal(ui.Modal, title="Закрытие обращения"):
    reason_input = ui.TextInput(
        label="Причина закрытия",
        placeholder="Например: Вопрос решен / Помощь оказана",
        default="Вопрос решен",
        max_length=150,
        required=False,
    )

    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        reason = (self.reason_input.value or "").strip() or "Вопрос решен"
        if not isinstance(interaction.channel, discord.TextChannel):
            await _safe_send_interaction(interaction, "Канал обращения не найден.", ephemeral=True)
            return
        if interaction.channel.id in _CLOSING_CHANNELS:
            await _safe_send_interaction(interaction, "Обращение уже закрывается.", ephemeral=True)
            return

        await _safe_send_interaction(interaction, "Закрываем обращение и сохраняем лог переписки...", ephemeral=True)
        await close_ticket_process(interaction.client, self.db, interaction.channel, interaction.user.name, reason)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error("Ошибка в модальном окне CloseReasonModal: %s", error, exc_info=error)
        await _safe_send_interaction(interaction, "Не удалось обработать закрытие обращения.", ephemeral=True)


class SuspectCheckModal(ui.Modal, title="Проверка игрока"):
    nick_input = ui.TextInput(
        label="Никнейм игрока",
        placeholder="Введите никнейм для проверки...",
        max_length=32,
        required=True,
    )

    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        if not is_mod_or_admin(interaction):
            await _safe_send_interaction(interaction, "Эта функция доступна только персоналу.", ephemeral=True)
            return
        nick = (self.nick_input.value or "").strip()
        if not nick:
            await _safe_send_interaction(interaction, "Укажите никнейм игрока.", ephemeral=True)
            return

        await _safe_defer(interaction, ephemeral=True)
        embed = build_suspect_embed(interaction.client, self.db, nick)
        await _safe_send_interaction(interaction, embed=embed, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error("Ошибка в модальном окне SuspectCheckModal: %s", error, exc_info=error)
        await _safe_send_interaction(interaction, "Не удалось сформировать досье игрока.", ephemeral=True)


class InsideTicketView(ui.View):
    def __init__(self, db: DatabaseManager):
        super().__init__(timeout=None)
        self.db = db

    @ui.button(label="Закрыть обращение", style=discord.ButtonStyle.danger, custom_id="persistent_close_btn")
    async def request_close(self, interaction: discord.Interaction, button: ui.Button):
        if isinstance(interaction.channel, discord.TextChannel) and interaction.channel.id in _CLOSING_CHANNELS:
            await _safe_send_interaction(interaction, "Обращение уже закрывается.", ephemeral=True)
            return
        opened = await _safe_send_modal(interaction, CloseReasonModal(self.db))
        if not opened:
            await _safe_send_interaction(interaction, "Не удалось открыть форму закрытия. Попробуйте снова.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: ui.Item[Any]) -> None:
        logger.error("Ошибка в InsideTicketView (%s): %s", getattr(item, "custom_id", item), error, exc_info=error)
        await _safe_send_interaction(interaction, "Произошла ошибка при обработке кнопки.", ephemeral=True)


_CREATING_TICKETS: set[int] = set()
_TICKET_CREATE_LOCK = asyncio.Lock()


TICKET_TOPICS: dict[str, dict[str, Any]] = {
    "report": {
        "label": "Жалоба на игрока",
        "desc": "Нарушение правил, гриферство, читы или оскорбления",
        "hints": [
            "Ваш никнейм и никнейм нарушителя",
            "Краткое описание ситуации и примерное время",
            "Скриншоты, видео или координаты (если есть)",
        ],
    },
    "bug": {
        "label": "Баг / Проблема",
        "desc": "Техническая ошибка, пропажа вещей или сбой сервера",
        "hints": [
            "Ваш никнейм на сервере",
            "Что произошло и как воспроизвести ошибку",
            "Координаты, время и скриншоты",
        ],
    },
    "donate": {
        "label": "Донат / Магазин",
        "desc": "Вопросы по покупкам, привилегиям и оплате",
        "hints": [
            "Ваш никнейм на сервере",
            "Что именно и когда вы приобретали",
            "Чек или номер заказа (если есть)",
        ],
    },
    "unban": {
        "label": "Заявка на разбан",
        "desc": "Обжалование бана или мута",
        "hints": [
            "Ваш никнейм на сервере",
            "Кто и за что выдал наказание",
            "Почему считаете нужным пересмотреть решение",
        ],
    },
    "other": {
        "label": "Другое",
        "desc": "Общий вопрос или предложение администрации",
        "hints": [
            "Ваш никнейм на сервере",
            "Подробное описание вопроса или предложения",
            "Скриншоты или ссылки (если требуются)",
        ],
    },
}


async def create_ticket_channel(
    guild: discord.Guild,
    user: discord.Member,
    db: DatabaseManager,
    fallback_channel: Optional[discord.TextChannel] = None,
    topic_key: str = "other",
) -> tuple[Optional[discord.TextChannel], str]:
    if user.id in _CREATING_TICKETS:
        return None, "Ваше обращение уже создается, пожалуйста подождите пару секунд..."
    _CREATING_TICKETS.add(user.id)
    try:
        # Проверка на черный список тикетов
        bl_reason = await _async_db_call(db.is_ticket_blacklisted, user.id)
        if bl_reason is not None:
            reason_text = bl_reason or "Не указана"
            return None, f"Вам заблокирован доступ к созданию обращений.\n**Причина:** {reason_text}"

        if await _async_db_call(db.user_has_open_ticket, user.id):
            # Проверяем, не был ли канал тикета удалён вручную без /close
            active_rows = await _async_db_call(db.get_all_active_tickets)
            existing_channel: Optional[discord.TextChannel] = None
            stale_channel_ids: list[int] = []
            for row in active_rows:
                row_ch_id, row_user_id = row[0], row[1]
                if row_user_id != user.id:
                    continue
                ch = guild.get_channel(row_ch_id)
                if isinstance(ch, discord.TextChannel):
                    existing_channel = ch
                else:
                    stale_channel_ids.append(row_ch_id)

            for stale_id in stale_channel_ids:
                await _async_db_call(db.delete_ticket, stale_id)

            if existing_channel is not None:
                return None, f"У вас уже есть активное обращение: {existing_channel.mention}."

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, attach_files=True, read_message_history=True, manage_channels=True),
        }

        mentions_list = [user.mention]

        # Роли для пинга в тикете (настраиваются !ticket_ping_role; фолбэк — Config)
        ping_roles: list[discord.Role] = []
        for role_id in get_ticket_ping_role_ids(db):
            role = guild.get_role(role_id)
            if not role or role in ping_roles:
                continue
            ping_roles.append(role)
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                read_message_history=True,
            )
            if role.mention not in mentions_list:
                mentions_list.append(role.mention)

        for role_id in Config.MOD_ROLE_IDS:
            role = guild.get_role(role_id)
            if role:
                # Исключаем роль СММ из пингов тикета
                if any(w in role.name.lower() for w in ("смм", "smm")):
                    continue
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
                # Если настроены отдельные роли пинга — не пингуем модерацию целиком
                if not ping_roles and role.mention not in mentions_list:
                    mentions_list.append(role.mention)

        # Выдача доступа роли спека к тикету
        spec_role = await get_or_create_spec_role(guild, db)
        if spec_role:
            overwrites[spec_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                read_message_history=True,
                embed_links=True,
            )

        target_category = None
        saved_cat_id = await _async_db_call(db.get_setting, "tickets_category_id")
        if saved_cat_id and str(saved_cat_id).isdigit():
            cand_cat = guild.get_channel(int(saved_cat_id))
            if isinstance(cand_cat, discord.CategoryChannel):
                target_category = cand_cat
        if not target_category and Config.TICKETS_CATEGORY_ID:
            target_category = guild.get_channel(Config.TICKETS_CATEGORY_ID)
        if not target_category and fallback_channel:
            target_category = fallback_channel.category

        # Проверяем лимит 50 каналов в категории
        if target_category and isinstance(target_category, discord.CategoryChannel) and len(target_category.channels) >= 50:
            target_category = None

        topic_meta = TICKET_TOPICS.get(topic_key, TICKET_TOPICS["other"])
        topic_label = topic_meta["label"]
        hints_block = "\n".join(f"• {h}" for h in topic_meta["hints"])

        async with _TICKET_CREATE_LOCK:
            ticket_num = await _async_db_call(db.get_next_ticket_number)
            channel_name = f"тикет-{ticket_num:03d}"

            try:
                ticket_channel = await guild.create_text_channel(
                    name=channel_name,
                    category=target_category,
                    overwrites=overwrites,
                    topic=f"Тема: {topic_label} | Игрок: {user.name} ({user.id}) | Создан: {get_msk_now().strftime('%d.%m.%Y %H:%M')}",
                )
            except discord.HTTPException as err:
                logger.error("Не удалось создать канал тикета в Discord: %s (код %s)", err, getattr(err, "code", None))
                if getattr(err, "code", 0) == 30013:
                    return None, "Категория тикетов переполнена (максимум 50). Обратитесь к администратору."
                return None, "Ошибка Discord при создании канала тикета. Попробуйте через пару минут."

            await _async_db_call(db.save_ticket, ticket_channel.id, user.id, user.name, ticket_num)

        await _ensure_member_can_write_in_ticket(user, guild, db)

        embed = discord.Embed(
            title=f"Обращение #{ticket_num:03d} • {topic_label}",
            description=(
                f"Здравствуйте, {user.mention}. Ваше обращение принято в работу.\n\n"
                "Чтобы мы помогли быстрее, укажите:\n"
                f"{hints_block}"
            ),
            color=Colors.INDIGO,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name="Vanilla Land • Служба поддержки", icon_url=guild.icon.url if guild.icon else None)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Номер", value=f"`#{ticket_num:03d}`", inline=True)
        embed.add_field(name="Тема", value=topic_label, inline=True)
        embed.add_field(name="Автор", value=user.mention, inline=True)
        embed.set_footer(text="Vanilla Land • Поддержка | Управление: !add, !remove, !rename, !close")

        try:
            await ticket_channel.send(content=" ".join(mentions_list), embed=embed, view=InsideTicketView(db))
        except discord.HTTPException as err:
            logger.warning("Не удалось отправить стартовое сообщение в %s: %s", ticket_channel.id, err)

        return ticket_channel, f"Обращение создано: {ticket_channel.mention}"
    finally:
        _CREATING_TICKETS.discard(user.id)


class TicketTopicSelect(ui.Select):
    def __init__(self, db: DatabaseManager, fallback_channel: Optional[discord.TextChannel]):
        options = [
            discord.SelectOption(label=meta["label"], value=key, description=meta["desc"])
            for key, meta in TICKET_TOPICS.items()
        ]
        super().__init__(placeholder="Выберите тему обращения...", min_values=1, max_values=1, options=options)
        self.db = db
        self.fallback_channel = fallback_channel

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        if not guild or not isinstance(user, discord.Member):
            return await _safe_send_interaction(interaction, "Команда доступна только на сервере.", ephemeral=True)
        if not await _safe_defer(interaction, ephemeral=True):
            return
        topic_key = self.values[0]
        _ch, msg = await create_ticket_channel(guild, user, self.db, self.fallback_channel, topic_key=topic_key)
        try:
            await interaction.edit_original_response(content=msg, embed=None, view=None)
        except Exception:
            await _safe_send_interaction(interaction, msg, ephemeral=True)


class TicketTopicView(ui.View):
    def __init__(self, db: DatabaseManager, fallback_channel: Optional[discord.TextChannel]):
        super().__init__(timeout=120)
        self.add_item(TicketTopicSelect(db, fallback_channel))


class TicketPanel(ui.View):
    def __init__(self, db: DatabaseManager):
        super().__init__(timeout=None)
        self.db = db

    @ui.button(label="Создать обращение", style=discord.ButtonStyle.primary, custom_id="persistent_create_ticket_btn")
    async def create_ticket(self, interaction: discord.Interaction, button: ui.Button):
        user = interaction.user
        guild = interaction.guild

        if not guild or not isinstance(user, discord.Member):
            await _safe_send_interaction(interaction, "Команда доступна только на сервере.", ephemeral=True)
            return

        fallback = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
        view = TicketTopicView(self.db, fallback)
        await _safe_send_interaction(
            interaction,
            "Выберите тему обращения из списка ниже:",
            view=view,
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: ui.Item[Any]) -> None:
        logger.error("Ошибка в TicketPanel (%s): %s", getattr(item, "custom_id", item), error, exc_info=error)
        await _safe_send_interaction(interaction, "Не удалось обработать запрос. Попробуйте через пару секунд.", ephemeral=True)


class TicketAutoReplyModal(ui.Modal, title="Добавить автоответ в тикетах"):
    trigger_input = ui.TextInput(
        label="Когда отвечать (фразы через | )",
        placeholder="Например: как привязать аккаунт | не работает link | привязка",
        max_length=250,
        required=True,
    )
    response_input = ui.TextInput(
        label="Текст ответа бота",
        style=discord.TextStyle.paragraph,
        placeholder="Подробный ответ, который бот отправит игроку в тикет...",
        max_length=1500,
        required=True,
    )

    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        trigger = (self.trigger_input.value or "").strip()
        response = (self.response_input.value or "").strip()
        if not trigger or not response:
            return await _safe_send_interaction(interaction, "Укажите и триггер, и текст ответа.", ephemeral=True)
        rule_id = await _async_db_call(
            self.db.add_ticket_auto_reply, trigger, response, 0.68, interaction.user.name
        )
        embed = AG.success(
            f"Автоответ #{rule_id} добавлен",
            f"• **Когда отвечает:** `{trigger}`\n• **Ответ:**\n{response[:400]}",
        )
        await _safe_send_interaction(interaction, embed=embed, ephemeral=True)


def _paginate_transcript_text(text: str, page_size: int = 1600) -> list[str]:
    """Разбивает текст переписки тикета на аккуратные страницы по границам строк."""
    clean = (text or "").strip()
    if not clean:
        return ["В этом тикете нет сохранённых сообщений."]

    pages: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in clean.splitlines():
        safe_line = line.replace("```", "'''")
        while len(safe_line) > page_size:
            chunk = safe_line[:page_size]
            if current_lines:
                pages.append("\n".join(current_lines))
                current_lines = []
                current_len = 0
            pages.append(chunk)
            safe_line = safe_line[page_size:]

        line_len = len(safe_line) + 1
        if current_lines and current_len + line_len > page_size:
            pages.append("\n".join(current_lines))
            current_lines = [safe_line]
            current_len = line_len
        else:
            current_lines.append(safe_line)
            current_len += line_len

    if current_lines:
        pages.append("\n".join(current_lines))

    return pages or ["В этом тикете нет сохранённых сообщений."]


async def _load_ticket_transcript_pages(
    guild: Optional[discord.Guild],
    ticket: dict,
) -> tuple[list[str], Optional[str]]:
    """Загружает содержимое тикета (из .txt файла или живого канала) и возвращает (страницы, путь_к_файлу)."""
    t_path = ticket.get("transcript_file")
    if t_path and await asyncio.to_thread(os.path.isfile, t_path):
        if str(t_path).lower().endswith(".txt"):
            def _read_txt() -> str:
                with open(t_path, "r", encoding="utf-8", errors="replace") as f:
                    raw_lines = f.read().splitlines()
                # Пропускаем шапку ====...==== в начале .txt файла
                body_start = 0
                for idx, ln in enumerate(raw_lines[:10]):
                    if ln.startswith("====") and idx > 0:
                        body_start = idx + 1
                        break
                return "\n".join(raw_lines[body_start:]).strip()

            body = await asyncio.to_thread(_read_txt)
            return _paginate_transcript_text(body), t_path
        return [
            "Для этого старого обращения сохранён HTML-транскрипт.\n"
            "Нажмите кнопку «Скачать файл» ниже, чтобы открыть полную переписку."
        ], t_path

    # Если тикет открыт в Discord — читаем последние сообщения прямо из канала
    ch_id = ticket.get("dc_channel_id")
    if guild and ch_id:
        ch = guild.get_channel(int(ch_id))
        if isinstance(ch, discord.TextChannel):
            live_lines: list[str] = []
            try:
                msgs = [m async for m in ch.history(limit=30, oldest_first=False)]
                for msg in reversed(msgs):
                    msg_time = msg.created_at.astimezone(MSK).strftime("%d.%m %H:%M")
                    if msg.author.bot:
                        if msg.embeds and msg.embeds[0].title:
                            live_lines.append(f"[{msg_time}] [БОТ] {msg.embeds[0].title}")
                        continue
                    content = msg.clean_content or ""
                    if msg.attachments:
                        att_str = " ".join(a.filename for a in msg.attachments)
                        content = f"{content} [Файлы: {att_str}]".strip()
                    if content:
                        live_lines.append(f"[{msg_time}] {msg.author.name}: {content}")
                if live_lines:
                    return _paginate_transcript_text("\n".join(live_lines)), None
            except Exception as err:
                logger.debug("Не удалось прочитать сообщения канала %s: %s", ch_id, err)

    return ["Транскрипт не найден на диске (возможно, тикет был удалён без сохранения лога)."], None


class UserTicketSelect(ui.Select):
    def __init__(self, tickets: list[dict], selected_num: Optional[int] = None):
        options: list[discord.SelectOption] = []
        for t in tickets[:25]:
            t_num = int(t.get("ticket_num") or 0)
            is_open = t.get("status") == "open"
            status_label = "Открыт" if is_open else "Закрыт"
            created = str(t.get("created_at") or "?")[:16]
            reason = str(t.get("close_reason") or ("Активное обращение" if is_open else "Без причины")).strip()
            desc = f"{created} • {reason}"
            if len(desc) > 95:
                desc = desc[:92] + "..."
            options.append(
                discord.SelectOption(
                    label=f"Тикет #{t_num:03d} ({status_label})",
                    description=desc,
                    value=str(t_num) if t_num > 0 else f"ch:{t.get('dc_channel_id')}",
                    default=(selected_num is not None and t_num == selected_num),
                )
            )
        super().__init__(
            placeholder="Выберите тикет для просмотра содержимого...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, UserTicketsView):
            return
        val = self.values[0]
        chosen = None
        for t in view.tickets:
            t_num = int(t.get("ticket_num") or 0)
            key = str(t_num) if t_num > 0 else f"ch:{t.get('dc_channel_id')}"
            if key == val:
                chosen = t
                break
        if not chosen:
            return await interaction.response.send_message("Тикет не найден.", ephemeral=True)

        await interaction.response.defer()
        await view.select_ticket(chosen, interaction)


class UserTicketsView(ui.View):
    """Интерактивный просмотр всех тикетов пользователя и их содержимого."""

    def __init__(
        self,
        tickets: list[dict],
        target_label: str,
        target_id: Optional[int],
        guild: Optional[discord.Guild],
    ):
        super().__init__(timeout=300)
        self.tickets = tickets[:25]
        self.target_label = target_label
        self.target_id = target_id
        self.guild = guild
        self.selected_ticket: Optional[dict] = None
        self.pages: list[str] = []
        self.page_idx: int = 0
        self.transcript_path: Optional[str] = None
        self._rebuild_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not is_mod_or_admin(interaction):
            await interaction.response.send_message("Эта панель доступна только персоналу сервера.", ephemeral=True)
            return False
        return True

    def _rebuild_items(self):
        self.clear_items()
        sel_num = int(self.selected_ticket.get("ticket_num") or 0) if self.selected_ticket else None
        self.add_item(UserTicketSelect(self.tickets, selected_num=sel_num))

        if self.selected_ticket is not None:
            total_pages = max(1, len(self.pages))
            prev_btn = ui.Button(
                label="Назад",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page_idx <= 0),
                row=1,
            )
            page_btn = ui.Button(
                label=f"Стр. {self.page_idx + 1}/{total_pages}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
                row=1,
            )
            next_btn = ui.Button(
                label="Вперёд",
                style=discord.ButtonStyle.secondary,
                disabled=(self.page_idx >= total_pages - 1),
                row=1,
            )
            prev_btn.callback = self._on_prev
            next_btn.callback = self._on_next
            self.add_item(prev_btn)
            self.add_item(page_btn)
            self.add_item(next_btn)

            if self.transcript_path:
                dl_btn = ui.Button(
                    label="Скачать файл",
                    style=discord.ButtonStyle.primary,
                    row=1,
                )
                dl_btn.callback = self._on_download
                self.add_item(dl_btn)

    async def _on_prev(self, interaction: discord.Interaction):
        if self.page_idx > 0:
            self.page_idx -= 1
        self._rebuild_items()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_next(self, interaction: discord.Interaction):
        if self.page_idx < len(self.pages) - 1:
            self.page_idx += 1
        self._rebuild_items()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_download(self, interaction: discord.Interaction):
        if not self.transcript_path or not await asyncio.to_thread(os.path.isfile, self.transcript_path):
            return await interaction.response.send_message("Файл транскрипта не найден на сервере.", ephemeral=True)
        await interaction.response.send_message(
            content=f"Транскрипт тикета `#{int(self.selected_ticket.get('ticket_num') or 0):03d}`:",
            file=discord.File(self.transcript_path),
            ephemeral=True,
        )

    async def select_ticket(self, ticket: dict, interaction: discord.Interaction):
        self.selected_ticket = ticket
        self.pages, self.transcript_path = await _load_ticket_transcript_pages(self.guild, ticket)
        self.page_idx = 0
        self._rebuild_items()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    def build_embed(self) -> discord.Embed:
        if self.selected_ticket is None:
            lines = []
            for t in self.tickets[:15]:
                t_num = int(t.get("ticket_num") or 0)
                is_open = t.get("status") == "open"
                st = "Открыт" if is_open else "Закрыт"
                created = t.get("created_at") or "?"
                if is_open:
                    extra = f"<#{t['dc_channel_id']}>"
                else:
                    closed_by = t.get("closed_by") or "—"
                    reason = (t.get("close_reason") or "Без причины")[:60]
                    extra = f"Закрыл: **{closed_by}** • {reason}"
                lines.append(f"• **`#{t_num:03d}`** [`{st}`] — `{created}`\n  {extra}")

            if len(self.tickets) > 15:
                lines.append(f"\n*И ещё {len(self.tickets) - 15} тикетов доступны в списке ниже.*")

            id_part = f" (`{self.target_id}`)" if self.target_id else ""
            embed = AG.embed(
                title=f"Тикеты пользователя • {self.target_label}",
                description=(
                    f"Найдено обращений: **{len(self.tickets)}**{id_part}\n"
                    "Выберите тикет в выпадающем меню ниже, чтобы открыть его содержимое.\n\n"
                    + "\n".join(lines)
                ),
                color=Colors.BLUE,
                footer="Vanilla Land • Архив обращений",
            )
            return embed

        t = self.selected_ticket
        t_num = int(t.get("ticket_num") or 0)
        is_open = t.get("status") == "open"
        st_label = "Открыт" if is_open else "Закрыт"
        page_text = self.pages[self.page_idx] if self.pages else "Пусто"

        embed = AG.embed(
            title=f"Тикет #{t_num:03d} • {t.get('user_name') or self.target_label}",
            description=f"```txt\n{page_text}\n```",
            color=Colors.GREEN if is_open else Colors.DARK,
            footer=f"Vanilla Land • Страница {self.page_idx + 1}/{max(1, len(self.pages))}",
        )
        embed.add_field(name="Статус", value=f"`{st_label}`", inline=True)
        embed.add_field(name="Автор", value=f"<@{t['user_id']}> (`{t['user_id']}`)", inline=True)
        embed.add_field(name="Создан", value=f"`{t.get('created_at') or '—'}`", inline=True)
        if not is_open:
            embed.add_field(name="Закрыл", value=f"**{t.get('closed_by') or '—'}**", inline=True)
            embed.add_field(name="Закрыт", value=f"`{t.get('closed_at') or '—'}`", inline=True)
            embed.add_field(name="Причина", value=(t.get("close_reason") or "Не указана")[:250], inline=True)
        else:
            embed.add_field(name="Канал", value=f"<#{t['dc_channel_id']}>", inline=True)
        return embed


class TicketsCog(commands.Cog, name="Тикеты"):
    def __init__(self, bot: commands.Bot, db: DatabaseManager):
        self.bot = bot
        self.db = db
        self._non_ticket_cache: dict[int, float] = {}
        self._auto_reply_cooldowns: dict[tuple[int, int], float] = {}
        self.auto_close_task.start()
        self._init_spec_task: Optional[asyncio.Task[None]] = asyncio.create_task(self.init_spec_role_on_start())

    def cog_unload(self):
        self.auto_close_task.cancel()
        if self._init_spec_task and not self._init_spec_task.done():
            self._init_spec_task.cancel()

    async def init_spec_role_on_start(self):
        """Автоматическая инициализация роли спека и синхронизация тикетов при старте"""
        await self.bot.wait_until_ready()
        await asyncio.sleep(2)
        for guild in self.bot.guilds:
            try:
                # Синхронизируем счётчик тикетов с существующими каналами тикетов в Discord (тикет-NNN, ticket-NNN)
                max_found = 0
                for ch in guild.text_channels:
                    m = re.match(r"^(?:тикет|ticket)[-_]?0*(\d+)$", ch.name, re.IGNORECASE)
                    if m:
                        num = int(m.group(1))
                        if num > max_found:
                            max_found = num
                if max_found > 0:
                    await _async_db_call(self.db.ensure_ticket_counter_at_least, max_found)

                spec_role = await get_or_create_spec_role(guild, self.db)
                if spec_role:
                    await sync_spec_role_to_tickets(guild, spec_role, self.db)
            except Exception as e:
                logger.debug("Ошибка авто-инициализации в %s: %s", guild.name, e)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.channel, discord.TextChannel):
            return

        ch_id = message.channel.id
        now_mono = time.monotonic()
        cached_until = self._non_ticket_cache.get(ch_id)
        if cached_until is not None and now_mono < cached_until:
            return

        try:
            if await _async_db_call(self.db.is_ticket_channel, ch_id):
                self._non_ticket_cache.pop(ch_id, None)
                await _async_db_call(self.db.update_ticket_activity, ch_id)

                # Умный автоответ в тикетах для сообщений от игроков (не персонала и не команд)
                content = (message.content or "").strip()
                if content and not content.startswith(tuple(Config.COMMAND_PREFIXES)) and not is_mod_or_admin(message):
                    match = await _async_db_call(self.db.find_matching_auto_reply, content)
                    if match:
                        rule = match["rule"]
                        r_id = int(rule["id"])
                        cd_key = (ch_id, r_id)
                        if (now_mono - self._auto_reply_cooldowns.get(cd_key, 0.0)) >= 120.0:
                            self._auto_reply_cooldowns[cd_key] = now_mono
                            if len(self._auto_reply_cooldowns) > 1000:
                                self._auto_reply_cooldowns.clear()
                            pct = int(round(match["score"] * 100))
                            emb = discord.Embed(
                                title="Быстрая подсказка • Vanilla Land",
                                description=rule["response_text"],
                                color=Colors.INDIGO,
                            )
                            emb.set_footer(text=f"Автоответ #{r_id} (совпадение {pct}%) • Если вопрос не решён, дождитесь ответа персонала")
                            try:
                                await message.reply(embed=emb, mention_author=False)
                            except Exception as send_err:
                                logger.debug("Ticket auto-reply send failed in %s: %s", ch_id, send_err)
            else:
                if len(self._non_ticket_cache) >= 2048:
                    self._non_ticket_cache.clear()
                self._non_ticket_cache[ch_id] = now_mono + 60.0
        except sqlite3.Error as err:
            logger.warning("Ошибка SQLite при обновлении активности канала %s: %s", ch_id, err)

    @tasks.loop(hours=1)
    async def auto_close_task(self):
        try:
            tickets = await _async_db_call(self.db.get_all_active_tickets)
        except sqlite3.Error as err:
            logger.error("Ошибка чтения активных тикетов в auto_close_task: %s", err)
            return

        now = get_msk_now()
        timeout = timedelta(hours=Config.AUTO_CLOSE_HOURS)

        for row in tickets:
            ch_id, user_id, user_name, last_act_str, created = row
            try:
                channel = self.bot.get_channel(ch_id)
                if not isinstance(channel, discord.TextChannel):
                    await _async_db_call(self.db.delete_ticket, ch_id)
                    continue

                target_time_str = last_act_str or created
                if target_time_str:
                    last_act = datetime.strptime(target_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=MSK)
                    if now - last_act > timeout:
                        try:
                            await channel.send(f"Обращение закрывается из-за неактивности более {Config.AUTO_CLOSE_HOURS}ч.")
                        except discord.NotFound:
                            await _async_db_call(self.db.delete_ticket, ch_id)
                            continue
                        except discord.HTTPException as send_err:
                            logger.warning("Не удалось отправить предупреждение об авто-закрытии в %s: %s", ch_id, send_err)

                        await close_ticket_process(
                            self.bot,
                            self.db,
                            channel,
                            "Авто-закрытие",
                            f"Неактивность более {Config.AUTO_CLOSE_HOURS}ч",
                        )
            except Exception as e:
                logger.error("Ошибка авто-закрытия %s: %s", ch_id, e)

    @auto_close_task.before_loop
    async def before_auto_close_task(self):
        await self.bot.wait_until_ready()

    # --- СОЗДАНИЕ ТИКЕТА ---
    @commands.hybrid_command(
        name="ticket",
        aliases=["тикет", "обращение", "поддержка", "создать_тикет"],
        description="Создать новое обращение в службу поддержки",
    )
    async def ticket_cmd(self, ctx: commands.Context):
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.send("Команда доступна только на сервере.", ephemeral=True)

        if self.db.is_ticket_channel(ctx.channel.id):
            return await ctx.send("Вы уже находитесь внутри обращения.", ephemeral=True)

        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        fallback = ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
        ticket_channel, msg = await create_ticket_channel(ctx.guild, ctx.author, self.db, fallback)
        await ctx.send(msg, ephemeral=True)

    # --- ЗАКРЫТИЕ ТИКЕТА ---
    @commands.hybrid_command(name="close", aliases=["закрыть", "клоз"], description="Закрыть текущее обращение")
    @app_commands.describe(reason="Причина закрытия тикета")
    async def close_cmd(self, ctx: commands.Context, *, reason: Optional[str] = "Не указана"):
        if not await _async_db_call(self.db.is_ticket_channel, ctx.channel.id):
            return await ctx.send("Эта команда доступна только внутри активного тикета.", ephemeral=True, delete_after=5)

        if ctx.channel.id in _CLOSING_CHANNELS:
            return await ctx.send("Обращение уже закрывается.", ephemeral=True)

        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        actual_reason = reason or "Не указана"
        try:
            await ctx.send(f"Закрытие обращения сотрудником **{ctx.author.name}**...", ephemeral=bool(ctx.interaction))
        except discord.HTTPException:
            pass
        if isinstance(ctx.channel, discord.TextChannel):
            await close_ticket_process(self.bot, self.db, ctx.channel, ctx.author.name, actual_reason)

    # --- ДОБАВИТЬ УЧАСТНИКА В ТИКЕТ (МОЖЕТ И АВТОР ТИКЕТА) ---
    @commands.hybrid_command(name="add", aliases=["добавить"], description="Добавить пользователя в текущий тикет")
    @app_commands.describe(member="Пользователь для добавления")
    async def add_user_cmd(self, ctx: commands.Context, member: discord.Member):
        if not await _async_db_call(self.db.is_ticket_channel, ctx.channel.id):
            return await ctx.send("Команда доступна только внутри активного тикета.", ephemeral=True, delete_after=5)

        if not can_manage_ticket(ctx, self.db):
            return await ctx.send("Управлять участниками тикета может только его создатель или персонал.", ephemeral=True)

        if isinstance(ctx.channel, discord.TextChannel):
            try:
                await ctx.channel.set_permissions(member, view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
                await _ensure_member_can_write_in_ticket(member, ctx.guild, self.db)
                await ctx.send(f"Пользователь {member.mention} добавлен в обращение.")
            except discord.Forbidden:
                await ctx.send("Недостаточно прав для изменения доступа в этом канале.", ephemeral=True)
            except discord.HTTPException as err:
                logger.warning("Ошибка добавления участника в тикет %s: %s", ctx.channel.id, err)
                await ctx.send("Не удалось добавить пользователя в обращение.", ephemeral=True)

    # --- ИСКЛЮЧИТЬ УЧАСТНИКА ИЗ ТИКЕТА (МОЖЕТ И АВТОР ТИКЕТА) ---
    @commands.hybrid_command(name="remove", aliases=["удалить", "исключить"], description="Исключить пользователя из текущего тикета")
    @app_commands.describe(member="Пользователь для удаления")
    async def remove_user_cmd(self, ctx: commands.Context, member: discord.Member):
        if not await _async_db_call(self.db.is_ticket_channel, ctx.channel.id):
            return await ctx.send("Команда доступна только внутри активного тикета.", ephemeral=True, delete_after=5)

        if not can_manage_ticket(ctx, self.db):
            return await ctx.send("Управлять участниками тикета может только его создатель или персонал.", ephemeral=True)

        if ctx.guild and ctx.guild.me and member.id == ctx.guild.me.id:
            return await ctx.send("Нельзя исключить бота из обращения.", ephemeral=True)

        # Нельзя удалить создателя тикета
        creator_id = await _async_db_call(self.db.get_ticket_user_id, ctx.channel.id)
        if member.id == creator_id:
            return await ctx.send("Нельзя исключить автора тикета.", ephemeral=True)

        if isinstance(ctx.channel, discord.TextChannel):
            try:
                await ctx.channel.set_permissions(member, overwrite=None)
                await ctx.send(f"Пользователь {member.mention} исключен из обращения.")
            except discord.Forbidden:
                await ctx.send("Недостаточно прав для изменения доступа в этом канале.", ephemeral=True)
            except discord.HTTPException as err:
                logger.warning("Ошибка исключения участника из тикета %s: %s", ctx.channel.id, err)
                await ctx.send("Не удалось исключить пользователя из обращения.", ephemeral=True)

    # --- ПЕРЕИМЕНОВАНИЕ ТИКЕТА ---
    @commands.hybrid_command(name="rename", aliases=["переименовать"], description="Переименовать текущий тикет")
    @app_commands.describe(new_name="Новое название канала тикета")
    async def rename_ticket_cmd(self, ctx: commands.Context, *, new_name: str):
        if not self.db.is_ticket_channel(ctx.channel.id):
            return await ctx.send("Команда доступна только внутри активного тикета.", ephemeral=True, delete_after=5)

        if not can_manage_ticket(ctx, self.db):
            return await ctx.send("Переименовывать тикет может только его создатель или персонал.", ephemeral=True)

        clean_name = re.sub(r"[^a-zа-яё0-9\-_]", "-", new_name.strip().lower()).strip("-")[:32]
        if not clean_name:
            return await ctx.send("Укажите корректное название (буквы или цифры).", ephemeral=True)

        try:
            old_name = ctx.channel.name
            await ctx.channel.edit(name=clean_name)
            await ctx.send(f"Канал переименован: `#{old_name}` ➔ `#{clean_name}`")
        except Exception as e:
            await ctx.send(f"Ошибка переименования: {e}", ephemeral=True)

    # --- СПИСОК АКТИВНЫХ ТИКЕТОВ ---
    @commands.hybrid_command(name="history", aliases=["история"], description="Список всех активных обращений")
    async def history_cmd(self, ctx: commands.Context):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу.", ephemeral=True)

        tickets = self.db.get_all_active_tickets()
        embed = AG.embed(
            title="Активные обращения • Vanilla Land",
            footer=f"Всего открыто: {len(tickets)}",
        )

        if not tickets:
            embed.description = "В данный момент нет открытых обращений."
            return await ctx.send(embed=embed)

        lines = []
        for ch_id, _u_id, u_name, last_act, _created in tickets:
            channel = self.bot.get_channel(ch_id)
            ch_mention = channel.mention if channel else f"`#{ch_id}` (удален)"
            lines.append(f"• {ch_mention} — {u_name} | Посл. активность: `{last_act}`")

        embed.description = "\n".join(lines[:25])
        await ctx.send(embed=embed)

    # --- БЛОКИРОВКА СОЗДАНИЯ ТИКЕТОВ (TICKETBAN) ---
    @commands.hybrid_command(name="ticketban", aliases=["тикетбан", "чстикетов"], description="Запретить пользователю создавать тикеты")
    @app_commands.describe(target="Пользователь (@упоминание или ID)", reason="Причина блокировки")
    async def ticket_ban_cmd(self, ctx: commands.Context, target: discord.User, *, reason: Optional[str] = "Не указана"):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        actual_reason = reason or "Не указана"
        self.db.add_ticket_blacklist(target.id, actual_reason, ctx.author.name)

        embed = AG.mod_action(
            action="Блокировка тикетов",
            target_str=f"{target.mention} (`{target.id}`)",
            moderator_str=ctx.author.mention,
            reason=actual_reason,
            color=Colors.RED,
            icon=target.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # --- РАЗБЛОКИРОВКА СОЗДАНИЯ ТИКЕТОВ (TICKETUNBAN) ---
    @commands.hybrid_command(name="ticketunban", aliases=["тикетразбан"], description="Снять запрет на создание тикетов")
    @app_commands.describe(target="Пользователь (@упоминание или ID)")
    async def ticket_unban_cmd(self, ctx: commands.Context, target: discord.User):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        if not self.db.is_ticket_blacklisted(target.id):
            return await ctx.send(f"Пользователь {target.mention} не находится в черном списке тикетов.", ephemeral=True)

        self.db.remove_ticket_blacklist(target.id)

        embed = AG.mod_action(
            action="Разблокировка тикетов",
            target_str=f"{target.mention} (`{target.id}`)",
            moderator_str=ctx.author.mention,
            reason="Досрочная разблокировка доступа к тикетам",
            color=Colors.GREEN,
            icon=target.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # --- СОЗДАНИЕ ПАНЕЛИ (ТОЛЬКО ДЛЯ АДМИНА) ---
    @commands.command(name="ticket_panel", aliases=["панель_тикетов", "тикет_панель"])
    @commands.has_permissions(administrator=True)
    async def send_ticket_panel(self, ctx: commands.Context):
        if Config.PANEL_CHANNEL_ID and ctx.channel.id != Config.PANEL_CHANNEL_ID:
            return await ctx.send(f"Панель можно создать только в канале: <#{Config.PANEL_CHANNEL_ID}>", delete_after=5)

        guild_icon = ctx.guild.icon.url if ctx.guild and ctx.guild.icon else None
        embed = AG.embed(
            title="Служба поддержки • Vanilla Land",
            description=(
                "Возникли трудности или есть вопрос к администрации?\n"
                "Нажмите кнопку ниже, чтобы создать обращение."
            ),
            footer="Vanilla Land • Поддержка",
            footer_icon=guild_icon,
            thumbnail=guild_icon,
        )
        await ctx.send(embed=embed, view=TicketPanel(self.db))
        try:
            await ctx.message.delete()
        except Exception:
            pass

    # --- НАСТРОЙКА И СИНХРОНИЗАЦИЯ РОЛИ СПЕКА ---
    @commands.hybrid_command(
        name="spec_role",
        aliases=["роль_спека", "создать_спека", "sync_spec", "спек"],
        description="Настройка и синхронизация роли Спек (наблюдатель тикетов)",
    )
    @app_commands.describe(role="Опционально: роль для назначения спеком (если не указана — создаст или найдет автоматически)")
    @commands.has_permissions(administrator=True)
    async def spec_role_cmd(self, ctx: commands.Context, role: Optional[discord.Role] = None):
        if not ctx.guild:
            return await ctx.send("Команда доступна только на сервере.", ephemeral=True)

        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        if role:
            self.db.set_setting("spec_role_id", str(role.id))
            Config.SPEC_ROLE_ID = role.id
            spec_role = role
            action_desc = f"Назначена роль: {role.mention} `(ID: {role.id})`"
        else:
            spec_role = await get_or_create_spec_role(ctx.guild, self.db)
            if not spec_role:
                return await ctx.send("Не удалось найти или создать роль спека. Проверьте права бота (Управление ролями).", ephemeral=True)
            action_desc = f"Используется роль: {spec_role.mention} `(ID: {spec_role.id})`"

        await sync_spec_role_to_tickets(ctx.guild, spec_role, self.db)

        embed = discord.Embed(
            title="Роль Спека (Наблюдателя тикетов) • Vanilla Land",
            description=(
                f"{action_desc}\n\n"
                "Права на просмотр и ответы в тикетах успешно синхронизированы для категории и всех активных обращений."
            ),
            color=discord.Color.from_rgb(0, 180, 216),
        )
        embed.set_footer(text="Vanilla Land • Поддержка")
        await ctx.send(embed=embed, ephemeral=True)

    # --- РОЛИ, КОТОРЫЕ ПИНГУЮТСЯ В ТИКЕТАХ (ВЛАДЕЛЕЦ) ---
    @commands.hybrid_command(
        name="ticket_ping_role",
        aliases=["роль_пинга", "ticket_ping", "пинг_тикет"],
        description="Управление ролями, которые пингуются в новых тикетах (владелец/админ)",
    )
    @app_commands.describe(
        action="add / remove / list / clear",
        role="Роль для add или remove",
    )
    async def ticket_ping_role_cmd(
        self,
        ctx: commands.Context,
        action: str = "list",
        role: Optional[discord.Role] = None,
    ):
        if not ctx.guild:
            return await ctx.send("Команда доступна только на сервере.", ephemeral=True)

        allowed = ctx.author.id == ctx.guild.owner_id
        if not allowed and isinstance(ctx.author, discord.Member):
            allowed = ctx.author.guild_permissions.administrator
        if not allowed:
            try:
                allowed = await self.bot.is_owner(ctx.author)
            except Exception:
                allowed = False
        if not allowed:
            return await ctx.send(
                "Только владелец сервера (или администратор) может менять роли пинга в тикетах.",
                ephemeral=True,
            )

        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        act = (action or "list").strip().lower()
        raw_saved = None
        try:
            raw_saved = self.db.get_setting("ticket_ping_role_ids")
        except Exception:
            raw_saved = None
        current_ids = get_ticket_ping_role_ids(self.db)

        def _save(ids: list[int]) -> None:
            self.db.set_setting("ticket_ping_role_ids", ",".join(str(i) for i in ids))

        if act in ("add", "добавить", "+"):
            if not role:
                return await ctx.send("Укажите роль: `!ticket_ping_role add @роль`", ephemeral=True)
            if role.id in current_ids:
                return await ctx.send(f"Роль {role.mention} уже пингуется в тикетах.", ephemeral=True)
            ids = current_ids + [role.id]
            _save(ids)
            # Даём доступ к уже открытым тикетам (без повторного пинга)
            updated = 0
            for row in self.db.get_all_active_tickets():
                ch = self.bot.get_channel(row[0])
                if isinstance(ch, discord.TextChannel):
                    try:
                        await ch.set_permissions(
                            role,
                            view_channel=True,
                            send_messages=True,
                            attach_files=True,
                            read_message_history=True,
                            reason=f"Роль пинга тикетов добавлена ({ctx.author.name})",
                        )
                        updated += 1
                    except Exception:
                        pass
            embed = AG.embed(
                title="Роль пинга тикетов добавлена",
                description=(
                    f"{role.mention} будет пинговаться в новых тикетах.\n"
                    f"Доступ выдан в активных тикетах: **{updated}**.\n\n"
                    f"Всего ролей пинга: **{len(ids)}**"
                ),
                color=Colors.GREEN,
            )
            return await ctx.send(embed=embed, ephemeral=True)

        if act in ("remove", "убрать", "удалить", "-"):
            if not role:
                return await ctx.send("Укажите роль: `!ticket_ping_role remove @роль`", ephemeral=True)
            if role.id not in current_ids:
                return await ctx.send(f"Роль {role.mention} не настроена для пинга в тикетах.", ephemeral=True)
            ids = [i for i in current_ids if i != role.id]
            _save(ids)
            note = ""
            if role.id in Config.MOD_ROLE_IDS:
                note = "\n*Роль остаётся в MOD_ROLE_IDS — доступ к тикетам у неё сохранится.*"
            embed = AG.embed(
                title="Роль пинга тикетов убрана",
                description=(
                    f"{role.mention} больше не будет пинговаться в новых тикетах.\n"
                    f"Осталось ролей пинга: **{len(ids)}**.{note}"
                ),
                color=Colors.YELLOW,
            )
            return await ctx.send(embed=embed, ephemeral=True)

        if act in ("clear", "сброс", "очистить"):
            _save([])
            return await ctx.send(
                "Роли пинга тикетов очищены: новые тикеты создаются без пинга ролей.",
                ephemeral=True,
            )

        # list / status
        source = "база данных" if raw_saved is not None else "Config/.env"
        if current_ids:
            roles = [ctx.guild.get_role(i) for i in current_ids]
            lines = [f"• {r.mention} (`{r.id}`)" if r else f"• `{i}` — роль не найдена" for r, i in zip(roles, current_ids, strict=False)]
            value = "\n".join(lines)
        else:
            value = "*Роли пинга не настроены (тикеты создаются без пинга).*"
        embed = AG.embed(
            title="Роли пинга в тикетах",
            description=(
                f"{value}\n\n"
                f"Источник: `{source}`\n\n"
                "`!ticket_ping_role add @роль` — добавить\n"
                "`!ticket_ping_role remove @роль` — убрать\n"
                "`!ticket_ping_role clear` — очистить всё"
            ),
            color=Colors.BLUE,
        )
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        name="suspect",
        aliases=["подозреваемый", "проверить_игрока", "check_player", "suspect_check"],
        description="Оперативное досье игрока (твинки, IP, баны, статистика) для персонала",
    )
    @app_commands.describe(player_name="Никнейм игрока для проверки")
    async def suspect_cmd(self, ctx: commands.Context, player_name: str):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        embed = build_suspect_embed(self.bot, self.db, player_name.strip())
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        name="ticket_history",
        aliases=["история_тикетов", "тикеты_история"],
        description="Показать историю последних обращений (тикет, пользователь, статус, дата)",
    )
    async def ticket_history_cmd(self, ctx: commands.Context, limit: int = 10):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)
        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        limit = max(1, min(limit, 25))
        history = await _async_db_call(self.db.get_ticket_history, limit)
        if not history:
            return await ctx.send("История обращений в базе данных пуста.", ephemeral=True)

        lines = []
        for h in history:
            num = h.get("ticket_num", 0)
            status_emoji = "🟢 Открыт" if h.get("status") == "open" else "🔴 Закрыт"
            u_name = h.get("user_name", "Неизвестен")
            u_id = h.get("user_id", 0)
            c_at = h.get("created_at", "")
            cl_by = h.get("closed_by") or ""
            reason = h.get("close_reason") or ""

            details = f"• **#тикет-{num:03d}** | {status_emoji} | {u_name} (`{u_id}`)\n  Создан: `{c_at}`"
            if cl_by:
                details += f" | Закрыл: **{cl_by}** (`{reason}`)"
            lines.append(details)

        embed = AG.embed(
            title="История обращений в поддержку",
            description="\n\n".join(lines),
            color=Colors.BLUE,
            footer=f"Vanilla Land • Показано {len(history)} последних тикетов",
        )
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        name="user_tickets",
        aliases=["тикеты_юзера", "тикеты_игрока", "tickets_user", "проверить_тикеты"],
        description="[Персонал] Показать все тикеты пользователя (по юзернейму или ID) и их содержимое",
    )
    @app_commands.describe(user="Discord @упоминание, ID или юзернейм пользователя")
    async def user_tickets_cmd(self, ctx: commands.Context, *, user: str):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)
        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        raw = (user or "").strip()
        if not raw:
            return await ctx.send("Укажите `@упоминание`, Discord ID или юзернейм пользователя.", ephemeral=True)

        clean_id = raw.strip("<@!>").strip()
        target_id: Optional[int] = None
        target_label = raw

        if clean_id.isdigit():
            target_id = int(clean_id)
            u_obj = ctx.guild.get_member(target_id) if ctx.guild else None
            if not u_obj:
                u_obj = self.bot.get_user(target_id)
            if not u_obj:
                try:
                    u_obj = await self.bot.fetch_user(target_id)
                except Exception:
                    u_obj = None
            if u_obj:
                target_label = f"{u_obj.name}"
        elif ctx.guild:
            q_low = raw.lower().lstrip("@")
            matched = discord.utils.find(
                lambda m: m.name.lower() == q_low or m.display_name.lower() == q_low,
                ctx.guild.members,
            )
            if not matched:
                matched = discord.utils.find(
                    lambda m: q_low in m.name.lower() or q_low in m.display_name.lower(),
                    ctx.guild.members,
                )
            if matched:
                target_id = matched.id
                target_label = matched.name

        tickets = await _async_db_call(
            self.db.get_user_tickets,
            user_id=target_id,
            username=None if target_id is not None else raw.lstrip("@"),
            limit=25,
        )
        if not tickets and target_id is not None:
            # Fallback: если в старых записях user_name совпадает, но поиск шёл по ID — уже покрыто, а если не найдено:
            tickets = []

        if not tickets:
            return await ctx.send(f"У пользователя `{raw}` не найдено ни одного обращения в базе.", ephemeral=True)

        if not target_id and tickets[0].get("user_id"):
            target_id = tickets[0]["user_id"]
        if tickets[0].get("user_name") and target_label == raw and not clean_id.isdigit():
            target_label = tickets[0]["user_name"]

        view = UserTicketsView(tickets, target_label, target_id, ctx.guild)
        await ctx.send(embed=view.build_embed(), view=view, ephemeral=True)

    @commands.hybrid_command(
        name="ticket_set_counter",
        aliases=["тикет_счетчик", "тикет_номер"],
        description="[Админ] Установить текущий номер счетчика тикетов (например 105)",
    )
    @commands.has_permissions(administrator=True)
    @app_commands.describe(number="Новое значение счётчика тикетов")
    async def ticket_set_counter_cmd(self, ctx: commands.Context, number: int):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только администраторам.", ephemeral=True)
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        val = await _async_db_call(self.db.set_ticket_counter, number)
        await ctx.send(f"Счётчик тикетов установлен на **{val}** (следующий тикет: `#тикет-{val + 1:03d}`).", ephemeral=True)

    @commands.hybrid_command(
        name="ticket_roles",
        aliases=["роли_тикетов", "тикет_роли"],
        description="[Персонал] Показать все роли, которые получают доступ или пинг в тикетах",
    )
    async def ticket_roles_cmd(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.send("Команда доступна только на сервере.", ephemeral=True)
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)
        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        guild = ctx.guild
        ping_ids = await _async_db_call(get_ticket_ping_role_ids, self.db)
        ping_lines = []
        for rid in ping_ids:
            r = guild.get_role(rid)
            ping_lines.append(f"• {r.mention} (`{rid}`)" if r else f"• *Удалённая роль* (`{rid}`)")

        mod_lines = []
        for rid in Config.MOD_ROLE_IDS:
            r = guild.get_role(rid)
            if r:
                smm_note = " — *не пингуется (СММ)*" if any(w in r.name.lower() for w in ("смм", "smm")) else ""
                mod_lines.append(f"• {r.mention} (`{rid}`){smm_note}")
            else:
                mod_lines.append(f"• *Не найдена на сервере* (`{rid}`)")

        spec_matches = [r for r in guild.roles if r.name.strip().lower() in SPEC_ROLE_NAMES]
        active_spec = get_spec_role(guild, self.db)
        spec_lines = []
        if active_spec:
            spec_lines.append(f"• Активная: {active_spec.mention} (`{active_spec.id}`)")
        else:
            spec_lines.append("• *Не найдена (будет создана при следующем тикете)*")
        if len(spec_matches) > 1:
            dup_str = ", ".join(f"{r.mention} (`{r.id}`)" for r in spec_matches)
            spec_lines.append(f"• **Найдены дубликаты ролей с таким названием:** {dup_str}")

        cat_roles_lines = []
        cat_id = Config.TICKETS_CATEGORY_ID
        saved_cat = await _async_db_call(self.db.get_setting, "tickets_category_id")
        if saved_cat and str(saved_cat).isdigit():
            cat_id = int(saved_cat)
        cat = guild.get_channel(cat_id) if cat_id else None
        if isinstance(cat, discord.CategoryChannel):
            for target_obj, ow in cat.overwrites.items():
                if isinstance(target_obj, discord.Role) and not target_obj.is_default():
                    if ow.view_channel is True:
                        cat_roles_lines.append(f"• {target_obj.mention} (`{target_obj.id}`)")

        embed = AG.embed(
            title="Роли доступа в тикетах • Vanilla Land",
            description="Список всех ролей, которые добавляются в права или пингуются при создании тикета.",
            color=Colors.INDIGO,
            footer="Управление: /ticket_ping_role и /spec_role",
        )
        embed.add_field(
            name="Роли пинга (ticket_ping_role)",
            value="\n".join(ping_lines) if ping_lines else "*Не заданы (пингуются роли модерации)*",
            inline=False,
        )
        embed.add_field(
            name="Роли модерации (MOD_ROLE_IDS)",
            value="\n".join(mod_lines) if mod_lines else "*Не заданы*",
            inline=False,
        )
        embed.add_field(
            name="Роль Спек",
            value="\n".join(spec_lines),
            inline=False,
        )
        if cat_roles_lines:
            embed.add_field(
                name=f"Роли в правах категории ({cat.name})",
                value="\n".join(cat_roles_lines),
                inline=False,
            )
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        name="ticket_reply",
        aliases=["автоответ", "шаблон", "faq_rule", "snippet"],
        description="[Персонал] Настройка автоответов бота в тикетах (точные и похожие фразы)",
    )
    @app_commands.describe(
        action="Действие: add (добавить), list (список), remove (удалить), test (проверить фразу)",
        trigger="Ключевая фраза (можно несколько через |) или фраза для test / ID для remove",
        response="Текст ответа (если не указать при add — откроется удобная форма)",
        similarity="Порог похожести от 0.50 до 0.95 (по умолчанию 0.68)",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Добавить правило (add)", value="add"),
            app_commands.Choice(name="Список правил (list)", value="list"),
            app_commands.Choice(name="Удалить по ID (remove)", value="remove"),
            app_commands.Choice(name="Протестировать фразу (test)", value="test"),
        ]
    )
    async def ticket_reply_cmd(
        self,
        ctx: commands.Context,
        action: Optional[str] = "list",
        trigger: Optional[str] = None,
        response: Optional[str] = None,
        similarity: Optional[float] = 0.68,
    ):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        act = (action or "list").strip().lower()
        if act == "add":
            if ctx.interaction and (not trigger or not response):
                await ctx.interaction.response.send_modal(TicketAutoReplyModal(self.db))
                return
            if not trigger or not response:
                return await ctx.send(
                    "Использование: `/ticket_reply add` (откроет форму) или `!ticket_reply add \"фраза1 | фраза2\" \"ответ\"`",
                    ephemeral=True,
                )
            thr = similarity if similarity is not None else 0.68
            rule_id = await _async_db_call(
                self.db.add_ticket_auto_reply, trigger, response, thr, ctx.author.name
            )
            embed = AG.success(
                f"Автоответ #{rule_id} добавлен",
                f"• **Триггер:** `{trigger}`\n• **Порог похожести:** `{int(round(thr * 100))}%`\n• **Ответ:**\n{response[:500]}",
            )
            return await ctx.send(embed=embed, ephemeral=True)

        if act == "remove":
            if not trigger or not str(trigger).strip().isdigit():
                return await ctx.send("Укажите числовой ID правила для удаления (смотрите `/ticket_reply list`).", ephemeral=True)
            deleted = await _async_db_call(self.db.delete_ticket_auto_reply, int(str(trigger).strip()))
            if deleted:
                return await ctx.send(f"Автоответ `#{trigger.strip()}` удалён.", ephemeral=True)
            return await ctx.send(f"Автоответ `#{trigger.strip()}` не найден.", ephemeral=True)

        if act == "test":
            if not trigger:
                return await ctx.send("Укажите фразу игрока в параметре `trigger` для проверки.", ephemeral=True)
            match = await _async_db_call(self.db.find_matching_auto_reply, trigger)
            if not match:
                return await ctx.send(f"Для фразы `{trigger}` подходящих шаблонов не найдено.", ephemeral=True)
            rule = match["rule"]
            pct = int(round(match["score"] * 100))
            embed = AG.embed(
                title=f"Совпадение найдено • Правило #{rule['id']} ({pct}%)",
                description=(
                    f"• **Фраза:** `{trigger}`\n"
                    f"• **Сработал вариант:** `{match['matched_variant']}`\n\n"
                    f"**Ответ бота:**\n{rule['response_text']}"
                ),
                color=Colors.GREEN,
            )
            return await ctx.send(embed=embed, ephemeral=True)

        # list
        rules = await _async_db_call(self.db.get_ticket_auto_replies)
        if not rules:
            return await ctx.send(
                "Список автоответов в тикетах пуст. Добавьте первый командой `/ticket_reply add`.",
                ephemeral=True,
            )
        lines = []
        for r in rules[:15]:
            preview = r["response_text"].replace("\n", " ")
            if len(preview) > 90:
                preview = preview[:87] + "..."
            lines.append(f"**#{r['id']}** (`{int(round(r['threshold']*100))}%`) — `{r['trigger_phrase']}`\n↳ {preview}")
        embed = AG.embed(
            title="Автоответы в тикетах • Vanilla Land",
            description="\n\n".join(lines),
            color=Colors.INDIGO,
            footer="Удалить: /ticket_reply remove <id> | Проверить: /ticket_reply test <фраза>",
        )
        await ctx.send(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.bot or before.is_timed_out() or not after.is_timed_out():
            return
        tickets = await _async_db_call(self.db.get_user_tickets, user_id=after.id, limit=10)
        has_open = any(
            t.get("status") == "open"
            and t.get("dc_channel_id")
            and after.guild.get_channel(int(t["dc_channel_id"])) is not None
            for t in tickets
        )
        if has_open:
            await _ensure_member_can_write_in_ticket(after, after.guild, self.db)


async def _ensure_member_can_write_in_ticket(member: discord.Member, guild: discord.Guild, db: DatabaseManager) -> bool:
    """Если участник в нативном Discord-таймауте, переводит его в роль мута, чтобы он мог писать в тикете."""
    if not isinstance(member, discord.Member) or not member.is_timed_out():
        return False

    from cogs.verification import get_mute_role

    mute_role = get_mute_role(guild, db)
    if not mute_role or not guild.me or guild.me.top_role <= mute_role:
        return False

    try:
        if mute_role not in member.roles:
            await member.add_roles(mute_role, reason="Доступ к тикету (сохранение мута через роль)")
        if not await _async_db_call(db.is_user_muted, member.id, guild.id):
            until = member.timed_out_until
            unmute_ts = until.timestamp() if until else (time.time() + 3600)
            await _async_db_call(db.save_mute, member.id, guild.id, unmute_ts, "Перенос таймаута в мут-роль для доступа к тикету")
        await member.timeout(None, reason="Доступ к тикету (мут сохранён через роль)")
        return True
    except discord.HTTPException as err:
        logger.warning("Не удалось перенести таймаут в роль мута для %s: %s", member.id, err)
        return False


async def setup(bot: commands.Bot):
    db: DatabaseManager = bot.db
    await bot.add_cog(TicketsCog(bot, db))
