"""
UI Kit & Embed Helper for Vanilla Land Discord Bot
===================================================
Чистый, лаконичный и человечный дизайн:
- Тёмная нейтральная основа Discord (#2B2D31)
- Понятный аккуратный текст без лишних значков и нагромождений
- Удобные интерактивные кнопки Discord
"""

from typing import Optional, List, Union
import discord
from discord import ui
from config import Config


class Colors:
    DARK = 0x2B2D31        # Основной цвет сервера
    GREEN = 0x57F287       # Успех, размут, подтверждение
    RED = 0xED4245         # Бан, кик, ошибка, удаление
    YELLOW = 0xFEE75C      # Предупреждение, мут
    BLUE = 0x5865F2        # Инфо, ссылки, тикеты

    # Алиасы для обратной совместимости
    INDIGO = DARK
    CYAN = BLUE
    EMERALD = GREEN
    CORAL = RED
    AMBER = YELLOW
    SLATE = DARK
    GOLD = YELLOW
    ORANGE = 0xF39C12
    PURPLE = 0x9B59B6


class AG:
    """Хелпер создания сообщений и эмбедов Vanilla Land"""

    # Безопасные маркеры (без вычурных спецсимволов)
    SPARK = ""
    DIAMOND = "•"
    DOT = "•"

    @staticmethod
    def embed(
        title: Optional[str] = None,
        description: Optional[str] = None,
        color: int = Colors.DARK,
        footer: Optional[str] = "Vanilla Land",
        footer_icon: Optional[str] = None,
        thumbnail: Optional[str] = None,
        image: Optional[str] = None,
        author_name: Optional[str] = None,
        author_icon: Optional[str] = None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
        )
        if author_name:
            embed.set_author(name=author_name, icon_url=author_icon)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        if image:
            embed.set_image(url=image)
        if footer:
            embed.set_footer(text=footer, icon_url=footer_icon)
        return embed

    @classmethod
    def info(
        cls,
        title: str,
        description: str,
        guild: Optional[discord.Guild] = None,
        footer: Optional[str] = "Vanilla Land",
    ) -> discord.Embed:
        icon = guild.icon.url if guild and guild.icon else None
        return cls.embed(
            title=title,
            description=description,
            color=Colors.DARK,
            footer=footer,
            footer_icon=icon,
            thumbnail=icon,
        )

    @classmethod
    def success(
        cls,
        title: str,
        description: str,
        footer: Optional[str] = "Vanilla Land",
    ) -> discord.Embed:
        return cls.embed(
            title=title,
            description=description,
            color=Colors.GREEN,
            footer=footer,
        )

    @classmethod
    def error(
        cls,
        title: str,
        description: str,
        footer: Optional[str] = "Vanilla Land",
    ) -> discord.Embed:
        return cls.embed(
            title=title,
            description=description,
            color=Colors.RED,
            footer=footer,
        )

    @classmethod
    def warning(
        cls,
        title: str,
        description: str,
        footer: Optional[str] = "Vanilla Land",
    ) -> discord.Embed:
        return cls.embed(
            title=title,
            description=description,
            color=Colors.YELLOW,
            footer=footer,
        )

    @classmethod
    def mod_action(
        cls,
        action: str,
        target_str: str,
        moderator_str: str,
        reason: str,
        duration: Optional[str] = None,
        color: int = Colors.DARK,
        icon: Optional[str] = None,
    ) -> discord.Embed:
        embed = cls.embed(
            title=action,
            color=color,
            footer="Vanilla Land • Модерация",
        )
        if icon:
            embed.set_thumbnail(url=icon)

        embed.add_field(name="Пользователь", value=target_str, inline=True)
        embed.add_field(name="Модератор", value=moderator_str, inline=True)
        if duration:
            embed.add_field(name="Длительность", value=f"`{duration}`", inline=True)

        embed.add_field(
            name="Причина",
            value=reason or "Не указана",
            inline=False,
        )
        return embed


# Для обратной совместимости импортов
AGColors = Colors


# =====================================================================
# КНОПКИ ДЛЯ ССЫЛОК
# =====================================================================

class DonateLinkView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        if Config.DONATE_URL:
            self.add_item(
                ui.Button(
                    label="🛒 Магазин (vanillaland.store)",
                    style=discord.ButtonStyle.link,
                    url=Config.DONATE_URL,
                )
            )
        if getattr(Config, "SITE_URL", None):
            self.add_item(
                ui.Button(
                    label="🌐 Сайт проекта",
                    style=discord.ButtonStyle.link,
                    url=Config.SITE_URL,
                )
            )
        if Config.TELEGRAM_URL:
            self.add_item(
                ui.Button(
                    label="Telegram",
                    style=discord.ButtonStyle.link,
                    url=Config.TELEGRAM_URL,
                )
            )
        if Config.VK_URL:
            self.add_item(
                ui.Button(
                    label="ВКонтакте",
                    style=discord.ButtonStyle.link,
                    url=Config.VK_URL,
                )
            )


class LinksView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        if getattr(Config, "SITE_URL", None):
            self.add_item(
                ui.Button(
                    label="Наш сайт",
                    style=discord.ButtonStyle.link,
                    url=Config.SITE_URL,
                )
            )
        if getattr(Config, "DISCORD_URL", None):
            self.add_item(
                ui.Button(
                    label="Discord",
                    style=discord.ButtonStyle.link,
                    url=Config.DISCORD_URL,
                )
            )
        if Config.TELEGRAM_URL:
            self.add_item(
                ui.Button(
                    label="Telegram",
                    style=discord.ButtonStyle.link,
                    url=Config.TELEGRAM_URL,
                )
            )
        if Config.DONATE_URL:
            self.add_item(
                ui.Button(
                    label="Донат",
                    style=discord.ButtonStyle.link,
                    url=Config.DONATE_URL,
                )
            )
        if Config.RULES_URL:
            self.add_item(
                ui.Button(
                    label="Правила",
                    style=discord.ButtonStyle.link,
                    url=Config.RULES_URL,
                )
            )


class RulesLinkView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        if Config.RULES_URL:
            self.add_item(
                ui.Button(
                    label="Правила в Google Docs",
                    style=discord.ButtonStyle.link,
                    url=Config.RULES_URL,
                )
            )
        if Config.TELEGRAM_URL:
            self.add_item(
                ui.Button(
                    label="Telegram",
                    style=discord.ButtonStyle.link,
                    url=Config.TELEGRAM_URL,
                )
            )
