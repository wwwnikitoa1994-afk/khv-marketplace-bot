import asyncio
import os
import json
import asyncpg
from datetime import datetime, timedelta
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage, StorageKey, StateType

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

TOKEN = os.getenv("BOT_TOKEN", "8634367728:AAG_gKuluoogGD2km02bakEH35kjvr6nALU")
# Обязательно укажите свой URL базы данных в переменных окружения на Render
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/dbname") 
CHANNEL_ID = "@khv_marketplace"
BOT_LINK = "https://t.me/khv_marketplace_bot"

ADMIN_IDS = [1095957868]
COOLDOWN_HOURS = 24  # Ограничение поднятия — 24 часа

# Замки для предотвращения гонки данных при загрузке фото (db_lock убран, так как asyncpg сам управляет пулом)
photo_locks = {}  
db_pool = None # Глобальный пул соединений базы данных

# =========================================
# PERSISTENT FSM STORAGE (POSTGRESQL)
# =========================================

class PostgresStorage(BaseStorage):
    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        state_str = state.state if hasattr(state, 'state') else state
        async with db_pool.acquire() as conn:
            exists = await conn.fetchval("SELECT 1 FROM fsm_states WHERE user_id = $1", key.user_id)
            if exists:
                await conn.execute("UPDATE fsm_states SET state = $1 WHERE user_id = $2", state_str, key.user_id)
            else:
                await conn.execute("INSERT INTO fsm_states (user_id, state, data) VALUES ($1, $2, $3)", key.user_id, state_str, '{}')

    async def get_state(self, key: StorageKey) -> str | None:
        async with db_pool.acquire() as conn:
            state = await conn.fetchval("SELECT state FROM fsm_states WHERE user_id = $1", key.user_id)
            return state

    async def set_data(self, key: StorageKey, data: dict) -> None:
        data_str = json.dumps(data, ensure_ascii=False)
        async with db_pool.acquire() as conn:
            exists = await conn.fetchval("SELECT 1 FROM fsm_states WHERE user_id = $1", key.user_id)
            if exists:
                await conn.execute("UPDATE fsm_states SET data = $1 WHERE user_id = $2", data_str, key.user_id)
            else:
                await conn.execute("INSERT INTO fsm_states (user_id, state, data) VALUES ($1, $2, $3)", key.user_id, None, data_str)

    async def get_data(self, key: StorageKey) -> dict:
        async with db_pool.acquire() as conn:
            data_str = await conn.fetchval("SELECT data FROM fsm_states WHERE user_id = $1", key.user_id)
            return json.loads(data_str) if data_str else {}

    async def clear(self, key: StorageKey) -> None:
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE fsm_states SET state = NULL, data = '{}' WHERE user_id = $1", key.user_id)

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

def get_cooldown_remaining(last_bump):
    try:
        last_bump_dt = datetime.fromisoformat(last_bump)
        remaining = (last_bump_dt + timedelta(hours=COOLDOWN_HOURS)) - datetime.now()
        if remaining.total_seconds() > 0:
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            return f"{hours}ч {minutes}м"
        return None
    except Exception:
        return None

def build_hashtags(action, category):
    hashtags = []
    if action:
        if "Продам" in action: hashtags.append("#продам")
        elif "Куплю" in action: hashtags.append("#куплю")
        elif "Отдам" in action: hashtags.append("#отдам")
        elif "Обменяю" in action: hashtags.append("#обменяю")

    if category:
        try:
            category_tag = category.split(" ")[1].lower()
            hashtags.append(f"#{category_tag}")
        except Exception:
            hashtags.append("#разное")
            
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
    try:
        if " " in category_raw:
            category_emoji, category_text = category_raw.split(" ", 1)
            category_emoji += " "
            category_text = category_text.lower()
    except Exception:
        pass

    caption = f"{action_emoji}<b>{action_text.upper()}</b> • {category_emoji}<i>{category_text}</i>\n\n"
    caption += f"📌 <b><u>{ad.get('title', '')}</u></b>\n\n"
    caption += f"📝 {ad.get('description', '')}\n"
    
    if ad.get("condition") and str(ad['condition']).strip() and str(ad['condition']) != "None":
        caption += f"📦 <i>Состояние:</i> <b>{ad['condition']}</b>\n"

    if ad.get("price") and str(ad['price']).strip() and str(ad['price']) != "None":
        if ad.get("old_price") and str(ad['old_price']) != "None" and "ПРОДАМ" in action_text.upper():
            caption += f"💰 <i>Цена:</i> <b><s>{ad['old_price']}</s> → {ad['price']}</b>\n"
        else:
            if "КУПЛЮ" in action_text.upper():
                caption += f"💰 <i>Бюджет:</i> <b>{ad['price']}</b>\n"
            else:
                caption += f"💰 <i>Цена:</i> <b>{ad['price']}</b>\n"

    if ad.get("exchange") and str(ad['exchange']).strip() and str(ad['exchange']) != "None":
        caption += f"🔄 <i>Интересует:</i> <b>{ad['exchange']}</b>\n"

    caption += f"\n📩 <i>Контакт:</i> {ad.get('contact', '')}\n\n"
    caption += f"{ad.get('hashtags', '')}"
    
    return caption

async def safe_delete_message(chat_id, message_id):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        print(f"Ошибка удаления сообщения {message_id}: {e}")

async def delete_old_album(message_ids_str):
    if message_ids_str:
        for msg_id in message_ids_str.split(","):
            if msg_id.strip():
                await safe_delete_message(CHANNEL_ID, int(msg_id))

# =========================================
# KEYBOARDS LOGIC
# =========================================

def get_my_ads_keyboard(ads):
    keyboard = []
    if ads:
        keyboard.append([InlineKeyboardButton(text="🔄 Поднять все доступные", callback_data="bump_all")])
    for ad in ads:
        keyboard.append([InlineKeyboardButton(text=f"📦 {ad['title']}", callback_data=f"ad_{ad['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_single_ad_keyboard(ad_id, last_bump, user_id):
    remaining_time = None if is_admin(user_id) else get_cooldown_remaining(last_bump)
    if remaining_time:
        bump_text = f"⏳ Поднять ({remaining_time})"
        edit_text = f"⏳ Изменить цену ({remaining_time})"
    else:
        bump_text = "🔄 Поднять"
        edit_text = "✏️ Изменить цену"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=bump_text, callback_data=f"bump_{ad_id}")],
        [InlineKeyboardButton(text=edit_text, callback_data=f"edit_{ad_id}")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data=f"close_{ad_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_ads")]
    ])
    return keyboard

# =========================================
# HANDLERS
# =========================================

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("🛒 Добро пожаловать в KHV Marketplace", reply_markup=main_keyboard)

@dp.message(F.text == "➕ Опубликовать объявление")
async def create_ad(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Выберите тип объявления:", reply_markup=action_keyboard)
    await state.set_state(AdForm.action)

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

@dp.message(F.text == "🚫 Отмена")
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Создание объявления отменено", reply_markup=main_keyboard)

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
    current_data = await state.get_data()
    photos = current_data.get("photos", [])
    await state.update_data(price=message.text, photos=photos)
    await message.answer("📷 Отправьте от 1 до 15 фото", reply_markup=photo_keyboard)
    await state.set_state(AdForm.photos)

@dp.message(AdForm.exchange)
async def get_exchange(message: Message, state: FSMContext):
    current_data = await state.get_data()
    photos = current_data.get("photos", [])
    await state.update_data(exchange=message.text, photos=photos)
    await message.answer("📷 Отправьте от 1 до 15 фото", reply_markup=photo_keyboard)
    await state.set_state(AdForm.photos)

@dp.message(AdForm.photos, F.photo)
async def get_photo(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in photo_locks:
        photo_locks[user_id] = asyncio.Lock()
        
    async with photo_locks[user_id]:  # Защита от race condition при одновременном приеме медиагруппы
        data = await state.get_data()
        photos = data.get("photos", [])
        if len(photos) >= 15:
            await message.answer("❌ Максимум 15 фото")
            return
        photos.append(message.photo[-1].file_id)
        await state.update_data(photos=photos)

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
        "contact": contact, "hashtags": hashtags
    }

    caption = build_caption(ad)
    media = [InputMediaPhoto(media=photo, caption=caption if i == 0 else "") for i, photo in enumerate(photos)]

    try:
        sent_messages = await bot.send_media_group(chat_id=CHANNEL_ID, media=media)
        msg_ids = [str(m.message_id) for m in sent_messages]

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="➕ Подать своё объявление", url=BOT_LINK)
        ]])
        btn_msg = await bot.send_message(chat_id=CHANNEL_ID, text="🛒 KHV Marketplace", reply_markup=keyboard, disable_web_page_preview=True)
        msg_ids.append(str(btn_msg.message_id))

        async with db_pool.acquire() as conn:
            await conn.execute("""
            INSERT INTO ads (user_id, username, action, category, title, description, condition, price, old_price, exchange, photos, message_ids, created_at, last_bump, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            """, 
                message.from_user.id, username, action, category, ad["title"], ad["description"],
                ad["condition"], ad["price"], None, ad["exchange"], ",".join(photos),
                ",".join(msg_ids), datetime.now().isoformat(), datetime.now().isoformat(), "active"
            )

        await message.answer("✅ Объявление опубликовано", reply_markup=main_keyboard)
        await state.clear()
    except Exception as e:
        await message.answer("❌ Ошибка публикации объявления. Попробуйте снова.")
        print(f"Publish error: {e}")

# =========================================
# INTERFACE & MASS BUMP
# =========================================

@dp.message(F.text == "📂 Мои объявления")
async def my_ads(message: Message):
    async with db_pool.acquire() as conn:
        ads = await conn.fetch("SELECT id, title, last_bump FROM ads WHERE user_id = $1 ORDER BY id DESC", message.from_user.id)
        
    if not ads:
        await message.answer("📭 У вас нет активных объявлений.")
        return
    await message.answer("📂 Ваши объявления:", reply_markup=get_my_ads_keyboard(ads))

@dp.callback_query(F.data.startswith("ad_"))
async def open_ad(callback: CallbackQuery):
    ad_id = int(callback.data.split("_")[1])
    async with db_pool.acquire() as conn:
        ad = await conn.fetchrow("SELECT last_bump FROM ads WHERE id = $1", ad_id)
        
    if not ad:
        await callback.answer("❌ Объявление не найдено", show_alert=True)
        return
    keyboard = get_single_ad_keyboard(ad_id, ad['last_bump'], callback.from_user.id)
    await callback.message.edit_text(f"📦 Управление объявлением ID {ad_id}", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "back_ads")
async def back_ads(callback: CallbackQuery):
    async with db_pool.acquire() as conn:
        ads = await conn.fetch("SELECT id, title, last_bump FROM ads WHERE user_id = $1 ORDER BY id DESC", callback.from_user.id)
        
    if not ads:
        await callback.message.edit_text("📭 У вас нет активных объявлений.")
        return
    await callback.message.edit_text("📂 Ваши объявления:", reply_markup=get_my_ads_keyboard(ads))
    await callback.answer()

@dp.callback_query(F.data == "bump_all")
async def bump_all_ads(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with db_pool.acquire() as conn:
        ad_rows = await conn.fetch("SELECT * FROM ads WHERE user_id = $1 ORDER BY id DESC", user_id)

    if not ad_rows:
        await callback.answer("📭 У вас нет активных объявлений.", show_alert=True)
        return

    bumped_count = 0
    waiting_reports = []

    for row in ad_rows:
        ad = dict(row)
        remaining_time = None if is_admin(user_id) else get_cooldown_remaining(ad["last_bump"])

        if remaining_time:
            waiting_reports.append(f"• \"{ad['title']}\" — осталось {remaining_time}")
        else:
            await delete_old_album(ad["message_ids"])

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

            try:
                sent_messages = await bot.send_media_group(chat_id=CHANNEL_ID, media=media)
                msg_ids = [str(m.message_id) for m in sent_messages]

                button = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="➕ Подать своё объявление", url=BOT_LINK)
                ]])
                btn_msg = await bot.send_message(chat_id=CHANNEL_ID, text="🛒 KHV Marketplace", reply_markup=button, disable_web_page_preview=True)
                msg_ids.append(str(btn_msg.message_id))

                async with db_pool.acquire() as conn:
                    await conn.execute("UPDATE ads SET message_ids = $1, last_bump = $2 WHERE id = $3", ",".join(msg_ids), datetime.now().isoformat(), ad["id"])
                
                bumped_count += 1
            except Exception as e:
                print(f"Mass bump error for ad {ad['id']}: {e}")

    alert_text = f"✅ Успешно поднято объявлений: {bumped_count}.\n\n" if bumped_count > 0 else "⏳ Ни одно объявление не поднято.\n\n"
    if waiting_reports:
        alert_text += "Оставшееся время до поднятия:\n" + "\n".join(waiting_reports)
    else:
        alert_text += "Все ваши объявления успешно обновлены!"

    async with db_pool.acquire() as conn:
        fresh_ads = await conn.fetch("SELECT id, title, last_bump FROM ads WHERE user_id = $1 ORDER BY id DESC", user_id)

    try:
        await callback.message.edit_text("📂 Ваши объявления:", reply_markup=get_my_ads_keyboard(fresh_ads))
    except Exception:
        pass

    await callback.answer(alert_text, show_alert=True)

# =========================================
# MANAGEMENT: CLOSE & EDIT PRICE & SINGLE BUMP
# =========================================

@dp.callback_query(F.data.regexp(r"^close_\d+$"))
async def close_ad(callback: CallbackQuery):
    ad_id = int(callback.data.split("_")[1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_close_{ad_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_close_{ad_id}")
    ]])
    await callback.message.edit_text("❓ Вы уверены, что хотите закрыть объявление?", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_close_"))
async def confirm_close_ad(callback: CallbackQuery):
    ad_id = int(callback.data.split("_")[2])
    async with db_pool.acquire() as conn:
        ad = await conn.fetchrow("SELECT message_ids FROM ads WHERE id = $1", ad_id)
        
    if not ad:
        await callback.answer("❌ Объявление не найдено", show_alert=True)
        return
        
    await delete_old_album(ad['message_ids'])
    
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM ads WHERE id = $1", ad_id)
        ads = await conn.fetch("SELECT id, title, last_bump FROM ads WHERE user_id = $1 ORDER BY id DESC", callback.from_user.id)
                
    if not ads:
        await callback.message.edit_text("📭 У вас нет активных объявлений.")
        return
    await callback.message.edit_text("📂 Ваши объявления:", reply_markup=get_my_ads_keyboard(ads))
    await callback.answer()

@dp.callback_query(F.data.startswith("cancel_close_"))
async def cancel_close_ad(callback: CallbackQuery):
    ad_id = int(callback.data.split("_")[2])
    async with db_pool.acquire() as conn:
        ad = await conn.fetchrow("SELECT last_bump FROM ads WHERE id = $1", ad_id)
        
    keyboard = get_single_ad_keyboard(ad_id, ad['last_bump'], callback.from_user.id)
    await callback.message.edit_text(f"📦 Управление объявлением ID {ad_id}", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_"))
async def edit_price(callback: CallbackQuery, state: FSMContext):
    ad_id = int(callback.data.split("_")[1])
    async with db_pool.acquire() as conn:
        ad = await conn.fetchrow("SELECT last_bump FROM ads WHERE id = $1", ad_id)
        
    if not ad:
        await callback.answer("❌ Объявление не найдено", show_alert=True)
        return
    if not is_admin(callback.from_user.id):
        remaining_time = get_cooldown_remaining(ad['last_bump'])
        if remaining_time:
            await callback.answer(f"⏳ Изменить цену нельзя.\nБудет доступно через: {remaining_time}", show_alert=True)
            return
            
    await state.update_data(editing_ad_id=ad_id)
    await callback.message.answer("💰 Введите новую цену:")
    await state.set_state(EditPrice.waiting_price)
    await callback.answer()

@dp.message(EditPrice.waiting_price)
async def save_new_price(message: Message, state: FSMContext):
    new_price = message.text
    data = await state.get_data()
    ad_id = data.get("editing_ad_id")

    async with db_pool.acquire() as conn:
        ad_row = await conn.fetchrow("SELECT * FROM ads WHERE id = $1", ad_id)
        
    if not ad_row:
        await message.answer("❌ Объявление не найдено")
        return

    ad = dict(ad_row)
    old_price = ad["price"]
    save_old_price = None
    try:
        old_digits = "".join(filter(str.isdigit, str(old_price)))
        new_digits = "".join(filter(str.isdigit, str(new_price)))
        if old_digits and new_digits and int(new_digits) < int(old_digits):
            save_old_price = old_price
    except Exception:
        pass

    await delete_old_album(ad["message_ids"])

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

    try:
        sent_messages = await bot.send_media_group(chat_id=CHANNEL_ID, media=media)
        msg_ids = [str(m.message_id) for m in sent_messages]

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="➕ Подать своё объявление", url=BOT_LINK)
        ]])
        btn_msg = await bot.send_message(chat_id=CHANNEL_ID, text="🛒 KHV Marketplace", reply_markup=keyboard, disable_web_page_preview=True)
        msg_ids.append(str(btn_msg.message_id))

        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE ads SET price = $1, old_price = $2, message_ids = $3, last_bump = $4 WHERE id = $5", 
                               new_price, save_old_price, ",".join(msg_ids), datetime.now().isoformat(), ad_id)
                               
        await message.answer("✅ Цена обновлена", reply_markup=main_keyboard)
        await state.clear()
    except Exception as e:
        await message.answer("❌ Произошла ошибка при обновлении цены.")
        print(f"Edit price error: {e}")

@dp.callback_query(F.data.startswith("bump_"))
async def bump_ad(callback: CallbackQuery):
    ad_id = int(callback.data.split("_")[1])
    async with db_pool.acquire() as conn:
        ad_row = await conn.fetchrow("SELECT * FROM ads WHERE id = $1", ad_id)
        
    if not ad_row:
        await callback.answer("❌ Объявление не найдено", show_alert=True)
        return

    ad = dict(ad_row)
    if not is_admin(callback.from_user.id):
        remaining_time = get_cooldown_remaining(ad["last_bump"])
        if remaining_time:
            await callback.answer(f"⏳ Поднять объявление нельзя.\nБудет доступно через: {remaining_time}", show_alert=True)
            return

    await delete_old_album(ad["message_ids"])

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

    try:
        sent_messages = await bot.send_media_group(chat_id=CHANNEL_ID, media=media)
        msg_ids = [str(m.message_id) for m in sent_messages]

        button = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="➕ Подать своё объявление", url=BOT_LINK)
        ]])
        btn_msg = await bot.send_message(chat_id=CHANNEL_ID, text="🛒 KHV Marketplace", reply_markup=button)
        msg_ids.append(str(btn_msg.message_id))

        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE ads SET message_ids = $1, last_bump = $2 WHERE id = $3", 
                               ",".join(msg_ids), datetime.now().isoformat(), ad_id)

        new_keyboard = get_single_ad_keyboard(ad_id, datetime.now().isoformat(), callback.from_user.id)
        await callback.message.edit_text(f"📦 Управление объявлением ID {ad_id}", reply_markup=new_keyboard)
        await callback.answer("✅ Объявление успешно поднято", show_alert=True)
    except Exception as e:
        await callback.answer("❌ Ошибка при поднятии объявления.", show_alert=True)
        print(f"Bump error: {e}")

# =========================================
# WEB SERVER & INITIALIZATION
# =========================================

async def healthcheck(request):
    return web.Response(text="Bot is running")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 10000)))
    await site.start()

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0)
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
            created_at TEXT,
            last_bump TEXT,
            status TEXT
        );
        """)
        
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS fsm_states (
            user_id BIGINT PRIMARY KEY,
            state TEXT,
            data TEXT
        );
        """)

async def main():
    await init_db()
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
