import math
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import Config
from design import AG, DonateLinkView, RulesLinkView


def format_uptime(start_time: float) -> str:
    uptime_sec = max(0, int(time.time() - start_time))
    hours, remainder = divmod(uptime_sec, 3600)
    minutes, seconds = divmod(remainder, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days > 0:
        parts.append(f"{days} дн.")
    if hours > 0:
        parts.append(f"{hours} ч.")
    if minutes > 0:
        parts.append(f"{minutes} мин.")
    parts.append(f"{seconds} сек.")
    return " ".join(parts)


def is_mod_or_admin_check(ctx) -> bool:
    author = ctx.author
    if not isinstance(author, discord.Member):
        return False
    guild = ctx.guild
    if author.guild_permissions.administrator or (guild and author.id == guild.owner_id):
        return True
    author_roles = {r.id for r in author.roles}
    return any(r_id in author_roles for r_id in Config.MOD_ROLE_IDS)


def build_overview_embed(guild: Optional[discord.Guild], is_staff: bool) -> discord.Embed:
    guild_icon = guild.icon.url if guild and guild.icon else None
    embed = AG.embed(
        title="Справочник команд • Vanilla Land",
        description=(
            "Добро пожаловать в центр команд **Vanilla Land**!\n\n"
            "Выберите интересующий раздел в **выпадающем меню ниже**, чтобы просмотреть "
            "полный список команд, их аргументы и русские аналоги."
        ),
        footer="Vanilla Land • Навигация",
        footer_icon=guild_icon,
        thumbnail=guild_icon,
    )

    embed.add_field(
        name="Доступные категории",
        value=(
            "• **Сервер Minecraft** — Онлайн, статистика игроков, мир, TPS и координаты\n"
            "• **Поддержка и тикеты** — Создание и управление персональными обращениями\n"
            "• **Утилиты Discord** — Аватары, профили участников, напоминания и сервер\n"
            "• **О проекте** — Адрес подключения, ссылка на правила и сайт"
        ),
        inline=False,
    )
    embed.add_field(
        name="Поддерживаемые префиксы",
        value="Все команды работают через обычный префикс `!` (включая русские команды) и через слэш `/`.",
        inline=False,
    )

    if is_staff:
        embed.add_field(
            name="Доступ персонала",
            value="Вам открыт доступ к категории модерации и администрирования в меню ниже.",
            inline=False,
        )

    return embed



def build_bridge_embed(guild: Optional[discord.Guild]) -> discord.Embed:
    guild_icon = guild.icon.url if guild and guild.icon else None
    embed = AG.embed(
        title="Сервер Minecraft • Vanilla Land",
        description="Команды для мониторинга игры и взаимодействия с сервером Vanilla Land SMP.",
        footer="Vanilla Land • Minecraft",
        footer_icon=guild_icon,
        thumbnail=guild_icon,
    )

    embed.add_field(
        name="Статистика и профили",
        value=(
            "• `!online` (`!онлайн`) — Список игроков в сети и текущий TPS\n"
            "• `!top [категория] [сезон]` (`!топ`, `!лидеры`, `/top_archive`) — Таблица лидеров (`3 сезон` и `4 сезон`)\n"
            "• `!profile [ник]` (`!профиль`, `!стата`) — Карточка игрока (скин, руды, K/D, дата первого входа)\n"
            "• `/playtime [ник]` (`!время_в_игре`) — Время в игре за текущий сезон и место в топе\n"
            "• `!skin <ник>` (`!скин`) — Рендер скина и ссылка на исходный файл скина\n"
            "• `!deaths` (`!смерти`) — Таблица смертей («Премия Дарвина»)"
        ),
        inline=False,
    )
    embed.add_field(
        name="Мир и окружение",
        value=(
            "• `!world` (`!мир`) — Игровое время, день мира, погода, фаза луны и TPS\n"
            "• `!tps` (`!тпс`) — Детальный мониторинг TPS, задержки тиков (MSPT) и оперативной памяти\n"
            "• `!time` (`!время`) — Текущий час и погода в верхнем мире"
        ),
        inline=False,
    )
    embed.add_field(
        name="Связь и координаты",
        value=(
            "• `!coords` (`!координаты`) — Отправка точных координат последней смерти в ЛС\n"
            "• `!msg_mc <ник> <текст>` (`!лс`) — Личное сообщение игроку на сервер из Discord"
        ),
        inline=False,
    )

    return embed


def build_tickets_embed(guild: Optional[discord.Guild]) -> discord.Embed:
    guild_icon = guild.icon.url if guild and guild.icon else None
    embed = AG.embed(
        title="Поддержка и тикеты • Vanilla Land",
        description="Создание персональных обращений к администрации для решения вопросов и жалоб.",
        footer="Vanilla Land • Поддержка",
        footer_icon=guild_icon,
        thumbnail=guild_icon,
    )

    embed.add_field(
        name="Команды тикетов",
        value=(
            "• `!ticket` (`!тикет`, `!обращение`) — Создать новое обращение\n"
            "• `!close [причина]` (`!закрыть`) — Закрыть текущее обращение с сохранением транскрипта\n"
            "• `!add @пользователь` (`!добавить`) — Добавить участника в тикет\n"
            "• `!remove @пользователь` (`!исключить`) — Убрать участника из тикета\n"
            "• `!rename [название]` (`!переименовать`) — Изменить название канала обращения"
        ),
        inline=False,
    )
    embed.add_field(
        name="Правила обращений",
        value=(
            "• Один пользователь может иметь только одно открытое обращение одновременно.\n"
            "• При отсутствии активности тикет автоматически архивируется через 24 часа."
        ),
        inline=False,
    )

    return embed


def build_utility_embed(guild: Optional[discord.Guild]) -> discord.Embed:
    guild_icon = guild.icon.url if guild and guild.icon else None
    embed = AG.embed(
        title="Утилиты Discord • Vanilla Land",
        description="Полезные команды для участников сервера.",
        footer="Vanilla Land • Утилиты",
        footer_icon=guild_icon,
        thumbnail=guild_icon,
    )

    embed.add_field(
        name="Профили и сервер",
        value=(
            "• `!user [@user]` (`!юзер`, `!userinfo`) — Карточка профиля участника, роли и дата регистрации\n"
            "• `!avatar [@user]` (`!аватар`, `!ава`) — Аватар пользователя в высоком разрешении\n"
            "• `!server` (`!сервер`) — Статистика сервера Discord (участники, каналы, бусты)"
        ),
        inline=False,
    )
    embed.add_field(
        name="Инструменты",
        value=(
            "• `!roll [макс]` (`!рандом`, `!ролл`) — Случайное число от 1 до 100 (или N)\n"
            "• `!remind <время> <текст>` (`!напомни`) — Установить напоминание (например: `10m`, `2h`, `1d`)"
        ),
        inline=False,
    )

    return embed


def build_info_embed(guild: Optional[discord.Guild]) -> discord.Embed:
    guild_icon = guild.icon.url if guild and guild.icon else None
    embed = AG.embed(
        title="О проекте • Vanilla Land",
        description="Основные данные для подключения и официальные ресурсы проекта.",
        footer="Vanilla Land • Информация",
        footer_icon=guild_icon,
        thumbnail=guild_icon,
    )

    embed.add_field(
        name="Подключение и ресурсы",
        value=(
            f"• **IP адрес:** `{Config.SERVER_IP}` (Java Edition 26.3)\n"
            f"• **Донат / Магазин:** [vanillaland.store]({Config.DONATE_URL})\n"
            f"• **Сайт проекта:** [vanillaland.fun]({Config.SITE_URL})\n"
            f"• **Telegram канал:** [t.me/vanilandes]({Config.TELEGRAM_URL})\n"
            f"• **Правила сервера:** [Открыть регламент]({Config.RULES_URL})"
        ),
        inline=False,
    )
    embed.add_field(
        name="Команды информации",
        value=(
            "• `!ip` (`!айпи`) — Адрес сервера и ссылка на Telegram\n"
            "• `!rules` (`!правила`) — Официальные правила проекта\n"
            "• `/rule <пункт/слово>` (`!правило`) — Быстрый поиск по пунктам правил\n"
            "• `!donate` (`!донат`) — Поддержка проекта и ссылка на магазин\n"
            "• `!ping` (`!пинг`) — Задержка отклика и время непрерывной работы бота"
        ),
        inline=False,
    )

    return embed


def build_mod_help_embed(guild: Optional[discord.Guild]) -> discord.Embed:
    guild_icon = guild.icon.url if guild and guild.icon else None
    embed = AG.embed(
        title="Команды персонала • Vanilla Land",
        description="Панель инструментов для модераторов и администрации сервера.",
        footer="Vanilla Land • Модерация",
        footer_icon=guild_icon,
        thumbnail=guild_icon,
    )

    embed.add_field(
        name="Модерация текстовых каналов",
        value=(
            "• `!mute [@user/ответ] [время] [причина]` — Заглушить участника\n"
            "• `!unmute [@user/ответ] [причина]` — Снять заглушение\n"
            "• `!kick [@user/ответ] [причина]` — Исключить с сервера\n"
            "• `!ban [@user/ответ/ID] [причина]` — Заблокировать на сервере\n"
            "• `!unban <ID> [причина]` — Разблокировать по ID\n"
            "• `!clear [кол-во]` — Удалить сообщения (1-100)\n"
            "• `!slowmode [время]` — Установить задержку отправки сообщений\n"
            "• `!lock [причина]` / `!unlock` — Заблокировать / открыть текущий канал\n"
            "• `!lockall` / `!unlockall` — Режим анти-рейда (блокировка всех каналов)"
        ),
        inline=False,
    )

    embed.add_field(
        name="Голосовые каналы и коммуникация",
        value=(
            "• `!vckick @user [причина]` — Отключить от голосового канала\n"
            "• `!vcban @user [время] [причина]` — Заблокировать вход в голосовые каналы\n"
            "• `/say <текст> [#канал] [as_embed]` — Отправить сообщение или рамку от имени бота\n"
            "• `!poll <вопрос> [варианты...]` — Создать опрос с реакциями"
        ),
        inline=False,
    )

    embed.add_field(
        name="Управление тикетами",
        value=(
            "• `!history` — Список всех активных тикетов\n"
            "• `/user_tickets <ник/ID>` (`!тикеты_юзера`) — Все тикеты пользователя и их содержимое\n"
            "• `!ticketban @user [причина]` — Запретить создание тикетов\n"
            "• `!ticketunban @user` — Снять запрет на тикеты"
        ),
        inline=False,
    )

    embed.add_field(
        name="Инструменты сервера Minecraft",
        value=(
            "• `!maintenance [on/off/таймер]` (`!техработы`) — Управление техработами сервера\n"
            "• `!bc <текст>` (`!бц`, `!announce`) — Цветное объявление на сервер Minecraft\n"
            "• `/whois <ник>` — Полное досье игрока (IP, сеть, привязка, статистика)\n"
            "• `!alts <ник/IP>` — Поиск мультиаккаунтов по совпадению IP\n"
            "• `!invsee <ник>` — Просмотр инвентаря онлайн-игрока\n"
            "• `!endersee <ник>` — Просмотр эндер-сундука\n"
            "• `!chunks` — Диагностика нагрузки чанков и мобов\n"
            "• `!automod [on/off]` — Переключение фильтра ссылок и рекламы\n"
            "• `!online` — Онлайн, TPS и список игроков (состояние моста)"
        ),
        inline=False,
    )

    embed.add_field(
        name="Безопасность и диагностика",
        value=(
            "• `/verification_lockdown [on/off] [причина]` — Экстренная блокировка верификации (защита от рейдов)\n"
            "• `/healthcheck` (`!статус`) — Аудит сервера, TPS, памяти, прав и моста `[Тех. Админ+]`\n"
            "• `/panic_whitelist [on/off] [kickall]` — Режим изоляции сервера (Panic Whitelist)\n"
            "• `/audit_perms` — Аудит прав ролей и каналов Discord-сервера\n"
            "• `/bridge_status` (`!мост_статус`) — Диагностика WebSocket-моста, RTT пинг и история разрывов\n"
            "• `/stats_graph [24h|7d]` — График онлайна и TPS сервера\n"
            "• `!alts_channel [#канал]` / `!alts_panel` — Оповещения о твинках и обходе банов"
        ),
        inline=False,
    )

    embed.add_field(
        name="Управление, бэкапы и ивенты",
        value=(
            "• `/setup_channels` — Единая настройка всех каналов бота и категории тикетов\n"
            "• `/db_backup [now|list|send|channel]` — Бэкап и ротация базы данных `tickets.db`\n"
            "• `/ticket_reply [add|list|remove|test]` — Автоответы в тикетах (точные и похожие фразы)\n"
            "• `/ticket_roles` — Просмотр всех ролей доступа и пинга в тикетах\n"
            "• `/giveaway` — GUI-конструктор создания и запуска розыгрышей\n"
            "• `/top_reset` / `/rules_sync` — Закрытие сезона топа / синхронизация правил"
        ),
        inline=False,
    )

    embed.add_field(
        name="Панели и роли (Администрация)",
        value=(
            "• `!verify_panel` — Панель верификации новых участников\n"
            "• `!ticket_panel` — Панель создания тикетов\n"
            "• `!roles_info` — Проверка настройки ролей верификации и мута\n"
            "• `!sync_roles` — Раздать начальные роли участникам без ролей\n"
            "• `!ticket_ping_role add/remove/list/clear @роль` — Роли, которые пингуются в новых тикетах"
            " *(владелец/админ)*"
        ),
        inline=False,
    )

    return embed


class HelpSelect(discord.ui.Select):
    def __init__(self, is_staff: bool, guild: Optional[discord.Guild], author_id: int):
        options = [
            discord.SelectOption(label="Главная", value="overview", description="Обзор всех разделов и возможностей"),
            discord.SelectOption(label="Поддержка и тикеты", value="tickets", description="Создание и управление обращениями"),
            discord.SelectOption(label="Сервер Minecraft", value="bridge", description="Онлайн, статистика, профили, мир, топы"),
            discord.SelectOption(label="Утилиты Discord", value="utility", description="Профили, аватарки, напоминания, рандом"),
            discord.SelectOption(label="О проекте", value="info", description="IP адрес, правила, донат и статус бота"),
        ]
        if is_staff:
            options.append(
                discord.SelectOption(label="Персонал и модерация", value="mod", description="Инструменты модераторов и администрации")
            )
        super().__init__(placeholder="Выберите категорию команд...", min_values=1, max_values=1, options=options)
        self.is_staff = is_staff
        self.guild = guild
        self.author_id = author_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(
                "Эта панель открыта другим пользователем. Используйте `!help`.",
                ephemeral=True
            )

        val = self.values[0]
        if val == "overview":
            embed = build_overview_embed(self.guild, self.is_staff)
        elif val == "bridge":
            embed = build_bridge_embed(self.guild)
        elif val == "tickets":
            embed = build_tickets_embed(self.guild)
        elif val == "utility":
            embed = build_utility_embed(self.guild)
        elif val == "info":
            embed = build_info_embed(self.guild)
        elif val == "mod":
            if not self.is_staff:
                return await interaction.response.send_message(
                    "У вас нет прав для просмотра команд персонала.",
                    ephemeral=True
                )
            embed = build_mod_help_embed(self.guild)
        else:
            embed = build_overview_embed(self.guild, self.is_staff)

        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpSearchModal(discord.ui.Modal, title="Поиск команды"):
    query_input = discord.ui.TextInput(
        label="Название команды или ключевое слово",
        placeholder="Например: top, мут, тикет, playtime, rule",
        max_length=50,
        required=True,
    )

    def __init__(self, bot: commands.Bot, is_staff: bool):
        super().__init__()
        self.bot = bot
        self.is_staff = is_staff

    async def on_submit(self, interaction: discord.Interaction):
        q = self.query_input.value.strip().lower().lstrip("!/")
        matches = []
        seen = set()
        for cmd in self.bot.commands:
            if cmd.hidden or cmd.name in seen:
                continue
            desc = (cmd.description or "").strip()
            aliases = [a.lower() for a in getattr(cmd, "aliases", [])]
            haystack = " ".join([cmd.name.lower(), desc.lower(), *aliases])
            if q in haystack:
                seen.add(cmd.name)
                sig = f" {cmd.signature}" if cmd.signature else ""
                matches.append(f"• `/{cmd.name}{sig}` — {desc or 'без описания'}")
                if len(matches) >= 12:
                    break

        if not matches:
            return await interaction.response.send_message(
                f"По запросу `{q}` команды не найдены.", ephemeral=True
            )
        embed = AG.embed(
            title=f"Поиск команд • «{q}»",
            description="\n".join(matches),
            color=Colors.BLUE,
            footer="Vanilla Land • Навигация",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class HelpSelectView(discord.ui.View):
    def __init__(self, is_staff: bool, guild: Optional[discord.Guild], author_id: int, bot: Optional[commands.Bot] = None):
        super().__init__(timeout=180)
        self.is_staff = is_staff
        self.guild = guild
        self.author_id = author_id
        self.bot = bot
        self.add_item(HelpSelect(is_staff, guild, author_id))

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Эта панель открыта другим пользователем. Используйте `!help`.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Minecraft", style=discord.ButtonStyle.secondary, row=1)
    async def btn_mc(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        await interaction.response.edit_message(embed=build_bridge_embed(self.guild), view=self)

    @discord.ui.button(label="Тикеты", style=discord.ButtonStyle.secondary, row=1)
    async def btn_tickets(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        await interaction.response.edit_message(embed=build_tickets_embed(self.guild), view=self)

    @discord.ui.button(label="Утилиты", style=discord.ButtonStyle.secondary, row=1)
    async def btn_utils(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        await interaction.response.edit_message(embed=build_utility_embed(self.guild), view=self)

    @discord.ui.button(label="Поиск команды", style=discord.ButtonStyle.primary, row=1)
    async def btn_search(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        bot_ref = self.bot or interaction.client
        await interaction.response.send_modal(HelpSearchModal(bot_ref, self.is_staff))


SERVER_RULES: list[dict[str, str]] = [
    {"id": "1.1", "title": "Запрещённое ПО", "text": "Запрещено использование чит-клиентов, X-Ray, автокликеров и модов, дающих преимущество.", "punishment": "Бан от 14 дней до перманентного"},
    {"id": "1.2", "title": "Обход наказаний", "text": "Запрещён обход блокировок и создание твинков для обхода выданных наказаний.", "punishment": "Перманентный бан твинка + продление основного бана"},
    {"id": "1.3", "title": "Краши и дюпы", "text": "Запрещены попытки краша, намеренного забивания тиков (лаг-машины) и дюпа предметов.", "punishment": "Перманентный бан"},
    {"id": "2.1", "title": "Реклама и скам", "text": "Запрещена реклама сторонних серверов, Discord-инвайтов, фишинговых и вредоносных ссылок.", "punishment": "Мут / Бан"},
    {"id": "2.2", "title": "Угрозы и доксинг", "text": "Запрещены угрозы расправой в реальной жизни, доксинг и публикация личных данных.", "punishment": "Перманентный бан"},
    {"id": "2.3", "title": "Уважение в общении", "text": "Относитесь с уважением к игрокам и администрации, избегайте травли и провокаций.", "punishment": "Мут от 30 минут"},
    {"id": "3.1", "title": "Гриферство и вандализм", "text": "Запрещён намеренный гриферский вандализм чужих построек и спавна.", "punishment": "Бан от 7 дней + откат постройки"},
    {"id": "3.2", "title": "Торговля и поселения", "text": "Разрешена честная ванильная торговля и создание поселений по договорённости с игроками.", "punishment": "Разрешено"},
]


class InfoCog(commands.Cog, name="Информация"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- IP ---
    @commands.hybrid_command(
        name="ip",
        aliases=["айпи", "сервер_айпи", "connect", "адрес"],
        description="IP адрес сервера и подключение"
    )
    async def ip_cmd(self, ctx: commands.Context):
        guild_icon = ctx.guild.icon.url if ctx.guild and ctx.guild.icon else None
        embed = AG.embed(
            title="Подключение • Vanilla Land",
            description=(
                f"**IP адрес:** `{Config.SERVER_IP}`\n"
                f"**Версия:** `26.3 (Java Edition)`\n"
                f"**Telegram:** [t.me/vanilandes]({Config.TELEGRAM_URL})"
            ),
            footer="Vanilla Land",
            footer_icon=guild_icon,
            thumbnail=guild_icon,
        )
        await ctx.send(embed=embed, view=DonateLinkView())

    # --- PING ---
    @commands.hybrid_command(
        name="ping",
        aliases=["пинг", "понг", "задержка", "аптайм", "uptime"],
        description="Задержка отклика и время непрерывной работы бота"
    )
    async def ping_cmd(self, ctx: commands.Context):
        lat = self.bot.latency
        ping_str = f"{round(lat * 1000)} ms" if lat and math.isfinite(lat) else "Подключение..."
        uptime_str = format_uptime(getattr(self.bot, "start_time", time.time()))
        guild_icon = ctx.guild.icon.url if ctx.guild and ctx.guild.icon else None

        embed = AG.embed(
            title="Статус бота • Vanilla Land",
            footer="Vanilla Land",
            footer_icon=guild_icon,
        )
        embed.add_field(name="Задержка", value=f"`{ping_str}`", inline=True)
        embed.add_field(name="Время работы", value=f"`{uptime_str}`", inline=True)

        await ctx.send(embed=embed)

    # --- RULES ---
    @commands.hybrid_command(
        name="rules",
        aliases=["правила", "регламент", "правила_сервера"],
        description="Официальный регламент и правила проекта"
    )
    async def rules_cmd(self, ctx: commands.Context):
        guild_icon = ctx.guild.icon.url if ctx.guild and ctx.guild.icon else None
        embed = AG.embed(
            title="Правила проекта • Vanilla Land",
            description=(
                "Ознакомьтесь с действующим регламентом и правилами сервера:\n\n"
                f"**[Открыть правила в Google Docs]({Config.RULES_URL})**\n\n"
                "*Незнание правил не освобождает от ответственности.*"
            ),
            footer="Vanilla Land • Правила",
            footer_icon=guild_icon,
            thumbnail=guild_icon,
        )
        await ctx.send(embed=embed, view=RulesLinkView())

    # --- RULE (ПОИСК ПО ПРАВИЛАМ) ---
    @commands.hybrid_command(
        name="rule",
        aliases=["правило", "пункт"],
        description="Поиск по правилам сервера (например: /rule 2.1 или /rule гриф)",
    )
    @app_commands.describe(query="Номер пункта (1.1, 2.1, 3.1) или ключевое слово")
    async def rule_cmd(self, ctx: commands.Context, *, query: str):
        q = (query or "").strip().lower()
        if not q:
            return await ctx.send("Укажите номер пункта или слово для поиска, например `/rule 2.1`.", ephemeral=True)

        found = []
        for r in SERVER_RULES:
            if q == r["id"].lower() or q in r["title"].lower() or q in r["text"].lower():
                found.append(r)

        if not found:
            return await ctx.send(
                f"По запросу `{query}` пункты правил не найдены. Полный регламент: {Config.RULES_URL}",
                ephemeral=True,
            )

        embed = AG.embed(
            title=f"Правила проекта • Поиск «{query}»",
            color=Colors.DARK,
            footer="Vanilla Land • Регламент",
        )
        for r in found[:5]:
            embed.add_field(
                name=f"Пункт {r['id']} — {r['title']}",
                value=f"{r['text']}\nНаказание: `{r['punishment']}`",
                inline=False,
            )
        await ctx.send(embed=embed, view=RulesLinkView())

    # --- DONATE ---
    @commands.hybrid_command(
        name="donate",
        aliases=["донат", "магазин", "сайт", "пожертвования", "shop", "store"],
        description="Поддержка проекта и ссылка на магазин vanillaland.store"
    )
    async def donate_cmd(self, ctx: commands.Context):
        guild_icon = ctx.guild.icon.url if ctx.guild and ctx.guild.icon else None
        embed = AG.embed(
            title="Магазин и донат • Vanilla Land",
            description=(
                "Пожертвования помогают серверу развиваться и оплачивать качественный хостинг.\n\n"
                f"• Официальный магазин доната: [**vanillaland.store**]({Config.DONATE_URL})\n"
                f"• Главный сайт проекта: [**vanillaland.fun**]({Config.SITE_URL})\n"
                f"• Новости и скидки в Telegram: [**t.me/vanilandes**]({Config.TELEGRAM_URL})\n\n"
                "*Спасибо каждому игроку, поддерживающему проект!*"
            ),
            footer=f"Vanilla Land • {Config.SERVER_IP}",
            footer_icon=guild_icon,
            thumbnail=guild_icon,
        )
        await ctx.send(embed=embed, view=DonateLinkView())

    # --- HELP ---
    @commands.hybrid_command(
        name="help",
        aliases=["хелп", "помощь", "команды", "справка", "menu", "меню"],
        description="Справка по командам бота с интерактивным выбором категорий"
    )
    async def help_cmd(self, ctx: commands.Context, *, category: Optional[str] = None):
        is_staff = is_mod_or_admin_check(ctx)
        guild = ctx.guild

        if category:
            cat_clean = category.lower().strip()
            if cat_clean in ("mod", "мод", "модерация", "admin", "админ", "персонал"):
                if not is_staff:
                    return await ctx.send("Эта справка доступна только персоналу сервера.", ephemeral=True)
                return await ctx.send(embed=build_mod_help_embed(guild))
            elif cat_clean in ("bridge", "mc", "майн", "сервер", "minecraft"):
                embed = build_bridge_embed(guild)
            elif cat_clean in ("tickets", "тикеты", "тикет", "поддержка"):
                embed = build_tickets_embed(guild)
            elif cat_clean in ("utility", "утилиты"):
                embed = build_utility_embed(guild)
            elif cat_clean in ("info", "инфо", "информация"):
                embed = build_info_embed(guild)
            else:
                embed = build_overview_embed(guild, is_staff)
        else:
            embed = build_overview_embed(guild, is_staff)

        view = HelpSelectView(is_staff, guild, ctx.author.id, bot=self.bot)
        await ctx.send(embed=embed, view=view)

    # --- HELP MOD ---
    @commands.hybrid_command(
        name="mod_help",
        aliases=["modhelp", "модхелп", "мод_хелп", "help_mod", "хелп_мод", "helpmod", "хелпмод"],
        description="Команды модерации для персонала сервера"
    )
    async def help_mod_cmd(self, ctx: commands.Context):
        if not is_mod_or_admin_check(ctx):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)
        await ctx.send(embed=build_mod_help_embed(ctx.guild))


async def setup(bot: commands.Bot):
    await bot.add_cog(InfoCog(bot))
