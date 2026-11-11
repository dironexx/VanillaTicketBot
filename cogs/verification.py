import asyncio
import logging
from typing import Optional, Union
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
from config import Config
from database import DatabaseManager
from design import AG, Colors
from cogs.tickets import get_spec_role, get_or_create_spec_role, sync_spec_role_to_tickets

logger = logging.getLogger("VanillaBot.Verification")


def get_verified_role(guild: discord.Guild, db: Optional[DatabaseManager] = None) -> Optional[discord.Role]:
    """Возвращает роль верифицированного участника: база данных -> Config -> поиск по имени"""
    if not guild:
        return None
    if db:
        saved = db.get_setting("verified_role_id")
        if saved and saved.isdigit() and int(saved) != 0:
            r = guild.get_role(int(saved))
            if r:
                return r
    if Config.VERIFIED_ROLE_ID:
        r = guild.get_role(Config.VERIFIED_ROLE_ID)
        if r:
            return r
    for role in guild.roles:
        name_lower = role.name.lower().strip()
        if name_lower in ("верифицированный", "верифицирован", "проверен", "проверенный", "verified", "игрок", "участник"):
            if db:
                db.set_setting("verified_role_id", str(role.id))
            return role
    return None


def is_bad_unverified_role(role: Optional[discord.Role]) -> bool:
    """Определяет старые/ошибочные роли вроде unverified/unveriferived для автоматической замены"""
    if not role:
        return False
    name_low = role.name.lower().strip()
    if name_low in ("неверифицирован", "неверифицированный", "не верифицирован"):
        return False
    if role.id == 1473543870397677704:
        return True
    return (
        name_low in (
            "unverified",
            "un-verified",
            "unveriferived",
            "unverifirived",
            "unverifired",
            "unverifered",
            "unverified_old",
        )
        or name_low.startswith("unverif")
    )


def get_unverified_role(guild: discord.Guild, db: Optional[DatabaseManager] = None) -> Optional[discord.Role]:
    """Возвращает роль не верифицированного участника: приоритет у роли с именем 'Неверифицирован'"""
    if not guild:
        return None
    # 1. Поиск по точному названию 'Неверифицирован'
    for role in guild.roles:
        if role.name.strip().lower() in ("неверифицирован", "неверифицированный"):
            return role

    # 2. По сохраненному ID в базе данных
    if db:
        saved = db.get_setting("unverified_role_id")
        if saved and saved.isdigit() and int(saved) != 0:
            r = guild.get_role(int(saved))
            if r and not is_bad_unverified_role(r):
                return r

    # 3. Config
    if Config.UNVERIFIED_ROLE_ID:
        r = guild.get_role(Config.UNVERIFIED_ROLE_ID)
        if r and not is_bad_unverified_role(r):
            return r

    return None


async def get_or_create_unverified_role(guild: discord.Guild, db: Optional[DatabaseManager] = None) -> Optional[discord.Role]:
    """Находит или гарантированно создает роль 'Неверифицирован', переносит участников и удаляет старые роли вроде unverified/unveriferived"""
    if not guild:
        return None

    # 1. Ищем существующую целевую роль 'Неверифицирован'
    target_role: Optional[discord.Role] = None
    for r in guild.roles:
        if r.name.strip().lower() in ("неверифицирован", "неверифицированный"):
            target_role = r
            break

    # 2. Находим старые/ошибочные роли (unverified, unveriferived, ID: 1473543870397677704)
    old_roles: list[discord.Role] = []
    for r in guild.roles:
        if target_role and r.id == target_role.id:
            continue
        if is_bad_unverified_role(r):
            old_roles.append(r)

    # 3. Если роли 'Неверифицирован' еще нет на сервере — создаем её прямо сейчас!
    if not target_role and guild.me.guild_permissions.manage_roles:
        try:
            target_role = await guild.create_role(
                name="Неверифицирован",
                color=discord.Color.from_rgb(140, 140, 140),
                reason="Создание роли для не верифицированных участников",
            )
            logger.info(f"Создана роль '{target_role.name}' ({target_role.id})")
        except Exception as e:
            logger.error(f"Не удалось создать роль 'Неверифицирован': {e}")

    # 4. Если целевая роль готова — обновляем базу данных и переносим участников со старых ролей
    if target_role:
        if db:
            db.set_setting("unverified_role_id", str(target_role.id))
        Config.UNVERIFIED_ROLE_ID = target_role.id

        if guild.me.guild_permissions.manage_roles:
            for old_r in old_roles:
                try:
                    # Переносим всех участников на новую роль
                    for member in old_r.members:
                        if target_role not in member.roles:
                            try:
                                await member.add_roles(target_role, reason="Перенос со старой роли на 'Неверифицирован'")
                            except Exception:
                                pass
                    # Удаляем старую роль
                    await old_r.delete(reason="Авто-удаление старой роли unverified/unveriferived")
                    logger.info(f"Удалена старая роль: {old_r.name} ({old_r.id})")
                except Exception as e:
                    logger.warning(f"Не удалось удалить старую роль {old_r.name}: {e}")

    return target_role


async def setup_unverified_channel_permissions(guild: discord.Guild, unverified_role: discord.Role):
    """Настраивает права: участникам с ролью 'Неверифицирован' виден ТОЛЬКО канал 1555500688715423835"""
    if not guild or not unverified_role or not guild.me.guild_permissions.manage_channels:
        return

    verif_ch_id = getattr(Config, "VERIFICATION_CHANNEL_ID", 1555500688715423835)

    # Ограничиваем конкурентность и защищаем от 429 Too Many Requests
    sem = asyncio.Semaphore(3)

    async def _set_perm(obj, reason):
        try:
            current_ow = obj.overwrites_for(unverified_role)
            # Если канал/категория уже скрыты — пропускаем, чтобы не спамить в API Discord
            if current_ow.view_channel is False:
                return
        except Exception:
            pass

        async with sem:
            try:
                await obj.set_permissions(unverified_role, view_channel=False, reason=reason)
                await asyncio.sleep(0.08)
            except Exception as e:
                logger.error(f"Ошибка настройки прав {obj.name} ({obj.id}): {e}")

    tasks = []
    
    # 1. Скрываем все КАТЕГОРИИ
    for cat in guild.categories:
        tasks.append(_set_perm(cat, "Принудительное скрытие категории для не верифицированных"))

    # 2. Скрываем все КАНАЛЫ (кроме канала верификации)
    for ch in guild.channels:
        if ch.id == verif_ch_id:
            continue
        tasks.append(_set_perm(ch, "Принудительное скрытие канала для не верифицированных"))

    if tasks:
        await asyncio.gather(*tasks)

    # 3. На канале верификации разрешаем просмотр
    verif_ch = guild.get_channel(verif_ch_id)
    if verif_ch:
        try:
            current_ow = verif_ch.overwrites_for(unverified_role)
            if current_ow.view_channel is not True or current_ow.send_messages is not False:
                await verif_ch.set_permissions(
                    unverified_role,
                    view_channel=True,
                    read_message_history=True,
                    send_messages=False,
                    reason="Разрешение доступа к каналу верификации",
                )
        except Exception as e:
            logger.error(f"Ошибка настройки канала верификации {verif_ch_id}: {e}")



def get_mute_role(guild: discord.Guild, db: Optional[DatabaseManager] = None) -> Optional[discord.Role]:
    """Возвращает роль мута: база данных -> Config -> поиск по имени"""
    if not guild:
        return None
    if db:
        saved = db.get_setting("mute_role_id")
        if saved and saved.isdigit() and int(saved) != 0:
            r = guild.get_role(int(saved))
            if r:
                return r
    if Config.MUTE_ROLE_ID:
        r = guild.get_role(Config.MUTE_ROLE_ID)
        if r:
            return r
    for role in guild.roles:
        name_lower = role.name.lower().strip()
        if name_lower in ("мут", "мьют", "muted", "mute", "заглушен"):
            if db:
                db.set_setting("mute_role_id", str(role.id))
            return role
    return None


async def grant_verified_role(member: discord.Member, guild: discord.Guild, db: Optional[DatabaseManager], interaction: discord.Interaction):
    """Атомарная выдача роли верифицированного, удаление unverified и сохранение мута"""
    verified_role = get_verified_role(guild, db)
    unverified_role = get_unverified_role(guild, db)

    if not verified_role:
        msg = "Роль верифицированного участника не найдена на сервере. Обратитесь к администрации."
        if interaction.response.is_done():
            return await interaction.followup.send(msg, ephemeral=True)
        return await interaction.response.send_message(msg, ephemeral=True)

    if verified_role in member.roles:
        msg = "Вы уже успешно прошли верификацию!"
        if interaction.response.is_done():
            return await interaction.followup.send(msg, ephemeral=True)
        return await interaction.response.send_message(msg, ephemeral=True)

    if guild.me.top_role <= verified_role:
        logger.error(
            f"Ошибка верификации: роль бота ({guild.me.top_role.name}) находится ниже роли "
            f"верификации ({verified_role.name}) в настройках Discord!"
        )
        msg = (
            "Ошибка прав доступа: роль бота в настройках сервера (Настройки сервера -> Роли) "
            f"должна находиться **выше** роли «{verified_role.name}». Обратитесь к администрации."
        )
        if interaction.response.is_done():
            return await interaction.followup.send(msg, ephemeral=True)
        return await interaction.response.send_message(msg, ephemeral=True)

    try:
        new_roles = [r for r in member.roles if unverified_role is None or r.id != unverified_role.id]
        if verified_role not in new_roles:
            new_roles.append(verified_role)

        if db and db.is_user_muted(member.id, guild.id):
            mute_role = get_mute_role(guild, db)
            if mute_role and mute_role not in new_roles:
                new_roles.append(mute_role)

        await member.edit(roles=new_roles, reason="Успешное прохождение верификации")

        success_msg = "**Верификация успешно пройдена!**\nВам открыт доступ ко всем каналам Vanilla Land. Приятной игры!"
        if interaction.response.is_done():
            await interaction.followup.send(success_msg, ephemeral=True)
        else:
            await interaction.response.send_message(success_msg, ephemeral=True)
        logger.info(f"Верификация успешно пройдена: {member} ({member.id})")
    except discord.Forbidden:
        fail_msg = "У бота нет прав управлять этой ролью (роль бота должна быть выше в списке ролей Discord)."
        if interaction.response.is_done():
            await interaction.followup.send(fail_msg, ephemeral=True)
        else:
            await interaction.response.send_message(fail_msg, ephemeral=True)
    except Exception as e:
        logger.error(f"Ошибка верификации {member.id}: {e}")
        err_msg = "Произошла ошибка при выдаче роли. Попробуйте еще раз."
        if interaction.response.is_done():
            await interaction.followup.send(err_msg, ephemeral=True)
        else:
            await interaction.response.send_message(err_msg, ephemeral=True)


class VerificationView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="Пройти верификацию",
        style=discord.ButtonStyle.secondary,
        custom_id="persistent_verify_btn",
    )
    async def verify_button(self, interaction: discord.Interaction, button: ui.Button):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Ошибка: действие доступно только на сервере.", ephemeral=True)

        member = interaction.user
        if not isinstance(member, discord.Member):
            member = guild.get_member(interaction.user.id) or await guild.fetch_member(interaction.user.id)

        if not member:
            return await interaction.response.send_message("Не удалось определить ваш профиль на сервере.", ephemeral=True)

        db: Optional[DatabaseManager] = getattr(interaction.client, "db", None)

        # 1. Проверка активного локдауна верификации (Anti-Raid Lockdown)
        lockdown_enabled = (db.get_setting("verification_lockdown_enabled") == "true") if db else False
        if lockdown_enabled:
            reason = db.get_setting("verification_lockdown_reason") if db else ""
            if not reason:
                reason = "Рейд ботов. Вход временно закрыт до стабилизации ситуации."

            embed = discord.Embed(
                title="🛑 Верификация временно приостановлена",
                description=(
                    f"**Причина:** {reason}\n\n"
                    "*На сервере действует защитный режим. Пожалуйста, подождите, пока администрация возобновит приём новых участников.*"
                ),
                color=Colors.RED,
            )
            embed.set_footer(text="Vanilla Land • Защита сервера")
            await interaction.response.send_message(embed=embed, ephemeral=True)

            try:
                mod_log_ch_id = getattr(Config, "MOD_LOG_CHANNEL_ID", None)
                if mod_log_ch_id:
                    ch = guild.get_channel(mod_log_ch_id)
                    if ch and isinstance(ch, discord.TextChannel):
                        await ch.send(f"⚠️ **Локдаун:** {member.mention} (`{member.id}`) пытался верифицироваться во время блокировки.")
            except Exception:
                pass
            return

        verified_role = get_verified_role(guild, db)
        if verified_role and verified_role in member.roles:
            return await interaction.response.send_message(
                "Вы уже успешно прошли верификацию!",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        await grant_verified_role(member, guild, db, interaction)


class VerificationCog(commands.Cog, name="Верификация"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: Optional[DatabaseManager] = getattr(bot, "db", None)
        self.auto_sync_roles_loop.start()
        asyncio.create_task(self.init_verification_on_start())

    def cog_unload(self):
        self.auto_sync_roles_loop.cancel()

    async def init_verification_on_start(self):
        """Автоматическая инициализация роли, изоляции каналов и панели верификации при старте"""
        await self.bot.wait_until_ready()
        await asyncio.sleep(2)
        for guild in self.bot.guilds:
            try:
                db = self.db or getattr(self.bot, "db", None)
                unverified_role = await get_or_create_unverified_role(guild, db)
                if unverified_role:
                    await setup_unverified_channel_permissions(guild, unverified_role)
                await self.ensure_verify_panel_posted(guild)
            except Exception as e:
                logger.warning(f"Ошибка при инициализации верификации в {guild.name}: {e}")

    async def ensure_verify_panel_posted(self, guild: discord.Guild):
        """Проверяет наличие интерактивной панели верификации в канале 1555500688715423835 и отправляет её, если нет"""
        verif_ch_id = getattr(Config, "VERIFICATION_CHANNEL_ID", 1555500688715423835)
        verif_ch = guild.get_channel(verif_ch_id)
        if not verif_ch or not isinstance(verif_ch, discord.TextChannel):
            return

        has_panel = False
        try:
            async for msg in verif_ch.history(limit=25):
                if msg.author.id == self.bot.user.id and msg.components:
                    for comp_row in msg.components:
                        for item in comp_row.children:
                            if getattr(item, "custom_id", None) == "persistent_verify_btn":
                                has_panel = True
                                break
                    if has_panel:
                        break
        except Exception as e:
            logger.debug(f"Не удалось прочитать историю канала верификации {verif_ch_id}: {e}")

        if not has_panel and verif_ch.permissions_for(guild.me).send_messages:
            try:
                guild_icon = guild.icon.url if guild.icon else None
                embed = AG.embed(
                    title="Верификация • Vanilla Land",
                    description=(
                        "Добро пожаловать на наш сервер ванильного выживания!\n\n"
                        "Нажмите на кнопку **«Пройти верификацию»** ниже, чтобы получить доступ ко всем каналам сервера."
                    ),
                    color=Colors.DARK,
                    footer="Vanilla Land",
                    footer_icon=guild_icon,
                    thumbnail=guild_icon,
                )
                await verif_ch.send(embed=embed, view=VerificationView())
                logger.info(f"Панель верификации автоматически размещена в канале {verif_ch.name} ({verif_ch.id})")
            except Exception as e:
                logger.error(f"Не удалось опубликовать панель верификации в {verif_ch.name}: {e}")

    # --- АВТОМАТИЧЕСКАЯ ВЫДАЧА РОЛИ НЕ ВЕРИФИЦИРОВАННОГО ПРИ ВХОДЕ ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild
        db = self.db or getattr(self.bot, "db", None)

        # 1. Защита от обхода мута при перезаходе (Mute Evasion)
        if db and db.is_user_muted(member.id, guild.id):
            mute_role = get_mute_role(guild, db)
            if mute_role and guild.me.top_role > mute_role:
                try:
                    await member.add_roles(mute_role, reason="Восстановление активного мута при перезаходе (Mute Evasion)")
                    logger.info(f"Восстановлен мут для перезашедшего участника: {member} ({member.id})")
                except Exception as e:
                    logger.warning(f"Не удалось восстановить мут для {member.id}: {e}")

        # 2. Если у участника уже есть роль верифицированного — не выдаем не верифицированного
        verified_role = get_verified_role(guild, db)
        if verified_role and verified_role in member.roles:
            return

        # 3. Поиск/создание роли не верифицированного и выдача
        unverified_role = await get_or_create_unverified_role(guild, db)
        if not unverified_role or unverified_role in member.roles:
            return

        if guild.me.top_role <= unverified_role:
            logger.error(
                f"Невозможно выдать роль '{unverified_role.name}' участнику {member}: "
                f"роль бота '{guild.me.top_role.name}' находится НИЖЕ в списке ролей Discord!"
            )
            return

        try:
            await member.add_roles(unverified_role, reason="Авто-выдача роли не верифицированного при входе")
            logger.info(f"Автоматически выдана роль '{unverified_role.name}' новому участнику {member} ({member.id})")
        except discord.Forbidden:
            logger.error(f"Недостаточно прав (Forbidden) для выдачи роли {unverified_role.name} участнику {member.id}")
        except Exception as e:
            logger.error(f"Ошибка при выдаче роли не верифицированного участнику {member.id}: {e}")

    # --- ВЫДАЧА РОЛИ ПОСЛЕ ПРИНЯТИЯ ПРАВИЛ DISCORD (ONBOARDING / SCREENING) ---
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.bot:
            return

        # Пользователь завершил Onboarding / Membership Screening
        if before.pending and not after.pending:
            guild = after.guild
            db = self.db or getattr(self.bot, "db", None)
            verified_role = get_verified_role(guild, db)

            if verified_role and verified_role in after.roles:
                return

            unverified_role = await get_or_create_unverified_role(guild, db)
            if unverified_role and unverified_role not in after.roles:
                if guild.me.top_role > unverified_role and guild.me.guild_permissions.manage_roles:
                    try:
                        await after.add_roles(unverified_role, reason="Авто-выдача роли не верифицированного после прохождения онбординга")
                        logger.info(f"Выдана роль не верифицированного после онбординга: {after} ({after.id})")
                    except Exception as e:
                        logger.warning(f"Ошибка выдачи роли после онбординга {after.id}: {e}")

    # --- FALLBACK НА СООБЩЕНИЯ (ДЛЯ ТЕХ, КТО ПРОСКОЧИЛ БЕЗ РОЛЕЙ) ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        member = message.author
        if not isinstance(member, discord.Member) or member.pending:
            return
        db = self.db or getattr(self.bot, "db", None)
        verified_role = get_verified_role(message.guild, db)
        unverified_role = get_unverified_role(message.guild, db)
        if not unverified_role or message.guild.me.top_role <= unverified_role:
            return
        has_v = verified_role and verified_role in member.roles
        has_u = unverified_role in member.roles
        if not has_v and not has_u and len(member.roles) <= 1:
            try:
                await member.add_roles(unverified_role, reason="Авто-выдача роли не верифицированного при активности")
            except Exception:
                pass

    # --- ИЗОЛЯЦИЯ НОВЫХ КАНАЛОВ ДЛЯ НЕ ВЕРИФИЦИРОВАННЫХ ---
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        if not guild.me.guild_permissions.manage_channels:
            return
        verif_ch_id = getattr(Config, "VERIFICATION_CHANNEL_ID", 1555500688715423835)
        if channel.id == verif_ch_id:
            return
        db = self.db or getattr(self.bot, "db", None)
        unverified_role = get_unverified_role(guild, db)
        if unverified_role:
            try:
                if isinstance(channel, discord.CategoryChannel) or channel.category is None:
                    await channel.set_permissions(unverified_role, view_channel=False, reason="Изоляция нового канала от не верифицированных")
            except Exception as e:
                logger.debug(f"Ошибка настройки прав нового канала {channel.name}: {e}")

    # --- ФОНОВЫЙ АУДИТ И СИНХРОНИЗАЦИЯ КАЖДЫЕ 5 МИНУТ ---
    @tasks.loop(minutes=5)
    async def auto_sync_roles_loop(self):
        try:
            for guild in self.bot.guilds:
                if not guild.me.guild_permissions.manage_roles:
                    continue
                db = self.db or getattr(self.bot, "db", None)
                unverified_role = await get_or_create_unverified_role(guild, db)
                verified_role = get_verified_role(guild, db)
                if not unverified_role or guild.me.top_role <= unverified_role:
                    continue

                for member in guild.members:
                    if member.bot or member.pending:
                        continue
                    has_v = verified_role and verified_role in member.roles
                    has_u = unverified_role in member.roles
                    if not has_v and not has_u and len(member.roles) <= 1:
                        try:
                            await member.add_roles(unverified_role, reason="Фоновый аудит: авто-выдача роли не верифицированного")
                            logger.info(f"Фоновый аудит: выдана роль {unverified_role.name} участнику {member} ({member.id})")
                        except Exception as e:
                            logger.warning(f"Ошибка фоновой выдачи роли {member.id}: {e}")
        except Exception as e:
            logger.error(f"Ошибка в auto_sync_roles_loop: {e}")

    @auto_sync_roles_loop.before_loop
    async def before_auto_sync_roles_loop(self):
        await self.bot.wait_until_ready()

    # --- ПАНЕЛЬ ВЕРИФИКАЦИИ ---
    @commands.command(name="verify_panel", aliases=["панель_верификации", "верификация_панель"])
    @commands.has_permissions(administrator=True)
    async def send_verify_panel(self, ctx: commands.Context):
        guild_icon = ctx.guild.icon.url if ctx.guild and ctx.guild.icon else None
        embed = AG.embed(
            title="Верификация • Vanilla Land",
            description=(
                "Добро пожаловать на наш сервер ванильного выживания!\n\n"
                "Нажмите на кнопку **«Пройти верификацию»** ниже, чтобы получить доступ ко всем каналам сервера."
            ),
            color=Colors.DARK,
            footer="Vanilla Land",
            footer_icon=guild_icon,
            thumbnail=guild_icon,
        )

        await ctx.send(embed=embed, view=VerificationView())
        try:
            await ctx.message.delete()
        except Exception:
            pass

    # --- СИНХРОНИЗАЦИЯ РОЛЕЙ ДЛЯ ВСЕХ ТЕКУЩИХ УЧАСТНИКОВ ---
    @commands.hybrid_command(
        name="sync_roles",
        aliases=[
            "синхронизация_ролей",
            "выдать_роли",
            "sync_unverified",
            "create_unverified_role",
            "создать_неверифицирован",
            "fix_roles",
        ],
        description="Создать роль Неверифицирован, удалить старые роли, выдать всем без ролей и настроить права",
    )
    @commands.has_permissions(administrator=True)
    async def sync_roles_cmd(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()

        guild = ctx.guild
        if not guild:
            return await ctx.send("Команда доступна только на сервере.", ephemeral=True)

        db = self.db or getattr(self.bot, "db", None)
        unverified_role = await get_or_create_unverified_role(guild, db)
        verified_role = get_verified_role(guild, db)
        mute_role = get_mute_role(guild, db)

        if unverified_role:
            await setup_unverified_channel_permissions(guild, unverified_role)

        if not unverified_role:
            return await ctx.send(
                "Роль не верифицированного не найдена. Укажите её через `!set_unverified_role @роль`.",
                ephemeral=True,
            )

        if guild.me.top_role <= unverified_role:
            return await ctx.send(
                f"Роль бота ({guild.me.top_role.mention}) находится ниже роли не верифицированного ({unverified_role.mention}). "
                "Переместите роль бота выше в Настройки сервера -> Роли.",
                ephemeral=True,
            )

        status_msg = await ctx.send("Проверка и синхронизация ролей участников сервера...")

        count_unverified = 0
        count_muted = 0
        skipped = 0

        for member in guild.members:
            if member.bot:
                continue

            # 1. Восстановление мута
            if db and db.is_user_muted(member.id, guild.id):
                if mute_role and mute_role not in member.roles and guild.me.top_role > mute_role:
                    try:
                        await member.add_roles(mute_role, reason="Синхронизация активного мута")
                        count_muted += 1
                    except Exception:
                        pass

            # 2. Проверка верификации
            has_verified = verified_role and verified_role in member.roles
            has_unverified = unverified_role in member.roles

            if not has_verified and not has_unverified:
                try:
                    await member.add_roles(unverified_role, reason="Синхронизация роли не верифицированного")
                    count_unverified += 1
                except Exception as e:
                    logger.warning(f"Ошибка выдачи роли {member.id}: {e}")
            else:
                skipped += 1

        # 3. Синхронизация роли спека для тикетов
        spec_sync_str = ""
        try:
            spec_role = await get_or_create_spec_role(guild, db)
            if spec_role:
                await sync_spec_role_to_tickets(guild, spec_role, db)
                spec_sync_str = f"\n• Синхронизирована роль {spec_role.mention} (доступ к тикетам)"
        except Exception as e:
            logger.debug(f"Ошибка синхронизации роли спека в sync_roles: {e}")

        embed = discord.Embed(
            title="Синхронизация ролей завершена",
            description=(
                f"• Выдана роль {unverified_role.mention}: **{count_unverified}** участникам\n"
                f"• Восстановлен мут: **{count_muted}** участникам\n"
                f"• Уже имели роли: **{skipped}** участников"
                f"{spec_sync_str}"
            ),
            color=Colors.GREEN,
        )
        embed.set_footer(text="Vanilla Land • Управление ролями")
        await status_msg.edit(content=None, embed=embed)

    # --- СТАТУС РОЛЕЙ И ИЕРАРХИИ БОТА ---
    @commands.hybrid_command(
        name="roles_info",
        aliases=["роли_статус", "роли", "roles_status"],
        description="Проверить привязку ролей (верификация, мут, спек) и иерархию прав бота",
    )
    @commands.has_permissions(administrator=True)
    async def roles_info_cmd(self, ctx: commands.Context):
        guild = ctx.guild
        if not guild:
            return

        db = self.db or getattr(self.bot, "db", None)
        unverified_role = get_unverified_role(guild, db)
        verified_role = get_verified_role(guild, db)
        mute_role = get_mute_role(guild, db)
        spec_role = get_spec_role(guild, db)

        bot_role = guild.me.top_role
        bot_pos = bot_role.position

        def format_role_status(r: Optional[discord.Role]) -> str:
            if not r:
                return "**[Не найдена]** *(настройте через !set_...)*"
            if bot_pos <= r.position:
                return f"{r.mention} `(ID: {r.id})`\n**[Внимание] Роль бота ниже этой роли**"
            return f"{r.mention} `(ID: {r.id})` — Управляется ботом"

        embed = discord.Embed(
            title="Статус и привязка системных ролей",
            description=f"**Высшая роль бота:** {bot_role.mention} *(позиция: #{bot_pos})*\n",
            color=Colors.BLUE,
        )
        embed.add_field(name="Роль не верифицированного", value=format_role_status(unverified_role), inline=False)
        embed.add_field(name="Роль верифицированного", value=format_role_status(verified_role), inline=False)
        embed.add_field(name="Роль мута", value=format_role_status(mute_role), inline=False)
        embed.add_field(name="Роль наблюдателя (Спек)", value=format_role_status(spec_role), inline=False)

        embed.add_field(
            name="Команды быстрой настройки",
            value=(
                "• `!set_unverified_role @роль` — привязать роль не верифицированного\n"
                "• `!set_verified_role @роль` — привязать роль верифицированного\n"
                "• `!set_mute_role @роль` — привязать роль мута\n"
                "• `!set_spec_role @роль` — привязать роль спека\n"
                "• `!spec_role` — создать/настроить роль спека и синхронизировать тикеты\n"
                "• `!sync_roles` — выдать роль не верифицированного и обновить доступы"
            ),
            inline=False,
        )
        embed.set_footer(text="Vanilla Land • Настройки ролей")
        await ctx.send(embed=embed)

    # --- НАСТРОЙКА РОЛЕЙ В БД ---
    @commands.hybrid_command(
        name="set_unverified_role",
        aliases=["сет_анверифед", "роль_неверифицированного"],
        description="Установить роль не верифицированного участника",
    )
    @app_commands.describe(role="Роль для не верифицированных участников")
    @commands.has_permissions(administrator=True)
    async def set_unverified_role_cmd(self, ctx: commands.Context, role: discord.Role):
        db = self.db or getattr(self.bot, "db", None)
        if db:
            db.set_setting("unverified_role_id", str(role.id))
        embed = discord.Embed(
            title="Роль не верифицированного обновлена",
            description=f"Новая роль: {role.mention} `(ID: {role.id})`\nТеперь все новые участники получают эту роль при входе.",
            color=Colors.GREEN,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="set_verified_role",
        aliases=["сет_верифед", "роль_верифицированного"],
        description="Установить роль верифицированного участника",
    )
    @app_commands.describe(role="Роль для верифицированных участников")
    @commands.has_permissions(administrator=True)
    async def set_verified_role_cmd(self, ctx: commands.Context, role: discord.Role):
        db = self.db or getattr(self.bot, "db", None)
        if db:
            db.set_setting("verified_role_id", str(role.id))
        embed = discord.Embed(
            title="Роль верифицированного обновлена",
            description=f"Новая роль: {role.mention} `(ID: {role.id})`\nЭту роль бот выдаёт при нажатии кнопки верификации.",
            color=Colors.GREEN,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="set_mute_role",
        aliases=["сет_мут", "роль_мута"],
        description="Установить роль мута",
    )
    @app_commands.describe(role="Роль для замученных участников")
    @commands.has_permissions(administrator=True)
    async def set_mute_role_cmd(self, ctx: commands.Context, role: discord.Role):
        db = self.db or getattr(self.bot, "db", None)
        if db:
            db.set_setting("mute_role_id", str(role.id))
        embed = discord.Embed(
            title="Роль мута обновлена",
            description=f"Новая роль: {role.mention} `(ID: {role.id})`\nЭту роль бот выдаёт при командах !mute.",
            color=Colors.GREEN,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="set_spec_role",
        aliases=["сет_спек", "роль_спека_привязать"],
        description="Установить роль наблюдателя тикетов (Спек)",
    )
    @app_commands.describe(role="Роль для наблюдателей тикетов")
    @commands.has_permissions(administrator=True)
    async def set_spec_role_cmd(self, ctx: commands.Context, role: discord.Role):
        db = self.db or getattr(self.bot, "db", None)
        if db:
            db.set_setting("spec_role_id", str(role.id))
        Config.SPEC_ROLE_ID = role.id
        if ctx.guild and db:
            await sync_spec_role_to_tickets(ctx.guild, role, db)
        embed = discord.Embed(
            title="Роль Спека обновлена",
            description=f"Новая роль: {role.mention} `(ID: {role.id})`\nОбладатели этой роли получают доступ ко всем тикетам и управлению ими.",
            color=Colors.GREEN,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="verification_lockdown",
        aliases=["локдаун", "рейд_стоп", "lockdown", "вериф_локдаун"],
        description="Экстренно приостановить или возобновить верификацию новых участников сервера",
    )
    @app_commands.describe(
        action="Действие: включить локдаун (приостановить) или выключить (возобновить)",
        reason="Обязательная причина при приостановке верификации (например: Рейд ботов)",
    )
    @commands.has_permissions(administrator=True)
    async def verification_lockdown_cmd(self, ctx: commands.Context, action: str, *, reason: Optional[str] = None):
        db = self.db or getattr(self.bot, "db", None)
        if not db:
            return await ctx.send("Ошибка: база данных недоступна.", ephemeral=True)

        is_enable = action.lower().strip() in ("включить", "вкл", "приостановить", "lock", "on", "enable", "true", "1")
        if is_enable:
            if not reason or not reason.strip():
                return await ctx.send(
                    "❌ **Ошибка:** При включении локдауна **обязательно** укажите причину!\n"
                    "Пример: `/verification_lockdown action:Включить reason:Рейд ботов. Вход временно закрыт.`",
                    ephemeral=True,
                )
            clean_reason = reason.strip()
            db.set_setting("verification_lockdown_enabled", "true")
            db.set_setting("verification_lockdown_reason", clean_reason)
            db.set_setting("verification_lockdown_by", str(ctx.author))
            from database import get_msk_now_str
            db.set_setting("verification_lockdown_at", get_msk_now_str())

            embed = discord.Embed(
                title="🛑 Локдаун верификации ВКЛЮЧЕН",
                description=(
                    "**Верификация новых участников временно заблокирована!**\n\n"
                    f"**Причина:** {clean_reason}\n"
                    f"**Инициатор:** {ctx.author.mention}\n"
                    f"**Время:** `{get_msk_now_str()}`\n\n"
                    "*При нажатии на кнопку верификации участникам будет показываться указанная причина.*"
                ),
                color=Colors.RED,
            )
            embed.set_footer(text="Vanilla Land • Защита от рейдов")
            await ctx.send(embed=embed)
        else:
            db.set_setting("verification_lockdown_enabled", "false")
            db.set_setting("verification_lockdown_reason", "")
            from database import get_msk_now_str
            embed = discord.Embed(
                title="✅ Локдаун верификации ВЫКЛЮЧЕН",
                description=(
                    "**Верификация новых участников возобновлена в штатном режиме.**\n"
                    f"**Снял ограничение:** {ctx.author.mention}\n"
                    f"**Время:** `{get_msk_now_str()}`"
                ),
                color=Colors.GREEN,
            )
            embed.set_footer(text="Vanilla Land • Защита от рейдов")
            await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationCog(bot))
