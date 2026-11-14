import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import ui, app_commands
from discord.ext import commands, tasks

from config import Config
from database import DatabaseManager, MSK, get_msk_now
from design import AG, Colors

logger = logging.getLogger("VanillaBot.Tickets")

SPEC_ROLE_NAMES = ("спек", "спектатор", "spectator", "наблюдатель", "спек тикеты", "тикет спек")


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
        saved = db.get_setting("spec_role_id")
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
            db.set_setting("spec_role_id", str(role.id))
        Config.SPEC_ROLE_ID = role.id
        return role

    if guild.me.guild_permissions.manage_roles:
        try:
            role = await guild.create_role(
                name="Спек",
                color=discord.Color.from_rgb(0, 180, 216),
                mentionable=False,
                reason="Создание роли спека для доступа к тикетам",
            )
            logger.info(f"Создана роль спека: '{role.name}' ({role.id})")
            if db:
                db.set_setting("spec_role_id", str(role.id))
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
    active_tickets = db.get_all_active_tickets()
    
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
    os.makedirs(Config.TRANSCRIPTS_DIR, exist_ok=True)
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
        with open(filename, "w", encoding="utf-8") as f:
            f.write(payload)

    await asyncio.to_thread(_write_transcript)
    return filename


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
        user_id = db.get_ticket_user_id(channel.id)

        try:
            saved_file = await save_transcript_to_file(channel)
        except Exception as e:
            logger.error(f"Ошибка создания транскрипта {channel.name}: {e}")
            saved_file = None

        if user_id:
            try:
                user = await bot.fetch_user(user_id)
                if user:
                    embed = AG.embed(
                        title=f"Обращение закрыто • #{channel.name}",
                        description=(
                            f"Ваше обращение закрыто сотрудником **{closed_by_name}**.\n\n"
                            f"**Причина:** {reason}\n"
                            f"Лог переписки прикреплен к сообщению."
                        ),
                        footer="Vanilla Land • Поддержка",
                    )
                    if saved_file and os.path.exists(saved_file):
                        await user.send(embed=embed, file=discord.File(saved_file))
                    else:
                        await user.send(embed=embed)
            except Exception as e:
                logger.error(f"Ошибка отправки ЛС {user_id}: {e}")

        # Сначала удаляем канал из Discord, и ТОЛЬКО после успеха удаляем из БД
        try:
            await channel.delete(reason=f"Тикет закрыт: {closed_by_name} ({reason})")
        except discord.NotFound:
            pass
        except Exception as e:
            logger.error(f"Ошибка удаления тикета {channel.id}: {e}")

        db.delete_ticket(channel.id)
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
        reason = self.reason_input.value.strip() or "Вопрос решен"
        await interaction.response.send_message("Закрываем обращение и сохраняем лог...", ephemeral=True)
        if isinstance(interaction.channel, discord.TextChannel):
            await close_ticket_process(interaction.client, self.db, interaction.channel, interaction.user.name, reason)


class InsideTicketView(ui.View):
    def __init__(self, db: DatabaseManager):
        super().__init__(timeout=None)
        self.db = db

    @ui.button(label="Закрыть обращение", style=discord.ButtonStyle.danger, custom_id="persistent_close_btn")
    async def request_close(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CloseReasonModal(self.db))


_CREATING_TICKETS: set[int] = set()


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
        bl_reason = db.is_ticket_blacklisted(user.id)
        if bl_reason is not None:
            reason_text = bl_reason or "Не указана"
            return None, f"Вам заблокирован доступ к созданию обращений.\n**Причина:** {reason_text}"

        if db.user_has_open_ticket(user.id):
            return None, "У вас уже есть активное обращение."

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

        ticket_num = db.get_next_ticket_number()
        channel_name = f"тикет-{ticket_num:03d}"

        target_category = None
        if Config.TICKETS_CATEGORY_ID:
            target_category = guild.get_channel(Config.TICKETS_CATEGORY_ID)
        if not target_category and fallback_channel:
            target_category = fallback_channel.category

        # Проверяем лимит 50 каналов в категории
        if target_category and isinstance(target_category, discord.CategoryChannel) and len(target_category.channels) >= 50:
            target_category = None

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
                return None, "❌ Категория тикетов переполнена (максимум 50). Обратитесь к администратору."
            return None, "❌ Ошибка Discord при создании канала тикета. Попробуйте через пару минут."

        db.save_ticket(ticket_channel.id, user.id, user.name)

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

        await ticket_channel.send(content=" ".join(mentions_list), embed=embed, view=InsideTicketView(db))
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
            return await interaction.response.send_message("Только на сервере.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        fallback = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
        ticket_channel, msg = await create_ticket_channel(guild, user, self.db, fallback)
        await interaction.followup.send(msg, ephemeral=True)


class TicketsCog(commands.Cog, name="Тикеты"):
    def __init__(self, bot: commands.Bot, db: DatabaseManager):
        self.bot = bot
        self.db = db
        self.auto_close_task.start()
        asyncio.create_task(self.init_spec_role_on_start())

    def cog_unload(self):
        self.auto_close_task.cancel()

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
                logger.debug(f"Ошибка авто-инициализации роли спека в {guild.name}: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if self.db.is_ticket_channel(message.channel.id):
            self.db.update_ticket_activity(message.channel.id)

    @tasks.loop(hours=1)
    async def auto_close_task(self):
        tickets = self.db.get_all_active_tickets()
        now = get_msk_now()
        timeout = timedelta(hours=Config.AUTO_CLOSE_HOURS)

        for row in tickets:
            ch_id, user_id, user_name, last_act_str, created = row
            try:
                target_time_str = last_act_str or created
                if target_time_str:
                    last_act = datetime.strptime(target_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=MSK)
                    if now - last_act > timeout:
                        channel = self.bot.get_channel(ch_id)
                        if channel and isinstance(channel, discord.TextChannel):
                            await channel.send(f"Обращение закрывается из-за неактивности более {Config.AUTO_CLOSE_HOURS}ч.")
                            await close_ticket_process(self.bot, self.db, channel, "Авто-закрытие", f"Неактивность более {Config.AUTO_CLOSE_HOURS}ч")
                        else:
                            self.db.delete_ticket(ch_id)
            except Exception as e:
                logger.error(f"Ошибка авто-закрытия {ch_id}: {e}")

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
        if not self.db.is_ticket_channel(ctx.channel.id):
            return await ctx.send("Эта команда доступна только внутри активного тикета.", ephemeral=True, delete_after=5)

        actual_reason = reason or "Не указана"
        await ctx.send(f"Закрытие обращения сотрудником **{ctx.author.name}**...")
        if isinstance(ctx.channel, discord.TextChannel):
            await close_ticket_process(self.bot, self.db, ctx.channel, ctx.author.name, actual_reason)

    # --- ДОБАВИТЬ УЧАСТНИКА В ТИКЕТ (МОЖЕТ И АВТОР ТИКЕТА) ---
    @commands.hybrid_command(name="add", aliases=["добавить"], description="Добавить пользователя в текущий тикет")
    @app_commands.describe(member="Пользователь для добавления")
    async def add_user_cmd(self, ctx: commands.Context, member: discord.Member):
        if not self.db.is_ticket_channel(ctx.channel.id):
            return await ctx.send("Команда доступна только внутри активного тикета.", ephemeral=True, delete_after=5)

        if not can_manage_ticket(ctx, self.db):
            return await ctx.send("Управлять участниками тикета может только его создатель или персонал.", ephemeral=True)

        if isinstance(ctx.channel, discord.TextChannel):
            await ctx.channel.set_permissions(member, view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
            await ctx.send(f"Пользователь {member.mention} добавлен в обращение.")

    # --- ИСКЛЮЧИТЬ УЧАСТНИКА ИЗ ТИКЕТА (МОЖЕТ И АВТОР ТИКЕТА) ---
    @commands.hybrid_command(name="remove", aliases=["удалить", "исключить"], description="Исключить пользователя из текущего тикета")
    @app_commands.describe(member="Пользователь для удаления")
    async def remove_user_cmd(self, ctx: commands.Context, member: discord.Member):
        if not self.db.is_ticket_channel(ctx.channel.id):
            return await ctx.send("Команда доступна только внутри активного тикета.", ephemeral=True, delete_after=5)

        if not can_manage_ticket(ctx, self.db):
            return await ctx.send("Управлять участниками тикета может только его создатель или персонал.", ephemeral=True)

        # Нельзя удалить создателя тикета
        creator_id = self.db.get_ticket_user_id(ctx.channel.id)
        if member.id == creator_id:
            return await ctx.send("Нельзя исключить автора тикета.", ephemeral=True)

        if isinstance(ctx.channel, discord.TextChannel):
            await ctx.channel.set_permissions(member, overwrite=None)
            await ctx.send(f"Пользователь {member.mention} исключен из обращения.")

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


async def setup(bot: commands.Bot):
    db: DatabaseManager = bot.db
    await bot.add_cog(TicketsCog(bot, db))
