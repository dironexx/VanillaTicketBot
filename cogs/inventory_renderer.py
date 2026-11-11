import io
import re
from typing import Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

# --- СЛОВАРЬ ПЕРЕВОДА ПРЕДМЕТОВ MINECRAFT НА РУССКИЙ ЯЗЫК ---
ITEM_TRANSLATIONS: Dict[str, Tuple[str, str]] = {
    # Броня и экипировка
    "NETHERITE_HELMET": ("Незеритовый шлем", "🪖"),
    "DIAMOND_HELMET": ("Алмазный шлем", "🪖"),
    "IRON_HELMET": ("Железный шлем", "🪖"),
    "GOLDEN_HELMET": ("Золотой шлем", "🪖"),
    "CHAINMAIL_HELMET": ("Кольчужный шлем", "🪖"),
    "LEATHER_HELMET": ("Кожаный шлем", "🪖"),
    "TURTLE_HELMET": ("Черепаший панцирь", "🐢"),
    "PIGLIN_HEAD": ("Голова пиглина", "🐷"),
    "PLAYER_HEAD": ("Голова игрока", "👤"),
    "ZOMBIE_HEAD": ("Голова зомби", "🧟"),
    "CREEPER_HEAD": ("Голова крипера", "💥"),
    "DRAGON_HEAD": ("Голова дракона", "🐉"),
    "SKELETON_SKULL": ("Череп скелета", "💀"),
    "WITHER_SKELETON_SKULL": ("Череп визер-скелета", "💀"),
    "CARVED_PUMPKIN": ("Вырезанная тыква", "🎃"),

    "NETHERITE_CHESTPLATE": ("Незеритовый нагрудник", "🛡️"),
    "DIAMOND_CHESTPLATE": ("Алмазный нагрудник", "🛡️"),
    "IRON_CHESTPLATE": ("Железный нагрудник", "🛡️"),
    "GOLDEN_CHESTPLATE": ("Золотой нагрудник", "🛡️"),
    "CHAINMAIL_CHESTPLATE": ("Кольчужный нагрудник", "🛡️"),
    "LEATHER_CHESTPLATE": ("Кожаная куртка", "🥼"),
    "ELYTRA": ("Элитры", "🪽"),

    "NETHERITE_LEGGINGS": ("Незеритовые поножи", "👖"),
    "DIAMOND_LEGGINGS": ("Алмазные поножи", "👖"),
    "IRON_LEGGINGS": ("Железные поножи", "👖"),
    "GOLDEN_LEGGINGS": ("Золотые поножи", "👖"),
    "CHAINMAIL_LEGGINGS": ("Кольчужные поножи", "👖"),
    "LEATHER_LEGGINGS": ("Кожаные штаны", "👖"),

    "NETHERITE_BOOTS": ("Незеритовые ботинки", "👢"),
    "DIAMOND_BOOTS": ("Алмазные ботинки", "👢"),
    "IRON_BOOTS": ("Железные ботинки", "👢"),
    "GOLDEN_BOOTS": ("Золотые ботинки", "👢"),
    "CHAINMAIL_BOOTS": ("Кольчужные ботинки", "👢"),
    "LEATHER_BOOTS": ("Кожаные ботинки", "👢"),

    # Оружие и инструменты
    "AIR": ("Пусто", "✋"),
    "TOTEM_OF_UNDYING": ("Тотем бессмертия", "🌟"),
    "SHIELD": ("Щит", "🛡️"),
    "DIAMOND_SWORD": ("Алмазный меч", "⚔️"),
    "NETHERITE_SWORD": ("Незеритовый меч", "⚔️"),
    "IRON_SWORD": ("Железный меч", "⚔️"),
    "GOLDEN_SWORD": ("Золотой меч", "⚔️"),
    "STONE_SWORD": ("Каменный меч", "⚔️"),
    "WOODEN_SWORD": ("Деревянный меч", "⚔️"),
    "BOW": ("Лук", "🏹"),
    "CROSSBOW": ("Арбалет", "🎯"),
    "TRIDENT": ("Трезубец", "🔱"),
    "MACE": ("Булава", "🔨"),
    "WIND_CHARGE": ("Ветровой заряд", "💨"),
    "DIAMOND_PICKAXE": ("Алмазная кирка", "⛏️"),
    "NETHERITE_PICKAXE": ("Незеритовая кирка", "⛏️"),
    "IRON_PICKAXE": ("Железная кирка", "⛏️"),
    "DIAMOND_AXE": ("Алмазный топор", "🪓"),
    "NETHERITE_AXE": ("Незеритовый топор", "🪓"),
    "IRON_AXE": ("Железный топор", "🪓"),
    "DIAMOND_SHOVEL": ("Алмазная лопата", "🥄"),
    "NETHERITE_SHOVEL": ("Незеритовая лопата", "🥄"),
    "IRON_SHOVEL": ("Железная лопата", "🥄"),

    # Расходники, еда и ценности
    "GOLDEN_APPLE": ("Золотое яблоко", "🍏"),
    "ENCHANTED_GOLDEN_APPLE": ("Зачарованное яблоко", "🍎"),
    "ENDER_PEARL": ("Жемчуг Края", "🔮"),
    "ENDER_EYE": ("Око Края", "👁️"),
    "FIREWORK_ROCKET": ("Фейерверк", "🎆"),
    "POTION": ("Зелье", "🧪"),
    "SPLASH_POTION": ("Взрывное зелье", "🧪"),
    "LINGERING_POTION": ("Оседающее зелье", "🧪"),
    "ARROW": ("Стрела", "🏹"),
    "TIPPED_ARROW": ("Стрела с эффектом", "🏹"),
    "COMPASS": ("Компас", "🧭"),
    "RECOVERY_COMPASS": ("Компас возврата", "🧭"),
    "CLOCK": ("Часы", "🕒"),
    "SPYGLASS": ("Подзорная труба", "🔭"),
    "WATER_BUCKET": ("Ведро воды", "🪣"),
    "LAVA_BUCKET": ("Ведро лавы", "🪣"),
    "MILK_BUCKET": ("Ведро молока", "🥛"),
    "EXPERIENCE_BOTTLE": ("Пузырек опыта", "✨"),
    "BREAD": ("Хлеб", "🍞"),
    "COOKED_BEEF": ("Стейк", "🥩"),
    "COOKED_PORKCHOP": ("Жареная свинина", "🥩"),
    "COOKED_MUTTON": ("Жареная баранина", "🥩"),
    "COOKED_CHICKEN": ("Жареная курица", "🍗"),
    "GOLDEN_CARROT": ("Золотая морковь", "🥕"),

    # Шалкеры
    "SHULKER_BOX": ("Шалкеровый ящик", "📦"),
    "WHITE_SHULKER_BOX": ("Белый шалкер", "📦"),
    "ORANGE_SHULKER_BOX": ("Оранжевый шалкер", "📦"),
    "MAGENTA_SHULKER_BOX": ("Сиреневый шалкер", "📦"),
    "LIGHT_BLUE_SHULKER_BOX": ("Голубой шалкер", "📦"),
    "YELLOW_SHULKER_BOX": ("Желтый шалкер", "📦"),
    "LIME_SHULKER_BOX": ("Лаймовый шалкер", "📦"),
    "PINK_SHULKER_BOX": ("Розовый шалкер", "📦"),
    "GRAY_SHULKER_BOX": ("Серый шалкер", "📦"),
    "LIGHT_GRAY_SHULKER_BOX": ("Светло-серый шалкер", "📦"),
    "CYAN_SHULKER_BOX": ("Бирюзовый шалкер", "📦"),
    "PURPLE_SHULKER_BOX": ("Пурпурный шалкер", "📦"),
    "BLUE_SHULKER_BOX": ("Синий шалкер", "📦"),
    "BROWN_SHULKER_BOX": ("Коричневый шалкер", "📦"),
    "GREEN_SHULKER_BOX": ("Зеленый шалкер", "📦"),
    "RED_SHULKER_BOX": ("Красный шалкер", "📦"),
    "BLACK_SHULKER_BOX": ("Черный шалкер", "📦"),

    # Ценные ресурсы и блоки
    "DIAMOND": ("Алмаз", "💎"),
    "NETHERITE_INGOT": ("Незеритовый слиток", "🪙"),
    "GOLD_INGOT": ("Золотой слиток", "🪙"),
    "IRON_INGOT": ("Железный слиток", "🪙"),
    "COPPER_INGOT": ("Медный слиток", "🪙"),
    "EMERALD": ("Изумруд", "💚"),
    "DIAMOND_BLOCK": ("Алмазный блок", "💎"),
    "NETHERITE_BLOCK": ("Незеритовый блок", "⬛"),
    "GOLD_BLOCK": ("Золотой блок", "🟨"),
    "IRON_BLOCK": ("Железный блок", "⬜"),
    "EMERALD_BLOCK": ("Изумрудный блок", "🟩"),
    "NETHER_STAR": ("Звезда Незера", "⭐"),
    "BEACON": ("Маяк", "🏮"),
    "CHEST": ("Сундук", "🧰"),
    "ENDER_CHEST": ("Эндер-сундук", "🟣"),
    "BARREL": ("Бочка", "🛢️"),
    "ANVIL": ("Наковальня", "🔨"),
    "ENCHANTING_TABLE": ("Стол зачарования", "📖"),
    "CRAFTING_TABLE": ("Верстак", "🪵"),
    "TORCH": ("Факел", "🕯️"),
    "SOUL_TORCH": ("Факел душ", "🕯️"),
    "LANTERN": ("Фонарь", "🏮"),
    "OBSIDIAN": ("Обсидиан", "🪨"),
    "CRYING_OBSIDIAN": ("Плачущий обсидиан", "🪨"),
    "RESPAWN_ANCHOR": ("Якорь возрождения", "⚓"),
    "COMMAND_BLOCK": ("Командный блок", "🕹️"),
    "NAME_TAG": ("Бирка", "🏷️"),
    "LEAD": ("Поводок", "🪢"),
    "SADDLE": ("Седло", "🐎"),
    "BOOK": ("Книга", "📕"),
    "ENCHANTED_BOOK": ("Зачарованная книга", "✨"),

    # Пластинки
    "MUSIC_DISC_13": ("Пластинка (13)", "🎵"),
    "MUSIC_DISC_CAT": ("Пластинка (cat)", "🎵"),
    "MUSIC_DISC_BLOCKS": ("Пластинка (blocks)", "🎵"),
    "MUSIC_DISC_CHIRP": ("Пластинка (chirp)", "🎵"),
    "MUSIC_DISC_FAR": ("Пластинка (far)", "🎵"),
    "MUSIC_DISC_MALL": ("Пластинка (mall)", "🎵"),
    "MUSIC_DISC_MELLOHI": ("Пластинка (mellohi)", "🎵"),
    "MUSIC_DISC_STAL": ("Пластинка (stal)", "🎵"),
    "MUSIC_DISC_STRAD": ("Пластинка (strad)", "🎵"),
    "MUSIC_DISC_WARD": ("Пластинка (ward)", "🎵"),
    "MUSIC_DISC_11": ("Пластинка (11)", "🎵"),
    "MUSIC_DISC_WAIT": ("Пластинка (wait)", "🎵"),
    "MUSIC_DISC_PIGSTEP": ("Пластинка (Pigstep)", "🎵"),
    "MUSIC_DISC_OTHERSIDE": ("Пластинка (otherside)", "🎵"),
    "MUSIC_DISC_5": ("Пластинка (5)", "🎵"),
    "MUSIC_DISC_RELIC": ("Пластинка (Relic)", "🎵"),
    "MUSIC_DISC_CREATOR": ("Пластинка (Creator)", "🎵"),
    "MUSIC_DISC_PRECIPICE": ("Пластинка (Precipice)", "🎵"),
}

# --- СЛОВАРЬ ПЕРЕВОДА ЭФФЕКТОВ ЗЕЛИЙ ---
EFFECT_TRANSLATIONS: Dict[str, Tuple[str, str]] = {
    "SPEED": ("Скорость", "⚡"),
    "SLOWNESS": ("Замедление", "🐌"),
    "HASTE": ("Спешка", "⛏️"),
    "MINING_FATIGUE": ("Усталость", "⛏️"),
    "STRENGTH": ("Сила", "🗡️"),
    "INSTANT_HEALTH": ("Мгновенное исцеление", "💖"),
    "INSTANT_DAMAGE": ("Мгновенный урон", "💔"),
    "JUMP_BOOST": ("Прыгучесть", "🦘"),
    "NAUSEA": ("Тошнота", "🌀"),
    "REGENERATION": ("Регенерация", "💗"),
    "RESISTANCE": ("Сопротивление", "🛡️"),
    "FIRE_RESISTANCE": ("Огнестойкость", "🔥"),
    "WATER_BREATHING": ("Подводное дыхание", "🫧"),
    "INVISIBILITY": ("Невидимость", "🫥"),
    "BLINDNESS": ("Слепота", "👁️"),
    "NIGHT_VISION": ("Ночное зрение", "👁️"),
    "HUNGER": ("Голод", "🍗"),
    "WEAKNESS": ("Слабость", "🥀"),
    "POISON": ("Отравление", "☠️"),
    "WITHER": ("Иссушение", "💀"),
    "HEALTH_BOOST": ("Доп. здоровье", "🧡"),
    "ABSORPTION": ("Поглощение", "💛"),
    "SATURATION": ("Насыщение", "🥩"),
    "GLOWING": ("Свечение", "✨"),
    "LEVITATION": ("Левитация", "🎈"),
    "LUCK": ("Удача", "🍀"),
    "BAD_LUCK": ("Невезение", "🍂"),
    "SLOW_FALLING": ("Плавное падение", "🪶"),
    "CONDUIT_POWER": ("Сила источника", "🔱"),
    "DOLPHINS_GRACE": ("Грация дельфина", "🐬"),
    "BAD_OMEN": ("Дурное знамение", "👹"),
    "HERO_OF_THE_VILLAGE": ("Герой деревни", "🏆"),
    "DARKNESS": ("Тьма", "🌑"),
}

ROMAN_NUMERALS = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X"}


def format_item_name(raw_name: str, with_emoji: bool = False) -> str:
    """Форматирует технический ID предмета в аккуратное русское название без детских эмодзи"""
    if not raw_name:
        return "Пусто"
    clean = raw_name.upper().strip()
    if clean in ("AIR", "EMPTY", "NONE", ""):
        return "Пусто"

    if clean in ITEM_TRANSLATIONS:
        name_ru, emoji = ITEM_TRANSLATIONS[clean]
        return f"{emoji} {name_ru}" if with_emoji else name_ru

    # Если предмет неизвестен — аккуратное форматирование
    words = clean.replace("_", " ").title().split()
    return " ".join(words)


def format_potion_effect(effect_raw: str) -> str:
    """Преобразует строку эффекта вида 'NIGHT_VISION 2 (48287s)' в 'Ночное зрение II (Бесконечно)'"""
    if not effect_raw:
        return "Нет эффектов"

    pattern = r"([A-Z_]+)\s+(\d+)\s*\((?:(\d+)s)?\)"
    match = re.search(pattern, effect_raw.strip(), re.IGNORECASE)
    if not match:
        return effect_raw

    eff_type = match.group(1).upper()
    lvl = int(match.group(2))
    duration_sec = int(match.group(3)) if match.group(3) else 0

    eff_name, _ = EFFECT_TRANSLATIONS.get(eff_type, (eff_type.replace("_", " ").title(), ""))
    lvl_str = ROMAN_NUMERALS.get(lvl, str(lvl))

    if duration_sec > 10000:
        dur_str = "Бесконечно"
    elif duration_sec >= 3600:
        h = duration_sec // 3600
        m = (duration_sec % 3600) // 60
        dur_str = f"{h} ч. {m} мин."
    elif duration_sec >= 60:
        m = duration_sec // 60
        s = duration_sec % 60
        dur_str = f"{m} мин. {s} сек." if s > 0 else f"{m} мин."
    else:
        dur_str = f"{duration_sec} сек."

    return f"**{eff_name} {lvl_str}** *({dur_str})*"



import os


class MinecraftTextureManager:
    """Менеджер и кэш оригинальных текстур Minecraft 26.3"""
    def __init__(self, assets_dir: str = "assets/textures"):
        self.item_dir = os.path.join(assets_dir, "item")
        self.block_dir = os.path.join(assets_dir, "block")
        self.cache: Dict[Tuple[str, int], Image.Image] = {}

    def get_texture(self, raw_name: Optional[str], target_size: int = 36) -> Optional[Image.Image]:
        if not raw_name or raw_name.upper() in ("AIR", "EMPTY", "NONE"):
            return None
        key = (raw_name.upper(), target_size)
        if key in self.cache:
            return self.cache[key]

        clean = raw_name.lower().strip()
        candidates = [clean]
        if "shulker_box" in clean:
            candidates.append(clean)
            candidates.append("shulker_box")
        if "potion" in clean:
            if "splash" in clean:
                candidates.append("splash_potion")
            elif "lingering" in clean:
                candidates.append("lingering_potion")
            else:
                candidates.append("potion")
        if "golden_apple" in clean:
            candidates.append("golden_apple")

        found_path = None
        for c in candidates:
            c_png = c if c.endswith(".png") else c + ".png"
            p1 = os.path.join(self.item_dir, c_png)
            if os.path.isfile(p1):
                found_path = p1
                break
            p2 = os.path.join(self.block_dir, c_png)
            if os.path.isfile(p2):
                found_path = p2
                break

        if not found_path:
            return None

        try:
            with Image.open(found_path) as im:
                im = im.convert("RGBA")
                resized = im.resize((target_size, target_size), Image.Resampling.NEAREST)
                self.cache[key] = resized
                return resized
        except Exception:
            return None

    def get_silhouette(self, slot_type: str, target_size: int = 32) -> Optional[Image.Image]:
        name_map = {
            "helmet": "empty_armor_slot_helmet.png",
            "chestplate": "empty_armor_slot_chestplate.png",
            "leggings": "empty_armor_slot_leggings.png",
            "boots": "empty_armor_slot_boots.png",
            "shield": "empty_armor_slot_shield.png",
            "mainhand": "empty_slot_sword.png",
        }
        fname = name_map.get(slot_type)
        if not fname:
            return None
        p = os.path.join(self.item_dir, fname)
        if not os.path.isfile(p):
            return None
        try:
            with Image.open(p) as im:
                im = im.convert("RGBA")
                r, g, b, a = im.split()
                a = a.point(lambda val: int(val * 0.45))
                im.putalpha(a)
                return im.resize((target_size, target_size), Image.Resampling.NEAREST)
        except Exception:
            return None


TEXTURE_MGR = MinecraftTextureManager()


def _get_font(size: int = 12) -> ImageFont.ImageFont:
    local_font = os.path.join("assets", "fonts", "font.ttf")
    if os.path.isfile(local_font):
        try:
            return ImageFont.truetype(local_font, size)
        except Exception:
            pass

    for name in ["segoeui.ttf", "arial.ttf", "calibri.ttf", "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _draw_slot(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int = 52,
    item_name: Optional[str] = None,
    count: int = 1,
    silhouette: Optional[str] = None,
    is_shulker: bool = False,
    sh_count: int = 0,
):
    """Отрисовывает аутентичный слот Minecraft с пиксельной текстурой предмета"""
    # 1. Фон слота (Minecraft dark inset)
    draw.rounded_rectangle([(x, y), (x + size, y + size)], radius=4, fill=(43, 45, 49, 255))
    # 2. Объемная тень/фаска слота
    draw.line([(x, y), (x + size, y)], fill=(24, 25, 28, 255), width=2)
    draw.line([(x, y), (x, y + size)], fill=(24, 25, 28, 255), width=2)
    draw.line([(x, y + size), (x + size, y + size)], fill=(59, 62, 69, 255), width=1)
    draw.line([(x + size, y), (x + size, y + size)], fill=(59, 62, 69, 255), width=1)

    tex = TEXTURE_MGR.get_texture(item_name, 36) if item_name and item_name.upper() != "AIR" else None
    if tex:
        ox = x + (size - 36) // 2
        oy = y + (size - 36) // 2
        img.paste(tex, (ox, oy), tex)
    elif silhouette:
        sil = TEXTURE_MGR.get_silhouette(silhouette, 32)
        if sil:
            ox = x + (size - 32) // 2
            oy = y + (size - 32) // 2
            img.paste(sil, (ox, oy), sil)

    # 3. Счетчик стака с тенью (Minecraft drop shadow)
    if count > 1:
        font_c = _get_font(13)
        c_str = str(count)
        draw.text((x + size - 5, y + size - 16), c_str, fill=(0, 0, 0, 255), font=font_c, anchor="ra")
        draw.text((x + size - 6, y + size - 17), c_str, fill=(255, 255, 255, 255), font=font_c, anchor="ra")

    # 4. Бейдж шалкера
    if is_shulker and sh_count > 0:
        draw.rounded_rectangle([(x + 3, y + 3), (x + 19, y + 15)], radius=3, fill=(168, 85, 247, 220))
        font_m = _get_font(9)
        draw.text((x + 5, y + 4), str(sh_count), fill=(255, 255, 255, 255), font=font_m)


def render_slots_grid(
    title: str,
    player_name: str,
    slots_map: Dict[int, dict],
    rows: int = 3,
    cols: int = 9,
    accent_color: str = "#8B5CF6",
    shulker_count: int = 0,
) -> io.BytesIO:
    """Генерирует высококачественное изображение контейнера (Эндер-сундук или Шалкер)"""
    slot_size = 52
    pad = 4
    margin_x, margin_y = 20, 16
    header_h = 48
    footer_h = 24

    total_w = margin_x * 2 + cols * slot_size + (cols - 1) * pad
    total_h = margin_y * 2 + header_h + rows * slot_size + (rows - 1) * pad + footer_h

    img = Image.new("RGBA", (total_w, total_h), (30, 31, 35, 255))
    draw = ImageDraw.Draw(img)

    # Внешняя рамка контейнера
    draw.rounded_rectangle([(4, 4), (total_w - 5, total_h - 5)], radius=8, outline=(54, 57, 63, 255), width=2)

    font_title = _get_font(16)
    font_sub = _get_font(12)
    font_idx = _get_font(10)

    # Заголовок
    draw.text((margin_x, margin_y + 2), title, fill=(242, 243, 245, 255), font=font_title)
    used_slots = len(slots_map)
    sub_text = f"Заполнено: {used_slots} / {rows * cols}"
    if shulker_count > 0:
        sub_text += f" • Шалкеров: {shulker_count}"
    draw.text((margin_x, margin_y + 24), sub_text, fill=(158, 164, 174, 255), font=font_sub)

    # Сетка слотов
    start_y = margin_y + header_h
    for r in range(rows):
        for c in range(cols):
            slot_idx = r * cols + c
            x = margin_x + c * (slot_size + pad)
            y = start_y + r * (slot_size + pad)

            item_data = slots_map.get(slot_idx)
            if not item_data:
                _draw_slot(img, draw, x, y, size=slot_size)
                continue

            raw_item = item_data.get("item", "").upper()
            cnt = item_data.get("count", 1)
            is_shulker = "SHULKER_BOX" in raw_item
            sh_items = item_data.get("shulker_items", [])

            _draw_slot(
                img,
                draw,
                x,
                y,
                size=slot_size,
                item_name=raw_item,
                count=cnt,
                is_shulker=is_shulker,
                sh_count=len(sh_items),
            )

    draw.text(
        (margin_x, total_h - margin_y - 10),
        "Vanilla Land Staff Inspection • vanillaland.ru-mc.ru",
        fill=(114, 118, 125, 220),
        font=font_idx,
    )

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def render_inventory_image(
    player_name: str,
    inventory_items: List[dict],
    armor: dict,
    main_hand: str,
    off_hand: str,
) -> io.BytesIO:
    """Генерирует полную визуальную раскладку инвентаря игрока с оригинальными текстурами Minecraft"""
    slot_size = 52
    pad = 4
    margin_x, margin_y = 20, 16

    # 9 колонок
    total_w = margin_x * 2 + 9 * slot_size + 8 * pad
    # Высота: Header + Экипировка (1 ряд) + Рюкзак (3 ряда) + Хотбар (1 ряд) + отступы
    total_h = 420

    img = Image.new("RGBA", (total_w, total_h), (30, 31, 35, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(4, 4), (total_w - 5, total_h - 5)], radius=8, outline=(54, 57, 63, 255), width=2)

    font_title = _get_font(16)
    font_sec = _get_font(11)

    # 1. Заголовок
    draw.text((margin_x, 15), f"Инвентарь игрока • {player_name}", fill=(242, 243, 245, 255), font=font_title)

    # 2. Ряд брони и рук
    draw.text((margin_x, 44), "ЭКИПИРОВКА И РУКИ:", fill=(158, 164, 174, 255), font=font_sec)
    eq_slots = [
        (armor.get("helmet", "AIR"), "helmet"),
        (armor.get("chestplate", "AIR"), "chestplate"),
        (armor.get("leggings", "AIR"), "leggings"),
        (armor.get("boots", "AIR"), "boots"),
    ]
    for i, (it, sil) in enumerate(eq_slots):
        _draw_slot(img, draw, margin_x + i * (slot_size + pad), 62, size=slot_size, item_name=it, count=1, silhouette=sil)

    # Разделитель экипировки и рук
    div_x = margin_x + 4 * (slot_size + pad) + 4
    draw.line([(div_x, 64), (div_x, 112)], fill=(54, 57, 63, 255), width=2)

    # Руки (Основная рука и Вторая рука / щит)
    hand_x = div_x + 10
    _draw_slot(img, draw, hand_x, 62, size=slot_size, item_name=main_hand, count=1, silhouette="mainhand")
    _draw_slot(img, draw, hand_x + slot_size + pad, 62, size=slot_size, item_name=off_hand, count=1, silhouette="shield")

    # Карта слотов инвентаря
    inv_map = {it["slot"]: it for it in inventory_items if "slot" in it}

    # 3. Основной рюкзак (слоты 9..35, 3 ряда по 9)
    draw.text((margin_x, 126), "ОСНОВНОЙ РЮКЗАК (Слоты 10-36):", fill=(158, 164, 174, 255), font=font_sec)
    for r in range(3):
        for c in range(9):
            slot_idx = 9 + r * 9 + c
            x = margin_x + c * (slot_size + pad)
            y = 144 + r * (slot_size + pad)

            item_data = inv_map.get(slot_idx)
            if not item_data:
                _draw_slot(img, draw, x, y, size=slot_size)
                continue

            raw_item = item_data.get("item", "").upper()
            cnt = item_data.get("count", 1)
            is_shulker = "SHULKER_BOX" in raw_item
            sh_items = item_data.get("shulker_items", [])

            _draw_slot(
                img,
                draw,
                x,
                y,
                size=slot_size,
                item_name=raw_item,
                count=cnt,
                is_shulker=is_shulker,
                sh_count=len(sh_items),
            )

    # 4. Хотбар (слоты 0..8, 1 ряд по 9)
    draw.text((margin_x, 322), "ХОТБАР (Слоты быстрого доступа 1-9):", fill=(250, 204, 21, 255), font=font_sec)
    for c in range(9):
        slot_idx = c
        x = margin_x + c * (slot_size + pad)
        y = 340

        item_data = inv_map.get(slot_idx)
        if not item_data:
            _draw_slot(img, draw, x, y, size=slot_size)
            continue

        raw_item = item_data.get("item", "").upper()
        cnt = item_data.get("count", 1)
        is_shulker = "SHULKER_BOX" in raw_item
        sh_items = item_data.get("shulker_items", [])

        _draw_slot(
            img,
            draw,
            x,
            y,
            size=slot_size,
            item_name=raw_item,
            count=cnt,
            is_shulker=is_shulker,
            sh_count=len(sh_items),
        )

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
