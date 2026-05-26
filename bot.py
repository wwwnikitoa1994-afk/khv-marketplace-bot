# FINAL KHV MARKETPLACE BOT
# Stable production version

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

TOKEN = "8634367728:AAG_gKuluoogGD2km02bakEH35kjvr6nALU"
CHANNEL_ID = "@khv_marketplace"
BOT_LINK = "https://t.me/khv_marketplace_bot"

ADMIN_IDS = [1095957868]
COOLDOWN_HOURS = 72

conn = sqlite3.connect(
    "database.db",
    check_same_thread=False
)

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
    button_message_id INTEGER,

    created_at TEXT,
    last_bump TEXT,

    status TEXT
)
""")

conn.commit()

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher(
    storage=MemoryStorage()
)

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Опубликовать объявление")],
        [KeyboardButton(text="📂 Мои объявления")]
    ],
    resize_keyboard=True
)

action_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🟢 Продам"),
            KeyboardButton(text="🔵 Куплю")
        ],
        [
            KeyboardButton(text="🟣 Отдам"),
            KeyboardButton(text="🟠 Обменяю")
        ]
    ],
    resize_keyboard=True
)

category_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📱 Техника"),
            KeyboardButton(text="🛋 Мебель")
        ],
        [
            KeyboardButton(text="👕 Одежда"),
            KeyboardButton(text="🎮 Развлечения")
        ],
        [
            KeyboardButton(text="🚗 Авто"),
            KeyboardButton(text="🧸 Детское")
        ],
        [
            KeyboardButton(text="🛠 Инструменты"),
            KeyboardButton(text="📚 Разное")
        ]
    ],
    resize_keyboard=True
)

condition_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="✨ Новое"),
            KeyboardButton(text="📦 Б/У")
        ]
    ],
    resize_keyboard=True
)

photo_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Опубликовать")],
        [KeyboardButton(text="🚫 Отмена")]
    ],
    resize_keyboard=True
)

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

def is_admin(user_id):
    return user_id in ADMIN_IDS

def check_cooldown(last_bump):

    if not last_bump:
        return True

    last_bump_time = datetime.fromisoformat(last_bump)

    return (
        datetime.now() - last_bump_time
    ) >= timedelta(hours=COOLDOWN_HOURS)

def ad_dict(row):

    columns = [
        "id",
        "user_id",
        "username",
        "action",
        "category",
        "title",
        "description",
        "condition",
        "price",
        "old_price",
        "exchange",
        "photos",
        "message_id",
        "button_message_id",
        "created_at",
        "last_bump",
        "status"
    ]

    return dict(zip(columns, row))

def build_hashtags(action, category):

    hashtags = ""

    if "Продам" in action:
        hashtags += "#продам "

    elif "Куплю" in action:
        hashtags += "#куплю "

    elif "Отдам" in action:
        hashtags += "#отдам "

    elif "Обменяю" in action:
        hashtags += "#обменяю "

    category_tag = category.split(" ")[1].lower()

    hashtags += f"#{category_tag}"

    return hashtags

def build_caption(ad):

    caption = (
        f"{ad['action'].upper()} • {ad['category']}\n\n"
        f"📌 <b>{ad['title']}</b>\n\n"
        f"📝 {ad['description']}\n\n"
    )

    if ad["condition"]:
        caption += f"📦 Состояние: {ad['condition']}\n\n"

    if ad["price"]:

        if ad["old_price"]:
            caption += (
                f"💰 <s>{ad['old_price']}</s> → {ad['price']}\n\n"
            )
        else:

            if "Куплю" in ad["action"]:
                caption += f"💰 Бюджет: {ad['price']}\n\n"
            else:
                caption += f"💰 Цена: {ad['price']}\n\n"

    if ad["exchange"]:
        caption += f"🔄 Интересует:\n{ad['exchange']}\n\n"

    caption += (
        f"📩 {ad['contact']}\n\n"
        f"{ad['hashtags']}\n\n"
        f"━━━━━━━━━━━━━━"
    )

    return caption

@dp.message(CommandStart())
async def start(message: Message):

    await message.answer(
        "🛒 Добро пожаловать в KHV Marketplace",
        reply_markup=main_keyboard
    )

@dp.message(F.text == "➕ Опубликовать объявление")
async def create_ad(
    message: Message,
    state: FSMContext
):

    await state.clear()

    await message.answer(
        "Выберите тип объявления:",
        reply_markup=action_keyboard
    )

    await state.set_state(AdForm.action)

@dp.message(AdForm.action)
async def get_action(
    message: Message,
    state: FSMContext
):

    await state.update_data(action=message.text)

    await message.answer(
        "Выберите категорию:",
        reply_markup=category_keyboard
    )

    await state.set_state(AdForm.category)

@dp.message(AdForm.category)
async def get_category(
    message: Message,
    state: FSMContext
):

    await state.update_data(category=message.text)

    await message.answer(
        "📌 Название товара:",
        reply_markup=ReplyKeyboardRemove()
    )

    await state.set_state(AdForm.title)

@dp.message(AdForm.title)
async def get_title(
    message: Message,
    state: FSMContext
):

    await state.update_data(title=message.text)

    await message.answer("📝 Описание товара:")

    await state.set_state(AdForm.description)

@dp.message(AdForm.description)
async def get_description(
    message: Message,
    state: FSMContext
):

    await state.update_data(description=message.text)

    data = await state.get_data()

    action = data["action"]

    if action in ["🟢 Продам", "🟠 Обменяю"]:

        await message.answer(
            "📦 Состояние товара:",
            reply_markup=condition_keyboard
        )

        await state.set_state(AdForm.condition)

    elif action == "🔵 Куплю":

        await message.answer("💰 Бюджет:")
        await state.set_state(AdForm.price)

    else:

        await state.update_data(photos=[])

        await message.answer(
            "📷 Отправьте от 1 до 15 фото",
            reply_markup=photo_keyboard
        )

        await state.set_state(AdForm.photos)

@dp.message(AdForm.condition)
async def get_condition(
    message: Message,
    state: FSMContext
):

    await state.update_data(condition=message.text)

    data = await state.get_data()

    if data["action"] == "🟠 Обменяю":

        await message.answer("🔄 На что хотите обмен?")
        await state.set_state(AdForm.exchange)

    else:

        await message.answer("💰 Цена:")
        await state.set_state(AdForm.price)

@dp.message(AdForm.exchange)
async def get_exchange(
    message: Message,
    state: FSMContext
):

    await state.update_data(exchange=message.text)
    await state.update_data(photos=[])

    await message.answer(
        "📷 Отправьте от 1 до 15 фото",
        reply_markup=photo_keyboard
    )

    await state.set_state(AdForm.photos)

@dp.message(AdForm.price)
async def get_price(
    message: Message,
    state: FSMContext
):

    await state.update_data(price=message.text)
    await state.update_data(photos=[])

    await message.answer(
        "📷 Отправьте от 1 до 15 фото",
        reply_markup=photo_keyboard
    )

    await state.set_state(AdForm.photos)

@dp.message(AdForm.photos, F.photo)
async def get_photo(
    message: Message,
    state: FSMContext
):

    data = await state.get_data()

    photos = data.get("photos", [])

    if len(photos) >= 15:

        await message.answer("❌ Максимум 15 фото")
        return

    photos.append(message.photo[-1].file_id)

    await state.update_data(photos=photos)

@dp.message(F.text == "🚫 Отмена")
async def cancel(
    message: Message,
    state: FSMContext
):

    await state.clear()

    await message.answer(
        "❌ Создание объявления отменено",
        reply_markup=main_keyboard
    )

@dp.message(AdForm.photos, F.text == "✅ Опубликовать")
async def publish_post(
    message: Message,
    state: FSMContext
):

    data = await state.get_data()

    photos = data.get("photos", [])

    if len(photos) == 0:

        await message.answer("❌ Добавьте хотя бы 1 фото")
        return

    username = message.from_user.username

    contact = (
        f"@{username}"
        if username
        else "Username отсутствует"
    )

    hashtags = build_hashtags(
        data["action"],
        data["category"]
    )

    ad = {
        "action": data["action"],
        "category": data["category"],
        "title": data["title"],
        "description": data["description"],
        "condition": data.get("condition"),
        "price": data.get("price"),
        "old_price": None,
        "exchange": data.get("exchange"),
        "contact": contact,
        "hashtags": hashtags
    }

    caption = build_caption(ad)

    media = []

    for i, photo in enumerate(photos):

        if i == 0:
            media.append(
                InputMediaPhoto(
                    media=photo,
                    caption=caption
                )
            )
        else:
            media.append(
                InputMediaPhoto(media=photo)
            )

    sent_messages = await bot.send_media_group(
        chat_id=CHANNEL_ID,
        media=media
    )

    message_id = sent_messages[0].message_id

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Подать своё объявление",
                    url=BOT_LINK
                )
            ]
        ]
    )

    button_message = await bot.send_message(
        chat_id=CHANNEL_ID,
        text="🛒 KHV Marketplace",
        reply_markup=keyboard
    )

    cursor.execute("""
    INSERT INTO ads (
        user_id,
        username,
        action,
        category,
        title,
        description,
        condition,
        price,
        old_price,
        exchange,
        photos,
        message_id,
        button_message_id,
        created_at,
        last_bump,
        status
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        message.from_user.id,
        username,
        data["action"],
        data["category"],
        data["title"],
        data["description"],
        data.get("condition"),
        data.get("price"),
        None,
        data.get("exchange"),
        ",".join(photos),
        message_id,
        button_message.message_id,
        datetime.now().isoformat(),
        datetime.now().isoformat(),
        "active"
    ))

    conn.commit()

    await message.answer(
        "✅ Объявление опубликовано",
        reply_markup=main_keyboard
    )

    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
