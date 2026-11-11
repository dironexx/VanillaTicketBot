# Vanilla Land • Discord Bot

Discord-бот службы поддержки, модерации и моста с Minecraft-сервером **Vanilla Land**.
Работает как отдельный процесс: Discord (discord.py) + WebSocket-мост с Paper-плагином `VanillaBridge`.

---

## Возможности

- **Тикеты**: панель с кнопкой, каналы `тикет-NNN`, транскрипт в `.txt` в ЛС, авто-закрытие по неактивности, `!add/!remove/!rename/!close`, ЧС на тикеты.
- **Модерация**: `!mute/!unmute/!kick/!ban/!unban/!clear/!slowmode/!lock/!unlock/!lockall/!unlockall/!vckick/!vcban`, мут = роль + Discord timeout + запись в БД + авто-снятие.
- **Мост Minecraft**: чат в обе стороны, входы/выходы/смерти, статистика (TPS/MSPT/ОЗУ), `/online`, `/top`, `/profile`, `/tps`, `/world`, `/time`, `/skin`, `/coords`, `/bc`, `/check`, `/invsee`, `/endersee`, `/chunks`, ЛС игроку (`/msg_mc`), техработы и рестарт.
- **Привязка и 2FA**: одноразовые 6-значные коды, `1 Discord = 1 ник`, подтверждение входа в ЛС (кнопки + код в игре), доверенные IP с настраиваемым сроком, пуш-уведомления, экстренный сброс.
- **Безопасность**: детект твинков по точному IP, сверка с LiteBans, режимы `alert/autokick/autoban`, `!whois`, `!alts`, `!alts_scan`, `!alts_history`, белый список, журнал инцидентов, `!healthcheck`.
- **Верификация**: роль «Неверифицирован», панель, изоляция каналов, локдаун от рейдов, `!sync_roles`, настройка ролей.
- **Автомод и логи**: анти-реклама (Discord/Telegram/паттерны), логи удаления/редактирования/входов/выходов.
- **Рендер инвентаря**: `/invsee`, `/endersee`, шалкеры — картинки на основе `assets/textures`.

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
  security.py           # LiteBans Guard, whois, твинки, healthcheck
  bridge.py             # WebSocket-мост с Minecraft (основной модуль)
  bridge_views.py       # UI моста: 2FA, безопасность, привязка (вспомогательный)
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

1. Загрузите на сервер: `main.py`, `bot.py`, `config.py`, `database.py`, `design.py`,
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

## Мост с Minecraft (плагин VanillaBridge 26.3)

- Плагин подключается к боту по `ws://`/`wss://` и передаёт секрет в query/заголовке.
- В `config.yml` плагина: `server-id` (`main`/`vps`), `bridge.ws-url`, `bridge.token`.
- Бот принимает несколько серверов одновременно (main + vps): сокеты хранятся множеством,
  широковещательные пакеты уходят всем.
- Пакеты: `join/quit/death/chat/stats/lifecycle`, `check_alts_bans` → `alts_bans_result`,
  `check_login` → `login_verdict`, `2fa_verified/2fa_rejected/clear_sessions`,
  `dm_request` → `dm_reply`, `execute_console_command`, `maintenance*`.

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
- 2FA: срок доверия IP задаётся в Discord (`/security`), значение передаётся плагину;
  при `0` подтверждение запрашивается при каждом входе.
- Автобаны за обход — только по результатам собственных запросов бота (anti-spoof),
  ручные `!whois`/`!alts` автосанкций не вызывают.

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
  cd scratch/VanillaBridgeProject && mvn -q package
  ```
- `scratch/` — старые патчи и бэкапы, в деплой не входят.
