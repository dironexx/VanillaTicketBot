# -*- coding: utf-8 -*-
"""
Модуль представлений (UI Views) моста Vanilla Land:
- Личные сообщения из Discord в игру (DmReplyModal, DmReplyView)
"""

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
            title=f"Сообщение отправлено игроку {self.target_player}",
            description=f"Текст: *{text}*",
            color=Colors.BLUE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Vanilla Land • ЛС моста")
        view = DmReplyView(self.bridge_cog, self.target_player)
        await interaction.response.send_message(embed=embed, view=view)
        try:
            sent_msg = await interaction.original_response()
            self.bridge_cog.db.save_dm_reply_target(sent_msg.id, self.target_player)
        except Exception:
            pass


class DmReplyView(ui.View):
    def __init__(self, bridge_cog: "BridgeCog", target_player: str = ""):
        super().__init__(timeout=None)
        self.bridge_cog = bridge_cog
        self.target_player = target_player

    @ui.button(label="Написать ещё / Ответить", style=discord.ButtonStyle.primary, custom_id="bridge:dm_reply_btn")
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
