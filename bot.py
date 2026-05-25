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

TOKEN = "8634367728:AAG_gKuluoogGD2km02bakEH35kjvr6nALU"
CHANNEL_ID = "@khv_marketplace"

BOT_LINK = "https://t.me/khv_marketplace_bot"

ADMIN_IDS = [
    1095957868
]

COOLDOWN_HOURS = 72

# =========================================
# DATABASE
# =========================================

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

    created_at TEXT,
    last_bump TEXT,

    status TEXT
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

    last_bump = datetime.fromisoformat(
        last_bump
    )

    return (
        datetime.now() - last_bump
    ) >= timedelta(hours=COOLDOWN_HOURS)

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

        caption += (
            f"{ad['condition']}\n\n"
        )

    if ad["price"]:

        if ad["old_price"]:

            caption += (
                f"💰 <s>{ad['old_price']}</s> "
                f"→ {ad['price']}\n\n"
            )

        else:

            if "Куплю" in ad["action"]:

                caption += (
                    f"💰 Бюджет: "
                    f"{ad['price']}\n\n"
                )

            else:

                caption += (
                    f"💰 Цена: "
                    f"{ad['price']}\n\n"
                )

    if ad["exchange"]:

        caption += (
            f"🔄 Интересует:\n"
            f"{ad['exchange']}\n\n"
        )

    caption += (
        f"📩 {ad['contact']}\n\n"
        f"{ad['hashtags']}\n\n"
        f"━━━━━━━━━━━━━━"
    )

    return caption

# =========================================
# START
# =========================================

@dp.message(CommandStart())
async def start(message: Message):

    await message.answer(
        "🛒 Добро пожаловать в KHV Marketplace",
        reply_markup=main_keyboard
    )

# =========================================
# CREATE AD
# =========================================

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

    await state.set_state(
        AdForm.action
    )

# =========================================
# ACTION
# =========================================

@dp.message(AdForm.action)
async def get_action(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        action=message.text
    )

    await message.answer(
        "Выберите категорию:",
        reply_markup=category_keyboard
    )

    await state.set_state(
        AdForm.category
    )

# =========================================
# CATEGORY
# =========================================

@dp.message(AdForm.category)
async def get_category(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        category=message.text
    )

    await message.answer(
        "📌 Название товара:",
        reply_markup=ReplyKeyboardRemove()
    )

    await state.set_state(
        AdForm.title
    )

# =========================================
# TITLE
# =========================================

@dp.message(AdForm.title)
async def get_title(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        title=message.text
    )

    await message.answer(
        "📝 Описание товара:"
    )

    await state.set_state(
        AdForm.description
    )

# =========================================
# DESCRIPTION
# =========================================

@dp.message(AdForm.description)
async def get_description(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        description=message.text
    )

    data = await state.get_data()

    action = data["action"]

    if action in [
        "🟢 Продам",
        "🟠 Обменяю"
    ]:

        await message.answer(
            "📦 Состояние товара:",
            reply_markup=condition_keyboard
        )

        await state.set_state(
            AdForm.condition
        )

    elif action == "🔵 Куплю":

        await message.answer(
            "💰 Бюджет:"
        )

        await state.set_state(
            AdForm.price
        )

    else:

        await state.update_data(
            photos=[]
        )

        await message.answer(
            "📷 Отправьте от 1 до 15 фото",
            reply_markup=photo_keyboard
        )

        await state.set_state(
            AdForm.photos
        )

# =========================================
# CONDITION
# =========================================

@dp.message(AdForm.condition)
async def get_condition(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        condition=message.text
    )

    data = await state.get_data()

    action = data["action"]

    if action == "🟢 Продам":

        await message.answer(
            "💰 Цена:"
        )

        await state.set_state(
            AdForm.price
        )

    else:

        await message.answer(
            "🔄 На что хотите обмен?"
        )

        await state.set_state(
            AdForm.exchange
        )

# =========================================
# PRICE
# =========================================

@dp.message(AdForm.price)
async def get_price(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        price=message.text
    )

    await state.update_data(
        photos=[]
    )

    await message.answer(
        "📷 Отправьте от 1 до 15 фото",
        reply_markup=photo_keyboard
    )

    await state.set_state(
        AdForm.photos
    )

# =========================================
# EXCHANGE
# =========================================

@dp.message(AdForm.exchange)
async def get_exchange(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        exchange=message.text
    )

    await state.update_data(
        photos=[]
    )

    await message.answer(
        "📷 Отправьте от 1 до 15 фото",
        reply_markup=photo_keyboard
    )

    await state.set_state(
        AdForm.photos
    )

# =========================================
# PHOTOS
# =========================================

@dp.message(
    AdForm.photos,
    F.photo
)
async def get_photo(
    message: Message,
    state: FSMContext
):

    data = await state.get_data()

    photos = data.get(
        "photos",
        []
    )

    if len(photos) >= 15:

        await message.answer(
            "❌ Максимум 15 фото"
        )

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
async def cancel(
    message: Message,
    state: FSMContext
):

    await state.clear()

    await message.answer(
        "❌ Создание объявления отменено",
        reply_markup=main_keyboard
    )

# =========================================
# PUBLISH
# =========================================

@dp.message(
    AdForm.photos,
    F.text == "✅ Опубликовать"
)
async def publish_post(
    message: Message,
    state: FSMContext
):

    data = await state.get_data()

    photos = data.get(
        "photos",
        []
    )

    if len(photos) == 0:

        await message.answer(
            "❌ Добавьте хотя бы 1 фото"
        )

        return

    action = data["action"]
    category = data["category"]

    username = message.from_user.username

    if username:
        contact = f"@{username}"
    else:
        contact = "Username отсутствует"

    hashtags = build_hashtags(
        action,
        category
    )

    ad = {
        "action": action,
        "category": category,
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
                InputMediaPhoto(
                    media=photo
                )
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

    await bot.send_message(
        chat_id=CHANNEL_ID,
        text=" ",
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
        created_at,
        last_bump,
        status
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        message.from_user.id,
        username,
        action,
        category,
        data["title"],
        data["description"],
        data.get("condition"),
        data.get("price"),
        None,
        data.get("exchange"),
        ",".join(photos),
        message_id,
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

# =========================================
# MY ADS KEYBOARD
# =========================================

def my_ads_keyboard(ads):

    keyboard = []

    keyboard.append([
        InlineKeyboardButton(
            text="🔄 Поднять все доступные",
            callback_data="bump_all"
        )
    ])

    for ad in ads:

        keyboard.append([
            InlineKeyboardButton(
                text=f"📦 {ad[1]}",
                callback_data=f"ad_{ad[0]}"
            )
        ])

    return InlineKeyboardMarkup(
        inline_keyboard=keyboard
    )

# =========================================
# MY ADS
# =========================================

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

    ads = cursor.fetchall()

    if not ads:

        await message.answer(
            "📭 У вас нет объявлений"
        )

        return

    await message.answer(
        "📂 Ваши объявления:",
        reply_markup=my_ads_keyboard(ads)
    )

# =========================================
# OPEN AD
# =========================================

@dp.callback_query(
    F.data.startswith("ad_")
)
async def open_ad(
    callback: CallbackQuery
):

    ad_id = int(
        callback.data.split("_")[1]
    )

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
                    text="✏️ Изменить цену",
                    callback_data=f"edit_{ad_id}"
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
        f"📦 Объявление ID {ad_id}",
        reply_markup=keyboard
    )

# =========================================
# CLOSE AD
# =========================================

@dp.callback_query(
    F.data.startswith("close_")
)
async def close_ad(
    callback: CallbackQuery
):

    ad_id = int(
        callback.data.split("_")[1]
    )

    cursor.execute("""
    SELECT message_id
    FROM ads
    WHERE id = ?
    """, (
        ad_id,
    ))

    ad = cursor.fetchone()

    if not ad:

        await callback.answer(
            "❌ Объявление не найдено",
            show_alert=True
        )

        return

    message_id = ad[0]

    try:

        await bot.delete_message(
            chat_id=CHANNEL_ID,
            message_id=message_id
        )

    except:
        pass

    cursor.execute("""
    UPDATE ads
    SET status = 'closed'
    WHERE id = ?
    """, (
        ad_id,
    ))

    conn.commit()

    await callback.message.edit_text(
        "❌ Объявление закрыто"
    )

# =========================================
# EDIT PRICE
# =========================================

@dp.callback_query(
    F.data.startswith("edit_")
)
async def edit_price(
    callback: CallbackQuery,
    state: FSMContext
):

    ad_id = int(
        callback.data.split("_")[1]
    )

    cursor.execute("""
    SELECT last_bump
    FROM ads
    WHERE id = ?
    """, (
        ad_id,
    ))

    ad = cursor.fetchone()

    if not ad:

        await callback.answer(
            "❌ Объявление не найдено",
            show_alert=True
        )

        return

    last_bump = ad[0]

    if (
        not is_admin(callback.from_user.id)
        and
        not check_cooldown(last_bump)
    ):

        await callback.answer(
            "⏳ Изменить цену пока нельзя",
            show_alert=True
        )

        return

    await state.update_data(
        editing_ad_id=ad_id
    )

    await callback.message.answer(
        "💰 Введите новую цену:"
    )

    await state.set_state(
        EditPrice.waiting_price
    )

# =========================================
# SAVE NEW PRICE
# =========================================

@dp.message(EditPrice.waiting_price)
async def save_new_price(
    message: Message,
    state: FSMContext
):

    new_price = message.text

    data = await state.get_data()

    ad_id = data["editing_ad_id"]

    cursor.execute("""
    SELECT *
    FROM ads
    WHERE id = ?
    """, (
        ad_id,
    ))

    ad = cursor.fetchone()

    if not ad:

        await message.answer(
            "❌ Объявление не найдено"
        )

        return

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
        "created_at",
        "last_bump",
        "status"
    ]

    ad = dict(zip(columns, ad))

    old_price = ad["price"]

    save_old_price = None

    try:

        old_int = int(
            "".join(
                filter(
                    str.isdigit,
                    old_price
                )
            )
        )

        new_int = int(
            "".join(
                filter(
                    str.isdigit,
                    new_price
                )
            )
        )

        if new_int < old_int:

            save_old_price = old_price

    except:
        pass

    try:

        await bot.delete_message(
            chat_id=CHANNEL_ID,
            message_id=ad["message_id"]
        )

    except:
        pass

    photos = ad["photos"].split(",")

    contact = (
        f"@{ad['username']}"
        if ad["username"]
        else "Username отсутствует"
    )

    hashtags = build_hashtags(
        ad["action"],
        ad["category"]
    )

    caption = build_caption({
        "action": ad["action"],
        "category": ad["category"],
        "title": ad["title"],
        "description": ad["description"],
        "condition": ad["condition"],
        "price": new_price,
        "old_price": save_old_price,
        "exchange": ad["exchange"],
        "contact": contact,
        "hashtags": hashtags
    })

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
                InputMediaPhoto(
                    media=photo
                )
            )

    sent_messages = await bot.send_media_group(
        chat_id=CHANNEL_ID,
        media=media
    )

    new_message_id = sent_messages[0].message_id

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

    await bot.send_message(
        chat_id=CHANNEL_ID,
        text=" ",
        reply_markup=keyboard
    )

    cursor.execute("""
    UPDATE ads
    SET
        price = ?,
        old_price = ?,
        message_id = ?,
        last_bump = ?
    WHERE id = ?
    """, (
        new_price,
        save_old_price,
        new_message_id,
        datetime.now().isoformat(),
        ad_id
    ))

    conn.commit()

    await message.answer(
        "✅ Цена обновлена",
        reply_markup=main_keyboard
    )

    await state.clear()

# =========================================
# BUMP
# =========================================

@dp.callback_query(
    F.data.startswith("bump_")
)
async def bump_ad(
    callback: CallbackQuery
):

    ad_id = int(
        callback.data.split("_")[1]
    )

    cursor.execute("""
    SELECT last_bump
    FROM ads
    WHERE id = ?
    """, (
        ad_id,
    ))

    ad = cursor.fetchone()

    if not ad:

        await callback.answer(
            "❌ Объявление не найдено",
            show_alert=True
        )

        return

    if (
        not is_admin(callback.from_user.id)
        and
        not check_cooldown(ad[0])
    ):

        await callback.answer(
            "⏳ Поднять объявление пока нельзя",
            show_alert=True
        )

        return

    cursor.execute("""
    UPDATE ads
    SET last_bump = ?
    WHERE id = ?
    """, (
        datetime.now().isoformat(),
        ad_id
    ))

    conn.commit()

    await callback.answer(
        "✅ Объявление поднято",
        show_alert=True
    )

# =========================================
# WEB SERVER
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
