import asyncio

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

TOKEN = "ТВОЙ_ТОКЕН"
CHANNEL_ID = "@khv_marketplace"

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher(storage=MemoryStorage())


class AdForm(StatesGroup):
    action = State()
    title = State()
    description = State()
    condition = State()
    price = State()
    photo = State()


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "🛒 Добро пожаловать в KHV Marketplace\n\n"
        "Что хотите сделать?\n\n"
        "🟢 Продам\n"
        "🔵 Куплю\n"
        "🟠 Обмен\n\n"
        "Напишите один из вариантов:"
    )

    await state.set_state(AdForm.action)


@dp.message(AdForm.action)
async def get_action(message: Message, state: FSMContext):
    await state.update_data(action=message.text)

    await message.answer("📌 Название товара:")

    await state.set_state(AdForm.title)


@dp.message(AdForm.title)
async def get_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)

    await message.answer("📝 Описание товара:")

    await state.set_state(AdForm.description)


@dp.message(AdForm.description)
async def get_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)

    await message.answer("📦 Состояние: Новое или Б/У")

    await state.set_state(AdForm.condition)


@dp.message(AdForm.condition)
async def get_condition(message: Message, state: FSMContext):
    await state.update_data(condition=message.text)

    await message.answer("💰 Цена:")

    await state.set_state(AdForm.price)


@dp.message(AdForm.price)
async def get_price(message: Message, state: FSMContext):
    await state.update_data(price=message.text)

    await message.answer("📷 Отправьте фото товара:")

    await state.set_state(AdForm.photo)


@dp.message(AdForm.photo, F.photo)
async def get_photo(message: Message, state: FSMContext):
    data = await state.get_data()

    action = data["action"]
    title = data["title"]
    description = data["description"]
    condition = data["condition"]
    price = data["price"]

    username = message.from_user.username

    if username:
        contact = f"@{username}"
    else:
        contact = "Username отсутствует"

    caption = (
        f"<b>{action.upper()}</b>\n\n"
        f"📌 <b>{title}</b>\n\n"
        f"📝 {description}\n\n"
        f"📦 Состояние: {condition}\n"
        f"💰 Цена: {price}\n\n"
        f"📩 Связь: {contact}"
    )

    photo = message.photo[-1].file_id

    await bot.send_photo(
        chat_id=CHANNEL_ID,
        photo=photo,
        caption=caption
    )

    await message.answer("✅ Объявление опубликовано!")

    await state.clear()


@dp.message(AdForm.photo)
async def no_photo(message: Message):
    await message.answer("❌ Нужно обязательно отправить фото товара")


async def healthcheck(request):
    return web.Response(text="Bot is running")


async def start_web_server():
    app = web.Application()

    app.router.add_get("/", healthcheck)

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", 10000)

    await site.start()


async def main():
    await start_web_server()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
