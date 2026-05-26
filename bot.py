
# -*- coding: utf-8 -*-

import asyncio
import sqlite3

from datetime import datetime, timedelta
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
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

# =========================================
# DB
# =========================================

conn = sqlite3.connect(
    "database.db",
    check_same_thread=False
)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS ads(
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
    last_bump TEXT
)
""")

conn.commit()

# =========================================
# BOT
# =========================================

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher(
    storage=MemoryStorage()
)

# =========================================
# KEYBOARDS
# =========================================

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Опубликовать объявление")],
        [KeyboardButton(text="📂 Мои объявления")]
    ],
    resize_keyboard=True
)

action_kb = ReplyKeyboardMarkup(
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

category_kb = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📱 Техника"),
            KeyboardButton(text="🛋 Мебель")
        ],
        [
            KeyboardButton(text="👕 Одежда"),
            KeyboardButton(text="🚗 Авто")
        ]
    ],
    resize_keyboard=True
)

condition_kb = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="✨ Новое"),
            KeyboardButton(text="📦 Б/У")
        ]
    ],
    resize_keyboard=True
)

photo_kb = ReplyKeyboardMarkup(
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

def build_hashtags(action, category):

    tags = ""

    if "Продам" in action:
        tags += "#продам "

    elif "Куплю" in action:
        tags += "#куплю "

    elif "Отдам" in action:
        tags += "#отдам "

    elif "Обменяю" in action:
        tags += "#обменяю "

    try:
        tags += "#" + category.split(" ", 1)[1].lower()
    except:
        tags += "#разное"

    return tags

def check_cooldown(last_bump):

    if not last_bump:
        return True

    last = datetime.fromisoformat(last_bump)

    return (
        datetime.now() - last
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
        "last_bump"
    ]

    return dict(zip(columns, row))

async def get_ad(ad_id):

    cursor.execute(
        "SELECT * FROM ads WHERE id = ?",
        (ad_id,)
    )

    row = cursor.fetchone()

    if not row:
        return None

    return ad_dict(row)

def build_caption(ad):

    text = (
        f"{ad['action']} • {ad['category']}\n\n"
        f"📌 <b>{ad['title']}</b>\n\n"
        f"📝 {ad['description']}\n\n"
    )

    if ad["condition"]:
        text += f"{ad['condition']}\n\n"

    if ad["price"]:

        if ad["old_price"]:
            text += f"💰 <s>{ad['old_price']}</s> → {ad['price']}\n\n"
        else:
            text += f"💰 {ad['price']}\n\n"

    if ad["exchange"]:
        text += f"🔄 {ad['exchange']}\n\n"

    text += (
        f"📩 {ad['contact']}\n\n"
        f"{ad['hashtags']}"
    )

    return text

# =========================================
# START
# =========================================

@dp.message(CommandStart())
async def start(message: Message):

    await message.answer(
        "🛒 Добро пожаловать",
        reply_markup=main_kb
    )

# =========================================
# CREATE
# =========================================

@dp.message(F.text == "➕ Опубликовать объявление")
async def create_ad(message: Message, state: FSMContext):

    await state.clear()

    await message.answer(
        "Выберите тип:",
        reply_markup=action_kb
    )

    await state.set_state(AdForm.action)

@dp.message(AdForm.action)
async def get_action(message: Message, state: FSMContext):

    await state.update_data(
        action=message.text
    )

    await message.answer(
        "Выберите категорию:",
        reply_markup=category_kb
    )

    await state.set_state(AdForm.category)

@dp.message(AdForm.category)
async def get_category(message: Message, state: FSMContext):

    await state.update_data(
        category=message.text
    )

    await message.answer(
        "Название:",
        reply_markup=ReplyKeyboardRemove()
    )

    await state.set_state(AdForm.title)

@dp.message(AdForm.title)
async def get_title(message: Message, state: FSMContext):

    await state.update_data(
        title=message.text
    )

    await message.answer("Описание:")

    await state.set_state(AdForm.description)

@dp.message(AdForm.description)
async def get_description(message: Message, state: FSMContext):

    await state.update_data(
        description=message.text
    )

    data = await state.get_data()

    if data["action"] in [
        "🟢 Продам",
        "🟠 Обменяю"
    ]:

        await message.answer(
            "Состояние:",
            reply_markup=condition_kb
        )

        await state.set_state(AdForm.condition)

    elif data["action"] == "🔵 Куплю":

        await message.answer("Бюджет:")
        await state.set_state(AdForm.price)

    else:

        await state.update_data(photos=[])

        await message.answer(
            "Отправьте фото",
            reply_markup=photo_kb
        )

        await state.set_state(AdForm.photos)

@dp.message(AdForm.condition)
async def get_condition(message: Message, state: FSMContext):

    await state.update_data(
        condition=message.text
    )

    data = await state.get_data()

    if data["action"] == "🟢 Продам":

        await message.answer("Цена:")
        await state.set_state(AdForm.price)

    else:

        await message.answer("На что обмен?")
        await state.set_state(AdForm.exchange)

@dp.message(AdForm.price)
async def get_price(message: Message, state: FSMContext):

    await state.update_data(
        price=message.text,
        photos=[]
    )

    await message.answer(
        "Отправьте фото",
        reply_markup=photo_kb
    )

    await state.set_state(AdForm.photos)

@dp.message(AdForm.exchange)
async def get_exchange(message: Message, state: FSMContext):

    await state.update_data(
        exchange=message.text,
        photos=[]
    )

    await message.answer(
        "Отправьте фото",
        reply_markup=photo_kb
    )

    await state.set_state(AdForm.photos)

@dp.message(AdForm.photos, F.photo)
async def get_photo(message: Message, state: FSMContext):

    data = await state.get_data()

    photos = data.get("photos", [])

    if len(photos) >= 15:

        await message.answer("Максимум 15 фото")
        return

    photos.append(
        message.photo[-1].file_id
    )

    await state.update_data(
        photos=photos
    )

# =========================================
# CANCEL
# =========================================

@dp.message(F.text == "🚫 Отмена")
async def cancel(message: Message, state: FSMContext):

    await state.clear()

    await message.answer(
        "Отменено",
        reply_markup=main_kb
    )

# =========================================
# PUBLISH
# =========================================

@dp.message(AdForm.photos, F.text == "✅ Опубликовать")
async def publish(message: Message, state: FSMContext):

    data = await state.get_data()

    photos = data.get("photos", [])

    if not photos:

        await message.answer("Добавьте фото")
        return

    username = message.from_user.username

    contact = (
        f"@{username}"
        if username else
        "ЛС закрыты"
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

    sent = await bot.send_media_group(
        chat_id=CHANNEL_ID,
        media=media
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Подать объявление",
                    url=BOT_LINK
                )
            ]
        ]
    )

    button_msg = await bot.send_message(
        chat_id=CHANNEL_ID,
        text="🛒 Marketplace",
        reply_markup=keyboard
    )

    cursor.execute("""
    INSERT INTO ads(
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
        last_bump
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        sent[0].message_id,
        button_msg.message_id,
        datetime.now().isoformat(),
        datetime.now().isoformat()
    ))

    conn.commit()

    await message.answer(
        "Объявление опубликовано",
        reply_markup=main_kb
    )

    await state.clear()

# =========================================
# MY ADS
# =========================================

def ads_keyboard(rows):

    keyboard = [
        [
            InlineKeyboardButton(
                text="🔄 Поднять все",
                callback_data="bump_all"
            )
        ]
    ]

    for ad in rows:

        keyboard.append([
            InlineKeyboardButton(
                text=f"📦 {ad[1]}",
                callback_data=f"ad_{ad[0]}"
            )
        ])

    return InlineKeyboardMarkup(
        inline_keyboard=keyboard
    )

@dp.message(F.text == "📂 Мои объявления")
async def my_ads(message: Message):

    cursor.execute("""
    SELECT id, title
    FROM ads
    WHERE user_id = ?
    ORDER BY id DESC
    """, (
        message.from_user.id,
    ))

    rows = cursor.fetchall()

    if not rows:

        await message.answer(
            "У вас нет объявлений"
        )

        return

    await message.answer(
        "Ваши объявления:",
        reply_markup=ads_keyboard(rows)
    )

# =========================================
# OPEN AD
# =========================================

@dp.callback_query(F.data.startswith("ad_"))
async def open_ad(callback: CallbackQuery):

    ad_id = int(callback.data.split("_")[1])

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Поднять",
                    callback_data=f"bump_{ad_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Закрыть",
                    callback_data=f"close_{ad_id}"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        f"Объявление #{ad_id}",
        reply_markup=keyboard
    )

# =========================================
# BUMP
# =========================================

@dp.callback_query(F.data.startswith("bump_"))
async def bump_ad(callback: CallbackQuery):

    ad_id = int(callback.data.split("_")[1])

    ad = await get_ad(ad_id)

    if not ad:
        return

    if not owner_check(ad, callback.from_user.id):

        await callback.answer(
            "Это не ваше объявление",
            show_alert=True
        )

        return

    if (
        not is_admin(callback.from_user.id)
        and
        not check_cooldown(ad["last_bump"])
    ):

        await callback.answer(
            "Поднимать пока нельзя",
            show_alert=True
        )

        return

    await callback.answer(
        "Объявление поднято",
        show_alert=True
    )

# =========================================
# BUMP ALL
# =========================================

@dp.callback_query(F.data == "bump_all")
async def bump_all(callback: CallbackQuery):

    await callback.answer(
        "Функция работает",
        show_alert=True
    )

# =========================================
# CLOSE
# =========================================

@dp.callback_query(F.data.startswith("close_"))
async def close_ad(callback: CallbackQuery):

    ad_id = int(callback.data.split("_")[1])

    ad = await get_ad(ad_id)

    if not ad:
        return

    if not owner_check(ad, callback.from_user.id):

        await callback.answer(
            "Это не ваше объявление",
            show_alert=True
        )

        return

    try:

        await bot.delete_message(
            chat_id=CHANNEL_ID,
            message_id=ad["message_id"]
        )

    except:
        pass

    try:

        await bot.delete_message(
            chat_id=CHANNEL_ID,
            message_id=ad["button_message_id"]
        )

    except:
        pass

    cursor.execute(
        "DELETE FROM ads WHERE id = ?",
        (ad_id,)
    )

    conn.commit()

    await callback.message.edit_text(
        "Объявление удалено"
    )

# =========================================
# WEB
# =========================================

async def healthcheck(request):

    return web.Response(
        text="Bot is running"
    )

async def start_web_server():

    app = web.Application()

    app.router.add_get(
        "/",
        healthcheck
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        10000
    )

    await site.start()

# =========================================
# MAIN
# =========================================

async def main():

    await start_web_server()

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
