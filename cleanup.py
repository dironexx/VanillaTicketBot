import logging
import os
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger("VanillaBot.Cleanup")

JUNK_FILE_PATTERNS = [
    "*_excerpt.txt",
    "*.excerpt.txt",
    "crop_*.png",
    "scratch_crop*.png",
    "*.tmp",
    "*.temp",
    "*.bak",
    "*.old",
    "*.orig",
    "dump.rdb",
    ".DS_Store",
    "Thumbs.db",
    "RELEASE_NOTES_*.md",
]

JUNK_DIR_NAMES = [
    ".backup_cogs",
    ".pi",
    ".ruff_cache",
    ".pytest_cache",
    "jar_latest",
]


def cleanup_project_junk(root_dir: Optional[Path] = None, db_manager=None) -> int:
    """
    Сканирует рабочую директорию проекта и безопасно удаляет остаточный мусор,
    временные скриншоты, дампы и кэши, не затрагивая критичные файлы (.env, tickets.db, assets и т.д.).
    При наличии старых повреждённых баз (tickets.db.corrupted_*) спасает данные в tickets.db.
    """
    if root_dir is None:
        root_dir = Path(__file__).resolve().parent

    cleaned_count = 0

    # 1. Удаление мусорных файлов по паттернам в корне проекта
    for pattern in JUNK_FILE_PATTERNS:
        for f_path in root_dir.glob(pattern):
            if f_path.is_file():
                try:
                    f_path.unlink()
                    cleaned_count += 1
                    logger.info("Удален временный/мусорный файл: %s", f_path.name)
                except Exception as err:
                    logger.debug("Не удалось удалить файл %s: %s", f_path.name, err)

    # 2. Удаление устаревших служебных директорий
    for d_name in JUNK_DIR_NAMES:
        d_path = root_dir / d_name
        if d_path.is_dir():
            try:
                shutil.rmtree(d_path, ignore_errors=True)
                cleaned_count += 1
                logger.info("Удалена мусорная папка: %s", d_name)
            except Exception as err:
                logger.debug("Не удалось удалить папку %s: %s", d_name, err)

    # 3. Очистка __pycache__ и скомпилированных .pyc файлов
    for pycache in root_dir.rglob("__pycache__"):
        if pycache.is_dir():
            try:
                shutil.rmtree(pycache, ignore_errors=True)
            except Exception:
                pass

    for pyc in root_dir.rglob("*.pyc"):
        if pyc.is_file():
            try:
                pyc.unlink()
            except Exception:
                pass

    # 4. Проверка и автоматическое спасение данных из старых tickets.db.corrupted_* файлов
    for corrupt_file in root_dir.glob("tickets.db.corrupted_*"):
        if corrupt_file.is_file():
            try:
                if db_manager and hasattr(db_manager, "salvage_corrupted_file"):
                    recovered = db_manager.salvage_corrupted_file(str(corrupt_file))
                    if recovered > 0:
                        logger.info("Из поврежденного файла %s спасено записей: %d", corrupt_file.name, recovered)

                backup_dir = root_dir / "backups" / "archive_corrupted"
                backup_dir.mkdir(parents=True, exist_ok=True)
                dest = backup_dir / corrupt_file.name
                shutil.move(str(corrupt_file), str(dest))
                cleaned_count += 1
                logger.info("Архивирован старый файл БД: %s -> %s", corrupt_file.name, dest)
            except Exception as err:
                logger.debug("Ошибка обработки поврежденного файла БД %s: %s", corrupt_file.name, err)

    if cleaned_count > 0:
        logger.info("Очистка проекта завершена. Удалено/архивировано объектов: %d", cleaned_count)

    return cleaned_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    count = cleanup_project_junk()
    print(f"Готово. Очищено объектов: {count}")
