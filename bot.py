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
COOLDOWN_HOURS = 72

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

def check_cooldown(last_bump):
    try:
        last_bump_dt = datetime.fromisoformat(last_bump)
        return (datetime.now() - last_bump_dt) >= timedelta(hours=COOLDOWN_HOURS)
    except Exception:
        return True

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
    """Безопасное удаление сообщений без падения бота при ошибках Telegram"""
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
# ACTION
# =========================================

@dp.message(AdForm.action)
async def get_action(message: Message, state: FSMContext):
    await state.update_data(action=message.text)
    await message.answer("Выберите категорию:", reply_markup=category_keyboard)
    await state.set_state(AdForm.category)

# =========================================
# CATEGORY
# =========================================

@dp.message(AdForm.category)
async def get_category(message: Message, state: FSMContext):
    await state.update_data(category=message.text)
    await message.answer("📌 Название товара:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdForm.title)

# =========================================
# TITLE
# =========================================

@dp.message(AdForm.title)
async def get_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("📝 Описание товара:")
    await state.set_state(AdForm.description)

# =========================================
# DESCRIPTION
# =========================================

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

# =========================================
# CONDITION
# =========================================

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

# =========================================
# PRICE
# =========================================

@dp.message(AdForm.price)
async def get_price(message: Message, state: FSMContext):
    await state.update_data(price=message.text, photos=[])
    await message.answer("📷 Отправьте от 1 до 15 фото", reply_markup=photo_keyboard)
    await state.set_state(AdForm.photos)

# =========================================
# EXCHANGE
# =========================================

@dp.message(AdForm.exchange)
async def get_exchange(message: Message, state: FSMContext):
    await state.update_data(exchange=message.text, photos=[])
    await message.answer("📷 Отправьте от 1 до 15 фото", reply_markup=photo_keyboard)
    await state.set_state(AdForm.photos)

# =========================================
# PHOTOS
# =========================================

@dp.message(AdForm.photos, F.photo)
async def get_photo(message: Message, state: FSMContext):
    # Небольшая задержка, чтобы избежать Race Condition при загрузке альбома
    await asyncio.sleep(0.1)
    data = await state.get_data()
    photos = data.get("photos", [])

    if len(photos) >= 15:
        await message.answer("❌ Максимум 15 фото")
        return

    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)

# =========================================
# CANCEL
# =========================================

@dp.message(F.text == "🚫 Отмена")
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Создание объявления отменено", reply_markup=main_keyboard)

# =========================================
# PUBLISH
# =========================================

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
        "action": action,
        "category": category,
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "condition": data.get("condition"),
        "price": data.get("price"),
        "old_price": None,
        "exchange": data.get("exchange"),
        "contact": contact,
        "hashtags": hashtags
    }

    caption = build_caption(ad)
    media = [InputMediaPhoto(media=photo, caption=caption if i == 0 else "") for i, photo in enumerate(photos)]

    try:
        sent_messages = await bot.send_media_group(chat_id=CHANNEL_ID, media=media)
        message_id = sent_messages[0].message_id

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="➕ Подать своё объявление", url=BOT_LINK)
        ]])
        
        await bot.send_message(chat_id=CHANNEL_ID, text="🛒 KHV Marketplace", reply_markup=keyboard, disable_web_page_preview=True)

        async with db_lock:
            cursor.execute("""
            INSERT INTO ads (user_id, username, action, category, title, description, condition, price, old_price, exchange, photos, message_id, created_at, last_bump, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message.from_user.id, username, action, category, ad["title"], ad["description"],
                ad["condition"], ad["price"], None, ad["exchange"], ",".join(photos),
                message_id, datetime.now().isoformat(), datetime.now().isoformat(), "active"
            ))
            conn.commit()

        await message.answer("✅ Объявление опубликовано", reply_markup=main_keyboard)
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Ошибка публикации объявления. Попробуйте позже.")
        print(f"Publish error: {e}")

# =========================================
# MY ADS KEYBOARD
# =========================================

def my_ads_keyboard(ads):
    keyboard = [[InlineKeyboardButton(text="🔄 Поднять все доступные", callback_data="bump_all")]]
    for ad in ads:
        keyboard.append([InlineKeyboardButton(text=f"📦 {ad[1]}", callback_data=f"ad_{ad[0]}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# =========================================
# MY ADS
# =========================================

@dp.message(F.text == "📂 Мои объявления")
async def my_ads(message: Message):
    async with db_lock:
        cursor.execute("SELECT id, title FROM ads WHERE user_id = ? ORDER BY id DESC", (message.from_user.id,))
        ads = cursor.fetchall()

    if not ads:
        await message.answer("📭 У вас нет объявлений")
        return

    await message.answer("📂 Ваши объявления:", reply_markup=my_ads_keyboard(ads))

# =========================================
# OPEN AD
# =========================================

@dp.callback_query(F.data.startswith("ad_"))
async def open_ad(callback: CallbackQuery):
    ad_id = int(callback.data.split("_")[1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Поднять", callback_data=f"bump_{ad_id}")],
        [InlineKeyboardButton(text="✏️ Изменить цену", callback_data=f"edit_{ad_id}")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data=f"close_{ad_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_ads")]
    ])
    await callback.message.edit_text(f"📦 Объявление ID {ad_id}", reply_markup=keyboard)

@dp.callback_query(F.data == "back_ads")
async def back_ads(callback: CallbackQuery):
    async with db_lock:
        cursor.execute("SELECT id, title FROM ads WHERE user_id = ? ORDER BY id DESC", (callback.from_user.id,))
        ads = cursor.fetchall()

    if not ads:
        await callback.message.edit_text("📭 У вас нет объявлений")
        return
    await callback.message.edit_text("📂 Ваши объявления:", reply_markup=my_ads_keyboard(ads))

# =================================================
# CLOSE AD
# =================================================

@dp.callback_query(F.data.regexp(r"^close_\d+$"))
async def close_ad(callback: CallbackQuery):
    ad_id = int(callback.data.split("_")[1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_close_{ad_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_close_{ad_id}")
    ]])
    await callback.message.edit_text("❓ Вы уверены что хотите закрыть объявление?", reply_markup=keyboard)

# =================================================
# CONFIRM CLOSE
# =================================================

@dp.callback_query(F.data.startswith("confirm_close_"))
async def confirm_close_ad(callback: CallbackQuery):
    ad_id = int(callback.data.split("_")[2])

    async with db_lock:
        cursor.execute("SELECT message_id FROM ads WHERE id = ?", (ad_id,))
        ad = cursor.fetchone()

    if not ad:
        await callback.answer("❌ Объявление не найдено", show_alert=True)
        return

    message_id = ad[0]
    await safe_delete_message(CHANNEL_ID, message_id)
    await safe_delete_message(CHANNEL_ID, message_id + 1)

    async with db_lock:
        cursor.execute("DELETE FROM ads WHERE id = ?", (ad_id,))
        conn.commit()
        cursor.execute("SELECT id, title FROM ads WHERE user_id = ? ORDER BY id DESC", (callback.from_user.id,))
        ads = cursor.fetchall()

    if not ads:
        await callback.message.edit_text("📭 У вас нет объявлений")
        return
    await callback.message.edit_text("📂 Ваши объявления:", reply_markup=my_ads_keyboard(ads))

# =================================================
# CANCEL CLOSE
# =================================================

@dp.callback_query(F.data.startswith("cancel_close_"))
async def cancel_close_ad(callback: CallbackQuery):
    ad_id = int(callback.data.split("_")[2])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Поднять", callback_data=f"bump_{ad_id}")],
        [InlineKeyboardButton(text="✏️ Изменить цену", callback_data=f"edit_{ad_id}")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data=f"close_{ad_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_ads")]
    ])
    await callback.message.edit_text(f"📦 Объявление ID {ad_id}", reply_markup=keyboard)

# =========================================
# EDIT PRICE
# =========================================

@dp.callback_query(F.data.startswith("edit_"))
async def edit_price(callback: CallbackQuery, state: FSMContext):
    ad_id = int(callback.data.split("_")[1])

    async with db_lock:
        cursor.execute("SELECT last_bump FROM ads WHERE id = ?", (ad_id,))
        ad = cursor.fetchone()

    if not ad:
        await callback.answer("❌ Объявление не найдено", show_alert=True)
        return

    last_bump = ad[0]
    if not is_admin(callback.from_user.id) and not check_cooldown(last_bump):
        await callback.answer("⏳ Изменить цену пока нельзя", show_alert=True)
        return

    await state.update_data(editing_ad_id=ad_id)
    await callback.message.answer("💰 Введите новую цену:")
    await state.set_state(EditPrice.waiting_price)

# =========================================
# SAVE NEW PRICE
# =========================================

@dp.message(EditPrice.waiting_price)
async def save_new_price(message: Message, state: FSMContext):
    new_price = message.text
    data = await state.get_data()
    ad_id = data.get("editing_ad_id")

    async with db_lock:
        cursor.execute("SELECT * FROM ads WHERE id = ?", (ad_id,))
        ad_row = cursor.fetchone()

    if not ad_row:
        await message.answer("❌ Объявление не найдено")
        return

    ad = dict(zip(DB_COLUMNS, ad_row))
    old_price = ad["price"]
    save_old_price = None

    # Исправлена уязвимость парсинга пустых строк в int
    try:
        old_digits = "".join(filter(str.isdigit, str(old_price)))
        new_digits = "".join(filter(str.isdigit, str(new_price)))
        if old_digits and new_digits and int(new_digits) < int(old_digits):
            save_old_price = old_price
    except Exception:
        pass

    await safe_delete_message(CHANNEL_ID, ad["message_id"])
    await safe_delete_message(CHANNEL_ID, ad["message_id"] + 1)

    photos = ad["photos"].split(",") if ad["photos"] else []
    contact = f"@{ad['username']}" if ad["username"] else "Username отсутствует"
    hashtags = build_hashtags(ad["action"], ad["category"])

    caption = build_caption({
        "action": ad["action"], "category": ad["category"], "title": ad["title"],
        "description": ad["description"], "condition": ad["condition"], "price": new_price,
        "old_price": save_old_price, "exchange": ad["exchange"], "contact": contact, "hashtags": hashtags
    })

    media = [InputMediaPhoto(media=photo, caption=caption if i == 0 else "") for i, photo in enumerate(photos)]

    try:
        sent_messages = await bot.send_media_group(chat_id=CHANNEL_ID, media=media)
        new_message_id = sent_messages[0].message_id

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="➕ Подать своё объявление", url=BOT_LINK)
        ]])
        await bot.send_message(chat_id=CHANNEL_ID, text="🛒 KHV Marketplace", reply_markup=keyboard, disable_web_page_preview=True)

        async with db_lock:
            cursor.execute("""
            UPDATE ads SET price = ?, old_price = ?, message_id = ?, last_bump = ? WHERE id = ?
            """, (new_price, save_old_price, new_message_id, datetime.now().isoformat(), ad_id))
            conn.commit()

        await message.answer("✅ Цена обновлена", reply_markup=main_keyboard)
        await state.clear()
    except Exception as e:
        await message.answer("❌ Произошла ошибка при обновлении цены в канале.")
        print(f"Edit price error: {e}")

# =========================================
# BUMP
# =========================================

@dp.callback_query(F.data.startswith("bump_"))
async def bump_ad(callback: CallbackQuery):
    ad_id = int(callback.data.split("_")[1])

    async with db_lock:
        cursor.execute("SELECT * FROM ads WHERE id = ?", (ad_id,))
        ad_row = cursor.fetchone()

    if not ad_row:
        await callback.answer("❌ Объявление не найдено", show_alert=True)
        return

    ad = dict(zip(DB_COLUMNS, ad_row))

    if not is_admin(callback.from_user.id) and not check_cooldown(ad["last_bump"]):
        await callback.answer("⏳ Поднять объявление пока нельзя", show_alert=True)
        return

    # Удаляем старые посты канала безопасно
    await safe_delete_message(CHANNEL_ID, ad["message_id"])
    await safe_delete_message(CHANNEL_ID, ad["message_id"] + 1)

    # Пересобираем данные и отправляем всю медиагруппу заново (исправлен вылет)
    photos = ad["photos"].split(",") if ad["photos"] else []
    contact = f"@{ad['username']}" if ad["username"] else "Username отсутствует"
    hashtags = build_hashtags(ad["action"], ad["category"])
    
    caption = build_caption({
        "action": ad["action"], "category": ad["category"], "title": ad["title"],
        "description": ad["description"], "condition": ad["condition"], "price": ad["price"],
        "old_price": ad["old_price"], "exchange": ad["exchange"], "contact": contact, "hashtags": hashtags
    })

    media = [InputMediaPhoto(media=photo, caption=caption if i == 0 else "") for i, photo in enumerate(photos)]

    try:
        sent_messages = await bot.send_media_group(chat_id=CHANNEL_ID, media=media)
        new_message_id = sent_messages[0].message_id

        button = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="➕ Подать своё объявление", url=BOT_LINK)
        ]])
        await bot.send_message(chat_id=CHANNEL_ID, text="🛒 KHV Marketplace", reply_markup=button)

        async with db_lock:
            cursor.execute("""
            UPDATE ads SET message_id = ?, last_bump = ? WHERE id = ?
            """, (new_message_id, datetime.now().isoformat(), ad_id))
            conn.commit()

        await callback.answer("✅ Объявление поднято", show_alert=True)
    except Exception as e:
        await callback.answer("❌ Ошибка при поднятии объявления.", show_alert=True)
        print(f"Bump error: {e}")

# =========================================
# WEB SERVER
# =========================================

async def healthcheck(request):
    return web.Response(text="Bot is running")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()

# =========================================
# MAIN
# =========================================

async def main():
    await start_web_server()
    # Удаляем вебхуки, чтобы полинг запускался без конфликтов
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
