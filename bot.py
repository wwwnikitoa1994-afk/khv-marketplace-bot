    import asyncio

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
    InputMediaPhoto
)

TOKEN = "8634367728:AAG_gKuluoogGD2km02bakEH35kjvr6nALU"
CHANNEL_ID = "@khv_marketplace"

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher(storage=MemoryStorage())


# ---------- KEYBOARDS ----------

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить объявление")]
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


# ---------- STATES ----------

class AdForm(StatesGroup):
    action = State()
    category = State()
    title = State()
    description = State()
    condition = State()
    price = State()
    exchange = State()
    photos = State()


# ---------- START ----------

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🛒 Добро пожаловать в KHV Marketplace",
        reply_markup=main_keyboard
    )


@dp.message(F.text == "➕ Добавить объявление")
async def create_ad(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "Выберите тип объявления:",
        reply_markup=action_keyboard
    )

    await state.set_state(AdForm.action)


# ---------- ACTION ----------

@dp.message(AdForm.action)
async def get_action(message: Message, state: FSMContext):
    await state.update_data(action=message.text)

    await message.answer(
        "Выберите категорию:",
        reply_markup=category_keyboard
    )

    await state.set_state(AdForm.category)


# ---------- CATEGORY ----------

@dp.message(AdForm.category)
async def get_category(message: Message, state: FSMContext):
    await state.update_data(category=message.text)

    await message.answer(
        "📌 Название товара:",
        reply_markup=ReplyKeyboardRemove()
    )

    await state.set_state(AdForm.title)


# ---------- TITLE ----------

@dp.message(AdForm.title)
async def get_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)

    await message.answer("📝 Описание товара:")

    await state.set_state(AdForm.description)


# ---------- DESCRIPTION ----------

@dp.message(AdForm.description)
async def get_description(message: Message, state: FSMContext):
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
        await message.answer(
            "📷 Отправьте от 1 до 15 фото.\n"
            "Когда закончите — напишите ГОТОВО"
        )

        await state.update_data(photos=[])

        await state.set_state(AdForm.photos)


# ---------- CONDITION ----------

@dp.message(AdForm.condition)
async def get_condition(message: Message, state: FSMContext):
    await state.update_data(condition=message.text)

    data = await state.get_data()

    action = data["action"]

    if action == "🟢 Продам":
        await message.answer("💰 Цена:")

        await state.set_state(AdForm.price)

    else:
        await message.answer("🔄 На что хотите обмен?")

        await state.set_state(AdForm.exchange)


# ---------- PRICE ----------

@dp.message(AdForm.price)
async def get_price(message: Message, state: FSMContext):
    await state.update_data(price=message.text)

    await message.answer(
        "📷 Отправьте от 1 до 15 фото.\n"
        "Когда закончите — напишите ГОТОВО"
    )

    await state.update_data(photos=[])

    await state.set_state(AdForm.photos)


# ---------- EXCHANGE ----------

@dp.message(AdForm.exchange)
async def get_exchange(message: Message, state: FSMContext):
    await state.update_data(exchange=message.text)

    await message.answer(
        "📷 Отправьте от 1 до 15 фото.\n"
        "Когда закончите — напишите ГОТОВО"
    )

    await state.update_data(photos=[])

    await state.set_state(AdForm.photos)


# ---------- PHOTOS ----------

@dp.message(AdForm.photos, F.photo)
async def get_photos(message: Message, state: FSMContext):
    data = await state.get_data()

    photos = data.get("photos", [])

    if len(photos) >= 15:
        await message.answer("❌ Максимум 15 фото")
        return

    photos.append(message.photo[-1].file_id)

    await state.update_data(photos=photos)

    await message.answer(
        f"✅ Фото добавлено ({len(photos)}/15)\n"
        "Отправьте ещё фото или напишите ГОТОВО"
    )


@dp.message(AdForm.photos, F.text.lower() == "готово")
async def publish_post(message: Message, state: FSMContext):
    data = await state.get_data()

    photos = data.get("photos", [])

    if len(photos) == 0:
        await message.answer("❌ Нужно минимум 1 фото")
        return

    action = data["action"]
    category = data["category"]
    title = data["title"]
    description = data["description"]

    username = message.from_user.username

    if username:
        contact = f"@{username}"
    else:
        contact = "Username отсутствует"

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

    caption = (
        f"{action.upper()} • {category}\n\n"
        f"📌 <b>{title}</b>\n\n"
        f"📝 {description}\n\n"
    )

    if "condition" in data:
        caption += f"{data['condition']}\n\n"

    if "price" in data:
        if "Куплю" in action:
            caption += f"💰 Бюджет: {data['price']}\n\n"
        else:
            caption += f"💰 Цена: {data['price']}\n\n"

    if "exchange" in data:
        caption += f"🔄 Интересует:\n{data['exchange']}\n\n"

    caption += (
        f"📩 {contact}\n\n"
        f"{hashtags}"
    )

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

    await bot.send_media_group(
        chat_id=CHANNEL_ID,
        media=media
    )

    await message.answer(
        "✅ Объявление опубликовано",
        reply_markup=main_keyboard
    )

    await state.clear()


# ---------- WEB ----------

async def healthcheck(request):
    return web.Response(text="Bot is running")


async def start_web_server():
    app = web.Application()

    app.router.add_get("/", healthcheck)

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", 10000)

    await site.start()


# ---------- MAIN ----------

async def main():
    await start_web_server()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
