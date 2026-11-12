import logging
import random
import re
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import Config
from database import DatabaseManager
from design import AG, Colors

logger = logging.getLogger("VanillaBot.Utility")

TIME_REGEX = re.compile(r"^(\d+)([smhdw])$", re.IGNORECASE)
TIME_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration_sec(duration_str: str) -> Optional[int]:
    if not duration_str:
        return None
    match = TIME_REGEX.match(duration_str.strip())
    if not match:
        if duration_str.strip().isdigit():
            return int(duration_str.strip())
        return None
    val, unit = match.groups()
    return int(val) * TIME_MULTIPLIERS[unit.lower()]


def is_mod_or_admin(ctx) -> bool:
    author = ctx.author
    if not isinstance(author, discord.Member):
        return False
    guild = ctx.guild
    if author.guild_permissions.administrator or (guild and author.id == guild.owner_id):
        return True
    author_roles = {r.id for r in author.roles}
    return any(r_id in author_roles for r_id in Config.MOD_ROLE_IDS)


class UtilityCog(commands.Cog, name="Утилиты"):
    def __init__(self, bot: commands.Bot, db: DatabaseManager):
        self.bot = bot
        self.db = db
        self.reminders_loop.start()

    def cog_unload(self):
        self.reminders_loop.cancel()

    # --- ФОНОВЫЙ ЦИКЛ НАПОМИНАНИЙ ---
    @tasks.loop(seconds=20)
    async def reminders_loop(self):
        now_ts = time.time()
        expired = self.db.get_expired_reminders(now_ts)

        for rem_id, user_id, channel_id, text in expired:
            channel = self.bot.get_channel(channel_id)
            user = self.bot.get_user(user_id)
            if not user:
                try:
                    user = await self.bot.fetch_user(user_id)
                except Exception:
                    user = None

            embed = AG.embed(
                title="Напоминание • Vanilla Land",
                description=text,
                color=Colors.YELLOW,
                footer="Vanilla Land • Напоминания",
            )

            sent = False
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(content=f"<@{user_id}>", embed=embed)
                    sent = True
                except Exception:
                    pass

            if not sent and user:
                try:
                    await user.send(embed=embed)
                except Exception:
                    pass

            self.db.delete_reminder(rem_id)

    @reminders_loop.before_loop
    async def before_reminders_loop(self):
        await self.bot.wait_until_ready()

    # --- USER (ПРОФИЛЬ УЧАСТНИКА) ---
    @commands.hybrid_command(name="user", aliases=["юзер", "дискорд_профиль", "userinfo", "user_info"], description="Информация о профиле пользователя Discord")
    @app_commands.describe(target="Пользователь для просмотра")
    async def user_cmd(self, ctx: commands.Context, target: Optional[discord.Member] = None):
        member = target or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if not member:
            return await ctx.send("Пользователь не найден.", ephemeral=True)

        created_ts = int(member.created_at.timestamp())
        joined_ts = int(member.joined_at.timestamp()) if member.joined_at else None

        top_role = member.top_role.mention if member.top_role.name != "@everyone" else "Нет"
        non_everyone_roles = [r.mention for r in reversed(member.roles) if r.name != "@everyone"]
        roles_count = len(non_everyone_roles)
        roles_preview = ", ".join(non_everyone_roles[:8]) if non_everyone_roles else "Нет специальных ролей"
        if roles_count > 8:
            roles_preview += f" *(и ещё {roles_count - 8})*"

        embed = AG.embed(
            title=f"Профиль участника • {member.display_name}",
            color=Colors.DARK,
            thumbnail=member.display_avatar.url,
            footer=f"Vanilla Land • Запросил {ctx.author.name}",
        )

        embed.add_field(
            name="Основная информация",
            value=(
                f"• **Тег:** {member.mention}\n"
                f"• **Имя:** `{member.name}`\n"
                f"• **ID аккаунта:** `{member.id}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Даты",
            value=(
                f"• **Создание аккаунта:** <t:{created_ts}:D> (<t:{created_ts}:R>)\n"
                f"• **Вступление на сервер:** <t:{joined_ts}:D> (<t:{joined_ts}:R>)" if joined_ts else "• **Вступление на сервер:** Неизвестно"
            ),
            inline=False,
        )

        embed.add_field(
            name=f"Роли на сервере [{roles_count}]",
            value=(
                f"• **Высшая роль:** {top_role}\n"
                f"• **Список:** {roles_preview}"
            ),
            inline=False,
        )

        await ctx.send(embed=embed)

    # --- AVATAR (АВАТАР ПОЛЬЗОВАТЕЛЯ) ---
    @commands.hybrid_command(
        name="avatar",
        aliases=["аватар", "ава", "ava", "pfp", "icon"],
        description="Просмотр аватара пользователя в полном размере",
    )
    @app_commands.describe(target="Пользователь для просмотра аватара (или пусто для своего)")
    async def avatar_cmd(self, ctx: commands.Context, target: Optional[discord.Member] = None):
        member = target or (ctx.author if isinstance(ctx.author, discord.Member) else None)
        if not member:
            return await ctx.send("Пользователь не найден.", ephemeral=True)

        avatar_url = member.display_avatar.url
        embed = AG.embed(
            title=f"Аватар • {member.display_name}",
            color=Colors.DARK,
            footer=f"Vanilla Land • Запросил {ctx.author.name}",
        )
        embed.set_image(url=avatar_url)
        embed.description = f"[Открыть оригинал в браузере]({avatar_url})"
        await ctx.send(embed=embed)

    # --- SERVER (СТАТИСТИКА СЕРВЕРА) ---
    @commands.hybrid_command(name="server", aliases=["сервер", "серверинфо"], description="Информация о Discord-сервере")
    async def server_cmd(self, ctx: commands.Context):
        guild = ctx.guild
        if not guild:
            return await ctx.send("Только на сервере.", ephemeral=True)

        created_ts = int(guild.created_at.timestamp())
        owner_mention = guild.owner.mention if guild.owner else "Неизвестно"

        total_members = guild.member_count or len(guild.members)
        bots_count = sum(1 for m in guild.members if m.bot)
        humans_count = total_members - bots_count

        embed = AG.embed(
            title=f"Информация о сервере • {guild.name}",
            color=Colors.DARK,
            thumbnail=guild.icon.url if guild.icon else None,
            footer="Vanilla Land",
        )

        embed.add_field(
            name="Основное",
            value=(
                f"• **Владелец:** {owner_mention}\n"
                f"• **ID сервера:** `{guild.id}`\n"
                f"• **Создан:** <t:{created_ts}:D> (<t:{created_ts}:R>)"
            ),
            inline=False,
        )

        embed.add_field(
            name="Участники",
            value=(
                f"• **Всего:** `{total_members}`\n"
                f"• **Игроков:** `{humans_count}` | **Ботов:** `{bots_count}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Каналы и бусты",
            value=(
                f"• **Текстовых:** `{len(guild.text_channels)}` | **Голосовых:** `{len(guild.voice_channels)}`\n"
                f"• **Бусты:** `{guild.premium_subscription_count}` (Уровень `{guild.premium_tier}`)"
            ),
            inline=True,
        )

        await ctx.send(embed=embed)

    # --- SAY (ДЛЯ ПЕРСОНАЛА) ---
    @commands.command(name="say", aliases=["сказать"])
    async def say_cmd(self, ctx: commands.Context, target_channel: Optional[discord.TextChannel] = None, *, text: str):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", delete_after=4)

        channel = target_channel or ctx.channel
        try:
            await ctx.message.delete()
        except Exception:
            pass

        await channel.send(text)

    # --- POLL ---
    @commands.command(name="poll", aliases=["опрос"])
    async def poll_cmd(self, ctx: commands.Context, *, content: str):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Создавать опросы может только персонал сервера.", delete_after=4)

        try:
            await ctx.message.delete()
        except Exception:
            pass

        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        parts = [p.strip() for p in content.split(",") if p.strip()]

        if len(parts) > 1 and len(parts) <= 11:
            question = parts[0]
            options = parts[1:]
            desc_lines = []
            for i, opt in enumerate(options):
                desc_lines.append(f"{emojis[i]} **{opt}**")

            embed = AG.embed(
                title=f"Опрос: {question}",
                description="\n\n".join(desc_lines),
                color=Colors.BLUE,
                footer=f"Vanilla Land • Автор: {ctx.author.name}",
            )
            poll_msg = await ctx.channel.send(embed=embed)
            for i in range(len(options)):
                await poll_msg.add_reaction(emojis[i])
        else:
            embed = AG.embed(
                title="Опрос",
                description=f"**{content}**",
                color=Colors.BLUE,
                footer=f"Vanilla Land • Автор: {ctx.author.name}",
            )
            poll_msg = await ctx.channel.send(embed=embed)
            await poll_msg.add_reaction("👍")
            await poll_msg.add_reaction("👎")

    # --- ROLL ---
    @commands.hybrid_command(name="roll", aliases=["ролл", "кубик", "рандом"], description="Бросить случайное число (1-100 или 1-N)")
    @app_commands.describe(max_val="Максимальное число (по умолчанию 100)")
    async def roll_cmd(self, ctx: commands.Context, max_val: Optional[int] = 100):
        maximum = max_val or 100
        if maximum < 2:
            maximum = 100
        result = random.randint(1, maximum)

        embed = AG.embed(
            title="Случайное число",
            description=f"{ctx.author.mention} выбросил: **{result}** *(из {maximum})*",
            color=Colors.BLUE,
            footer="Vanilla Land",
        )
        await ctx.send(embed=embed)

    # --- REMIND ---
    @commands.hybrid_command(name="remind", aliases=["напомни", "напоминание"], description="Установить напоминание")
    @app_commands.describe(duration="Через сколько напомнить (например: 10m, 1h, 2d)", text="Текст напоминания")
    async def remind_cmd(self, ctx: commands.Context, duration: str, *, text: str):
        sec = parse_duration_sec(duration)
        if not sec or sec < 10:
            return await ctx.send("Укажите корректное время (минимум 10s, например: `10m`, `1h`, `1d`).", ephemeral=True)

        remind_ts = time.time() + sec
        self.db.save_reminder(ctx.author.id, ctx.channel.id, remind_ts, text)

        embed = AG.embed(
            title="Напоминание установлено",
            description=f"Напоминание сработает через **{duration}**.\n\n**Текст:** {text}",
            color=Colors.BLUE,
            footer="Vanilla Land • Напоминания",
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    db: DatabaseManager = bot.db
    await bot.add_cog(UtilityCog(bot, db))
