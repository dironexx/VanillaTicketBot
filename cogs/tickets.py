import asyncio
import html
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
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
    """Неблокирующий event loop вызов БД с асинхронным ожиданием при занятости SQLite WAL."""
    attempt = 0
    while True:
        try:
            return func(*args, **kwargs)
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
    if Config.TICKETS_CATEGORY_ID:
        category = guild.get_channel(Config.TICKETS_CATEGORY_ID)
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


async def save_transcript_html(
    channel: discord.TextChannel,
    closed_by_name: str = "Персонал",
    reason: str = "Вопрос решен"
) -> str:
    """Генерирует автономный HTML-файл переписки тикета в темной теме Obsidian / Linear"""
    file_time = get_msk_now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(Config.TRANSCRIPTS_DIR, f"{channel.name}_{file_time}.html")

    messages_html = []
    msg_count = 0

    async for msg in channel.history(limit=None, oldest_first=True):
        msg_count += 1
        msg_time = msg.created_at.astimezone(MSK).strftime("%d.%m.%Y %H:%M:%S")
        author_name = html.escape(msg.author.display_name)
        author_avatar = msg.author.display_avatar.url if hasattr(msg.author, "display_avatar") else ""
        role_color = "#99aab5"
        if isinstance(msg.author, discord.Member) and msg.author.color.value != 0:
            role_color = f"#{msg.author.color.value:06x}"

        # Markdown форматирование
        raw_text = html.escape(msg.clean_content or "")
        raw_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", raw_text)
        raw_text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", raw_text)
        raw_text = re.sub(r"`(.+?)`", r"<code>\1</code>", raw_text)
        raw_text = raw_text.replace("\n", "<br>")

        attachments_html = []
        for att in msg.attachments:
            att_url = html.escape(att.url)
            is_image = any(att.filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"))
            if is_image:
                attachments_html.append(f'<div class="attachment"><a href="{att_url}" target="_blank"><img src="{att_url}" alt="Attachment" class="att-img" /></a></div>')
            else:
                att_name = html.escape(att.filename)
                attachments_html.append(f'<div class="attachment"><a href="{att_url}" target="_blank" class="att-file">[Файл] {att_name}</a></div>')

        embeds_html = []
        for emb in msg.embeds:
            border_color = f"#{emb.color.value:06x}" if emb.color and emb.color.value else "#5865f2"
            emb_title = f'<div class="embed-title">{html.escape(emb.title)}</div>' if emb.title else ""
            emb_desc = f'<div class="embed-desc">{html.escape(emb.description or "").replace(chr(10), "<br>")}</div>' if emb.description else ""
            fields_html = []
            for f in emb.fields:
                f_name = html.escape(f.name)
                f_val = html.escape(f.value).replace("\n", "<br>")
                fields_html.append(f'<div class="embed-field"><div class="field-name">{f_name}</div><div class="field-val">{f_val}</div></div>')
            f_block = f'<div class="embed-fields">{"".join(fields_html)}</div>' if fields_html else ""
            embeds_html.append(f'<div class="embed" style="border-left-color: {border_color};">{emb_title}{emb_desc}{f_block}</div>')

        bot_badge = '<span class="bot-badge">БОТ</span>' if msg.author.bot else ""
        avatar_img = f'<img src="{author_avatar}" class="avatar" alt="Avatar" />' if author_avatar else '<div class="avatar-placeholder"></div>'

        messages_html.append(f"""
        <div class="message">
            {avatar_img}
            <div class="message-content">
                <div class="message-header">
                    <span class="author" style="color: {role_color};">{author_name}</span>
                    {bot_badge}
                    <span class="timestamp">{msg_time}</span>
                </div>
                <div class="message-body">{raw_text}</div>
                {"".join(attachments_html)}
                {"".join(embeds_html)}
            </div>
        </div>
        """)

    guild_name = html.escape(channel.guild.name)
    ch_name = html.escape(channel.name)
    closed_by_clean = html.escape(closed_by_name)
    reason_clean = html.escape(reason)
    now_date = get_msk_now().strftime("%d.%m.%Y %H:%M:%S")

    html_page = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Транскрипт #{ch_name} • {guild_name}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background-color: #313338;
            color: #dbdee1;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            font-size: 15px;
            line-height: 1.4;
            padding: 20px;
        }}
        .container {{
            max-width: 960px;
            margin: 0 auto;
            background-color: #2b2d31;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.4);
        }}
        .header {{
            background-color: #1e1f22;
            padding: 24px;
            border-bottom: 2px solid #232428;
        }}
        .header h1 {{
            font-size: 20px;
            color: #f2f3f5;
            margin-bottom: 12px;
        }}
        .header-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 10px;
            font-size: 13px;
            color: #949ba4;
        }}
        .header-item strong {{ color: #f2f3f5; }}
        .chat {{
            padding: 20px 24px;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }}
        .message {{
            display: flex;
            gap: 16px;
            padding: 6px 8px;
            border-radius: 4px;
            transition: background 0.1s;
        }}
        .message:hover {{ background-color: #2e3035; }}
        .avatar {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            flex-shrink: 0;
        }}
        .avatar-placeholder {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background-color: #5865f2;
            flex-shrink: 0;
        }}
        .message-content {{ flex-grow: 1; min-width: 0; }}
        .message-header {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 4px;
        }}
        .author {{ font-weight: 600; font-size: 15px; }}
        .bot-badge {{
            background-color: #5865f2;
            color: #ffffff;
            font-size: 10px;
            font-weight: 700;
            padding: 1px 4px;
            border-radius: 3px;
        }}
        .timestamp {{
            font-size: 12px;
            color: #949ba4;
        }}
        .message-body {{
            word-break: break-word;
            color: #dbdee1;
        }}
        .message-body code {{
            background: #1e1f22;
            padding: 2px 4px;
            border-radius: 3px;
            font-family: monospace;
            font-size: 13px;
        }}
        .attachment {{ margin-top: 8px; }}
        .att-img {{
            max-width: 100%;
            max-height: 380px;
            border-radius: 6px;
        }}
        .att-file {{
            color: #00a8fc;
            text-decoration: none;
            font-size: 13px;
            background: #1e1f22;
            padding: 4px 8px;
            border-radius: 4px;
            display: inline-block;
        }}
        .att-file:hover {{ text-decoration: underline; }}
        .embed {{
            margin-top: 8px;
            background-color: #1e1f22;
            border-left: 4px solid #5865f2;
            border-radius: 4px;
            padding: 12px;
            max-width: 520px;
        }}
        .embed-title {{
            font-weight: 600;
            color: #f2f3f5;
            margin-bottom: 6px;
        }}
        .embed-desc {{
            font-size: 14px;
            color: #dbdee1;
            margin-bottom: 8px;
        }}
        .embed-fields {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 8px;
        }}
        .field-name {{ font-size: 12px; font-weight: 600; color: #949ba4; }}
        .field-val {{ font-size: 13px; color: #dbdee1; }}
        .footer {{
            padding: 16px 24px;
            background-color: #1e1f22;
            border-top: 1px solid #232428;
            font-size: 12px;
            color: #949ba4;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>#{ch_name} • Архив обращения</h1>
            <div class="header-grid">
                <div class="header-item">Сервер: <strong>{guild_name}</strong></div>
                <div class="header-item">Дата закрытия: <strong>{now_date}</strong></div>
                <div class="header-item">Закрыл: <strong>{closed_by_clean}</strong></div>
                <div class="header-item">Причина: <strong>{reason_clean}</strong></div>
                <div class="header-item">Сообщений: <strong>{msg_count}</strong></div>
            </div>
        </div>
        <div class="chat">
            {"".join(messages_html)}
        </div>
        <div class="footer">
            Vanilla Land Support • play.vanillaland.fun
        </div>
    </div>
</body>
</html>
"""

    def _write() -> None:
        os.makedirs(Config.TRANSCRIPTS_DIR, exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_page)

    await asyncio.to_thread(_write)
    return filename


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
    linked = summary.get("linked")
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
    if linked:
        embed.add_field(name="Discord", value=f"<@{linked['discord_user_id']}> (`{linked['discord_user_id']}`)", inline=True)
    else:
        embed.add_field(name="Discord", value="*Не привязан*", inline=True)

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
            saved_file = await save_transcript_html(channel, closed_by_name, reason)
        except discord.NotFound:
            channel_already_deleted = True
            logger.info("Канал тикета %s (%s) уже удален до сохранения транскрипта.", channel.name, channel.id)
        except Exception as e:
            logger.error("Ошибка создания HTML-транскрипта %s: %s", channel.name, e)
            try:
                saved_file = await save_transcript_to_file(channel)
            except discord.NotFound:
                channel_already_deleted = True
            except Exception as e2:
                logger.error("Ошибка создания txt-транскрипта %s: %s", channel.name, e2)

        file_exists = bool(saved_file and await asyncio.to_thread(os.path.exists, saved_file))

        if user_id:
            try:
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                if user:
                    embed = AG.embed(
                        title=f"Обращение закрыто • #{channel.name}",
                        description=(
                            f"Ваше обращение закрыто сотрудником **{closed_by_name}**.\n\n"
                            f"**Причина:** {reason}\n"
                            f"HTML-лог переписки прикреплен к сообщению."
                        ),
                        footer="Vanilla Land • Поддержка",
                    )
                    if file_exists and saved_file:
                        await user.send(embed=embed, file=discord.File(saved_file))
                    else:
                        await user.send(embed=embed)
            except (discord.Forbidden, discord.NotFound):
                logger.info("Не удалось отправить транскрипт в ЛС пользователю %s (закрыты ЛС или покинул сервер).", user_id)
            except Exception as e:
                logger.warning("Ошибка отправки ЛС %s: %s", user_id, e)

        # Отправка транскрипта в канал логов
        if Config.LOG_CHANNEL_ID:
            log_ch = bot.get_channel(Config.LOG_CHANNEL_ID)
            if isinstance(log_ch, discord.TextChannel):
                user_display = f"<@{user_id}> (`{user_id}`)" if user_id else "*Неизвестен*"
                embed_log = AG.embed(
                    title=f"Тикет закрыт • #{channel.name}",
                    description=(
                        f"**Пользователь:** {user_display}\n"
                        f"**Закрыл:** **{closed_by_name}**\n"
                        f"**Причина:** {reason}"
                    ),
                    footer="Vanilla Land • Архив тикетов",
                )
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
            await _async_db_call(db.delete_ticket, channel.id)
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

        await _safe_send_interaction(interaction, "Закрываем обращение и сохраняем HTML-лог...", ephemeral=True)
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

    @ui.button(label="Досье игрока", style=discord.ButtonStyle.secondary, custom_id="persistent_suspect_btn")
    async def request_suspect(self, interaction: discord.Interaction, button: ui.Button):
        if not is_mod_or_admin(interaction):
            await _safe_send_interaction(interaction, "Эта функция доступна только персоналу.", ephemeral=True)
            return
        opened = await _safe_send_modal(interaction, SuspectCheckModal(self.db))
        if not opened:
            await _safe_send_interaction(interaction, "Не удалось открыть форму проверки. Попробуйте снова.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: ui.Item[Any]) -> None:
        logger.error("Ошибка в InsideTicketView (%s): %s", getattr(item, "custom_id", item), error, exc_info=error)
        await _safe_send_interaction(interaction, "Произошла ошибка при обработке кнопки.", ephemeral=True)


_CREATING_TICKETS: set[int] = set()
_TICKET_CREATE_LOCK = asyncio.Lock()


async def create_ticket_channel(
    guild: discord.Guild,
    user: discord.Member,
    db: DatabaseManager,
    fallback_channel: Optional[discord.TextChannel] = None,
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
        if Config.TICKETS_CATEGORY_ID:
            target_category = guild.get_channel(Config.TICKETS_CATEGORY_ID)
        if not target_category and fallback_channel:
            target_category = fallback_channel.category

        # Проверяем лимит 50 каналов в категории
        if target_category and isinstance(target_category, discord.CategoryChannel) and len(target_category.channels) >= 50:
            target_category = None

        async with _TICKET_CREATE_LOCK:
            ticket_num = await _async_db_call(db.get_next_ticket_number)
            channel_name = f"тикет-{ticket_num:03d}"

            try:
                ticket_channel = await guild.create_text_channel(
                    name=channel_name,
                    category=target_category,
                    overwrites=overwrites,
                    topic=f"Игрок: {user.name} ({user.id}) | Создан: {get_msk_now().strftime('%d.%m.%Y %H:%M')}",
                )
            except discord.HTTPException as err:
                logger.error("Не удалось создать канал тикета в Discord: %s (код %s)", err, getattr(err, "code", None))
                if getattr(err, "code", 0) == 30013:
                    return None, "Категория тикетов переполнена (максимум 50). Обратитесь к администратору."
                return None, "Ошибка Discord при создании канала тикета. Попробуйте через пару минут."

            await _async_db_call(db.save_ticket, ticket_channel.id, user.id, user.name)

        embed = AG.embed(
            title=f"Обращение #{ticket_num:03d}",
            description=(
                f"Здравствуйте, {user.mention}!\n\n"
                f"**Пожалуйста, укажите:**\n"
                f"• Ваш точный никнейм в игре\n"
                f"• Суть проблемы или вопроса\n"
                f"• Скриншоты или видео (если есть)\n\n"
                f"Персонал ответит вам в ближайшее время."
            ),
            footer="Vanilla Land • Поддержка | Команды: !add, !remove, !rename, !close",
        )

        try:
            await ticket_channel.send(content=" ".join(mentions_list), embed=embed, view=InsideTicketView(db))
        except discord.HTTPException as err:
            logger.warning("Не удалось отправить стартовое сообщение в %s: %s", ticket_channel.id, err)

        return ticket_channel, f"Обращение создано: {ticket_channel.mention}"
    finally:
        _CREATING_TICKETS.discard(user.id)


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

        if not await _safe_defer(interaction, ephemeral=True):
            return

        fallback = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
        _ticket_channel, msg = await create_ticket_channel(guild, user, self.db, fallback)
        await _safe_send_interaction(interaction, msg, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: ui.Item[Any]) -> None:
        logger.error("Ошибка в TicketPanel (%s): %s", getattr(item, "custom_id", item), error, exc_info=error)
        await _safe_send_interaction(interaction, "Не удалось обработать запрос. Попробуйте через пару секунд.", ephemeral=True)


class TicketsCog(commands.Cog, name="Тикеты"):
    def __init__(self, bot: commands.Bot, db: DatabaseManager):
        self.bot = bot
        self.db = db
        self._non_ticket_cache: dict[int, float] = {}
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
                spec_role = await get_or_create_spec_role(guild, self.db)
                if spec_role:
                    await sync_spec_role_to_tickets(guild, spec_role, self.db)
            except Exception as e:
                logger.debug("Ошибка авто-инициализации роли спека в %s: %s", guild.name, e)

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

        clean_name = new_name.strip().replace(" ", "-").lower()[:32]
        if not clean_name:
            return await ctx.send("Укажите корректное название.", ephemeral=True)

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


async def setup(bot: commands.Bot):
    db: DatabaseManager = bot.db
    await bot.add_cog(TicketsCog(bot, db))
