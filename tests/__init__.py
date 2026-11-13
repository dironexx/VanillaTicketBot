import os

# Тесты не должны менять реальный .env проекта.
os.environ.setdefault("VANILLA_ENV_SYNC", "0")
