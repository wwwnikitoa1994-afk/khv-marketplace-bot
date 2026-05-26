import asyncio
import sqlite3
from datetime import datetime, timedelta
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from aiogram.types import (
    Message,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InputMediaPhoto,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)

# =========================================
# CONFIG
# =========================================

TOKEN = "8634367728:AAGEhyOUZ8FjJtUXuRDfBpq-Bbzk5DDD8r4"
CHANNEL_ID = "@khv_marketplace"
BOT_LINK = "https://t.me/khv_marketplace_bot"

ADMIN_IDS = [1095957868]
COOLDOWN_HOURS = 24

# Блокировка для безопасной работы SQLite в асинхронной среде
db_lock = asyncio.Lock()

# =========================================
# DATABASE
# =========================================

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS ads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    action TEXT,
    category TEXT,
    title TEXT,
    description TEXT,
    condition TEXT,
    price TEXT,
    old_price TEXT,
    exchange TEXT,
    photos TEXT,
    message_id INTEGER,
    created_at TEXT,
    last_bump TEXT,
    status TEXT
)
""")
conn.commit()

# Столбцы для удобной конвертации строк БД в dict
DB_COLUMNS = [
    "id", "user_id", "username", "action", "category", "title", 
    "description", "condition", "price", "old_price", "exchange", 
    "photos", "message_id", "created_at", "last_bump", "status"
]

# =========================================
# BOT
# =========================================

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# =========================================
# KEYBOARDS
# =========================================

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Опубликовать объявление")],
        [KeyboardButton(text="📂 Мои объявления")]
    ],
    resize_keyboard=True
)

action_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🟢 Продам"), KeyboardButton(text="🔵 Куплю")],
        [KeyboardButton(text="🟣 Отдам"), KeyboardButton(text="🟠 Обменяю")]
    ],
    resize_keyboard=True
)

category_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 Техника"), KeyboardButton(text="🛋 Мебель")],
        [KeyboardButton(text="👕 Одежда"), KeyboardButton(text="🎮 Развлечения")],
        [KeyboardButton(text="🚗 Авто"), KeyboardButton(text="🧸 Детское")],
        [KeyboardButton(text="🛠 Инструменты"), KeyboardButton(text="📚 Разное")]
    ],
    resize_keyboard=True
)

condition_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="✨ Новое"), KeyboardButton(text="📦 Б/У")]],
    resize_keyboard=True
)

photo_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Опубликовать")],
        [KeyboardButton(text="🚫 Отмена")]
    ],
    resize_keyboard=True
)

# =========================================
# STATES
# =========================================

class AdForm(StatesGroup):
    action = State()
    category = State()
    title = State()
    description = State()
    condition = State()
    price = State()
    exchange = State()
    photos = State()

class EditPrice(StatesGroup):
    waiting_price = State()

# =========================================
# HELPERS
# =========================================

def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_cooldown_remaining(last_bump, user_id):
    """Возвращает строку с оставшимся временем КД. Для админов всегда None."""
    if is_admin(user_id):
        return None
    try:
        last_bump_dt = datetime.fromisoformat(last_bump)
        remaining = (last_bump_dt + timedelta(hours=COOLDOWN_HOURS)) - datetime.now()
        if remaining.total_seconds() > 0:
            days = remaining.days
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            time_str = ""
            if days > 0: time_str += f"{days} дн. "
            if hours > 0 or days > 0: time_str += f"{hours} ч. "
            time_str += f"{minutes} мин."
            return time_str
        return None
    except Exception:
        return None

def build_hashtags(action, category):
    hashtags = ""
    if "Продам" in action: hashtags += "#продам "
    elif "Куплю" in action: hashtags += "#куплю "
    elif "Отдам" in action: hashtags += "#отдам "
    elif "Обменяю" in action: hashtags += "#обменяю "

    try:
        category_tag = category.split(" ")[1].lower()
        hashtags += f"#{category_tag}"
    except Exception:
        hashtags += "#разное"
    return hashtags

def build_caption(ad):
    caption = (
        f"{ad['action'].upper()} • {ad['category']}\n\n"
        f"📌 <b>{ad['title']}</b>\n\n"
        f"📝 {ad['description']}\n\n"
    )
    if ad.get("condition"):
        caption += f"📦 Состояние: {ad['condition']}\n\n"

    if ad.get("price"):
        if ad.get("old_price"):
            caption += f"💰 <s>{ad['old_price']}</s> → {ad['price']}\n\n"
        else:
            if "Куплю" in ad["action"]:
                caption += f"💰 Бюджет: {ad['price']}\n\n"
            else:
                caption += f"💰 Цена: {ad['price']}\n\n"

    if ad.get("exchange"):
        caption += f"🔄 Интересует:\n{ad['exchange']}\n\n"

    caption += (
        f"📩 Контакт: {ad['contact']}\n\n"
        f"{ad['hashtags']}\n\n"
        f"━━━━━━━━━━━━━━"
    )
    return caption

async def safe_delete_message(chat_id, message_id):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

# =========================================
# START
# =========================================

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("🛒 Добро пожаловать в KHV Marketplace", reply_markup=main_keyboard)

# =========================================
# CREATE AD
# =========================================

@dp.message(F.text == "➕ Опубликовать объявление")
async def create_ad(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Выберите тип объявления:", reply_markup=action_keyboard)
    await state.set_state(AdForm.action)

# =========================================
# MULTI-STEPS (PUBLISH PROCESS)
# =========================================

@dp.message(AdForm.action)
async def get_action(message: Message, state: FSMContext):
    await state.update_data(action=message.text)
    await message.answer("Выберите категорию:", reply_markup=category_keyboard)
    await state.set_state(AdForm.category)

@dp.message(AdForm.category)
async def get_category(message: Message, state: FSMContext):
    await state.update_data(category=message.text)
    await message.answer("📌 Название товара:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdForm.title)

@dp.message(AdForm.title)
async def get_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("📝 Описание товара:")
    await state.set_state(AdForm.description)

@dp.message(AdForm.description)
async def get_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    data = await state.get_data()
    action = data.get("action", "")

    if action in ["🟢 Продам", "🟠 Обменяю"]:
        await message.answer("📦 Состояние товара:", reply_markup=condition_keyboard)
        await state.set_state(AdForm.condition)
    elif action == "🔵 Куплю":
        await message.answer("💰 Бюджет:")
        await state.set_state(AdForm.price)
    else:
        await state.update_data(photos=[])
        await message.answer("📷 Отправьте от 1 до 15 фото", reply_markup=photo_keyboard)
        await state.set_state(AdForm.photos)

@dp.message(AdForm.condition)
async def get_condition(message: Message, state: FSMContext):
    await state.update_data(condition=message.text)
    data = await state.get_data()
    action = data.get("action", "")

    if action == "🟢 Продам":
        await message.answer("💰 Цена:")
        await state.set_state(AdForm.price)
    else:
        await message.answer("🔄 На что хотите обмен?")
        await state.set_state(AdForm.exchange)

@dp.message(AdForm.price)
async def get_price(message: Message, state: FSMContext):
    await state.update_data(price=message.text, photos=[])
    await message.answer("📷 Отправьте от 1 до 15 фото", reply_markup=photo_keyboard)
    await state.set_state(AdForm.photos)

@dp.message(AdForm.exchange)
async def get_exchange(message: Message, state: FSMContext):
    await state.update_data(exchange=message.text, photos=[])
    await message.answer("📷 Отправьте от 1 до 15 фото", reply_markup=photo_keyboard)
    await state.set_state(AdForm.photos)

@dp.message(AdForm.photos, F.photo)
async def get_photo(message: Message, state: FSMContext):
    await asyncio.sleep(0.1)
    data = await state.get_data()
    photos = data.get("photos", [])

    if len(photos) >= 15:
        await message.answer("❌ Максимум 15 фото")
        return

    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)

@dp.message(F.text == "🚫 Отмена")
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Создание объявления отменено", reply_markup=main_keyboard)

@dp.message(AdForm.photos, F.text == "✅ Опубликовать")
async def publish_post(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])

    if not photos:
        await message.answer("❌ Добавьте хотя бы 1 фото")
        return

    action = data.get("action", "Разное")
    category = data.get("category", "Разное")
    username = message.from_user.username
    contact = f"@{username}" if username else "Username отсутствует"
    hashtags = build_hashtags(action, category)

    ad = {
        "action": action, "category": category, "title": data.get("title", ""),
        "description": data.get("description", ""), "condition": data.get("condition"),
        "price": data.get("price"), "old_price": None, "exchange": data.get("exchange"),
        "contact": contact, "hashtags":
