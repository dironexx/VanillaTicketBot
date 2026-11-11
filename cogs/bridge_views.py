# -*- coding: utf-8 -*-
"""
Модуль представлений (UI Views) моста Vanilla Land:
- Двухфакторная аутентификация (2FA Verify / Public Alert)
- Центр безопасности аккаунтов (AccountSecurityView)
- Панель постоянной привязки аккаунтов (PermanentLinkPanelView)
- Модальные окна ввода ников и ответов в ЛС (LinkModal, DmReplyModal)
"""

import asyncio
import secrets
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, TYPE_CHECKING

import discord
from discord import ui

from config import Config
from database import DatabaseManager
from design import AG, Colors

if TYPE_CHECKING:
    from cogs.bridge import BridgeCog

def get_skin_avatar_url(player_name: str, skin_hash: Optional[str] = None, db: Optional[DatabaseManager] = None) -> str:
    clean_hash = ""
    if skin_hash:
        clean_hash = skin_hash.split("/")[-1].split(".")[0].strip()
    if not clean_hash and db:
        db_hash = db.get_player_skin(player_name)
        if db_hash:
            clean_hash = db_hash
    if clean_hash:
        return f"https://mc-heads.net/avatar/{clean_hash}/128.png"
    return f"https://mc-heads.net/avatar/{player_name}/128.png"


def get_skin_body_url(player_name: str, skin_hash: Optional[str] = None, db: Optional[DatabaseManager] = None) -> str:
    clean_hash = ""
    if skin_hash:
        clean_hash = skin_hash.split("/")[-1].split(".")[0].strip()
    if not clean_hash and db:
        db_hash = db.get_player_skin(player_name)
        if db_hash:
            clean_hash = db_hash
    if clean_hash:
        # Visage поддерживает прямое отображение 3D тела по хэшу текстуры
        return f"https://visage.surgeplay.com/full/384/{clean_hash}"
    return f"https://mc-heads.net/body/{player_name}/300.png"



# --- ПЕРЕВОДЧИК СООБЩЕНИЙ О СМЕРТЯХ (РУССКИЙ ЯЗЫК) ---
MOB_TRANSLATIONS = {
    "zombie": "Зомби",
    "skeleton": "Скелетом",
    "spider": "Пауком",
    "cave spider": "Пещерным пауком",
    "creeper": "Крипером",
    "enderman": "Эндерменом",
    "witch": "Ведьмой",
    "drowned": "Утопленником",
    "phantom": "Фантомом",
    "piglin": "Пиглином",
    "piglin brute": "Жестоким пиглином",
    "zombified piglin": "Зомби-пиглином",
    "blaze": "Ифритом",
    "ghast": "Гастом",
    "magma cube": "Магма-кубом",
    "slime": "Слизнем",
    "wither skeleton": "Визер-скелетом",
    "wither": "Иссушителем",
    "ender dragon": "Драконом Края",
    "warden": "Варденом",
    "shulker": "Шалкером",
    "guardian": "Стражем",
    "elder guardian": "Древним стражем",
    "pillager": "Разбойником",
    "vindicator": "Поборником",
    "evoker": "Заклинателем",
    "ravager": "Разорителем",
    "vex": "Вексом",
    "breeze": "Бризом",
    "bogged": "Болотником",
    "iron golem": "Железным големом",
    "wolf": "Волком",
    "bee": "Пчелой",
    "polar bear": "Белым медведем",
}


class DmReplyModal(ui.Modal):
    def __init__(self, bridge_cog: "BridgeCog", target_player: str):
        super().__init__(title=f"Ответ игроку {target_player}")
        self.bridge_cog = bridge_cog
        self.target_player = target_player

        self.text_input = ui.TextInput(
            label="Текст сообщения в Minecraft",
            placeholder="Введите ваше сообщение...",
            style=discord.TextStyle.paragraph,
            max_length=200,
            required=True,
        )
        self.add_item(self.text_input)

    async def on_submit(self, interaction: discord.Interaction):
        text = self.text_input.value.strip()
        if not text:
            return await interaction.response.send_message("Сообщение не может быть пустым.", ephemeral=True)

        is_online = any(p.lower() == self.target_player.lower() for p in self.bridge_cog.mc_players)
        if not is_online:
            return await interaction.response.send_message(
                f"Игрок **{self.target_player}** сейчас не на сервере (оффлайн). Сообщение не может быть доставлено.",
                ephemeral=True,
            )

        payload = {
            "type": "dm",
            "target": self.target_player,
            "author": interaction.user.display_name,
            "author_id": str(interaction.user.id),
            "content": text,
        }
        await self.bridge_cog.broadcast_packet(payload)

        embed = discord.Embed(
            title=f"✉️ Сообщение отправлено игроку {self.target_player}",
            description=f"Текст: *{text}*",
            color=Colors.BLUE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Vanilla Land • ЛС моста")
        view = DmReplyView(self.bridge_cog, self.target_player)
        await interaction.response.send_message(embed=embed, view=view)


class DmReplyView(ui.View):
    def __init__(self, bridge_cog: "BridgeCog", target_player: str):
        super().__init__(timeout=None)
        self.bridge_cog = bridge_cog
        self.target_player = target_player

    @ui.button(label="✉️ Написать ещё / Ответить", style=discord.ButtonStyle.primary, custom_id="bridge:dm_reply_btn")
    async def reply_btn(self, interaction: discord.Interaction, button: ui.Button):
        modal = DmReplyModal(self.bridge_cog, self.target_player)
        await interaction.response.send_modal(modal)


# --- 2FA ИНТЕРАКТИВНЫЕ ЭЛЕМЕНТЫ UI (ANTI-GRAVITY / GAMING HUD) ---

class TwoFactorVerifyView(ui.View):
    """Интерактивное меню 2FA подтверждения входа в аккаунт с кнопками ДА/НЕТ (Anti-Gravity / Gaming HUD)"""
    def __init__(
        self,
        bridge_cog: "BridgeCog",
        player: str,
        ip: str,
        code: str,
        discord_user_id: int,
        expires_at: float,
        session_id: str = "",
        public_alert_msg: Optional[discord.Message] = None,
    ):
        super().__init__(timeout=Config.LOGIN_2FA_TIMEOUT_SEC)
        self.bridge_cog = bridge_cog
        self.player = player
        self.ip = ip
        self.code = code
        self.discord_user_id = discord_user_id
        self.expires_at = expires_at
        self.session_id = session_id
        self.public_alert_msg = public_alert_msg
        self.message: Optional[discord.Message] = None

    def _session_stale(self) -> bool:
        """Подтверждение относится к актуальной сессии входа, а не к старой/чужой."""
        pending = self.bridge_cog.pending_2fa.get(self.player.lower())
        if not pending or not self.session_id:
            return True
        return pending.get("session_id") != self.session_id

    def build_verify_embed(self) -> discord.Embed:
        now_ts = int(time.time())
        exp_ts = int(self.expires_at)
        c = self.code
        # Преобразуем код в четкий моноширинный блок аутентификатора
        code_block = (
            "```\n"
            "┌─────────────────────────────────────────┐\n"
            "│      ОДНОРАЗОВЫЙ КОД ПОДТВЕРЖДЕНИЯ      │\n"
            f"│             {c[0]}  {c[1]}  {c[2]}   {c[3]}  {c[4]}  {c[5]}           │\n"
            "└─────────────────────────────────────────┘\n"
            "```"
        )
        linked = self.bridge_cog.db.get_linked_account_by_mc(self.player)
        trust_hrs = linked.get("trust_duration_hours", Config.IP_SESSION_HOURS) if linked else Config.IP_SESSION_HOURS
        trust_str = f"{int(trust_hrs)} ч." if trust_hrs > 0 else "Строгий (1 вход)"

        embed = discord.Embed(
            title="🛡️ Двухфакторная защита • Vanilla Land",
            description=(
                f"{code_block}\n"
                "> Зафиксирована попытка входа с нового IP или истёк срок доверенной сессии.\n"
                "> Подтвердите вход кнопкой ниже или введите 6-значный код в игре."
            ),
            color=Colors.BLUE,
        )
        embed.add_field(name="👤 Аккаунт", value=f"**`{self.player}`**", inline=True)
        embed.add_field(name="🌐 IP-адрес", value=f"`{self.ip}`", inline=True)
        embed.add_field(name="⏳ Истекает", value=f"<t:{exp_ts}:R>", inline=True)
        embed.add_field(name="🕒 Время запроса", value=f"<t:{now_ts}:T>", inline=True)
        embed.add_field(name="🛡️ Доверие к IP", value=f"`{trust_str}`", inline=True)
        embed.add_field(name="🎮 Быстрый ввод", value=f"`/code {self.code}`", inline=True)

        embed.set_footer(text="Vanilla Land Security • Двухфакторная защита 2FA")
        skin_url = get_skin_avatar_url(self.player, None, self.bridge_cog.db)
        if skin_url:
            embed.set_thumbnail(url=skin_url)
        return embed

    @ui.button(label="Подтвердить вход", style=discord.ButtonStyle.success, emoji="🛡️", custom_id="2fa:verify_btn")
    async def confirm_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("❌ Это действие доступно только владельцу аккаунта.", ephemeral=True)
        if self._session_stale():
            return await interaction.response.send_message(
                "⚠️ Это подтверждение устарело. Запросите новый код на сервере.", ephemeral=True
            )

        # Доверяем IP на настроенный пользователем срок
        linked = self.bridge_cog.db.get_linked_account_by_mc(self.player)
        trust_hrs = linked.get("trust_duration_hours", Config.IP_SESSION_HOURS) if linked else Config.IP_SESSION_HOURS
        self.bridge_cog.db.trust_ip_session(self.player, self.ip, trust_hrs)
        self.bridge_cog.db.record_login(self.player, self.ip, status="SUCCESS")
        self.bridge_cog.pending_2fa.pop(self.player.lower(), None)

        # Отправляем подтверждение на сервер Minecraft
        await self.bridge_cog.broadcast_packet({
            "type": "2fa_verified",
            "player": self.player,
            "ip": self.ip,
            "trust_hours": trust_hrs,
        })

        if self.public_alert_msg:
            try:
                await self.public_alert_msg.delete()
            except Exception:
                pass
            self.public_alert_msg = None

        exp_session_ts = int(time.time() + (trust_hrs * 3600)) if trust_hrs > 0 else int(time.time())
        exp_session_str = f"<t:{exp_session_ts}:F> (<t:{exp_session_ts}:R>)" if trust_hrs > 0 else "*Строгий режим (до следующего входа)*"

        embed = discord.Embed(
            title="✔ Вход успешно подтверждён • Vanilla Land",
            description=(
                f"Вы подтвердили вход в игровой аккаунт **`{self.player}`**.\n"
                "Игрок мгновенно разморожен на сервере, приятной игры!\n\n"
                f"• **Доверенный IP:** `{self.ip}`\n"
                f"• **Срок действия сессии:** {exp_session_str}"
            ),
            color=Colors.GREEN,
        )
        embed.set_footer(text="Vanilla Land Security • Вход подтверждён")
        skin_url = get_skin_avatar_url(self.player, None, self.bridge_cog.db)
        if skin_url:
            embed.set_thumbnail(url=skin_url)

        for child in self.children:
            child.disabled = True
        button.label = "Вход подтверждён"
        button.emoji = "✅"
        button.style = discord.ButtonStyle.secondary

        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="Заблокировать (Это не я)", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="2fa:reject_btn")
    async def reject_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("❌ Это действие доступно только владельцу аккаунта.", ephemeral=True)
        if self._session_stale():
            return await interaction.response.send_message(
                "⚠️ Это подтверждение устарело. Запросите новый код на сервере.", ephemeral=True
            )

        self.bridge_cog.pending_2fa.pop(self.player.lower(), None)
        self.bridge_cog.db.record_login(self.player, self.ip, status="FAILED")

        # Отправляем команду кика на сервер Minecraft
        await self.bridge_cog.broadcast_packet({
            "type": "2fa_rejected",
            "player": self.player,
        })

        if self.public_alert_msg:
            try:
                await self.public_alert_msg.delete()
            except Exception:
                pass
            self.public_alert_msg = None

        embed = discord.Embed(
            title="🚨 Вход заблокирован • Vanilla Land",
            description=(
                f"Вход в аккаунт **`{self.player}`** с IP `{self.ip}` был заблокирован вами.\n"
                "Неизвестный игрок немедленно исключён с сервера Minecraft.\n\n"
                "🔒 **Рекомендация по безопасности:**\n"
                "Если вы не пытались зайти на сервер, ваш пароль мог быть скомпрометирован.\n"
                "Зайдите на сервер и немедленно смените пароль командой `/changepassword`."
            ),
            color=Colors.RED,
        )
        embed.set_footer(text="Vanilla Land Security • Вход заблокирован владельцем")
        skin_url = get_skin_avatar_url(self.player, None, self.bridge_cog.db)
        if skin_url:
            embed.set_thumbnail(url=skin_url)

        for child in self.children:
            child.disabled = True
        button.label = "Вход заблокирован"
        button.emoji = "⛔"

        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                embed = discord.Embed(
                    title="⏱️ Время подтверждения истекло • Vanilla Land",
                    description=(
                        f"Срок действия одноразового кода для аккаунта **`{self.player}`** истёк (3 минуты).\n"
                        f"Попытка входа с IP `{self.ip}` отклонена сервером по таймауту.\n\n"
                        "> Для входа на сервер переподключитесь и запросите новый код."
                    ),
                    color=Colors.DARK,
                )
                embed.set_footer(text="Vanilla Land Security • Таймаут 2FA")
                skin_url = get_skin_avatar_url(self.player, None, self.bridge_cog.db)
                if skin_url:
                    embed.set_thumbnail(url=skin_url)
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass


class TwoFactorPublicAlertView(ui.View):
    """Интерактивное уведомление в публичном/верификационном канале, когда у игрока закрыты ЛС"""
    def __init__(
        self,
        bridge_cog: "BridgeCog",
        player: str,
        ip: str,
        code: str,
        discord_user_id: int,
        expires_at: float,
        session_id: str = "",
    ):
        super().__init__(timeout=Config.LOGIN_2FA_TIMEOUT_SEC)
        self.bridge_cog = bridge_cog
        self.player = player
        self.ip = ip
        self.code = code
        self.discord_user_id = discord_user_id
        self.expires_at = expires_at
        self.session_id = session_id
        self.message: Optional[discord.Message] = None

    def _session_stale(self) -> bool:
        pending = self.bridge_cog.pending_2fa.get(self.player.lower())
        if not pending or not self.session_id:
            return True
        return pending.get("session_id") != self.session_id

    @ui.button(label="Подтвердить вход", style=discord.ButtonStyle.success, emoji="🛡️", custom_id="2fa_pub:verify")
    async def confirm_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("❌ Это действие предназначено только для владельца аккаунта.", ephemeral=True)
        if self._session_stale():
            return await interaction.response.send_message(
                "⚠️ Это подтверждение устарело. Запросите новый код на сервере.", ephemeral=True
            )

        linked = self.bridge_cog.db.get_linked_account_by_mc(self.player)
        trust_hrs = linked.get("trust_duration_hours", Config.IP_SESSION_HOURS) if linked else Config.IP_SESSION_HOURS
        self.bridge_cog.db.trust_ip_session(self.player, self.ip, trust_hrs)
        self.bridge_cog.db.record_login(self.player, self.ip, status="SUCCESS")
        self.bridge_cog.pending_2fa.pop(self.player.lower(), None)

        await self.bridge_cog.broadcast_packet({
            "type": "2fa_verified",
            "player": self.player,
            "ip": self.ip,
            "trust_hours": trust_hrs,
        })

        embed = discord.Embed(
            title="✔ Вход успешно подтверждён • Vanilla Land",
            description=f"Вход в аккаунт **`{self.player}`** подтверждён владельцем. Приятной игры на сервере!",
            color=Colors.GREEN,
        )
        for child in self.children:
            child.disabled = True
        button.label = "Вход подтверждён"
        button.emoji = "✅"
        button.style = discord.ButtonStyle.secondary
        await interaction.response.edit_message(embed=embed, view=self)

        if self.message:
            await asyncio.sleep(8)
            try:
                await self.message.delete()
            except Exception:
                pass

    @ui.button(label="Заблокировать", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="2fa_pub:reject")
    async def reject_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.discord_user_id:
            return await interaction.response.send_message("❌ Это действие предназначено только для владельца аккаунта.", ephemeral=True)
        if self._session_stale():
            return await interaction.response.send_message(
                "⚠️ Это подтверждение устарело. Запросите новый код на сервере.", ephemeral=True
            )

        self.bridge_cog.pending_2fa.pop(self.player.lower(), None)
        self.bridge_cog.db.record_login(self.player, self.ip, status="FAILED")

        await self.bridge_cog.broadcast_packet({
            "type": "2fa_rejected",
            "player": self.player,
        })

        embed = discord.Embed(
            title="🚨 Вход заблокирован • Vanilla Land",
            description=f"Вход в аккаунт **`{self.player}`** заблокирован. Игрок немедленно исключён с сервера.",
            color=Colors.RED,
        )
        for child in self.children:
            child.disabled = True
        button.label = "Заблокирован"
        button.emoji = "⛔"
        await interaction.response.edit_message(embed=embed, view=self)

        if self.message:
            await asyncio.sleep(8)
            try:
                await self.message.delete()
            except Exception:
                pass

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.delete()
            except Exception:
                pass


class LoginAlertView(ui.View):
    """Пуш-уведомление о входе (persistent: игрок резолвится по interaction.user.id)."""

    def __init__(self, bridge_cog: "BridgeCog", player_name: str = "", discord_user_id: int = 0):
        super().__init__(timeout=None)
        self.bridge_cog = bridge_cog
        self.player_name = player_name
        self.discord_user_id = discord_user_id

    @ui.button(label="Заблокировать (Экстренный кик)", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="sec:alert_kick")
    async def alert_kick_btn(self, interaction: discord.Interaction, button: ui.Button):
        is_dm = interaction.guild is None
        if self.discord_user_id and interaction.user.id != self.discord_user_id:
            msg = "❌ Действие недоступно для этого пользователя."
            return await interaction.response.send_message(msg) if is_dm else await interaction.response.send_message(msg, ephemeral=True)

        linked = self.bridge_cog.db.get_linked_account_by_discord(interaction.user.id)
        if not linked:
            msg = "❌ У вас нет привязанного аккаунта Minecraft."
            return await interaction.response.send_message(msg) if is_dm else await interaction.response.send_message(msg, ephemeral=True)
        player_name = linked["player_name"]

        self.bridge_cog.db.clear_ip_sessions(player_name)
        await self.bridge_cog.broadcast_packet({"type": "emergency_kick", "player": player_name})
        await self.bridge_cog.broadcast_packet({"type": "clear_sessions", "player": player_name})

        embed = discord.Embed(
            title="🚨 Аккаунт экстренно заблокирован • Vanilla Land",
            description=(
                f"Все доверенные сессии игрока **`{player_name}`** сброшены.\n"
                "Если кто-то находился на сервере под вашим аккаунтом — он немедленно исключён.\n\n"
                "🔒 **Рекомендация по безопасности:**\n"
                "Немедленно зайдите на сервер и смените пароль: `/changepassword`."
            ),
            color=Colors.RED,
        )
        embed.set_footer(text="Vanilla Land Security • Экстренная блокировка")
        skin_url = get_skin_avatar_url(player_name, None, self.bridge_cog.db)
        if skin_url:
            embed.set_thumbnail(url=skin_url)
        await interaction.response.edit_message(embed=embed, view=None)


class AccountSecurityView(ui.View):
    """Центр безопасности аккаунта (persistent: данные резолвятся по interaction.user.id)."""

    def __init__(self, bridge_cog: "BridgeCog", discord_user_id: int = 0, player_name: str = ""):
        super().__init__(timeout=None)
        self.bridge_cog = bridge_cog
        self.discord_user_id = discord_user_id
        self.player_name = player_name
        self.update_buttons()

    def _linked(self, user_id: int):
        return self.bridge_cog.db.get_linked_account_by_discord(user_id)

    async def _reply(self, interaction: discord.Interaction, text: str):
        if interaction.guild is None:
            return await interaction.response.send_message(text)
        return await interaction.response.send_message(text, ephemeral=True)

    def update_buttons(self, user_id: Optional[int] = None):
        uid = int(user_id or self.discord_user_id or 0)
        if not uid:
            return
        linked = self._linked(uid)
        is_2fa = linked.get("two_factor_enabled", True) if linked else False
        trust_hours = linked.get("trust_duration_hours", 48) if linked else 48
        alerts_on = linked.get("login_alerts_enabled", False) if linked else False
        trust_tag = "Строгий" if trust_hours <= 0 else (f"{trust_hours}ч" if trust_hours < 168 else "7д")

        for child in self.children:
            if not isinstance(child, ui.Button):
                continue
            if child.custom_id == "sec:toggle_2fa":
                child.label = f"2FA: {'ВКЛ' if is_2fa else 'ВЫКЛ'}"
                child.emoji = "🛡️" if is_2fa else "⚠️"
                child.style = discord.ButtonStyle.primary if is_2fa else discord.ButtonStyle.secondary
            elif child.custom_id == "sec:trust_duration":
                child.label = f"Срок IP: {trust_tag}"
                child.emoji = "⏳"
            elif child.custom_id == "sec:toggle_alerts":
                child.label = f"Алерты: {'ВКЛ' if alerts_on else 'ВЫКЛ'}"
                child.emoji = "🔔" if alerts_on else "🔕"
                child.style = discord.ButtonStyle.primary if alerts_on else discord.ButtonStyle.secondary

    def build_embed(
        self,
        notice: Optional[str] = None,
        user_id: Optional[int] = None,
        player_name: Optional[str] = None,
    ) -> discord.Embed:
        uid = int(user_id or self.discord_user_id or 0)
        linked = self._linked(uid) if uid else None
        player_name = player_name or (linked or {}).get("player_name") or self.player_name

        if not linked:
            return AG.embed(
                title="Безопасность аккаунта • Vanilla Land",
                description="У вас нет привязанного аккаунта Minecraft. Используйте `/link`.",
                color=Colors.DARK,
            )

        is_2fa = linked.get("two_factor_enabled", True)
        trust_hours = linked.get("trust_duration_hours", 48)
        alerts_on = linked.get("login_alerts_enabled", False)
        sessions = self.bridge_cog.db.get_trusted_ip_sessions(player_name)

        trust_str = "Каждый вход" if trust_hours <= 0 else f"{trust_hours} ч."
        status_2fa = f"Включен (сессия = {trust_str})" if is_2fa else "Выключен"
        alerts_str = "Включены" if alerts_on else "Выключены"
        linked_at = linked.get("linked_at", "Не зафиксирована")

        desc = (
            f"• 👤 **Игровой ник:** `{player_name}`\n"
            f"• 🔗 **Привязка Discord:** <@{uid}>\n"
            f"• 🔐 **2FA - Подтверждение входа:** `{status_2fa}`\n"
            f"• 🔔 **Push-уведомления в ЛС:** `{alerts_str}`\n"
            f"• 📅 **Дата привязки:** `{linked_at}`"
        )
        if notice:
            desc = f"**{notice}**\n\n" + desc

        embed = discord.Embed(
            title=f"Безопасность аккаунта • {player_name}",
            description=desc,
            color=0xFF8C00 if is_2fa else Colors.DARK,
        )
        skin_url = get_skin_avatar_url(player_name, None, self.bridge_cog.db)
        if skin_url:
            embed.set_thumbnail(url=skin_url)

        if sessions and trust_hours > 0:
            lines = []
            for s in sessions[:5]:
                exp_ts = int(s["expires_at"])
                lines.append(f"• `{s['ip']}` — истекает <t:{exp_ts}:R> (<t:{exp_ts}:t>)")
            embed.add_field(
                name=f"🛡️ Доверенные IP-сессии ({len(sessions)} шт.)",
                value="\n".join(lines),
                inline=False,
            )
        else:
            msg = (
                "*Строгий режим: доверенные сессии не сохраняются (код запрашивается при каждом входе).*"
                if trust_hours <= 0
                else "*Нет активных сессий (при следующем входе потребуется код).* "
            )
            embed.add_field(name="🛡️ Доверенные IP-сессии", value=msg, inline=False)

        embed.set_footer(text="Vanilla Land • Центр безопасности 2FA")
        return embed

    @ui.button(label="2FA", style=discord.ButtonStyle.primary, emoji="🛡️", custom_id="sec:toggle_2fa", row=0)
    async def toggle_2fa_btn(self, interaction: discord.Interaction, button: ui.Button):
        linked = self._linked(interaction.user.id)
        if not linked:
            return await self._reply(interaction, "❌ У вас нет привязанного аккаунта Minecraft.")
        new_state = not linked.get("two_factor_enabled", True)
        self.bridge_cog.db.set_two_factor_enabled(interaction.user.id, new_state)
        if self.discord_user_id:
            self.update_buttons(interaction.user.id)
        notice = "✔ Двухфакторная защита 2FA активирована." if new_state else "⚠️ Двухфакторная защита 2FA отключена."
        await interaction.response.edit_message(
            embed=self.build_embed(notice, interaction.user.id, linked["player_name"]), view=self
        )

    @ui.button(label="Срок IP: 48ч", style=discord.ButtonStyle.secondary, emoji="⏳", custom_id="sec:trust_duration", row=0)
    async def trust_duration_btn(self, interaction: discord.Interaction, button: ui.Button):
        linked = self._linked(interaction.user.id)
        if not linked:
            return await self._reply(interaction, "❌ У вас нет привязанного аккаунта Minecraft.")
        cur = linked.get("trust_duration_hours", 48)
        next_val = {48: 168, 168: 0, 0: 24, 24: 48}.get(cur, 48)
        self.bridge_cog.db.set_trust_duration(interaction.user.id, next_val)
        if self.discord_user_id:
            self.update_buttons(interaction.user.id)
        label_map = {48: "48 часов", 168: "7 дней", 0: "Строгий режим (каждый вход)", 24: "24 часа"}
        notice = f"✔ Срок доверия к IP установлен на {label_map.get(next_val, '48ч')}."
        await interaction.response.edit_message(
            embed=self.build_embed(notice, interaction.user.id, linked["player_name"]), view=self
        )

    @ui.button(label="Уведомления", style=discord.ButtonStyle.secondary, emoji="🔔", custom_id="sec:toggle_alerts", row=0)
    async def toggle_alerts_btn(self, interaction: discord.Interaction, button: ui.Button):
        linked = self._linked(interaction.user.id)
        if not linked:
            return await self._reply(interaction, "❌ У вас нет привязанного аккаунта Minecraft.")
        new_val = not linked.get("login_alerts_enabled", False)
        self.bridge_cog.db.set_login_alerts_enabled(interaction.user.id, new_val)
        if self.discord_user_id:
            self.update_buttons(interaction.user.id)
        notice = "✔ Уведомления о входе в ЛС включены." if new_val else "🔕 Уведомления о входе в ЛС выключены."
        await interaction.response.edit_message(
            embed=self.build_embed(notice, interaction.user.id, linked["player_name"]), view=self
        )

    @ui.button(label="Журнал входов", style=discord.ButtonStyle.secondary, emoji="📜", custom_id="sec:login_history", row=1)
    async def login_history_btn(self, interaction: discord.Interaction, button: ui.Button):
        linked = self._linked(interaction.user.id)
        if not linked:
            return await self._reply(interaction, "❌ У вас нет привязанного аккаунта Minecraft.")
        player_name = linked["player_name"]
        logins = self.bridge_cog.db.get_recent_logins(player_name, 5)
        if not logins:
            notice = "📜 История входов пока пуста."
        else:
            lines = []
            for item in logins:
                dt_str = datetime.fromtimestamp(item["time"], timezone.utc).strftime("%d.%m %H:%M")
                masked_ip = item["ip"]
                parts = masked_ip.split(".")
                if len(parts) == 4:
                    masked_ip = f"{parts[0]}.{parts[1]}.***.***"
                status_icon = "✔" if item["status"] == "SUCCESS" else "❌"
                lines.append(f"• `{dt_str} UTC` — `{masked_ip}` ({status_icon} {item['status']})")
            notice = "📜 **Последние входы в аккаунт:**\n" + "\n".join(lines)
        await interaction.response.edit_message(
            embed=self.build_embed(notice, interaction.user.id, player_name), view=self
        )

    @ui.button(label="Экстренный сброс и кик", style=discord.ButtonStyle.danger, emoji="🚨", custom_id="sec:emergency_kick", row=1)
    async def emergency_kick_btn(self, interaction: discord.Interaction, button: ui.Button):
        linked = self._linked(interaction.user.id)
        if not linked:
            return await self._reply(interaction, "❌ У вас нет привязанного аккаунта Minecraft.")
        player_name = linked["player_name"]
        self.bridge_cog.db.clear_ip_sessions(player_name)
        await self.bridge_cog.broadcast_packet({"type": "emergency_kick", "player": player_name})
        await self.bridge_cog.broadcast_packet({"type": "clear_sessions", "player": player_name})
        notice = "🚨 Все доверенные IP сброшены. Если кто-то находился на сервере — он исключён."
        await interaction.response.edit_message(
            embed=self.build_embed(notice, interaction.user.id, player_name), view=self
        )

    @ui.button(label="Отвязать аккаунт", style=discord.ButtonStyle.secondary, emoji="🔗", custom_id="sec:unlink_btn", row=1)
    async def unlink_btn(self, interaction: discord.Interaction, button: ui.Button):
        linked = self._linked(interaction.user.id)
        if not linked:
            return await self._reply(interaction, "❌ У вас нет привязанного аккаунта Minecraft.")
        player_name = linked["player_name"]
        unlinked = self.bridge_cog.db.unlink_account_by_discord(interaction.user.id)
        target_name = unlinked or player_name
        self.bridge_cog.pending_2fa.pop(target_name.lower(), None)
        try:
            await self.bridge_cog.broadcast_packet({"type": "account_unlinked", "player": target_name})
        except Exception:
            pass

        embed = discord.Embed(
            title="Аккаунт отвязан • Vanilla Land",
            description=(
                f"Аккаунт Minecraft **`{target_name}`** успешно отвязан от вашего Discord профиля. "
                "Двухфакторная защита 2FA отключена."
            ),
            color=Colors.DARK,
        )
        embed.set_footer(text="Vanilla Land • Безопасность аккаунта")
        await interaction.response.edit_message(embed=embed, view=None)


class LinkModal(ui.Modal, title="Привязка аккаунта Minecraft"):
    def __init__(self, bridge_cog: "BridgeCog"):
        super().__init__()
        self.bridge_cog = bridge_cog

        self.input_field = ui.TextInput(
            label="Никнейм в игре или 6-значный код",
            placeholder="Например: Steve или 123456 (если получили код в игре)",
            max_length=24,
            required=True,
        )
        self.add_item(self.input_field)

    async def on_submit(self, interaction: discord.Interaction):
        # 0. Проверяем, не привязан ли уже этот Discord-пользователь
        linked = self.bridge_cog.db.get_linked_account_by_discord(interaction.user.id)
        if linked:
            view = AccountSecurityView(self.bridge_cog, interaction.user.id, linked["player_name"])
            embed = AG.embed(
                title="Аккаунт уже привязан • Vanilla Land",
                description=(
                    f"К вашему Discord-профилю уже привязан игровой аккаунт **`{linked['player_name']}`**.\n\n"
                    "• Привязать более одного аккаунта **нельзя**.\n"
                    "• Если вы хотите сменить игровой ник, сначала отвяжите текущий аккаунт командой `!unlink`.\n\n"
                    "> Ниже представлены настройки безопасности вашего текущего аккаунта:"
                ),
                color=Colors.YELLOW,
                thumbnail=get_skin_avatar_url(linked["player_name"], None, self.bridge_cog.db),
            )
            return await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        val = self.input_field.value.strip()
        if not val:
            return await interaction.response.send_message("Введите ваш ник или код.", ephemeral=True)

        # 1. Если введен 6-значный код
        if val.isdigit() and len(val) == 6:
            if not self.bridge_cog.link_rate_ok(interaction.user.id):
                return await interaction.response.send_message(
                    "⏳ Слишком много попыток ввода кода. Попробуйте снова через 10 минут.", ephemeral=True
                )
            code_info = self.bridge_cog.db.get_link_code(val)
            if code_info and code_info.get("discord_user_id") and int(code_info["discord_user_id"]) != int(interaction.user.id):
                return await interaction.response.send_message(
                    "❌ Этот код принадлежит другому Discord-пользователю. Получите код в своём аккаунте.", ephemeral=True
                )
            if code_info:
                code_info = self.bridge_cog.db.consume_link_code(val)
            if code_info and code_info.get("player_name"):
                player_name = code_info["player_name"]
                already_mc = self.bridge_cog.db.get_linked_account_by_mc(player_name)
                if already_mc:
                    return await interaction.response.send_message(
                        f"Игровой аккаунт **`{player_name}`** уже привязан к Discord! Повторная привязка невозможна.",
                        ephemeral=True
                    )
                success = self.bridge_cog.db.link_account(player_name, "", interaction.user.id, two_factor=1)
                if success:
                    embed = AG.embed(
                        title="Аккаунт успешно привязан • Vanilla Land",
                        description=(
                            f"Ваш аккаунт Minecraft **`{player_name}`** успешно привязан.\n\n"
                            "• **Двухфакторная защита (2FA):** `Включена`\n"
                            "> Теперь при входе с новых IP бот будет запрашивать подтверждение в ЛС."
                        ),
                        color=Colors.GREEN,
                        thumbnail=get_skin_avatar_url(player_name, None, self.bridge_cog.db),
                    )
                    view = AccountSecurityView(self.bridge_cog, interaction.user.id, player_name)
                    return await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                else:
                    return await interaction.response.send_message("Не удалось привязать: этот аккаунт уже привязан.", ephemeral=True)
            else:
                return await interaction.response.send_message("Код не найден или истёк срок его действия (10 минут).", ephemeral=True)

        # 2. Если введён никнейм игрока
        player_name = val
        already_linked = self.bridge_cog.db.get_linked_account_by_mc(player_name)
        if already_linked:
            return await interaction.response.send_message(
                f"Игровой аккаунт **`{player_name}`** уже привязан к Discord! Повторная привязка невозможна.",
                ephemeral=True
            )

        # Генерируем 6-значный код
        code = f"{secrets.randbelow(900000) + 100000}"
        self.bridge_cog.db.create_link_code(player_name=player_name, discord_user_id=interaction.user.id, code=code, lifetime_sec=600)

        embed = AG.embed(
            title="Завершение привязки • Vanilla Land",
            description=(
                f"Для привязки аккаунта **`{player_name}`** зайдите на сервер Minecraft и введите команду:\n\n"
                f"```fix\n/link {code}\n```\n"
                "• **Срок действия кода:** `10 минут`\n"
                f"• **Одноразовый код:** `{code}`\n\n"
                "*После ввода команды в игре аккаунт будет мгновенно привязан к вашему Discord.*"
            ),
            color=Colors.INDIGO,
            thumbnail=get_skin_avatar_url(player_name, None, self.bridge_cog.db),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class PermanentLinkPanelView(ui.View):
    """Постоянная панель привязки аккаунтов с кнопками"""
    def __init__(self, bridge_cog: "BridgeCog"):
        super().__init__(timeout=None)
        self.bridge_cog = bridge_cog

    @ui.button(label="Привязать аккаунт", style=discord.ButtonStyle.success, emoji="🔗", custom_id="bridge:permanent_link_btn", row=0)
    async def link_btn(self, interaction: discord.Interaction, button: ui.Button):
        linked = self.bridge_cog.db.get_linked_account_by_discord(interaction.user.id)
        if linked:
            view = AccountSecurityView(self.bridge_cog, interaction.user.id, linked["player_name"])
            embed = discord.Embed(
                title=f"Аккаунт уже привязан • {linked['player_name']}",
                description=(
                    f"К вашему Discord-профилю уже привязан игровой аккаунт **`{linked['player_name']}`**.\n\n"
                    "• Привязать более одного аккаунта нельзя.\n"
                    "• Если вы хотите сменить никнейм, сначала отвяжите текущий аккаунт кнопкой в меню ниже.\n\n"
                    "> Ниже представлены параметры безопасности вашего аккаунта:"
                ),
                color=0xFF8C00,
            )
            skin_url = get_skin_avatar_url(linked["player_name"], None, self.bridge_cog.db)
            if skin_url:
                embed.set_thumbnail(url=skin_url)
            return await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        modal = LinkModal(self.bridge_cog)
        await interaction.response.send_modal(modal)

    @ui.button(label="Мой статус 2FA", style=discord.ButtonStyle.secondary, emoji="⚙️", custom_id="bridge:my_security_btn", row=0)
    async def status_btn(self, interaction: discord.Interaction, button: ui.Button):
        linked = self.bridge_cog.db.get_linked_account_by_discord(interaction.user.id)
        if not linked:
            return await interaction.response.send_message("❌ У вас пока нет привязанного игрового аккаунта. Нажмите зелёную кнопку «Привязать аккаунт».", ephemeral=True)
        view = AccountSecurityView(self.bridge_cog, interaction.user.id, linked["player_name"])
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)


