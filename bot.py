import os
import asyncio
import random
from datetime import datetime
from typing import Optional

import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

# ================== НАСТРОЙКИ ==================
API_TOKEN = os.getenv("API_TOKEN")  # токен берём из Render secrets
CHANNEL_ID = "-1002768607899"
ADMIN_ID = 8059166788
PHOTOS_FOLDER = "Photo"
VIDEOS_FOLDER = "Video"
DB_PATH = "database.db"
# ===============================================

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
awaiting_broadcast: dict[int, bool] = {}

# ----------------- БАЗА ДАННЫХ -----------------
CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 0,
    referrals INTEGER DEFAULT 0,
    inviter_id INTEGER,
    reg_date TEXT
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_USERS_SQL)
        await db.commit()

async def get_user(user_id: int) -> Optional[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, username, balance, referrals, inviter_id, reg_date FROM users WHERE user_id = ?", (user_id,))
        return await cur.fetchone()

async def add_user(user_id: int, username: Optional[str], inviter_id: Optional[int] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        if await cur.fetchone():
            return False

        reg_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            "INSERT INTO users (user_id, username, balance, referrals, inviter_id, reg_date) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, 10, 0, inviter_id, reg_date),
        )
        await db.commit()

        if inviter_id and inviter_id != user_id:
            cur = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (inviter_id,))
            if await cur.fetchone():
                await db.execute("UPDATE users SET balance = balance + 10, referrals = referrals + 1 WHERE user_id = ?", (inviter_id,))
                await db.commit()
                try:
                    await bot.send_message(inviter_id, f"🎉 Твой реферал @{username or 'без ника'} зарегистрировался — тебе +10💎!")
                except Exception:
                    pass
        return True

async def update_balance(user_id: int, delta: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
        await db.commit()

async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*), COALESCE(SUM(referrals),0) FROM users")
        total_users, total_referrals = await cur.fetchone()
        return total_users or 0, total_referrals or 0

# ----------------- МЕДИА -----------------
def random_media_from(folder: str) -> Optional[str]:
    path = os.path.abspath(folder)
    if not os.path.isdir(path):
        return None
    files = [os.path.join(path, f) for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
    return random.choice(files) if files else None

# ----------------- КНОПКИ -----------------
reply_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="🤝 Пригласить друга")],
        [KeyboardButton(text="📸 Фото за кристаллики"), KeyboardButton(text="🎥 Видео за кристаллики")],
    ],
    resize_keyboard=True,
)

def profile_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📸 Получить Фото (1💎)", callback_data="get_photo")],
            [InlineKeyboardButton(text="🎥 Получить Видео (3💎)", callback_data="get_video")],
        ]
    )

def after_media_kb(media_type: str):
    cost = 1 if media_type == "photo" else 3
    more_cd = "more_photo" if media_type == "photo" else "more_video"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Показать ещё (-{cost}💎)", callback_data=more_cd)],
            [InlineKeyboardButton(text="Меню", callback_data="menu")],
        ]
    )

# ----------------- ПРОФИЛЬ -----------------
async def send_profile(user_id: int, msg: types.Message):
    user = await get_user(user_id)
    text = (
        f"👤 Ник: @{user[1] or 'Без ника'}\n"
        f"👥 Рефералов: {user[3]}\n"
        f"💎 Внутренний баланс: {user[2]} кристалликов"
    )
    await msg.answer(text, reply_markup=profile_inline_kb())

# ----------------- ХЕНДЛЕРЫ -----------------
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    args = message.text.split()
    inviter = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    await add_user(message.from_user.id, message.from_user.username, inviter)
    await send_profile(message.from_user.id, message)
    await message.answer("👇 Выберите действие:", reply_markup=reply_kb)

@dp.message(F.text == "👤 Мой профиль")
async def profile(message: types.Message):
    await send_profile(message.from_user.id, message)

@dp.message(F.text == "🤝 Пригласить друга")
async def invite(message: types.Message):
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    await message.answer(f"🔗 Ваша ссылка для приглашения:\n{link}\n\nЗа каждого друга — +10💎!")

# ----------------- МЕДИА -----------------
async def send_random_media(user_id: int, media_type: str, msg: types.Message):
    cost = 1 if media_type == "photo" else 3
    folder = PHOTOS_FOLDER if media_type == "photo" else VIDEOS_FOLDER
    user = await get_user(user_id)

    if not user:
        await add_user(user_id, None)
        user = await get_user(user_id)

    if user[2] < cost:
        await msg.answer(f"⚠️ Недостаточно кристалликов ({cost}💎 нужно).")
        return

    file_path = random_media_from(folder)
    if not file_path:
        await msg.answer(f"⚠️ В папке {folder} нет файлов.")
        return

    await update_balance(user_id, -cost)

    try:
        if media_type == "photo":
            await msg.answer_photo(
                types.FSInputFile(file_path),
                caption="📸 Фото (скрытое)",
                reply_markup=after_media_kb(media_type),
                has_spoiler=True
            )
        else:
            await msg.answer_video(
                types.FSInputFile(file_path),
                caption="🎥 Видео (скрытое)",
                reply_markup=after_media_kb(media_type),
                has_spoiler=True
            )
    except Exception:
        await msg.answer("Ошибка при отправке файла.")
        await update_balance(user_id, +cost)

@dp.message(F.text == "📸 Фото за кристаллики")
async def photo_cmd(msg: types.Message):
    await send_random_media(msg.from_user.id, "photo", msg)

@dp.message(F.text == "🎥 Видео за кристаллики")
async def video_cmd(msg: types.Message):
    await send_random_media(msg.from_user.id, "video", msg)

@dp.callback_query(F.data.in_(["get_photo", "more_photo"]))
async def cb_photo(callback: types.CallbackQuery):
    await send_random_media(callback.from_user.id, "photo", callback.message)

@dp.callback_query(F.data.in_(["get_video", "more_video"]))
async def cb_video(callback: types.CallbackQuery):
    await send_random_media(callback.from_user.id, "video", callback.message)

@dp.callback_query(F.data == "menu")
async def cb_menu(callback: types.CallbackQuery):
    await send_profile(callback.from_user.id, callback.message)

# ----------------- АДМИН -----------------
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа.")
        return
    users, refs = await get_stats()
    await message.answer(f"⚙️ Админ-панель\n\n👥 Пользователей: {users}\n🔗 Всего рефералов: {refs}")

# ----------------- ЗАПУСК -----------------
async def main():
    print("✅ Бот запущен")
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
