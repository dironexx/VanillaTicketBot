import asyncio
import logging
import re
import time
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
            content=f"🔊 **Решение принято:** Мут снят администратором {interaction.user.mention}.",
            view=self,
        )

    @ui.button(label="Оставить суточный мут", style=discord.ButtonStyle.secondary, emoji="⏳")
    async def keep_mute_button(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"⏳ **Решение принято:** Суточный мут оставлен в силе (подтвердил {interaction.user.mention}).",
            view=self,
        )


class LogsCog(commands.Cog, name="Логирование и Защита"):
    def __init__(self, bot: commands.Bot, db: DatabaseManager):
        self.bot = bot
        self.db = db

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

        # 3. Fallback: поиск по названию
        for name in ("логи", "logs", "журнал", "аудит", "лог", "server-logs"):
            found = discord.utils.get(guild.text_channels, name=name)
            if found:
                return found

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

        # Игнорируем администрацию и модераторов
        if is_mod_or_admin(message.author):
            return

        # Проверка включения автомодерации
        if not self.db.is_automod_enabled():
            return

        content_lower = message.content.lower()
        is_violation = False
        violation_type = ""

        # 1. Сторонние Discord-инвайты
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
                    title="Блокировка на сервере • Vanilla Land",
                    description=(
                        f"Вы были заблокированы на сервере **Vanilla Land**.\n\n"
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

            # 3. Бан нарушителя с удалением сообщений за 1 день
            try:
                await author.ban(reason="АвтоМодерация - реклама", delete_message_days=1)
            except Exception as e:
                logger.error(f"Ошибка бана нарушителя за рекламу: {e}")

            # 4. Лог в канал Администрации
            admin_ch = self.get_admin_channel(guild)
            if admin_ch:
                alert_embed = AG.embed(
                    title="Автомодерация • Блокировка за рекламу",
                    description=(
                        f"Пользователь был автоматически **заблокирован (Бан)**.\n\n"
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
                await admin_ch.send(embed=alert_embed)

    # --- ЛОГ УДАЛЕНИЯ СООБЩЕНИЙ ---
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        log_ch = self.get_log_channel(message.guild)
        if not log_ch or log_ch.id == message.channel.id:
            return

        raw_content = message.clean_content or "*[Содержимое недоступно]*"
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
        if message.attachments:
            att_urls = "\n".join([f"• [{a.filename}]({a.url})" for a in message.attachments])
            embed.add_field(name="Вложения", value=att_urls, inline=False)

        try:
            await log_ch.send(embed=embed)
        except Exception:
            pass

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

    # --- ЛОГ ВХОДА УЧАСТНИКА (С ПРОВЕРКОЙ ВОЗРАСТА АККАУНТА) ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        log_ch = self.get_log_channel(member.guild)
        if not log_ch:
            return

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
        log_ch = self.get_log_channel(member.guild)
        if not log_ch:
            return

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
    db: DatabaseManager = getattr(bot, "db")
    await bot.add_cog(LogsCog(bot, db))
