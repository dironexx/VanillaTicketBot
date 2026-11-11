import asyncio
import logging
from main import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger("VanillaBot").info("Бот остановлен.")
