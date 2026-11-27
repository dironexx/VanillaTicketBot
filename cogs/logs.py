import asyncio
import io
import logging
import re
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import ui
from discord.ext import commands

from config import Config
from database import DatabaseManager
from design import AG, Colors
from cogs.verification import get_mute_role

logger = logging.getLogger("VanillaBot.Logs")

INVITE_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discord(?:app)?\.com/invite)/[a-zA-Z0-9\-]+",
    re.IGNORECASE,
)

PHISHING_REGEX = re.compile(
    r"(?:https?://)?(?:[a-z0-9-]+\.)*(?:"
    r"discrod|dlscord|discorcl|discord-?nitro|discordgift|discord-?airdrop|"
    r"free-?nitro|nitro-?gift|stean|steamcommunitty|steamcommunnity|"
    r"minecrafft|optifine-?free"
    r")[a-z0-9.-]*\.[a-z]{2,}",
    re.IGNORECASE,
)


def is_mod_or_admin(member: discord.Member) -> bool:
    if member.guild_permissions.administrator or member.id == member.guild.owner_id:
        return True
    user_roles = {r.id for r in member.roles}
    return any(r_id in user_roles for r_id in Config.MOD_ROLE_IDS)


class AntiInviteActionView(ui.View):
    """Интерактивные кнопки решения по рекламе для Администрации"""

    def __init__(self, target_id: int, db: DatabaseManager):
        super().__init__(timeout=86400)  # Активна 24 часа
        self.target_id = target_id
        self.db = db

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not is_mod_or_admin(interaction.user):
            await interaction.response.send_message("Только администрация может принимать решения.", ephemeral=True)
            return False
        return True

    @ui.button(label="Забанить нарушителя", style=discord.ButtonStyle.danger)
    async def ban_button(self, interaction: discord.Interaction, button: ui.Button):
        guild = interaction.guild
        if not guild:
            return
        try:
            await guild.ban(discord.Object(id=self.target_id), reason=f"Реклама (решение {interaction.user.name})")
            self.db.delete_mute(self.target_id, guild.id)
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content=f"**Решение принято:** Нарушитель забанен администратором {interaction.user.mention}.",
                view=self,
            )
        except Exception as e:
            await interaction.response.send_message(f"Ошибка бана: {e}", ephemeral=True)

    @ui.button(label="Размутить (ошибка)", style=discord.ButtonStyle.success)
    async def unmute_button(self, interaction: discord.Interaction, button: ui.Button):
        guild = interaction.guild
        if not guild:
            return
        member = guild.get_member(self.target_id)
        if not member:
            try:
                member = await guild.fetch_member(self.target_id)
            except (discord.NotFound, discord.HTTPException):
                member = None
        mute_role = get_mute_role(guild, self.db)

        if member and mute_role and mute_role in member.roles:
            try:
                await member.remove_roles(mute_role, reason=f"Размут (решение {interaction.user.name})")
                if member.is_timed_out():
                    await member.timeout(None)
            except Exception:
                pass

        self.db.delete_mute(self.target_id, guild.id)
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=f"**Решение принято:** Мут снят администратором {interaction.user.mention}.",
            view=self,
        )

    @ui.button(label="Оставить мут (1 ч)", style=discord.ButtonStyle.secondary)
    async def keep_mute_button(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"**Решение принято:** Мут оставлен в силе (подтвердил {interaction.user.mention}).",
            view=self,
        )


class LogsCog(commands.Cog, name="Логирование и Защита"):
    def __init__(self, bot: commands.Bot, db: DatabaseManager):
        self.bot = bot
        self.db = db
        self._event_lock = asyncio.Lock()
        self._mem_events: dict[str, float] = {}
        self._msg_cache: dict[int, dict] = {}
        self._msg_order: deque[int] = deque()

    async def _cache_message(self, message: discord.Message) -> None:
        """Кэширует текст и медиа последних 800 сообщений в памяти на случай очистки кэша Discord."""
        if len(self._msg_order) >= 800:
            oldest_id = self._msg_order.popleft()
            self._msg_cache.pop(oldest_id, None)

        att_cache: list[dict] = []
        image_exts = (".png", ".jpg", ".jpeg", ".webp", ".gif")
        for idx, att in enumerate(message.attachments):
            fname_low = (att.filename or "").lower().split("?")[0]
            ctype = (att.content_type or "").lower()
            is_img = ctype.startswith("image/") or fname_low.endswith(image_exts)
            raw_bytes = None
            if is_img and len(att_cache) < 2 and getattr(att, "size", 0) <= 2 * 1024 * 1024:
                try:
                    raw_bytes = await att.read()
                except Exception:
                    raw_bytes = None
            att_cache.append({
                "filename": att.filename or f"file_{idx}",
                "url": att.url,
                "proxy_url": att.proxy_url,
                "is_image": is_img,
                "bytes": raw_bytes,
            })

        self._msg_order.append(message.id)
        self._msg_cache[message.id] = {
            "author_id": message.author.id,
            "author_mention": message.author.mention,
            "channel_id": message.channel.id,
            "content": message.clean_content or "",
            "attachments": att_cache,
        }

    def get_log_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        # 1. Из базы данных
        saved_id = self.db.get_setting("log_channel_id")
        if saved_id and saved_id.isdigit():
            ch = guild.get_channel(int(saved_id))
            if isinstance(ch, discord.TextChannel):
                return ch

        # 2. Из Config.LOG_CHANNEL_ID (по умолчанию 1472696138053456077)
        if Config.LOG_CHANNEL_ID:
            ch = guild.get_channel(Config.LOG_CHANNEL_ID)
            if isinstance(ch, discord.TextChannel):
                return ch

        # 3. Fallback: поиск по названию (точное и нечеткое с учетом эмодзи)
        for ch in guild.text_channels:
            low = ch.name.lower().strip()
            if any(k in low for k in ("логи", "logs", "журнал", "аудит", "лог-", "-лог")):
                return ch

        return None

    def get_admin_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        saved_id = self.db.get_setting("admin_log_channel_id")
        if saved_id and saved_id.isdigit():
            ch = guild.get_channel(int(saved_id))
            if isinstance(ch, discord.TextChannel):
                return ch

        if Config.ADMIN_LOG_CHANNEL_ID:
            ch = guild.get_channel(Config.ADMIN_LOG_CHANNEL_ID)
            if isinstance(ch, discord.TextChannel):
                return ch

        for ch in guild.text_channels:
            low = ch.name.lower().strip()
            if any(k in low for k in ("алерты", "alerts", "админ-лог", "модерация-лог")):
                return ch

        return self.get_log_channel(guild)

    # --- КОМАНДЫ НАСТРОЙКИ КАНАЛОВ ЛОГОВ ---
    @commands.command(name="set_log_channel", aliases=["сет_лог_канал", "канал_логов"])
    @commands.has_permissions(administrator=True)
    async def set_log_channel_cmd(self, ctx: commands.Context, channel: discord.TextChannel):
        self.db.set_setting("log_channel_id", str(channel.id))
        embed = AG.success(
            "Канал аудита обновлен",
            f"Все события и логи сервера теперь отправляются в {channel.mention} (`{channel.id}`).",
        )
        await ctx.send(embed=embed)

    @commands.command(name="set_admin_channel", aliases=["сет_админ_канал", "канал_админов"])
    @commands.has_permissions(administrator=True)
    async def set_admin_channel_cmd(self, ctx: commands.Context, channel: discord.TextChannel):
        self.db.set_setting("admin_log_channel_id", str(channel.id))
        embed = AG.success(
            "Канал алертов обновлен",
            f"Оповещения безопасности (анти-реклама) теперь отправляются в {channel.mention} (`{channel.id}`).",
        )
        await ctx.send(embed=embed)

    # --- АНТИ-ИНВАЙТ (ЗАЩИТА ОТ РЕКЛАМЫ ДС-СЕРВЕРОВ) ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return

        await self._cache_message(message)

        # Игнорируем администрацию и модераторов
        if is_mod_or_admin(message.author):
            return

        # Проверка включения автомодерации
        if not self.db.is_automod_enabled():
            return

        content_lower = message.content.lower()
        is_violation = False
        violation_type = ""

        # 0. Фишинг и скам-ссылки
        if PHISHING_REGEX.search(message.content):
            is_violation = True
            violation_type = "Фишинг / скам-ссылка"

        # 1. Сторонние Discord-инвайты
        if not is_violation:
            match_inv = INVITE_REGEX.search(message.content)
            if match_inv:
                invite_url = match_inv.group(0).lower()
                if "ba5cmk7f6a" not in invite_url:
                    is_violation = True
                    violation_type = "Ссылка-инвайт на Discord"

        # 2. Сторонние Telegram-каналы
        if not is_violation:
            tg_match = re.search(r"(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]+)", message.content, re.IGNORECASE)
            if tg_match:
                channel_name = tg_match.group(1).lower()
                if channel_name not in ("vanilandes",):
                    is_violation = True
                    violation_type = "Сторонняя ссылка Telegram"

        # 3. Текстовая реклама других серверов и рекрутинг без ссылок
        if not is_violation:
            patterns = [
                r"(?:ищем|набор|требу[ею]тся|нужен|ищу)\s+.*?(?:tiktok|тиктокер|медиа|ютубер|модератор|стафф|персонал|монтаж).*?(?:для|на)\s+сервер",
                r"для\s+сервера\s+[a-zA-Z0-9а-яА-Я_-]+",
                r"(?:сервер|проект)\s+[a-zA-Z0-9а-яА-Я_-]+\s+.*?(?:напиши\s+(?:мне\s+)?в\s+лс|жду\s+в\s+лс|пиши\s+в\s+лс|пишите\s+в\s+лс)",
                r"(?:айпи|ip)\s*[:=]\s*[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                r"заходи(?:те)?\s+на\s+(?:мой|наш|новый)?\s*сервер",
                r"открытие\s+(?:нового\s+)?сервера\s+[a-zA-Z0-9а-яА-Я_-]+",
            ]
            for p in patterns:
                if re.search(p, content_lower):
                    if "vanilla land" not in content_lower and "vanillaland" not in content_lower:
                        is_violation = True
                        violation_type = "Реклама стороннего сервера / набор"
                        break

        if is_violation:
            author = message.author
            guild = message.guild
            content_copy = message.content

            # 1. Мгновенно удаляем сообщение
            try:
                await message.delete()
            except Exception:
                pass

            # 2. Отправляем нарушителю сообщение в ЛС перед баном
            try:
                dm_embed = AG.embed(
                    title="Мут на сервере • Vanilla Land",
                    description=(
                        f"Вам выдан мут на 1 час на сервере **Vanilla Land**.\n\n"
                        f"• **Причина:** `АвтоМодерация - реклама`\n"
                        f"• **Канал:** #{message.channel.name}\n"
                        f"• **Детали:** {violation_type}\n\n"
                        "На сервере запрещено распространение любой рекламы сторонних проектов и серверов."
                    ),
                    color=Colors.RED,
                    footer="Vanilla Land • АвтоМодерация",
                )
                await author.send(embed=dm_embed)
            except Exception:
                pass

            # 3. Мут на 1 час вместо мгновенного бана (решение о бане — кнопкой)
            mute_role = get_mute_role(guild, self.db)
            if mute_role and guild.me.top_role > mute_role:
                try:
                    await author.add_roles(mute_role, reason="АвтоМодерация - реклама")
                    self.db.save_mute(author.id, guild.id, time.time() + 3600, "АвтоМодерация - реклама")
                except Exception as e:
                    logger.error(f"Ошибка мута нарушителя за рекламу: {e}")

            # 4. Лог в канал Администрации
            admin_ch = self.get_admin_channel(guild)
            if admin_ch:
                alert_embed = AG.embed(
                    title="Автомодерация • Мут за рекламу",
                    description=(
                        f"Пользователю автоматически выдан **мут на 1 час** (решение о бане — кнопкой ниже).\n\n"
                        f"• **Нарушитель:** {author.mention} (`{author.name}` | ID: `{author.id}`)\n"
                        f"• **Канал:** {message.channel.mention}\n"
                        f"• **Тип нарушения:** `{violation_type}`\n"
                        f"• **Причина:** `АвтоМодерация - реклама`\n\n"
                        f"**Текст удалённого сообщения:**\n"
                        f"```{content_copy[:1500]}```"
                    ),
                    color=Colors.RED,
                    thumbnail=author.display_avatar.url,
                    footer=f"Vanilla Land • ID: {author.id}",
                )
                await admin_ch.send(embed=alert_embed, view=AntiInviteActionView(author.id, self.db))

    # --- ЛОГ УДАЛЕНИЯ СООБЩЕНИЙ ---
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        log_ch = self.get_log_channel(message.guild)
        if not log_ch or log_ch.id == message.channel.id:
            return

        if message.clean_content:
            raw_content = message.clean_content
        elif message.attachments:
            raw_content = "*[Без текста]*"
        else:
            raw_content = "*[Содержимое недоступно]*"
        content = raw_content[:1000] + "..." if len(raw_content) > 1000 else raw_content

        embed = AG.embed(
            title="Сообщение удалено",
            description=(
                f"• **Автор:** {message.author.mention} (`{message.author.id}`)\n"
                f"• **Канал:** {message.channel.mention}\n\n"
                f"**Текст сообщения:**\n{content}"
            ),
            color=Colors.RED,
            footer=f"Vanilla Land • ID: {message.id}",
        )

        image_files: list[discord.File] = []
        other_links: list[str] = []
        first_image_set = False
        image_exts = (".png", ".jpg", ".jpeg", ".webp", ".gif")

        cached_entry = self._msg_cache.pop(message.id, None)
        cached_atts = (cached_entry or {}).get("attachments", [])

        for idx, att in enumerate(message.attachments):
            fname_low = (att.filename or "").lower().split("?")[0]
            ctype = (att.content_type or "").lower()
            is_image = ctype.startswith("image/") or fname_low.endswith(image_exts)

            if is_image and len(image_files) < 4 and getattr(att, "size", 0) <= 8 * 1024 * 1024:
                img_bytes = None
                if idx < len(cached_atts) and cached_atts[idx].get("bytes"):
                    img_bytes = cached_atts[idx]["bytes"]
                else:
                    for use_cached in (True, False):
                        try:
                            img_bytes = await att.read(use_cached=use_cached)
                            if img_bytes:
                                break
                        except Exception:
                            continue

                if img_bytes:
                    clean_name = re.sub(r"[^a-zA-Z0-9._-]", "_", att.filename or f"image_{idx}.png")
                    safe_name = f"{idx}_{clean_name}"
                    image_files.append(discord.File(io.BytesIO(img_bytes), filename=safe_name))
                    if not first_image_set:
                        embed.set_image(url=f"attachment://{safe_name}")
                        first_image_set = True
                    continue

                # Если Discord уже удалил файл из CDN, пробуем показать по proxy_url / url
                if not first_image_set:
                    embed.set_image(url=att.proxy_url or att.url)
                    first_image_set = True
                other_links.append(f"• [{att.filename}]({att.url})")
            else:
                other_links.append(f"• [{att.filename}]({att.url})")

        if other_links:
            links_val = "\n".join(other_links)
            if len(links_val) > 1020:
                links_val = links_val[:1017] + "..."
            embed.add_field(name="Вложения", value=links_val, inline=False)

        try:
            if image_files:
                await log_ch.send(embed=embed, files=image_files)
            else:
                await log_ch.send(embed=embed)
        except Exception as send_err:
            logger.debug("Не удалось отправить лог удаления сообщения %s: %s", message.id, send_err)

    async def _send_cached_delete_log(self, guild: discord.Guild, channel_id: int, msg_id: int, cached: dict) -> None:
        log_ch = self.get_log_channel(guild)
        if not log_ch or log_ch.id == channel_id:
            return
        raw_content = cached.get("content") or ("*[Без текста]*" if cached.get("attachments") else "*[Содержимое недоступно]*")
        content = raw_content[:1000] + "..." if len(raw_content) > 1000 else raw_content
        embed = AG.embed(
            title="Сообщение удалено",
            description=(
                f"• **Автор:** {cached.get('author_mention', 'Неизвестен')} (`{cached.get('author_id', '?')}`)\n"
                f"• **Канал:** <#{channel_id}>\n\n"
                f"**Текст сообщения:**\n{content}"
            ),
            color=Colors.RED,
            footer=f"Vanilla Land • ID: {msg_id}",
        )
        image_files: list[discord.File] = []
        other_links: list[str] = []
        first_image_set = False
        for idx, att in enumerate(cached.get("attachments", [])):
            if att.get("is_image") and att.get("bytes") and len(image_files) < 4:
                clean_name = re.sub(r"[^a-zA-Z0-9._-]", "_", att.get("filename") or f"image_{idx}.png")
                safe_name = f"{idx}_{clean_name}"
                image_files.append(discord.File(io.BytesIO(att["bytes"]), filename=safe_name))
                if not first_image_set:
                    embed.set_image(url=f"attachment://{safe_name}")
                    first_image_set = True
            else:
                other_links.append(f"• [{att.get('filename', 'file')}]({att.get('url', '')})")
        if other_links:
            embed.add_field(name="Вложения", value="\n".join(other_links)[:1020], inline=False)
        try:
            if image_files:
                await log_ch.send(embed=embed, files=image_files)
            else:
                await log_ch.send(embed=embed)
        except Exception as err:
            logger.debug("Ошибка отправки raw-лога удаления %s: %s", msg_id, err)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.cached_message is not None or not payload.guild_id:
            return
        cached = self._msg_cache.pop(payload.message_id, None)
        if not cached:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild:
            await self._send_cached_delete_log(guild, payload.channel_id, payload.message_id, cached)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        cached_ids = {m.id for m in payload.cached_messages}
        for mid in payload.message_ids:
            if mid in cached_ids:
                continue
            cached = self._msg_cache.pop(mid, None)
            if cached:
                await self._send_cached_delete_log(guild, payload.channel_id, mid, cached)

    # --- ЛОГ РЕДАКТИРОВАНИЯ СООБЩЕНИЙ ---
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.clean_content == after.clean_content:
            return

        log_ch = self.get_log_channel(before.guild)
        if not log_ch or log_ch.id == before.channel.id:
            return

        old_text = before.clean_content or "*[Пусто]*"
        new_text = after.clean_content or "*[Пусто]*"
        if len(old_text) > 450:
            old_text = old_text[:450] + "..."
        if len(new_text) > 450:
            new_text = new_text[:450] + "..."

        embed = AG.embed(
            title="Сообщение отредактировано",
            description=(
                f"• **Автор:** {before.author.mention} (`{before.author.id}`)\n"
                f"• **Канал:** {before.channel.mention} ([Перейти к сообщению]({after.jump_url}))\n\n"
                f"**До:**\n{old_text}\n\n"
                f"**После:**\n{new_text}"
            ),
            color=Colors.BLUE,
            footer=f"Vanilla Land • ID: {after.id}",
        )
        try:
            await log_ch.send(embed=embed)
        except Exception:
            pass

    # --- ЛОГ ВХОДА УЧАСТНИКА (С ТРОЙНОЙ ЗАЩИТОЙ ОТ ДУБЛИРОВАНИЯ) ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        now = time.time()
        evt_key = f"{member.id}:join"

        # 1. In-memory дедупликация (мгновенная блокировка повторных вызовов gateway)
        async with self._event_lock:
            last_t = self._mem_events.get(evt_key, 0.0)
            if (now - last_t) < 45.0:
                logger.debug("Игнорирование in-memory дубликата входа для %s (%s)", member.name, member.id)
                return
            self._mem_events[evt_key] = now
            # Очистка устаревших ключей раз в 100 записей
            if len(self._mem_events) > 100:
                self._mem_events = {k: v for k, v in self._mem_events.items() if (now - v) < 120.0}

        # 2. SQLite атомарная дедупликация (защита между потоками и процессами)
        if hasattr(self.db, "claim_member_event") and not self.db.claim_member_event(member.id, "join", window_sec=45.0):
            logger.debug("Игнорирование DB дублирующего события входа для %s (%s)", member.name, member.id)
            return

        log_ch = self.get_log_channel(member.guild)
        if not log_ch:
            return

        # 3. Дедупликация на уровне Discord канала (защита на случай параллельно работающего старого инстанса)
        try:
            async for last_msg in log_ch.history(limit=6):
                if last_msg.author.id == self.bot.user.id and last_msg.embeds:
                    for emb in last_msg.embeds:
                        if emb.title == "Новый участник" and str(member.id) in (emb.description or ""):
                            logger.warning("Лог входа для %s (%s) уже присутствует в канале, пропуск дубля.", member.name, member.id)
                            return
        except Exception as hist_err:
            logger.debug("History check note: %s", hist_err)

        created_ts = int(member.created_at.timestamp())
        account_age_days = (datetime.now(member.created_at.tzinfo) - member.created_at).days

        warning_note = ""
        if account_age_days < 7:
            warning_note = f"\n• **Внимание:** Аккаунту меньше {account_age_days} дн. (возможен твинк или бот)!"

        embed = AG.embed(
            title="Новый участник",
            description=(
                f"• **Участник:** {member.mention} (`{member.name}`)\n"
                f"• **ID:** `{member.id}`\n"
                f"• **Регистрация:** <t:{created_ts}:D> (<t:{created_ts}:R>){warning_note}"
            ),
            color=Colors.GREEN,
            thumbnail=member.display_avatar.url,
            footer=f"Vanilla Land • Всего участников: {member.guild.member_count}",
        )
        try:
            await log_ch.send(embed=embed)
        except Exception:
            pass

    # --- ЛОГ ВЫХОДА УЧАСТНИКА ---
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        now = time.time()
        evt_key = f"{member.id}:remove"

        async with self._event_lock:
            last_t = self._mem_events.get(evt_key, 0.0)
            if (now - last_t) < 45.0:
                logger.debug("Игнорирование in-memory дубликата выхода для %s (%s)", member.name, member.id)
                return
            self._mem_events[evt_key] = now

        if hasattr(self.db, "claim_member_event") and not self.db.claim_member_event(member.id, "remove", window_sec=45.0):
            logger.debug("Игнорирование DB дублирующего события выхода для %s (%s)", member.name, member.id)
            return

        log_ch = self.get_log_channel(member.guild)
        if not log_ch:
            return

        try:
            async for last_msg in log_ch.history(limit=6):
                if last_msg.author.id == self.bot.user.id and last_msg.embeds:
                    for emb in last_msg.embeds:
                        if emb.title == "Участник покинул сервер" and str(member.id) in (emb.description or ""):
                            return
        except Exception:
            pass

        roles = [r.name for r in member.roles if r.name != "@everyone"]
        roles_str = ", ".join(roles[:5]) if roles else "Нет"

        embed = AG.embed(
            title="Участник покинул сервер",
            description=(
                f"• **Участник:** {member.mention} (`{member.name}`)\n"
                f"• **ID:** `{member.id}`\n"
                f"• **Роли:** {roles_str}"
            ),
            color=Colors.DARK,
            thumbnail=member.display_avatar.url,
            footer=f"Vanilla Land • Осталось участников: {member.guild.member_count}",
        )
        try:
            await log_ch.send(embed=embed)
        except Exception:
            pass


async def setup(bot: commands.Bot):
    db: DatabaseManager = bot.db
    await bot.add_cog(LogsCog(bot, db))
