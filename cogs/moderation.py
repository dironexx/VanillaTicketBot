import asyncio
import logging
import re
import time
from datetime import timedelta
from typing import Optional, Union

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import Config
from database import DatabaseManager
from design import AG, Colors
from cogs.verification import get_mute_role

logger = logging.getLogger("VanillaBot.Moderation")

TIME_REGEX = re.compile(r"^(\d+)([smhdw])$", re.IGNORECASE)
TIME_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
TIME_NAMES = {"s": "сек.", "m": "мин.", "h": "ч.", "d": "дн.", "w": "нед."}


def parse_duration(duration_str: str) -> Optional[tuple[int, str]]:
    if not duration_str:
        return None
    match = TIME_REGEX.match(duration_str.strip())
    if not match:
        # Если просто число секунд
        if duration_str.strip().isdigit():
            val = int(duration_str.strip())
            return val, f"{val} сек."
        return None
    val, unit = match.groups()
    val = int(val)
    unit = unit.lower()
    return val * TIME_MULTIPLIERS[unit], f"{val} {TIME_NAMES[unit]}"


def is_mod_or_admin(ctx_or_interaction) -> bool:
    """Строгая проверка: роли из MOD_ROLE_IDS или владелец/администратор"""
    user = ctx_or_interaction.user if hasattr(ctx_or_interaction, "user") else ctx_or_interaction.author
    if not isinstance(user, discord.Member):
        return False
    guild = ctx_or_interaction.guild
    if user.guild_permissions.administrator or (guild and user.id == guild.owner_id):
        return True
    user_roles = {r.id for r in user.roles}
    return any(r_id in user_roles for r_id in Config.MOD_ROLE_IDS)


async def send_dm_notification(
    user_or_member: Union[discord.Member, discord.User],
    action: str,
    guild_name: str,
    reason: str,
    moderator_name: str,
    duration: Optional[str] = None,
):
    try:
        embed = AG.embed(
            title=f"Уведомление • {guild_name}",
            color=Colors.YELLOW,
            footer="Vanilla Land • Модерация",
        )
        embed.add_field(name="Наказание", value=action, inline=True)
        if duration:
            embed.add_field(name="Длительность", value=f"`{duration}`", inline=True)
        embed.add_field(name="Модератор", value=moderator_name, inline=True)
        embed.add_field(name="Причина", value=reason or "Не указана", inline=False)
        await user_or_member.send(embed=embed)
    except discord.Forbidden:
        pass
    except Exception as e:
        logger.error(f"Ошибка при отправке ЛС {user_or_member}: {e}")


async def extract_target_from_ctx(ctx: commands.Context) -> Optional[discord.Member]:
    if ctx.message.reference and ctx.message.reference.message_id:
        try:
            ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if isinstance(ref_msg.author, discord.Member):
                return ref_msg.author
            elif isinstance(ref_msg.author, discord.User) and ctx.guild:
                m = ctx.guild.get_member(ref_msg.author.id)
                if not m:
                    try:
                        m = await ctx.guild.fetch_member(ref_msg.author.id)
                    except Exception:
                        pass
                return m
        except Exception:
            pass
    return None


class ModerationCog(commands.Cog, name="Модерация"):
    def __init__(self, bot: commands.Bot, db: DatabaseManager):
        self.bot = bot
        self.db = db
        self.auto_unmute_loop.start()
        self.auto_vc_unban_loop.start()

    def cog_unload(self):
        self.auto_unmute_loop.cancel()
        self.auto_vc_unban_loop.cancel()

    # --- АВТО-РАЗМУТ ---
    @tasks.loop(seconds=30)
    async def auto_unmute_loop(self):
        try:
            now_ts = time.time()
            expired = self.db.get_expired_mutes(now_ts)

            for user_id, guild_id, reason in expired:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    self.db.delete_mute(user_id, guild_id)
                    continue

                member = guild.get_member(user_id)
                if not member:
                    try:
                        member = await guild.fetch_member(user_id)
                    except (discord.NotFound, discord.HTTPException):
                        member = None

                mute_role = get_mute_role(guild, self.db)

                if member and mute_role and mute_role in member.roles:
                    try:
                        await member.remove_roles(mute_role, reason="Время мута истекло")
                        if member.is_timed_out():
                            await member.timeout(None, reason="Время мута истекло")
                        logger.info(f"Авто-размут: {member} ({user_id})")
                    except Exception as e:
                        logger.error(f"Ошибка авто-размута {user_id}: {e}")

                self.db.delete_mute(user_id, guild_id)
        except Exception as e:
            logger.error(f"Ошибка в auto_unmute_loop: {e}")

    @auto_unmute_loop.before_loop
    async def before_auto_unmute(self):
        await self.bot.wait_until_ready()

    # --- АВТО-РАЗБАН ГОЛОСА (VC UNBAN) ---
    @tasks.loop(seconds=30)
    async def auto_vc_unban_loop(self):
        try:
            now_ts = time.time()
            expired = self.db.get_expired_vc_bans(now_ts)

            for user_id, guild_id, reason in expired:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    self.db.delete_vc_ban(user_id, guild_id)
                    continue

                member = guild.get_member(user_id)
                if not member:
                    try:
                        member = await guild.fetch_member(user_id)
                    except (discord.NotFound, discord.HTTPException):
                        member = None

                if member:
                    for vc in guild.voice_channels:
                        if member in vc.overwrites:
                            try:
                                await vc.set_permissions(member, overwrite=None, reason="Время бана в войсе истекло")
                            except Exception:
                                pass
                self.db.delete_vc_ban(user_id, guild_id)
        except Exception as e:
            logger.error(f"Ошибка в auto_vc_unban_loop: {e}")

    @auto_vc_unban_loop.before_loop
    async def before_auto_vc_unban(self):
        await self.bot.wait_until_ready()

    # --- MUTE ---
    @commands.hybrid_command(name="mute", aliases=["мут"], description="Замутить пользователя")
    @app_commands.describe(target="Пользователь для мута", duration="Длительность (10m, 2h, 1d)", reason="Причина (не обязательно)")
    async def mute_cmd(
        self,
        ctx: commands.Context,
        target: Optional[discord.Member] = None,
        duration: Optional[str] = "15m",
        *,
        reason: Optional[str] = "Не указана",
    ):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        if target is None:
            target = await extract_target_from_ctx(ctx)

        if target is None:
            return await ctx.send("Укажите пользователя (@упоминание) или ответьте на его сообщение командой `!mute [время] [причина]`.", ephemeral=True)

        if target.id == ctx.author.id:
            return await ctx.send("Вы не можете замутить себя.", ephemeral=True)
        if target.id == self.bot.user.id:
            return await ctx.send("Вы не можете замутить бота.", ephemeral=True)
        if target.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("Роль этого пользователя равна или выше вашей в иерархии.", ephemeral=True)

        parsed = parse_duration(duration or "15m")
        if not parsed:
            actual_reason = f"{duration} {reason}".strip() if reason != "Не указана" else duration
            parsed = (900, "15 мин.")
        else:
            actual_reason = reason or "Не указана"

        sec, human_time = parsed
        unmute_ts = time.time() + sec

        mute_role = get_mute_role(ctx.guild, self.db)
        if not mute_role:
            return await ctx.send("Роль мута не найдена на сервере! Привяжите её через `!set_mute_role @роль`.", ephemeral=True)

        if ctx.guild.me.top_role <= mute_role:
            return await ctx.send(
                f"Роль бота ({ctx.guild.me.top_role.mention}) находится ниже или равна роли мута ({mute_role.mention}) в настройках Discord! "
                "Переместите роль бота выше роли мута в Настройки сервера -> Роли.",
                ephemeral=True,
            )

        await send_dm_notification(target, "Мут", ctx.guild.name, actual_reason, ctx.author.name, human_time)

        try:
            await target.add_roles(mute_role, reason=f"Мут от {ctx.author.name}: {actual_reason} ({human_time})")
            if sec <= 2419200:
                try:
                    await target.timeout(timedelta(seconds=sec), reason=f"Мут: {actual_reason}")
                except Exception:
                    pass
        except discord.Forbidden:
            return await ctx.send("У бота нет прав управлять этой ролью (роль бота должна быть выше).", ephemeral=True)

        self.db.save_mute(target.id, ctx.guild.id, unmute_ts, actual_reason)

        embed = AG.mod_action(
            action="Мут участника",
            target_str=f"{target.mention} (`{target.id}`)",
            moderator_str=ctx.author.mention,
            duration=human_time,
            reason=actual_reason,
            color=Colors.YELLOW,
            icon=target.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # --- UNMUTE ---
    @commands.hybrid_command(name="unmute", aliases=["размут"], description="Снять мут")
    @app_commands.describe(target="Пользователь для размута", reason="Причина (не обязательно)")
    async def unmute_cmd(self, ctx: commands.Context, target: Optional[discord.Member] = None, *, reason: Optional[str] = "Не указана"):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        if target is None:
            target = await extract_target_from_ctx(ctx)

        if target is None:
            return await ctx.send("Укажите пользователя для размута.", ephemeral=True)

        actual_reason = reason or "Не указана"
        mute_role = get_mute_role(ctx.guild, self.db)
        has_role = mute_role and mute_role in target.roles
        is_in_db = self.db.is_user_muted(target.id, ctx.guild.id)

        if not has_role and not is_in_db and not target.is_timed_out():
            return await ctx.send(f"Пользователь {target.mention} не находится в муте.", ephemeral=True)

        if mute_role and mute_role in target.roles:
            try:
                await target.remove_roles(mute_role, reason=f"Размут от {ctx.author.name}: {actual_reason}")
            except discord.Forbidden:
                return await ctx.send("У бота нет прав на снятие роли мута.", ephemeral=True)

        if target.is_timed_out():
            try:
                await target.timeout(None, reason=f"Размут от {ctx.author.name}")
            except Exception:
                pass

        self.db.delete_mute(target.id, ctx.guild.id)

        try:
            embed_dm = AG.embed(
                title=f"Снятие мута • {ctx.guild.name}",
                color=Colors.GREEN,
                footer="Vanilla Land • Модерация",
            )
            embed_dm.add_field(name="Модератор", value=ctx.author.name, inline=True)
            embed_dm.add_field(name="Причина", value=actual_reason, inline=False)
            await target.send(embed=embed_dm)
        except Exception:
            pass

        embed = AG.mod_action(
            action="Снятие мута",
            target_str=f"{target.mention} (`{target.id}`)",
            moderator_str=ctx.author.mention,
            reason=actual_reason,
            color=Colors.GREEN,
            icon=target.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # --- KICK ---
    @commands.hybrid_command(name="kick", aliases=["кик"], description="Выгнать пользователя")
    @app_commands.describe(target="Пользователь для кика", reason="Причина (не обязательно)")
    async def kick_cmd(self, ctx: commands.Context, target: Optional[discord.Member] = None, *, reason: Optional[str] = "Не указана"):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        if target is None:
            target = await extract_target_from_ctx(ctx)

        if target is None:
            return await ctx.send("Укажите пользователя (@упоминание) или ответьте на его сообщение командой `!kick [причина]`.", ephemeral=True)

        if target.id == ctx.author.id:
            return await ctx.send("Вы не можете кикнуть себя.", ephemeral=True)
        if target.id == self.bot.user.id:
            return await ctx.send("Вы не можете кикнуть бота.", ephemeral=True)
        if target.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("Роль этого пользователя равна или выше вашей в иерархии.", ephemeral=True)

        actual_reason = reason or "Не указана"
        await send_dm_notification(target, "Кик", ctx.guild.name, actual_reason, ctx.author.name)

        try:
            await target.kick(reason=f"Кик от {ctx.author.name}: {actual_reason}")
        except discord.Forbidden:
            return await ctx.send("У бота нет прав для кика (роль бота должна быть выше).", ephemeral=True)

        embed = AG.mod_action(
            action="Исключение участника (Kick)",
            target_str=f"**{target.name}** (`{target.id}`)",
            moderator_str=ctx.author.mention,
            reason=actual_reason,
            color=Colors.RED,
            icon=target.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # --- BAN ---
    @commands.hybrid_command(name="ban", aliases=["бан"], description="Заблокировать пользователя")
    @app_commands.describe(target="Пользователь (@упоминание или ID) для бана", reason="Причина (не обязательно)")
    async def ban_cmd(self, ctx: commands.Context, target: Optional[str] = None, *, reason: Optional[str] = "Не указана"):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        member_to_ban = None
        user_id_to_ban = None

        if target is None:
            extracted = await extract_target_from_ctx(ctx)
            if extracted:
                member_to_ban = extracted
                user_id_to_ban = extracted.id

        if not user_id_to_ban and target:
            clean_id = target.strip("<@!>")
            if clean_id.isdigit():
                user_id_to_ban = int(clean_id)
                member_to_ban = ctx.guild.get_member(user_id_to_ban)

        if not user_id_to_ban:
            return await ctx.send("Укажите пользователя (@упоминание / ID) или ответьте на его сообщение командой `!ban [причина]`.", ephemeral=True)

        if user_id_to_ban == ctx.author.id:
            return await ctx.send("Вы не можете забанить себя.", ephemeral=True)
        if user_id_to_ban == self.bot.user.id:
            return await ctx.send("Вы не можете забанить бота.", ephemeral=True)

        if member_to_ban and member_to_ban.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("Роль этого пользователя равна или выше вашей в иерархии.", ephemeral=True)

        actual_reason = reason or "Не указана"

        try:
            user_obj = member_to_ban or await self.bot.fetch_user(user_id_to_ban)
            if user_obj:
                await send_dm_notification(user_obj, "Перманентный Бан", ctx.guild.name, actual_reason, ctx.author.name)
        except Exception:
            pass

        try:
            await ctx.guild.ban(discord.Object(id=user_id_to_ban), reason=f"Бан от {ctx.author.name}: {actual_reason}")
        except discord.Forbidden:
            return await ctx.send("У бота нет прав для бана этого пользователя.", ephemeral=True)

        banned_name = member_to_ban.name if member_to_ban else f"ID: {user_id_to_ban}"
        embed = AG.mod_action(
            action="Блокировка участника (Ban)",
            target_str=f"**{banned_name}** (`{user_id_to_ban}`)",
            moderator_str=ctx.author.mention,
            reason=actual_reason,
            color=Colors.RED,
            icon=member_to_ban.display_avatar.url if member_to_ban else None,
        )
        await ctx.send(embed=embed)

    # --- UNBAN ---
    @commands.hybrid_command(name="unban", aliases=["разбан"], description="Разблокировать по Discord ID")
    @app_commands.describe(user_id="Discord ID пользователя для разбана", reason="Причина (не обязательно)")
    async def unban_cmd(self, ctx: commands.Context, user_id: str, *, reason: Optional[str] = "Не указана"):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        clean_id = user_id.strip("<@!>")
        if not clean_id.isdigit():
            return await ctx.send("Укажите корректный цифровой Discord ID пользователя.", ephemeral=True)

        uid = int(clean_id)
        actual_reason = reason or "Не указана"

        try:
            ban_entry = await ctx.guild.fetch_ban(discord.Object(id=uid))
        except discord.NotFound:
            return await ctx.send("Этот пользователь не найден в списке заблокированных.", ephemeral=True)
        except discord.Forbidden:
            return await ctx.send("У бота нет прав для просмотра списка банов.", ephemeral=True)

        try:
            await ctx.guild.unban(ban_entry.user, reason=f"Разбан от {ctx.author.name}: {actual_reason}")
        except discord.Forbidden:
            return await ctx.send("У бота нет прав для разбана пользователей.", ephemeral=True)

        embed = AG.mod_action(
            action="Разблокировка пользователя (Unban)",
            target_str=f"**{ban_entry.user.name}** (`{uid}`)",
            moderator_str=ctx.author.mention,
            reason=actual_reason,
            color=Colors.GREEN,
            icon=ban_entry.user.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # --- CLEAR ---
    @commands.hybrid_command(name="clear", aliases=["очистить", "purge", "clean"], description="Очистить сообщения в канале")
    @app_commands.describe(amount="Количество сообщений для удаления (1-100)")
    async def clear_cmd(self, ctx: commands.Context, amount: int = 10):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        if amount < 1:
            return await ctx.send("Укажите число больше 0.", ephemeral=True)
        if amount > 100:
            amount = 100

        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        to_delete = amount if ctx.interaction else amount + 1

        try:
            deleted = await ctx.channel.purge(limit=to_delete)
            count = len(deleted)
            if not ctx.interaction and count > 0:
                count -= 1

            if ctx.interaction:
                await ctx.send(f"Удалено сообщений: **{count}**", ephemeral=True)
            else:
                confirm_msg = await ctx.channel.send(f"Удалено сообщений: **{count}**")
                await asyncio.sleep(4)
                try:
                    await confirm_msg.delete()
                except Exception:
                    pass
        except discord.Forbidden:
            await ctx.send("У бота нет прав для удаления сообщений (Manage Messages).", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Ошибка при очистке: {e}", ephemeral=True)

    # --- SLOWMODE ---
    @commands.hybrid_command(name="slowmode", aliases=["медленный", "слоумод"], description="Установить задержку отправки сообщений в канале")
    @app_commands.describe(delay="Задержка (например: 5s, 10s, 1m или 0 для отключения)")
    async def slowmode_cmd(self, ctx: commands.Context, delay: str = "0"):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        parsed = parse_duration(delay)
        seconds = parsed[0] if parsed else (int(delay) if delay.isdigit() else 0)

        if seconds < 0 or seconds > 21600:
            return await ctx.send("Задержка должна быть от 0 до 6 часов (21600 сек).", ephemeral=True)

        try:
            await ctx.channel.edit(slowmode_delay=seconds)
            if seconds == 0:
                await ctx.send("Медленный режим отключен.")
            else:
                await ctx.send(f"Медленный режим установлен: **{seconds} сек.**")
        except discord.Forbidden:
            await ctx.send("У бота нет прав для управления каналом.", ephemeral=True)

    # --- LOCK (БЛОКИРОВКА КАНАЛА) ---
    @commands.hybrid_command(name="lock", aliases=["закрыть_чат", "лок"], description="Заблокировать отправку сообщений в текущем канале")
    @app_commands.describe(reason="Причина блокировки чата")
    async def lock_cmd(self, ctx: commands.Context, *, reason: Optional[str] = "Не указана"):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        actual_reason = reason or "Не указана"
        try:
            await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False, reason=f"Lock by {ctx.author.name}: {actual_reason}")
            embed = AG.embed(
                title="Канал временно заблокирован",
                description=(
                    f"Отправка сообщений в этом чате приостановлена модератором {ctx.author.mention}.\n\n"
                    f"• **Причина:** {actual_reason}"
                ),
                color=Colors.YELLOW,
                footer="Vanilla Land • Блокировка чата",
            )
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("У бота нет прав для управления правами канала.", ephemeral=True)

    # --- UNLOCK (РАЗБЛОКИРОВКА КАНАЛА) ---
    @commands.hybrid_command(name="unlock", aliases=["открыть_чат", "анлок"], description="Разблокировать текущий канал")
    async def unlock_cmd(self, ctx: commands.Context):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        try:
            await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=None, reason=f"Unlock by {ctx.author.name}")
            embed = AG.embed(
                title="Канал разблокирован",
                description=f"Отправка сообщений разрешена модератором {ctx.author.mention}. Приятного общения!",
                color=Colors.GREEN,
                footer="Vanilla Land • Разблокировка чата",
            )
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("У бота нет прав для управления правами канала.", ephemeral=True)

    # --- LOCKALL (БЛОКИРОВКА ВСЕХ ТЕКСТОВЫХ КАНАЛОВ) ---
    @commands.hybrid_command(name="lockall", aliases=["закрыть_все", "локолл"], description="Заблокировать все общедоступные каналы")
    @app_commands.describe(reason="Причина общей блокировки")
    async def lockall_cmd(self, ctx: commands.Context, *, reason: Optional[str] = "Экстренная блокировка"):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        actual_reason = reason or "Экстренная блокировка"
        msg = await ctx.send("Блокировка каналов...")
        self.db.clear_locked_channels(ctx.guild.id)
        locked_count = 0

        for ch in ctx.guild.text_channels:
            perms = ch.permissions_for(ctx.guild.default_role)
            # Блокируем только те каналы, где @everyone реально мог писать
            if perms.send_messages:
                try:
                    await ch.set_permissions(ctx.guild.default_role, send_messages=False, reason=f"Lockall by {ctx.author.name}: {actual_reason}")
                    self.db.save_locked_channel(ch.id, ctx.guild.id)
                    locked_count += 1
                except Exception:
                    pass

        embed = AG.embed(
            title="Блокировка каналов",
            description=(
                f"Режим изоляции включен модератором {ctx.author.mention}.\n\n"
                f"• **Заблокировано чатов:** `{locked_count}`\n"
                f"• **Причина:** {actual_reason}"
            ),
            color=Colors.RED,
            footer="Vanilla Land • Безопасность",
        )
        await msg.delete()
        await ctx.send(embed=embed)

    # --- UNLOCKALL (РАЗБЛОКИРОВКА ТОЛЬКО РАНЕЕ ЗАКРЫТЫХ КАНАЛОВ) ---
    @commands.hybrid_command(name="unlockall", aliases=["открыть_все", "анлоколл"], description="Разблокировать ранее закрытые каналы")
    async def unlockall_cmd(self, ctx: commands.Context):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        msg = await ctx.send("Восстановление доступа к каналам...")
        locked_ids = self.db.get_locked_channels(ctx.guild.id)

        if not locked_ids:
            return await msg.edit(content="Нет каналов, заблокированных через команду `!lockall`.")

        unlocked_count = 0
        for ch_id in locked_ids:
            ch = ctx.guild.get_channel(ch_id)
            if ch and isinstance(ch, discord.TextChannel):
                try:
                    await ch.set_permissions(ctx.guild.default_role, send_messages=None, reason=f"Unlockall by {ctx.author.name}")
                    unlocked_count += 1
                except Exception:
                    pass

        self.db.clear_locked_channels(ctx.guild.id)
        embed = AG.embed(
            title="Каналы разблокированы",
            description=(
                f"Режим изоляции снят модератором {ctx.author.mention}.\n\n"
                f"• **Открыто чатов обратно:** `{unlocked_count}`\n"
                f"*(Каналы правил, новостей и логов остались защищены)*"
            ),
            color=Colors.GREEN,
            footer="Vanilla Land • Безопасность",
        )
        await msg.delete()
        await ctx.send(embed=embed)

    # --- VCKICK (КИК ИЗ ГОЛОСОВОГО КАНАЛА) ---
    @commands.hybrid_command(name="vckick", aliases=["гскик", "кик_войс"], description="Выгнать пользователя из голосового канала")
    @app_commands.describe(target="Пользователь в голосовом канале", reason="Причина (не обязательно)")
    async def vckick_cmd(self, ctx: commands.Context, target: Optional[discord.Member] = None, *, reason: Optional[str] = "Не указана"):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        if target is None:
            target = await extract_target_from_ctx(ctx)

        if target is None:
            return await ctx.send("Укажите пользователя (@упоминание).", ephemeral=True)

        if not target.voice or not target.voice.channel:
            return await ctx.send(f"Пользователь {target.mention} не находится в голосовом канале.", ephemeral=True)

        actual_reason = reason or "Не указана"
        try:
            await target.move_to(None, reason=f"VC Kick by {ctx.author.name}: {actual_reason}")
            embed = AG.mod_action(
                action="Кик из голосового канала",
                target_str=f"{target.mention} (`{target.id}`)",
                moderator_str=ctx.author.mention,
                reason=actual_reason,
                color=Colors.YELLOW,
                icon=target.display_avatar.url,
            )
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("У бота нет прав перемещать участников (Move Members).", ephemeral=True)

    # --- VCBAN (БАН В ГОЛОСОВЫХ КАНАЛАХ) ---
    @commands.hybrid_command(name="vcban", aliases=["гсбан", "бан_войс"], description="Заблокировать доступ к голосовым каналам")
    @app_commands.describe(target="Пользователь", duration="Длительность (10m, 1h, 1d)", reason="Причина (не обязательно)")
    async def vcban_cmd(
        self,
        ctx: commands.Context,
        target: Optional[discord.Member] = None,
        duration: Optional[str] = "1h",
        *,
        reason: Optional[str] = "Не указана",
    ):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        if target is None:
            target = await extract_target_from_ctx(ctx)

        if target is None:
            return await ctx.send("Укажите пользователя (@упоминание).", ephemeral=True)

        parsed = parse_duration(duration or "1h")
        if not parsed:
            actual_reason = f"{duration} {reason}".strip() if reason != "Не указана" else duration
            parsed = (3600, "1 ч.")
        else:
            actual_reason = reason or "Не указана"

        sec, human_time = parsed
        unban_ts = time.time() + sec

        # Отключаем из голосового канала, если находится
        if target.voice and target.voice.channel:
            try:
                await target.move_to(None, reason=f"VC Ban: {actual_reason}")
            except Exception:
                pass

        # Запрещаем подключение во всех голосовых каналах
        for vc in ctx.guild.voice_channels:
            try:
                await vc.set_permissions(target, connect=False, reason=f"VC Ban by {ctx.author.name}: {actual_reason}")
            except Exception:
                pass

        self.db.save_vc_ban(target.id, ctx.guild.id, unban_ts, actual_reason)

        await send_dm_notification(target, "Блокировка голосовых каналов", ctx.guild.name, actual_reason, ctx.author.name, human_time)

        embed = AG.mod_action(
            action="Блокировка голосовых каналов",
            target_str=f"{target.mention} (`{target.id}`)",
            moderator_str=ctx.author.mention,
            duration=human_time,
            reason=actual_reason,
            color=Colors.RED,
            icon=target.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # --- КОМАНДА /automod (ВКЛЮЧЕНИЕ / ВЫКЛЮЧЕНИЕ АВТОМОДЕРАЦИИ) ---
    @commands.hybrid_command(
        name="automod",
        aliases=["автомод", "автомодерация"],
        description="Управление системой АвтоМодерации сервера (только персонал)",
    )
    @app_commands.describe(mode="Режим: on или off (оставьте пустым для проверки статуса)")
    async def automod_cmd(self, ctx: commands.Context, mode: Optional[str] = None):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        if not mode:
            status = self.db.is_automod_enabled()
            status_text = "**[ВКЛЮЧЕНА]**" if status else "**[ВЫКЛЮЧЕНА]**"
            embed = AG.embed(
                title="Автомодерация • Статус защиты",
                description=(
                    f"Текущий статус: {status_text}\n\n"
                    "**Что защищает АвтоМодерация:**\n"
                    "• Мгновенное удаление сторонних ссылок и инвайтов\n"
                    "• Детект текстовой рекламы и набора на чужие проекты\n"
                    "• Автоматический перманентный **Бан** нарушителей\n"
                    "• Оповещение нарушителю в ЛС и подробный лог в админ-чат\n\n"
                    "**Команды управления:**\n"
                    "• `!automod on` — Включить защиту\n"
                    "• `!automod off` — Выключить защиту"
                ),
                color=Colors.GREEN if status else Colors.RED,
                footer="Vanilla Land • Безопасность",
            )
            return await ctx.send(embed=embed)

        mode_clean = mode.lower().strip()
        if mode_clean in ("on", "вкл", "true", "1", "enable"):
            self.db.set_automod_enabled(True)
            embed = AG.embed(
                title="Автомодерация включена",
                description="Система автомодерации успешно **активирована**.\nРеклама и спам сторонних серверов блокируются автоматически.",
                color=Colors.GREEN,
            )
            await ctx.send(embed=embed)
        elif mode_clean in ("off", "выкл", "false", "0", "disable"):
            self.db.set_automod_enabled(False)
            embed = AG.embed(
                title="Автомодерация выключена",
                description="Система автомодерации **отключена** персоналом.\nАвтоматический фильтр рекламы временно приостановлен.",
                color=Colors.YELLOW,
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("Укажите `!automod on` или `!automod off`", ephemeral=True)


async def setup(bot: commands.Bot):
    db: DatabaseManager = bot.db
    await bot.add_cog(ModerationCog(bot, db))
