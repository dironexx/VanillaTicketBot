# 🧠 AI Handover & Architecture Context • VanillaTicketBot

> **Документ предназначен для быстрой передачи контекста проекту другим AI-агентам (Gemini, Claude, GPT) и разработчикам.**  
> Ознакомьтесь с этим документом перед внесением изменений в кодовую базу.

---

## 📌 1. Краткий обзор системы

Проект представляет собой высоконагруженную экосистему поддержки, модерации, безопасности и синхронизации для Minecraft-сервера **Vanilla Land**:
1. **Discord Bot (Python 3.11+, discord.py 2.7+)** — основной демон службы поддержки, биллинга, тикетов, авторизации и модерации.
2. **VanillaBridge (Java 21, Paper 1.21+)** — Paper-плагин, общающийся с ботом через двусторонний WebSocket (порт по умолчанию `25007` или `25549`).
3. **Proxy Auth (Velocity / Victime / Rahu)** — прокси-сервер, через который игроки подключаются к серверу.

---

## 🏗️ 2. Архитектурная карта проекта

```
VanilaTicketBOT/
├── main.py                     # Точка входа Discord бота (инициализация, сигналы ОС)
├── bot.py                      # Обёртка запуска main()
├── config.py                   # Загрузка env, фильтрация Docker IP, резолвер доменов
├── config_sync.py              # Автосинхронизация .env без перезаписи секретов
├── database.py                 # Потокобезопасная SQLite ORM (ACID, WAL, миграции)
├── design.py                   # UI-дизайн система (цвета, стили эмбедов AG.embed)
├── requirements.txt            # Зависимости: discord.py, python-dotenv, Pillow, aiohttp
├── cogs/
│   ├── bridge.py               # WebSocket-сервер моста, чат, онлайн, /health, /mail, [item]
│   ├── bridge_views.py         # UI моста: интерактивные кнопки, модалки, сессии
│   ├── tickets.py              # Тикеты, HTML-транскрипты, досье нарушителя (/suspect)
│   ├── security.py             # LiteBans Guard, детекция твинков по IP, whois, алерты
│   ├── inventory_renderer.py   # Pillow рендерер инвентарей и карточки профиля (/profile)
│   ├── verification.py         # Верификация Discord ➔ Minecraft
│   ├── moderation.py           # Муты, баны, кики, таймауты Discord
│   ├── info.py                 # Справка по командам (/ip, /rules, /server)
│   ├── logs.py                 # Логирование событий и автомодерация ссылок
│   └── utility.py              # Вспомогательные утилиты сервера
├── tests/
│   ├── test_bot_logic.py       # Комплексные тесты бизнес-логики (27 тестов)
│   ├── test_config_sync.py     # Тесты парсера и синка конфигураций
│   ├── test_database.py        # Тесты транзакций и безопасности БД
│   └── test_renderer.py        # Тесты графического рендерера
├── assets/                     # Текстуры предметов/блоков и шрифты для Pillow
└── scratch/VanillaBridgeProject/ # Исходники Paper-плагина VanillaBridge (Maven)
    ├── pom.xml
    └── src/main/java/my/bridge/
        ├── VanillaBridge.java       # Ядро плагина
        ├── BridgeClient.java        # WebSocket-клиент
        ├── ChatBridgeListener.java  # Чат, смерти, предметы [item]
        └── SecurityIpManager.java   # Контроль сессий и IP
```

---

## ⚠️ 3. Критически важные подводные камни (Gotchas)

1. **Docker / Pterodactyl Internal IP (`172.18.0.1`):**
   - Контейнеры Pterodactyl часто выставляют системную переменную `SERVER_IP=172.18.0.1`.
   - В `config.py` написан метод `_is_private_or_docker_ip()`. Он **принудительно фильтрует** любые приватные адреса (`127.0.0.1`, `172.16.0.0/12`, `10.0.0.0/8`, `192.168.0.0/16`) и возвращает публичный домен `vanillaland.ru-mc.ru`.
   - Никогда не убирайте эту проверку, иначе бот снова начнёт писать внутренний IP контейнера в статусе Discord и голосовом канале!

2. **Двухфакторная аутентификация (2FA):**
   - В боте параметр `ENABLE_LOGIN_2FA` установлен в `False` по умолчанию в `config.py` и `config.yml`.
   - Это сделано намеренно: на проекте аутентификация игроков вынесена на прокси-уровень (**Victime** на Velocity). Если включить 2FA в боте, игроки будут застревать в заморозке.

3. **Совместимость с прокси Selene / Rahu:**
   - На Velocity команда `/maintenance whitelist add <ник>` плагина Rahu вызывает `SeleneApi.setWhitelisted(nick, true)`.
   - В оригинале Selene этого метода не было, что вызывало `NoSuchMethodError`. В обновлённом `selene.jar` метод внедрён с сохранением в `maintenance_whitelist.txt`.

4. **Кодировка на Windows:**
   - Консоль Windows (cmd/powershell) по умолчанию использует `cp1251`. Запускать бота и тесты нужно строго с флагом `-X utf8`:
     ```bash
     python -X utf8 main.py
     python -X utf8 -m unittest discover -s tests -v
     ```

5. **Мост и WebSocket:**
   - Порт моста по умолчанию: `25007` (или `25549`).
   - Пароль моста задаётся переменной `BRIDGE_SECRET`.
   - Бот поддерживает мульти-серверное подключение (агрегирует статистику онлайна со всех подключенных сокетов).

---

## 📦 4. Недавно внедрённый функционал (v1.2.2+)

- **Предпросмотр предметов `[item]`**: отправка предмета из рук в чат Minecraft автоматически генерирует в Discord красивый Embed с названием, количеством, чарами и описанием предмета.
- **Внутриигровая почта `/mail`**:
  - `/mail send <ник> <текст>` — отправка письма даже офлайн-игроку.
  - При входе игрок получает всплывающее уведомление о непрочитанных письмах.
  - `/mail read` — чтение писем. Хранилище реализовано в SQLite (таблица `offline_mail`).
- **HTML-транскрипты тикетов**: при закрытии тикета формируется стилизованный автономный HTML-документ переписки (`transcripts/ticket-XXX.html`) и отправляется в ЛС пользователю и канал архива.
- **Досье подозреваемого `/suspect`**: модераторская карточка нарушителя с маскированными IP, привязанным Discord, историей твинков, алертами LiteBans и скином игрока (без посторонней воды и смертей).
- **Графическая карточка профиля `/profile`**: генерация 800x420 PNG в стиле Linear Dark Craft на Pillow (Bento-сетка: руды, PvP K/D, время в игре, мир, скин с теневым заземлением).
- **Uptime Kuma Healthcheck**: HTTP-эндпоинт `/health` отдаёт структурированный JSON со статусом бота, задержкой WebSocket, онлайном игроков и TPS.

---

## 🧪 5. Инструкции по тестированию и деплою

### Запуск тестов
```bash
python -X utf8 -m unittest discover -s tests -v
```
*(Все 27 юнит-тестов должны завершаться со статусом `OK`).*

### Сборка плагина VanillaBridge (Java)
```bash
cd scratch/VanillaBridgeProject
mvn clean package -DskipTests
```
*(Готовый артефакт собирается в `target/VanillaBridge-1.0.jar`).*

### Сборка архива обновления для хостинга
```bash
python scratch/make_bot_archive.py
```
*(Создаёт чистый ZIP-архив без мусора, логов и локальных БД в `Downloads/VanillaTicketBOT_update.zip`).*
