import asyncio
import logging
import os
import sys
import time

import discord
from discord.ext import commands

from config import Config, _resolve_token
from database import DatabaseManager
from cogs.tickets import InsideTicketView, TicketPanel
from cogs.verification import VerificationView

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("VanillaBot")


class VanillaSupportBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=Config.COMMAND_PREFIXES,
            intents=intents,
            help_command=None,
            proxy=Config.DISCORD_PROXY,
        )

        self.start_time = time.time()
        self.db = DatabaseManager(Config.DB_PATH, Config.TRANSCRIPTS_DIR)

    async def setup_hook(self):
        # Персистентные кнопки (тикеты + верификация)
        self.add_view(TicketPanel(self.db))
        self.add_view(InsideTicketView(self.db))
        self.add_view(VerificationView())

        # Загрузка всех модулей (Cogs)
        await self.load_extension("cogs.tickets")
        await self.load_extension("cogs.info")
        await self.load_extension("cogs.moderation")
        await self.load_extension("cogs.utility")
        await self.load_extension("cogs.verification")
        await self.load_extension("cogs.logs")
        await self.load_extension("cogs.bridge")
        await self.load_extension("cogs.security")

        # Глобальный обработчик ошибок слэш-команд (предотвращает зависания)
        async def on_tree_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
            logger.error(f"Ошибка слэш-команды /{interaction.command.name if interaction.command else 'unknown'}: {error}")
            try:
                msg = "Произошла внутренняя ошибка при выполнении команды."
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=(interaction.guild is not None))
                else:
                    await interaction.response.send_message(msg, ephemeral=(interaction.guild is not None))
            except Exception:
                pass

        self.tree.on_error = on_tree_error

        # Синхронизация слэш-команд
        try:
            synced = await self.tree.sync()
            logger.info(f"Синхронизировано команд: {len(synced)}")
        except Exception as e:
            logger.error(f"Ошибка синхронизации команд: {e}")

    async def on_ready(self):
        logger.info(f"Бот успешно запущен как {self.user} (ID: {self.user.id})")
        # Очищаем локальные дубликаты с гильдий, чтобы не было задвоения с глобальными командами
        for guild in self.guilds:
            try:
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
            except Exception:
                pass

        await self.change_presence(
            activity=discord.CustomActivity(name=Config.SERVER_IP)
        )

    # --- ОБРАБОТЧИК НЕИЗВЕСТНЫХ КОМАНД И ОШИБОК ---
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if ctx.channel.id == Config.BRIDGE_CHANNEL_ID:
            return

        if isinstance(error, commands.CommandNotFound):
            # Игнорируем неизвестные префикс-команды, чтобы не спамить в общие чаты
            return

        if isinstance(error, commands.MissingPermissions):
            try:
                await ctx.send("У вас недостаточно прав для выполнения этой команды.", delete_after=5)
            except Exception:
                pass
            return

        if isinstance(error, commands.MissingRequiredArgument):
            try:
                await ctx.send(f"Не указан обязательный аргумент: `{error.param.name}`. Проверьте `!help`.", delete_after=5)
            except Exception:
                pass
            return

        logger.warning(f"Ошибка команды {ctx.command}: {error}")

    async def close(self):
        logger.info("Остановка бота...")
        await super().close()


async def main():
    token = Config.DISCORD_TOKEN or _resolve_token()
    if not token:
        logger.critical("ОШИБКА: Токен Discord бота не обнаружен в .env или переменных окружения!")
        sys.exit(1)

    if Config.DISCORD_PROXY:
        logger.info(f"Используется прокси для подключения к Discord: {Config.DISCORD_PROXY}")

    bot = VanillaSupportBot()
    try:
        async with bot:
            await bot.start(token)
    except Exception as e:
        err_msg = str(e)
        if any(w in err_msg.lower() for w in ["cannot connect to host", "timeout", "connection refused", "ssl"]):
            logger.critical(
                f"\n{'='*70}\n"
                f"КРИТИЧЕСКАЯ ОШИБКА СЕТИ / БЛОКИРОВКИ DISCORD:\n{e}\n\n"
                f"Внимание: если бот запущен на хостинге в РФ (Москва), Discord заблокирован РКН!\n"
                f"Для работы на российском хостинге укажите прокси в переменной окружения:\n"
                f"DISCORD_PROXY=http://ip:port (или http://user:pass@ip:port)\n"
                f"Либо перенесите бота на зарубежный хостинг (bot-hosting.net, Hetzner, Oracle, Aeza EU).\n"
                f"{'='*70}"
            )
        else:
            logger.critical(f"Ошибка при запуске бота: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")
