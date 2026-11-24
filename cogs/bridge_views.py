# -*- coding: utf-8 -*-
"""
Модуль представлений (UI Views) моста Vanilla Land:
- Личные сообщения из Discord в игру (DmReplyModal, DmReplyView)
- Привязка игрового аккаунта к Discord (AccountLinkView, LinkModal, PermanentLinkPanelView)
"""

import secrets
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

import discord
from discord import ui

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
        msg = await interaction.response.send_message(embed=embed, view=view)
        try:
            self.bridge_cog.db.save_dm_reply_target(msg.id, self.target_player)
        except Exception:
            pass


class DmReplyView(ui.View):
    def __init__(self, bridge_cog: "BridgeCog", target_player: str = ""):
        super().__init__(timeout=None)
        self.bridge_cog = bridge_cog
        self.target_player = target_player

    @ui.button(label="✉️ Написать ещё / Ответить", style=discord.ButtonStyle.primary, custom_id="bridge:dm_reply_btn")
    async def reply_btn(self, interaction: discord.Interaction, button: ui.Button):
        target = self.target_player
        if not target and self.bridge_cog.db and interaction.message:
            target = self.bridge_cog.db.get_dm_reply_target(interaction.message.id)
        if not target:
            return await interaction.response.send_message(
                "Диалог устарел. Используйте `/msg_mc`, чтобы начать новый.", ephemeral=True
            )
        modal = DmReplyModal(self.bridge_cog, target)
        await interaction.response.send_modal(modal)


class AccountLinkView(ui.View):
    """Просмотр привязанного игрового аккаунта и отвязка (persistent)."""

    def __init__(self, bridge_cog: "BridgeCog", discord_user_id: int = 0, player_name: str = ""):
        super().__init__(timeout=None)
        self.bridge_cog = bridge_cog
        self.discord_user_id = discord_user_id
        self.player_name = player_name

    def _linked(self, user_id: int):
        return self.bridge_cog.db.get_linked_account_by_discord(user_id)

    async def _reply(self, interaction: discord.Interaction, text: str):
        if interaction.guild is None:
            return await interaction.response.send_message(text)
        return await interaction.response.send_message(text, ephemeral=True)

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
                title="Привязка аккаунта • Vanilla Land",
                description="У вас нет привязанного аккаунта Minecraft. Используйте `/link`.",
                color=Colors.DARK,
            )

        linked_at = linked.get("linked_at", "Не зафиксирована")
        desc = (
            f"• 👤 **Игровой ник:** `{player_name}`\n"
            f"• 🔗 **Привязка Discord:** <@{uid}>\n"
            f"• 📅 **Дата привязки:** `{linked_at}`"
        )
        if notice:
            desc = f"**{notice}**\n\n" + desc

        embed = discord.Embed(
            title=f"Привязанный аккаунт • {player_name}",
            description=desc,
            color=Colors.BLUE,
        )
        skin_url = get_skin_avatar_url(player_name, None, self.bridge_cog.db)
        if skin_url:
            embed.set_thumbnail(url=skin_url)
        embed.set_footer(text="Vanilla Land • Привязка профиля")
        return embed

    @ui.button(label="Отвязать аккаунт", style=discord.ButtonStyle.danger, emoji="🔗", custom_id="sec:unlink_btn", row=0)
    async def unlink_btn(self, interaction: discord.Interaction, button: ui.Button):
        linked = self._linked(interaction.user.id)
        if not linked:
            return await self._reply(interaction, "❌ У вас нет привязанного аккаунта Minecraft.")
        player_name = linked["player_name"]
        unlinked = self.bridge_cog.db.unlink_account_by_discord(interaction.user.id)
        target_name = unlinked or player_name
        try:
            await self.bridge_cog.broadcast_packet({"type": "account_unlinked", "player": target_name})
        except Exception:
            pass

        embed = discord.Embed(
            title="Аккаунт отвязан • Vanilla Land",
            description=f"Аккаунт Minecraft **`{target_name}`** успешно отвязан от вашего Discord профиля.",
            color=Colors.DARK,
        )
        embed.set_footer(text="Vanilla Land • Привязка профиля")
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
        linked = self.bridge_cog.db.get_linked_account_by_discord(interaction.user.id)
        if linked:
            view = AccountLinkView(self.bridge_cog, interaction.user.id, linked["player_name"])
            embed = view.build_embed(
                notice="К вашему Discord-профилю уже привязан этот аккаунт.",
                user_id=interaction.user.id,
                player_name=linked["player_name"],
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
                        ephemeral=True,
                    )
                success = self.bridge_cog.db.link_account(player_name, "", interaction.user.id, two_factor=0)
                if success:
                    embed = AG.embed(
                        title="Аккаунт успешно привязан • Vanilla Land",
                        description=f"Ваш аккаунт Minecraft **`{player_name}`** успешно привязан к профилю Discord!",
                        color=Colors.GREEN,
                        thumbnail=get_skin_avatar_url(player_name, None, self.bridge_cog.db),
                    )
                    view = AccountLinkView(self.bridge_cog, interaction.user.id, player_name)
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
                ephemeral=True,
            )

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
            view = AccountLinkView(self.bridge_cog, interaction.user.id, linked["player_name"])
            embed = view.build_embed(
                notice="К вашему профилю уже привязан аккаунт. Вы можете отвязать его ниже.",
                user_id=interaction.user.id,
                player_name=linked["player_name"],
            )
            return await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        modal = LinkModal(self.bridge_cog)
        await interaction.response.send_modal(modal)

    @ui.button(label="Мой аккаунт", style=discord.ButtonStyle.secondary, emoji="👤", custom_id="bridge:my_security_btn", row=0)
    async def status_btn(self, interaction: discord.Interaction, button: ui.Button):
        linked = self.bridge_cog.db.get_linked_account_by_discord(interaction.user.id)
        if not linked:
            return await interaction.response.send_message("❌ У вас пока нет привязанного игрового аккаунта. Нажмите зелёную кнопку «Привязать аккаунт».", ephemeral=True)
        view = AccountLinkView(self.bridge_cog, interaction.user.id, linked["player_name"])
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)
