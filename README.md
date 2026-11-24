# Vanilla Land • Discord Bot & Bridge v1.4

Discord-бот службы поддержки, модерации и моста с Minecraft-сервером **Vanilla Land** (версия 1.4).
Работает как отдельный процесс: Discord (discord.py) + WebSocket-мост с плагином `VanillaBridge` (поддержка Leaf 26.3, Folia и Paper).

> 💡 **Для AI-агентов и разработчиков:** Полный архитектурный контекст и инструкции собраны в [AI_HANDOVER.md](AI_HANDOVER.md).

---

## Возможности

- **Тикеты**: панель с кнопкой, каналы `тикет-NNN`, транскрипт в автономном HTML (`.html`) и `.txt` в ЛС и архив, досье подозреваемого `/suspect`, авто-закрытие по неактивности, `!add/!remove/!rename/!close`, ЧС на тикеты.
- **Модерация и утилиты**: `!mute/!unmute/!kick/!ban/!unban/!clear/!slowmode/!lock/!unlock/!lockall/!unlockall/!vckick/!vcban`, мут = роль + Discord timeout + запись в БД + авто-снятие, команда `/say` (текст и embed от имени бота).
- **Мост Minecraft**: стилизованные embed-уведомления в Discord (старт/рестарт, входы/выходы, смерти с переводом), автоцензура мата внутри игрового чата (`п*****с`), внутриигровая офлайн-почта `/mail [send|read]`, статистика (TPS/MSPT/ОЗУ), диагностика сокетов `/bridge_status`, авто-бэкапы БД с ротацией `/db_backup`, авто-синхронизация голосовых каналов (Онлайн, TPS, IP `play.vanillaland.fun`), `/online`, `/top` (`3 сезон` и `4 сезон`), `/top_archive`, `/profile` (PNG-карточка), `/tps`, `/world`, `/time`, `/skin`, `/coords`, `/bc`, `/check`, `/invsee`, `/endersee`, `/chunks`, ЛС игроку (`/msg_mc`), техработы и рестарт, эндпоинт `/health` для Uptime Kuma.
- **Привязка аккаунтов**: одноразовые 6-значные коды привязки (`/link`, `/unlink`), синхронизация профиля `1 Discord = 1 ник`. Система 2FA полностью удалена из кода бота и плагина.
- **Безопасность**: детекция твинков и мультиаккаунтов по истории IP-адресов, `!whois`, `!alts`, `!alts_scan`, `!alts_history`, белый список, журнал инцидентов, `!healthcheck`.
- **Верификация**: роль «Неверифицирован», панель, изоляция каналов, локдаун от рейдов, `!sync_roles`, настройка ролей.
- **Автомод и логи**: анти-реклама (Discord/Telegram/паттерны) — удаление + мут 1 ч + кнопки решения для персонала; логи удаления/редактирования/входов/выходов.
- **Рендер графики**: `/profile` (800×420 PNG в стиле Obsidian/Linear), `/invsee`, `/endersee`, шалкеры — картинки на основе `assets/textures` и Pillow.

---

## Структура проекта

```
main.py                 # точка входа (класс бота, загрузка когов, синк слэшей)
bot.py                  # обёртка запуска main()
config.py               # загрузка .env и настройки
database.py             # SQLite (WAL), таблицы, миграции, самовосстановление
design.py               # UI-кит: эмбеды, цвета, кнопки-ссылки
cogs/
  tickets.py            # тикеты
  moderation.py         # мут/бан/кик/войс/каналы
  verification.py       # верификация и роли
  info.py               # справка по командам
  utility.py            # user/avatar/server/say/poll/roll/remind
  logs.py               # логи и автомод
  security.py           # детекция твинков по IP, whois, мультиаккаунты, healthcheck
  bridge.py             # WebSocket-мост с Minecraft (основной модуль)
  bridge_views.py       # UI моста: привязка и ЛС-ответы (вспомогательный)
  inventory_renderer.py # рендер инвентаря на Pillow (вспомогательный)
assets/
  textures/item/*.png   # текстуры предметов (16×16)
  textures/block/*.png  # текстуры блоков (16×16)
  fonts/font.ttf        # шрифт для рендера
scratch/VanillaBridgeProject/  # исходники Paper-плагина (в деплое не нужны)
```

> `cogs/bridge_views.py` и `cogs/inventory_renderer.py` — не коги, а вспомогательные модули
> (коги — только файлы с `setup()`).

---

## Требования

- Python **3.11+** (проверено на 3.13).
- Пакеты из `requirements.txt`: `discord.py`, `python-dotenv`, `Pillow` (плюс `aiohttp`, он приходит с discord.py).
- Желательно Linux (VPS/VDS) или Windows; на Windows запускайте с `-X utf8`, иначе cp1251 может уронить вывод на эмодзи:
  ```bash
  python -X utf8 main.py
  ```

Установка:

```bash
python -m venv .venv
# Linux: source .venv/bin/activate | Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## Конфигурация (.env)

Скопируйте `.env.example` в `.env` и заполните. **`.env` с токенами не коммитится** (см. `.gitignore`).

| Переменная | Назначение |
|---|---|
| `DISCORD_TOKEN` | токен бота (Developer Portal) |
| `GUILD_ID` | ID сервера (рекомендуется; 0 = первый доступный) |
| `PANEL_CHANNEL_ID` | канал панели тикетов |
| `TICKETS_CATEGORY_ID` | категория тикетов (0 = категория канала панели) |
| `MOD_ROLE_IDS` | ID ролей персонала через запятую |
| `ADMIN_ROLE_IDS` | ID ролей для security-команд; пусто = `MOD_ROLE_IDS` |
| `MUTE_ROLE_ID` | роль мута |
| `UNVERIFIED_ROLE_ID` / `VERIFIED_ROLE_ID` | роли верификации |
| `VERIFICATION_CHANNEL_ID` | канал верификации |
| `TICKET_PING_ROLE_ID` | роль для пинга в тикетах |
| `LOG_CHANNEL_ID` / `ADMIN_LOG_CHANNEL_ID` / `ALTS_ALERT_CHANNEL_ID` | каналы логов, алертов, безопасности |
| `BRIDGE_CHANNEL_ID` / `EVENTS_CHANNEL_ID` / `COMMANDS_CHANNEL_ID` | каналы моста |
| `BRIDGE_PORT` | порт WebSocket-моста (по умолчанию 25549) |
| `BRIDGE_SECRET` | общий секрет моста (см. ниже) |
| `SERVER_IP` / `SITE_URL` / `DONATE_URL` / `TELEGRAM_URL` / `VK_URL` / `RULES_URL` | информация о проекте |
| `DB_PATH` / `TRANSCRIPTS_DIR` | путь к БД и транскриптам |
| `AUTO_CLOSE_HOURS` | авто-закрытие тикетов (по умолчанию 24) |

> `.env.example` — только шаблон. Начиная с этой версии бот **не** загружает его как конфиг
> (раньше он мог перебивать переменные хостинга фейковым токеном).

---

## Деплой (VPS/VDS)

1. Загрузите на сервер: `main.py`, `bot.py`, `config.py`, `config_sync.py`, `database.py`, `design.py`,
   `cogs/`, `assets/`, `requirements.txt`, `.env` (создать на сервере, не заливать из репозитория).
2. Установите зависимости и запустите:
   ```bash
   cd /opt/vanilla-bot
   python3 -m venv .venv && . .venv/bin/activate
   pip install -r requirements.txt
   python -X utf8 main.py
   ```
3. Пример unit-файла systemd (`/etc/systemd/system/vanilla-bot.service`):
   ```ini
   [Unit]
   Description=Vanilla Land Discord Bot
   After=network-online.target

   [Service]
   Type=simple
   WorkingDirectory=/opt/vanilla-bot
   EnvironmentFile=/opt/vanilla-bot/.env
   ExecStart=/opt/vanilla-bot/.venv/bin/python -X utf8 main.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
   ```bash
   systemctl daemon-reload && systemctl enable --now vanilla-bot
   ```

**Важно:** `design.py` и `assets/` обязательны. Без `design.py` бот не загрузит коги
(`ModuleNotFoundError`), без `assets/` рендер инвентаря будет с пустыми слотами.

В порту моста (`BRIDGE_PORT`) должен быть доступен плагин; при использовании
`wss://bridge.vanillaland.fun/ws` трафик терминирует Cloudflare/nginx — тогда наружу
можно не открывать порт напрямую.

---

## Мост с Minecraft (плагин VanillaBridge v1.3)

- Плагин поддерживает **Leaf 26.3**, **Folia** и **Paper** через кросс-платформенный модуль `UniversalScheduler`.
- Подключается к боту по `ws://`/`wss://` и передаёт секрет в query/заголовке.
- В `config.yml` плагина: `server-id` (`main`/`vps`), `bridge.ws-url`, `bridge.token`.
- Аутентификация и 2FA на сервере возложены на плагин **Victim** (на прокси/Velocity/Limbo), поэтому внутренний 2FA моста отключён (`ENABLE_LOGIN_2FA: false`).
- Бот принимает несколько серверов одновременно (main + vps): сокеты хранятся множеством,
  широковещательные пакеты уходят всем.
- Пакеты: `join/quit/death/chat/stats/lifecycle`, `dm_request` → `dm_reply`, `execute_console_command`, `maintenance*`, `announcement`.

### Секрет моста

`BRIDGE_SECRET` должен быть одинаковым в `.env` бота и `bridge.token` плагина.

Сгенерировать новый:

```bash
python -X utf8 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Затем:

1. вписать в `.env` → `BRIDGE_SECRET=...`;
2. вписать в `plugins/VanillaBridge/config.yml` → `bridge.token: "..."`;
3. перезапустить сервер Minecraft и бота.

**Не оставляйте значение по умолчанию** `vanillaland_secret_2026`: зная секрет, можно
подключиться к мосту и слать поддельные пакеты. Бот предупреждает об этом в логе.

---

## Автосинхронизация конфигов

- **Бот:** при старте `config_sync.py` добавляет в `.env` только отсутствующие
  несекретные ключи (`ADMIN_ROLE_IDS`, `BRIDGE_PORT` и т.п.). Существующие значения
  не перезаписываются; `DISCORD_TOKEN` и `BRIDGE_SECRET` не трогаются.
- **Плагин:** `migrateConfig()` вызывает `copyDefaults(true)` — в `config.yml`
  добавляются новые ключи (например, `security.trust-duration-hours`), значения
  существующих сохраняются.
- Отключить для тестов: `VANILLA_ENV_SYNC=0`.

## Тесты

```bash
python -X utf8 -m unittest discover -s tests -t . -v
```

Тесты не меняют реальный `.env` (`VANILLA_ENV_SYNC=0`) и используют временные БД.

## Ассеты и рендер

`assets/textures` — это **не ресурспак** для игроков (нет `pack.mcmeta`), а источник
текстур для PIL-рендера в боте. Структура: `item/`, `block/`, плюс `fonts/font.ttf`.

Известные ограничения текущего набора:

- часть предметов без плоской текстуры (`CHEST`, `ENDER_CHEST`, `ENCHANTING_TABLE`,
  `SHIELD`, `COMPASS`, `CLOCK`, `TIPPED_ARROW`, головы и др.);
- у блочных предметов (`*_stairs`, `*_slab`, `*_fence`, `*_door`, …) отдельных PNG нет —
  слот будет пустым;
- текстуры 16×16 масштабируются с нецелым коэффициентом (36 px) — планируется 32/48 px
  и таблица алиасов.

---

## Безопасность

- Не коммитьте `.env`, `tickets.db`, `transcripts/`, `scratch/` — они в `.gitignore`.
- Ротируйте `BRIDGE_SECRET` и не используйте дефолт.
- 2FA: двухфакторная аутентификация работает через плагин **Victim** на Proxy-сервере.
- Безопасность: мониторинг твинков и мультиаккаунтов по IP через базу данных бота.

---

## Диагностика

| Симптом | Причина / решение |
|---|---|
| `ModuleNotFoundError: design` | не загружен `design.py` |
| Пустые слоты в `/invsee` | нет `assets/` или нужной текстуры (см. выше) |
| `UnicodeEncodeError` на Windows | запускать `python -X utf8 main.py` |
| `LoginFailure` / неверный токен | проверьте `DISCORD_TOKEN` в `.env` |
| Мост не подключается | `BRIDGE_SECRET` не совпадает с плагином, порт/файрвол, `ws-url` |
| `database disk image is malformed` | бот сам делает бэкап `*.corrupted_*` и создаёт новую БД |
| Кнопки «висят» после рестарта | часть вью не зарегистрирована как persistent (известное ограничение) |

Проверка синтаксиса перед выкладкой:

```bash
python -X utf8 -m py_compile main.py bot.py config.py database.py design.py cogs/*.py
python -X utf8 -m pyflakes main.py bot.py config.py database.py design.py cogs/*.py
```

---

## Команды (кратко)

- **Игрокам**: `!online`, `!top`, `!profile`, `!skin`, `!deaths`, `!world`, `!tps`, `!time`,
  `!coords`, `!msg_mc`, `!link`, `!security`, `!unlink`, `!ticket`, `!close`, `!add`, `!remove`,
  `!user`, `!avatar`, `!server`, `!roll`, `!remind`, `!ip`, `!rules`, `!donate`, `!ping`.
- **Персоналу**: `!mute`, `!unmute`, `!kick`, `!ban`, `!unban`, `!clear`, `!slowmode`,
  `!lock`, `!unlock`, `!lockall`, `!unlockall`, `!vckick`, `!vcban`, `!history`, `!ticketban`,
  `!ticketunban`, `!check`, `!invsee`, `!endersee`, `!chunks`, `!bc`, `!maintenance`, `!automod`,
  `!alts`, `!whois`, `!chat_search`.
- **Администрации**: `!ticket_panel`, `!verify_panel`, `!link_panel`, `!sync_roles`,
  `!roles_info`, `!spec_role`, `!ticket_ping_role`, `!set_*_role`, `!verification_lockdown`, `!alts_panel`,
  `!alts_scan`, `!alts_history`, `!alts_whitelist`, `!record_ip`, `!healthcheck`,
  `!panic_whitelist`, `!backup_status`, `!backup_create`, `!rules_sync`, `!purge_junk`.

Слэш-команды синхронизируются при старте; старые гильдейские копии очищаются автоматически.

---

## Разработка

- Точка входа — `main.py` (не `bot.py`, он лишь обёртка).
- Плагин: `scratch/VanillaBridgeProject` (`pom.xml`, Paper API 1.21, Java 21), сборка:
  ```bash
  cd scratch/VanillaBridgeProject && mvn -q -DskipTests package
  # готовый jar: scratch/VanillaBridgeProject/target/VanillaBridge-1.0.jar
  # копия для выкладки: jar_latest/VanillaBridge-1.0.jar
  ```
- `scratch/` — старые патчи и бэкапы, в деплой не входят.
