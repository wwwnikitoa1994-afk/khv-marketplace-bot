import asyncio
import os
import json
import asyncpg
import html
import sys
import logging
import collections
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage, StorageKey, StateType
from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError

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
# CONFIG & LOGGER
# =========================================

logger = logging.getLogger("KHV_Market_Bot")
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler("bot.log", maxBytes=5*1024*1024, backupCount=2, encoding="utf-8")
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(funcName)s - %(message)s')
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)
logger.addHandler(logging.StreamHandler(sys.stdout))

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.critical("КРИТИЧЕСКАЯ ОШИБКА: Переменная окружения BOT_TOKEN не задана!")
    sys.exit(1)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/dbname") 
CHANNEL_ID = "@khv_marketplace"
BOT_LINK = "https://t.me/khv_marketplace_bot"

ADMIN_IDS = [1095957868]
COOLDOWN_HOURS = 24  

photo_locks = collections.defaultdict(asyncio.Lock)
ad_locks = collections.defaultdict(asyncio.Lock)
db_pool = None 

# Кэш для защиты от спам-кликов по inline-кнопкам
click_cache = {}

ALLOWED_ACTIONS = ["🟢 Продам", "🔵 Куплю", "🟣 Отдам", "🟠 Обменяю"]
ALLOWED_CATEGORIES = [
    "📱 Техника", "🛋 Мебель", "👕 Одежда", "🎮 Развлечения", 
    "🚗 Авто", "🧸 Детское", "🛠 Инструменты", "📚 Разное"
]
ALLOWED_CONDITIONS = ["✨ Новое", "📦 Б/У"]

# =========================================
# PERSISTENT FSM STORAGE
# =========================================

class PostgresStorage(BaseStorage):
    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        state_str = state.state if hasattr(state, 'state') else state
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO fsm_states (user_id, state)
                VALUES ($1, $2)
                ON CONFLICT (user_id) 
                DO UPDATE SET state = EXCLUDED.state
            """, key.user_id, state_str)

    async def get_state(self, key: StorageKey) -> str | None:
        async with db_pool.acquire() as conn:
            return await conn.fetchval("SELECT state FROM fsm_states WHERE user_id = $1", key.user_id)

    async def set_data(self, key: StorageKey, data: dict) -> None:
        data_str = json.dumps(data, ensure_ascii=False)
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO fsm_states (user_id, data)
                VALUES ($1, $2::jsonb)
                ON CONFLICT (user_id) 
                DO UPDATE SET data = EXCLUDED.data
            """, key.user_id, data_str)

    async def get_data(self, key: StorageKey) -> dict:
        async with db_pool.acquire() as conn:
            data_str = await conn.fetchval("SELECT data::text FROM fsm_states WHERE user_id = $1", key.user_id)
            return json.loads(data_str) if data_str else {}

    async def clear(self, key: StorageKey) -> None:
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM fsm_states WHERE user_id = $1", key.user_id)

    async def close(self) -> None:
        pass

# =========================================
# BOT INITIALIZATION
# =========================================

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = PostgresStorage()
dp = Dispatcher(storage=storage)

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
    keyboard=[[KeyboardButton(text=i) for i in ALLOWED_ACTIONS[:2]], 
              [KeyboardButton(text=i) for i in ALLOWED_ACTIONS[2:]]],
    resize_keyboard=True
)

category_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=ALLOWED_CATEGORIES[0]), KeyboardButton(text=ALLOWED_CATEGORIES[1])],
        [KeyboardButton(text=ALLOWED_CATEGORIES[2]), KeyboardButton(text=ALLOWED_CATEGORIES[3])],
        [KeyboardButton(text=ALLOWED_CATEGORIES[4]), KeyboardButton(text=ALLOWED_CATEGORIES[5])],
        [KeyboardButton(text=ALLOWED_CATEGORIES[6]), KeyboardButton(text=ALLOWED_CATEGORIES[7])]
    ],
    resize_keyboard=True
)

condition_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=i) for i in ALLOWED_CONDITIONS]],
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
# HELPERS
# =========================================

def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_spamming(user_id):
    """Антифлуд: игнорируем нажатия чаще 1 раза в секунду"""
    now = datetime.now()
    if user_id in click_cache and (now - click_cache[user_id]).total_seconds() < 1.0:
        return True
    click_cache[user_id] = now
    return False

def get_cooldown_remaining(last_bump):
    try:
        if isinstance(last_bump, str):
            last_bump = datetime.fromisoformat(last_bump)
        last_bump = last_bump.replace(tzinfo=None) 
        remaining = (last_bump + timedelta(hours=COOLDOWN_HOURS)) - datetime.now()
        
        if remaining.total_seconds() >= 60:
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            return f"{hours}ч {minutes}м"
        return None
    except Exception as e:
        logger.error(f"Time parsing error: {e}")
        return None

def build_hashtags(action, category):
    hashtags = []
    if action:
        if "Продам" in action: hashtags.append("#продам")
        elif "Куплю" in action: hashtags.append("#куплю")
        elif "Отдам" in action: hashtags.append("#отдам")
        elif "Обменяю" in action: hashtags.append("#обменяю")

    if category:
        parts = category.split(maxsplit=1)
        category_tag = parts[1].lower() if len(parts) > 1 else "разное"
        hashtags.append(f"#{category_tag}")
            
    return " ".join(hashtags) if hashtags else "#разное"

def build_caption(ad):
    action_raw = str(ad.get('action', ''))
    category_raw = str(ad.get('category', ''))
    
    action_emoji = ""
    action_text = action_raw
    if " " in action_raw:
        action_emoji, action_text = action_raw.split(" ", 1)
        action_emoji += " "

    category_emoji = ""
    category_text = category_raw
    parts = category_raw.split(maxsplit=1)
    if len(parts) > 1:
        category_emoji, category_text = parts[0] + " ", parts[1].lower()

    title = html.escape(str(ad.get('title', '')))
    description = html.escape(str(ad.get('description', '')))
    condition = html.escape(str(ad.get('condition', '')))
    price = html.escape(str(ad.get('price', '')))
    old_price = html.escape(str(ad.get('old_price', ''))) if ad.get('old_price') else None
    exchange = html.escape(str(ad.get('exchange', '')))
    contact = html.escape(str(ad.get('contact', '')))
    hashtags = html.escape(str(ad.get('hashtags', '')))

    caption = f"{action_emoji}<b>{action_text.upper()}</b> • {category_emoji}<i>{category_text}</i>\n\n"
    caption += f"📌 <b><u>{title}</u></b>\n\n"
    caption += f"📝 {description}\n"
    
    if ad.get("condition") and condition.strip() and condition != "None":
        caption += f"📦 <i>Состояние:</i> <b>{condition}</b>\n"

    if ad.get("price") and price.strip() and price != "None":
        if old_price and old_price != "None" and "ПРОДАМ" in action_text.upper():
            caption += f"💰 <i>Цена:</i> <b><s>{old_price}</s> → {price}</b>\n"
        else:
            if "КУПЛЮ" in action_text.upper():
                caption += f"💰 <i>Бюджет:</i> <b>{price}</b>\n"
            else:
                caption += f"💰 <i>Цена:</i> <b>{price}</b>\n"

    if ad.get("exchange") and exchange.strip() and exchange != "None":
        caption += f"🔄 <i>Интересует:</i> <b>{exchange}</b>\n"

    caption += f"\n📩 <i>Контакт:</i> {contact}\n\n"
    caption += f"{hashtags}"
    
    return caption

async def safe_delete_message(chat_id, message_id):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение {message_id} в {chat_id}: {e}")

async def delete_old_album(message_ids_str):
    if message_ids_str:
        for msg_id in message_ids_str.split(","):
            if msg_id.strip():
                await safe_delete_message(CHANNEL_ID, int(msg_id))

async def with_retry(func, *args, retries=3, **kwargs):
    for attempt in range(retries):
        try:
            return await func(*args, **kwargs)
        except TelegramRetryAfter as e:
            logger.warning(f"FloodWait: ожидание {e.retry_after} сек.")
            await asyncio.sleep(e.retry_after)
        except TelegramAPIError as e:
            if attempt == retries - 1:
                logger.error(f"Telegram API Ошибка: {e}")
                raise e
            await asyncio.sleep(2)

# =========================================
# KEYBOARDS LOGIC
# =========================================

def get_my_ads_keyboard(ads, user_id):
    keyboard = []
    for ad in ads:
        remaining = None if is_admin(user_id) else get_cooldown_remaining(ad['last_bump'])
        icon = "⏳" if remaining else "✅"
        keyboard.append([InlineKeyboardButton(text=f"{icon} {ad['title']}", callback_data=f"ad_{ad['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_single_ad_keyboard(ad_id, last_bump, user_id):
    remaining_time = None if is_admin(user_id) else get_cooldown_remaining(last_bump)
    
    if remaining_time:
        bump_text = f"⏳ Поднять ({remaining_time})"
        edit_text = f"⏳ Изменить цену ({remaining_time})"
    else:
        bump_text = "🔄 Можно поднять сейчас"
        edit_text = "✏️ Изменить цену"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=bump_text, callback_data=f"bump_{ad_id}")],
        [InlineKeyboardButton(text=edit_text, callback_data=f"edit_{ad_id}")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data=f"close_{ad_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_ads")]
    ])
    return keyboard

# =========================================
# STATES & FSM
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
# HANDLERS: CREATE AD
# =========================================

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("🛒 Добро пожаловать в KHV Marketplace", reply_markup=main_keyboard)

@dp.message(F.text == "➕ Опубликовать объявление")
async def create_ad(message: Message, state: FSMContext):
    await state.clear()
    photo_locks.pop(message.from_user.id, None)  
    await message.answer("Выберите тип объявления:", reply_markup=action_keyboard)
    await state.set_state(AdForm.action)

@dp.message(F.text == "🚫 Отмена")
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    photo_locks.pop(message.from_user.id, None)  
    await message.answer("❌ Действие отменено", reply_markup=main_keyboard)

@dp.message(AdForm.action, F.text)
async def get_action(message: Message, state: FSMContext):
    if message.text not in ALLOWED_ACTIONS:
        return await message.answer("⚠️ Пожалуйста, выберите действие, используя кнопки на клавиатуре ниже.")

    await state.update_data(action=message.text)
    await message.answer("Выберите категорию:", reply_markup=category_keyboard)
    await state.set_state(AdForm.category)

@dp.message(AdForm.category, F.text)
async def get_category(message: Message, state: FSMContext):
    if message.text not in ALLOWED_CATEGORIES:
        return await message.answer("⚠️ Пожалуйста, выберите категорию, используя кнопки на клавиатуре ниже.")

    await state.update_data(category=message.text)
    await message.answer("📌 Название товара:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdForm.title)

@dp.message(AdForm.title, F.text)
async def get_title(message: Message, state: FSMContext):
    if len(message.text) > 100:
        return await message.answer("⚠️ Название слишком длинное. Пожалуйста, уложитесь в 100 символов:")
        
    await state.update_data(title=message.text)
    await message.answer("📝 Описание товара:")
    await state.set_state(AdForm.description)

@dp.message(AdForm.description, F.text)
async def get_description(message: Message, state: FSMContext):
    if len(message.text) > 700:
        return await message.answer("⚠️ Описание слишком длинное. Пожалуйста, сократите текст (максимум 700 символов):")

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
        await message.answer("📷 Отправьте от 1 до 10 фото", reply_markup=photo_keyboard)
        await state.set_state(AdForm.photos)

@dp.message(AdForm.condition, F.text)
async def get_condition(message: Message, state: FSMContext):
    if message.text not in ALLOWED_CONDITIONS:
        return await message.answer("⚠️ Пожалуйста, выберите состояние товара, используя кнопки ниже.")

    await state.update_data(condition=message.text)
    data = await state.get_data()
    action = data.get("action", "")

    if action == "🟢 Продам":
        await message.answer("💰 Цена:")
        await state.set_state(AdForm.price)
    else:
        await message.answer("🔄 На что хотите обмен?")
        await state.set_state(AdForm.exchange)

@dp.message(AdForm.price, F.text)
async def get_price(message: Message, state: FSMContext):
    if len(message.text) > 50:
        return await message.answer("⚠️ Текст цены слишком длинный. Укажите сумму кратко:")

    current_data = await state.get_data()
    photos = current_data.get("photos", [])
    await state.update_data(price=message.text, photos=photos)
    await message.answer("📷 Отправьте от 1 до 10 фото", reply_markup=photo_keyboard)
    await state.set_state(AdForm.photos)

@dp.message(AdForm.exchange, F.text)
async def get_exchange(message: Message, state: FSMContext):
    if len(message.text) > 100:
        return await message.answer("⚠️ Условия обмена слишком длинные (максимум 100 символов):")

    current_data = await state.get_data()
    photos = current_data.get("photos", [])
    await state.update_data(exchange=message.text, photos=photos)
    await message.answer("📷 Отправьте от 1 до 10 фото", reply_markup=photo_keyboard)
    await state.set_state(AdForm.photos)

@dp.message(AdForm.photos, F.photo)
async def get_photo(message: Message, state: FSMContext):
    user_id = message.from_user.id
    async with photo_locks[user_id]:  
        data = await state.get_data()
        photos = data.get("photos", [])
        if len(photos) >= 10:
            return await message.answer("❌ Максимум 10 фото. Лишние проигнорированы.")
        photos.append(message.photo[-1].file_id)
        await state.update_data(photos=photos)

@dp.message(AdForm.photos, F.text == "✅ Опубликовать")
async def publish_post(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    if not photos:
        return await message.answer("❌ Добавьте хотя бы 1 фото перед публикацией.")

    action = data.get("action", "Разное")
    category = data.get("category", "Разное")
    username = message.from_user.username
    contact = f"@{username}" if username else "Username отсутствует"
    hashtags = build_hashtags(action, category)

    ad = {
        "action": action, "category": category, "title": data.get("title", ""),
        "description": data.get("description", ""), "condition": data.get("condition"),
        "price": data.get("price"), "old_price": None, "exchange": data.get("exchange"),
        "contact": contact, "hashtags": hashtags
    }

    caption = build_caption(ad)
    media = [InputMediaPhoto(media=photo, caption=caption if i == 0 else "") for i, photo in enumerate(photos)]

    msg_ids = []
    try:
        sent_messages = await with_retry(bot.send_media_group, chat_id=CHANNEL_ID, media=media)
        msg_ids = [str(m.message_id) for m in sent_messages]

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="➕ Подать своё объявление", url=BOT_LINK)
        ]])
        btn_msg = await with_retry(bot.send_message, chat_id=CHANNEL_ID, text="🛒 KHV Marketplace", reply_markup=keyboard, disable_web_page_preview=True)
        msg_ids.append(str(btn_msg.message_id))

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                INSERT INTO ads (user_id, username, action, category, title, description, condition, price, old_price, exchange, photos, message_ids, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """, 
                    message.from_user.id, username, action, category, ad["title"], ad["description"],
                    ad["condition"], ad["price"], None, ad["exchange"], ",".join(photos),
                    ",".join(msg_ids), "active"
                )

        await message.answer("✅ Объявление опубликовано", reply_markup=main_keyboard)
        await state.clear()
        photo_locks.pop(message.from_user.id, None)  
        logger.info(f"Объявление опубликовано: {ad['title']} (User: {message.from_user.id})")

    except Exception as e:
        await delete_old_album(",".join(msg_ids)) 
        await message.answer("❌ Ошибка публикации объявления. Попробуйте снова.")
        logger.error(f"Publish error: {e}")

# =========================================
# HANDLERS: EDIT PRICE
# =========================================

@dp.message(EditPrice.waiting_price, F.text)
async def save_new_price(message: Message, state: FSMContext):
    if len(message.text) > 50:
        return await message.answer("⚠️ Текст цены слишком длинный. Укажите сумму кратко:")

    new_price = message.text
    data = await state.get_data()
    ad_id = data.get("editing_ad_id")

    lock = ad_locks[ad_id]
    if lock.locked():
        return await message.answer("⏳ Применяем прошлые изменения, подождите...")

    async with lock:
        try:
            async with db_pool.acquire() as conn:
                ad_row = await conn.fetchrow("SELECT * FROM ads WHERE id = $1", ad_id)
                
            if not ad_row:
                await state.clear()
                return await message.answer("❌ Объявление не найдено")

            ad = dict(ad_row)

            if ad['user_id'] != message.from_user.id and not is_admin(message.from_user.id):
                await state.clear()
                return await message.answer("❌ У вас нет прав на изменение этого объявления")

            old_price = ad["price"]
            save_old_price = None
            try:
                old_digits = "".join(filter(str.isdigit, str(old_price)))
                new_digits = "".join(filter(str.isdigit, str(new_price)))
                if old_digits and new_digits and int(new_digits) < int(old_digits):
                    save_old_price = old_price
            except Exception:
                pass

            photos = ad["photos"].split(",") if ad["photos"] else []
            username = ad["username"]
            contact = f"@{username}" if username else "Username отсутствует"
            hashtags = build_hashtags(ad["action"], ad["category"])

            caption = build_caption({
                "action": ad["action"], "category": ad["category"], "title": ad["title"],
                "description": ad["description"], "condition": ad["condition"], "price": new_price,
                "old_price": save_old_price, "exchange": ad["exchange"], "contact": contact, "hashtags": hashtags
            })
            media = [InputMediaPhoto(media=photo, caption=caption if i == 0 else "") for i, photo in enumerate(photos)]

            msg_ids = []
            
            sent_messages = await with_retry(bot.send_media_group, chat_id=CHANNEL_ID, media=media)
            msg_ids = [str(m.message_id) for m in sent_messages]

            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="➕ Подать своё объявление", url=BOT_LINK)
            ]])
            btn_msg = await with_retry(bot.send_message, chat_id=CHANNEL_ID, text="🛒 KHV Marketplace", reply_markup=keyboard, disable_web_page_preview=True)
            msg_ids.append(str(btn_msg.message_id))

            old_message_ids = ad["message_ids"]
            async with db_pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("UPDATE ads SET price = $1, old_price = $2, message_ids = $3, last_bump = CURRENT_TIMESTAMP WHERE id = $4", 
                                       new_price, save_old_price, ",".join(msg_ids), ad_id)
                                       
            await delete_old_album(old_message_ids)
            await message.answer("✅ Цена обновлена", reply_markup=main_keyboard)
            await state.clear()
            logger.info(f"Цена изменена для ID {ad_id}: {save_old_price} -> {new_price}")
        except Exception as e:
            await delete_old_album(",".join(msg_ids)) 
            await message.answer("❌ Произошла ошибка при обновлении цены.")
            logger.error(f"Edit price error for ID {ad_id}: {e}")
        finally:
            ad_locks.pop(ad_id, None)

# =========================================
# INTERFACE
# =========================================

@dp.message(F.text == "📂 Мои объявления")
async def my_ads(message: Message):
    async with db_pool.acquire() as conn:
        ads = await conn.fetch("SELECT id, title, last_bump FROM ads WHERE user_id = $1 ORDER BY id DESC", message.from_user.id)
        
    if not ads:
        return await message.answer("📭 У вас нет активных объявлений.")
    await message.answer("📂 Ваши объявления:", reply_markup=get_my_ads_keyboard(ads, message.from_user.id))

@dp.callback_query(F.data.startswith("ad_"))
async def open_ad(callback: CallbackQuery):
    if is_spamming(callback.from_user.id): return await callback.answer()

    ad_id = int(callback.data.split("_")[1])
    async with db_pool.acquire() as conn:
        ad = await conn.fetchrow("SELECT title, last_bump, user_id FROM ads WHERE id = $1", ad_id)
        
    if not ad:
        return await callback.answer("❌ Объявление не найдено", show_alert=True)

    if ad['user_id'] != callback.from_user.id and not is_admin(callback.from_user.id):
        return await callback.answer("❌ У вас нет прав на просмотр этого объявления", show_alert=True)

    keyboard = get_single_ad_keyboard(ad_id, ad['last_bump'], callback.from_user.id)
    header_text = f"📦 Управление:\n<b>{html.escape(ad['title'])}</b>"
    await callback.message.edit_text(header_text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "back_ads")
async def back_ads(callback: CallbackQuery):
    if is_spamming(callback.from_user.id): return await callback.answer()

    async with db_pool.acquire() as conn:
        ads = await conn.fetch("SELECT id, title, last_bump FROM ads WHERE user_id = $1 ORDER BY id DESC", callback.from_user.id)
        
    if not ads:
        return await callback.message.edit_text("📭 У вас нет активных объявлений.")
    await callback.message.edit_text("📂 Ваши объявления:", reply_markup=get_my_ads_keyboard(ads, callback.from_user.id))
    await callback.answer()

# =========================================
# MANAGEMENT: CLOSE & SINGLE BUMP
# =========================================

@dp.callback_query(F.data.regexp(r"^close_\d+$"))
async def close_ad(callback: CallbackQuery):
    if is_spamming(callback.from_user.id): return await callback.answer()

    ad_id = int(callback.data.split("_")[1])
    async with db_pool.acquire() as conn:
        ad = await conn.fetchrow("SELECT title, user_id FROM ads WHERE id = $1", ad_id)

    if not ad:
        return await callback.answer("❌ Объявление не найдено", show_alert=True)

    if ad['user_id'] != callback.from_user.id and not is_admin(callback.from_user.id):
        return await callback.answer("❌ У вас нет прав на закрытие этого объявления", show_alert=True)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_close_{ad_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_close_{ad_id}")
    ]])
    header_text = f"📦 Управление:\n<b>{html.escape(ad['title'])}</b>\n\n❓ Вы уверены, что хотите закрыть объявление?"
    await callback.message.edit_text(header_text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_close_"))
async def confirm_close_ad(callback: CallbackQuery):
    ad_id = int(callback.data.split("_")[2])
    
    lock = ad_locks[ad_id]
    if lock.locked():
        return await callback.answer("⏳ Операция выполняется...", show_alert=False)
        
    await callback.answer("Удаление...", show_alert=False)
        
    async with lock:
        try:
            async with db_pool.acquire() as conn:
                ad = await conn.fetchrow("SELECT message_ids, user_id FROM ads WHERE id = $1", ad_id)
                
            if not ad:
                return await callback.message.edit_text("❌ Объявление не найдено")

            if ad['user_id'] != callback.from_user.id and not is_admin(callback.from_user.id):
                return await callback.message.edit_text("❌ У вас нет прав на удаление этого объявления")
                
            async with db_pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("DELETE FROM ads WHERE id = $1", ad_id)
            await delete_old_album(ad['message_ids'])
            logger.info(f"Объявление {ad_id} закрыто пользователем {callback.from_user.id}")

            async with db_pool.acquire() as conn:
                ads = await conn.fetch("SELECT id, title, last_bump FROM ads WHERE user_id = $1 ORDER BY id DESC", callback.from_user.id)
                        
            if not ads:
                return await callback.message.edit_text("📭 У вас нет активных объявлений.")
            await callback.message.edit_text("📂 Ваши объявления:", reply_markup=get_my_ads_keyboard(ads, callback.from_user.id))
        except Exception as e:
            logger.error(f"Delete Error for ad {ad_id}: {e}")
            return await callback.message.edit_text("❌ Ошибка при удалении")
        finally:
            ad_locks.pop(ad_id, None)

@dp.callback_query(F.data.startswith("cancel_close_"))
async def cancel_close_ad(callback: CallbackQuery):
    if is_spamming(callback.from_user.id): return await callback.answer()

    ad_id = int(callback.data.split("_")[2])
    async with db_pool.acquire() as conn:
        ad = await conn.fetchrow("SELECT title, last_bump, user_id FROM ads WHERE id = $1", ad_id)
        
    if not ad:
        return await callback.answer("❌ Объявление не найдено", show_alert=True)

    if ad['user_id'] != callback.from_user.id and not is_admin(callback.from_user.id):
        return await callback.answer("❌ Доступ ограничен", show_alert=True)

    keyboard = get_single_ad_keyboard(ad_id, ad['last_bump'], callback.from_user.id)
    header_text = f"📦 Управление:\n<b>{html.escape(ad['title'])}</b>"
    await callback.message.edit_text(header_text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_"))
async def edit_price_button(callback: CallbackQuery, state: FSMContext):
    if is_spamming(callback.from_user.id): return await callback.answer()

    ad_id = int(callback.data.split("_")[1])
    async with db_pool.acquire() as conn:
        ad = await conn.fetchrow("SELECT last_bump, user_id FROM ads WHERE id = $1", ad_id)
        
    if not ad:
        return await callback.answer("❌ Объявление не найдено", show_alert=True)

    if ad['user_id'] != callback.from_user.id and not is_admin(callback.from_user.id):
        return await callback.answer("❌ У вас нет прав на редактирование", show_alert=True)

    if not is_admin(callback.from_user.id):
        remaining_time = get_cooldown_remaining(ad['last_bump'])
        if remaining_time:
            return await callback.answer(f"⏳ Изменить цену нельзя.\nБудет доступно через: {remaining_time}", show_alert=True)
            
    await state.update_data(editing_ad_id=ad_id)
    await callback.message.answer("💰 Введите новую цену (кратко):")
    await state.set_state(EditPrice.waiting_price)
    await callback.answer()

@dp.callback_query(F.data.startswith("bump_"))
async def bump_ad(callback: CallbackQuery):
    if is_spamming(callback.from_user.id): return await callback.answer()

    ad_id = int(callback.data.split("_")[1])
    lock = ad_locks[ad_id]
    
    if lock.locked():
        return await callback.answer("⏳ Операция уже выполняется...", show_alert=False)

    # Моментальный ответ на Callback для обхода таймаута в 10 секунд
    await callback.answer("⏳ Обновляем объявление...", show_alert=False)

    async with lock:
        try:
            async with db_pool.acquire() as conn:
                ad_row = await conn.fetchrow("SELECT * FROM ads WHERE id = $1", ad_id)
                
            if not ad_row:
                return await callback.message.edit_text("❌ Объявление не найдено")

            ad = dict(ad_row)

            if ad['user_id'] != callback.from_user.id and not is_admin(callback.from_user.id):
                return await callback.message.edit_text("❌ Доступ запрещен")

            if not is_admin(callback.from_user.id):
                remaining_time = get_cooldown_remaining(ad["last_bump"])
                if remaining_time:
                    return await callback.message.answer(f"⏳ Поднять объявление нельзя. Доступно через: {remaining_time}")

            photos = ad["photos"].split(",") if ad["photos"] else []
            username = ad["username"]
            contact = f"@{username}" if username else "Username отсутствует"
            hashtags = build_hashtags(ad["action"], ad["category"])

            caption = build_caption({
                "action": ad["action"], "category": ad["category"], "title": ad["title"],
                "description": ad["description"], "condition": ad["condition"], "price": ad["price"],
                "old_price": ad["old_price"], "exchange": ad["exchange"], "contact": contact, "hashtags": hashtags
            })
            media = [InputMediaPhoto(media=photo, caption=caption if i == 0 else "") for i, photo in enumerate(photos)]

            msg_ids = []
            sent_messages = await with_retry(bot.send_media_group, chat_id=CHANNEL_ID, media=media)
            msg_ids = [str(m.message_id) for m in sent_messages]

            button = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="➕ Подать своё объявление", url=BOT_LINK)
            ]])
            btn_msg = await with_retry(bot.send_message, chat_id=CHANNEL_ID, text="🛒 KHV Marketplace", reply_markup=button)
            msg_ids.append(str(btn_msg.message_id))

            old_message_ids = ad["message_ids"]
            async with db_pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("UPDATE ads SET message_ids = $1, last_bump = CURRENT_TIMESTAMP WHERE id = $2", 
                                       ",".join(msg_ids), ad_id)

            await delete_old_album(old_message_ids)

            # Обновление шапки с текущим временем, чтобы избежать ошибки MessageNotModified
            now_str = datetime.now().strftime("%H:%M:%S")
            header_text = f"📦 Управление:\n<b>{html.escape(ad['title'])}</b>\n\n🔄 <i>Обновлено: {now_str}</i>"
            new_keyboard = get_single_ad_keyboard(ad_id, datetime.now(), callback.from_user.id)
            
            try:
                await callback.message.edit_text(header_text, reply_markup=new_keyboard)
            except TelegramAPIError:
                pass 
                
            logger.info(f"Объявление ID {ad_id} поднято")
        except Exception as e:
            await delete_old_album(",".join(msg_ids)) 
            await callback.message.answer("❌ Ошибка при поднятии объявления.")
            logger.error(f"Bump error for ID {ad_id}: {e}")
        finally:
            ad_locks.pop(ad_id, None)

# =========================================
# GLOBAL FALLBACK
# =========================================

# Должен быть строго в самом конце файла, чтобы ловить только "мусор"
@dp.message(AdForm.action)
@dp.message(AdForm.category)
@dp.message(AdForm.title)
@dp.message(AdForm.description)
@dp.message(AdForm.condition)
@dp.message(AdForm.price)
@dp.message(AdForm.exchange)
@dp.message(EditPrice.waiting_price)
async def handle_invalid_content(message: Message):
    await message.answer("⚠️ Ожидается текстовое сообщение. Пожалуйста, отправьте текст (или воспользуйтесь кнопками). Для отмены нажмите «🚫 Отмена».")


# =========================================
# WEB SERVER & INITIALIZATION
# =========================================

async def healthcheck(request):
    try:
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return web.Response(text="Bot & DB are running", status=200)
    except Exception as e:
        logger.error(f"Healthcheck failed (DB is down): {e}")
        return web.Response(text="Database connection failed", status=500)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 10000)))
    await site.start()

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS ads (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
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
            message_ids TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            last_bump TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            status TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ads_user_id ON ads(user_id);
        CREATE INDEX IF NOT EXISTS idx_ads_last_bump ON ads(last_bump);
        
        CREATE TABLE IF NOT EXISTS fsm_states (
            user_id BIGINT PRIMARY KEY,
            state TEXT,
            data JSONB DEFAULT '{}'::jsonb
        );
        """)

async def on_shutdown(dispatcher: Dispatcher):
    logger.info("Выполняем graceful shutdown...")
    if bot.session:
        await bot.session.close()
    if db_pool:
        await db_pool.close()

async def main():
    logger.info("Запуск бота...")
    await init_db()
    dp.shutdown.register(on_shutdown)
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
