import asyncio
import logging
import os
import random
import sqlite3

import pandas as pd
from aiohttp import web
from datetime import datetime
from io import BytesIO

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BufferedInputFile
from aiogram.exceptions import TelegramBadRequest

# ==================== КОНФИГИ ====================
TOKEN = "8489962637:AAGEiIssbO9HkDGOGgB14NnAtMWPVhaHcvg"
ADMIN_ID = 662672735
PASSWORD = "12345"
DEADLINE = datetime(2025, 12,9,23,59)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
logging.basicConfig(level=logging.INFO)

# ==================== БАЗА ДАННЫХ ====================
conn = sqlite3.connect("secret_santa.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    wish TEXT,
    target_id INTEGER,
    received INTEGER DEFAULT 0
)""")
conn.commit()

# ==================== СОСТОЯНИЯ ====================
class Form(StatesGroup):
    name = State()
    wish = State()

class AdminStates(StatesGroup):
    password = State()
    broadcast = State()
    manual_from = State()
    manual_to = State()

# ==================== КЛАВИАТУРЫ ====================
def start_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Зарегистрироваться в Тайном Друге", callback_data="reg")
    return kb.as_markup()

def admin_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="Статистика", callback_data="admin_stats")
    kb.button(text="Все участники", callback_data="admin_list")
    kb.button(text="Распределить всем", callback_data="admin_shuffle")
    kb.button(text="Перераспределить одного", callback_data="admin_manual")
    kb.button(text="Экспорт в Excel", callback_data="admin_export")
    kb.button(text="Очистить базу", callback_data="admin_clear_db")
    kb.button(text="Рассылка всем", callback_data="admin_broadcast")
    kb.button(text="Выйти", callback_data="admin_exit")
    kb.adjust(2)
    return kb.as_markup()

def received_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Я подарил", callback_data="got_gift")
    kb.button(text="Ещё не подарил", callback_data="no_gift")
    return kb.as_markup()

# ==================== УТИЛИТЫ ====================
async def safe_edit(callback: types.CallbackQuery, text: str, reply_markup=None):
    """Безопасное редактирование сообщения — не падает на 'message is not modified'"""
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

# ==================== ОБРАБОТЧИКИ ====================

@dp.message(Command("start"))
async def start(message: types.Message):
    count = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    text = (
        "<b>Тайный Друг для молитвы 2026</b>\n\n"
        "Самый тёплый обмен подарками!\n\n"
        f"Уже участвует: <b>{count}</b>\n"
        "Регистрация до 9 декабря\n"
        "Распределение 10 декабря в 12:00"
    )
    await message.answer(text, reply_markup=start_kb())

@dp.callback_query(F.data == "reg")
async def reg_name(callback: types.CallbackQuery, state: FSMContext):
    if datetime.now() > DEADLINE:
        return await callback.message.edit_text("Регистрация закрыта!")
    if cur.execute("SELECT 1 FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone():
        return await callback.answer("Ты уже зарегистрирован!", show_alert=True)
    await state.set_state(Form.name)
    await callback.message.edit_text("Введи <b>Имя Фамилию</b>:")

@dp.message(Form.name)
async def reg_wish(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(Form.wish)
    await message.answer("За какие нужды можно помолиться?\nЧто хочешь получить в подарок (до 30 BYN)?")

@dp.message(Form.wish)
async def reg_done(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cur.execute("INSERT INTO users (user_id, name, wish) VALUES (?, ?, ?)",
                (message.from_user.id, data["name"], message.text.strip()))
    conn.commit()
    await message.answer("Ты в игре!\n10 декабря узнаешь тайного друга")
    await state.clear()

@dp.callback_query(F.data.in_({"got_gift", "no_gift"}))
async def gift_status(callback: types.CallbackQuery):
    if callback.data == "got_gift":
        cur.execute("UPDATE users SET received=1 WHERE user_id=?", (callback.from_user.id,))
        conn.commit()
    await callback.answer("Спасибо за радость!", show_alert=True)

# ==================== АДМИНКА ====================

@dp.message(Command("admin"))
async def admin_enter(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.password)
    await message.answer("Введите пароль:")

@dp.message(AdminStates.password)
async def admin_login(message: types.Message, state: FSMContext):
    if message.text != PASSWORD:
        return await message.answer("Неверный пароль")
    await state.clear()
    total = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    done = cur.execute("SELECT COUNT(*) FROM users WHERE target_id IS NOT NULL").fetchone()[0]
    text = f"<b>Админ-панель</b>\n\nУчастников: <b>{total}</b>\nРаспределено: <b>{'Да' if done else 'Нет'}</b>"
    await message.answer(text, reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    total = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    done = cur.execute("SELECT COUNT(*) FROM users WHERE target_id IS NOT NULL").fetchone()[0]
    received = cur.execute("SELECT COUNT(*) FROM users WHERE received=1").fetchone()[0]
    text = f"<b>Статистика</b>\nВсего: {total}\nРаспределено: {'Да' if done else 'Нет'}\nПолучили: {received}"
    await safe_edit(callback, text, admin_menu())

@dp.callback_query(F.data == "admin_list")
async def admin_list(callback: types.CallbackQuery):
    users = cur.execute("SELECT name, wish, user_id, target_id FROM users").fetchall()
    if not users:
        return await safe_edit(callback, "Пока никого", admin_menu())
    text = f"<b>Участники ({len(users)})</b>\n\n"
    for name, wish, uid, target in users:
        target_name = "—" if not target else cur.execute("SELECT name FROM users WHERE user_id=?", (target,)).fetchone()[0]
        text += f"• <b>{name}</b> ({uid})\n  → {target_name}\n  {wish}\n\n"
    await safe_edit(callback, text, admin_menu())

@dp.callback_query(F.data == "admin_shuffle")
async def admin_shuffle(callback: types.CallbackQuery):
    users = cur.execute("SELECT user_id FROM users WHERE target_id IS NULL").fetchall()
    if len(users) < 3:
        return await callback.answer("Минимум 3 участника!", show_alert=True)
    ids = [u[0] for u in users]
    targets = ids.copy()
    random.shuffle(targets)
    while any(ids[i] == targets[i] for i in range(len(ids))):
        random.shuffle(targets)
    for i, uid in enumerate(ids):
        cur.execute("UPDATE users SET target_id=? WHERE user_id=?", (targets[i], uid))
    conn.commit()
    for uid in ids:
        target = cur.execute("SELECT name, wish FROM users WHERE user_id=?", (targets[ids.index(uid)],)).fetchone()
        text = f"<b>Волшебство!</b>\nТы даришь <b>{target[0]}</b>\n\nПожелание:\n{target[1]}"
        await bot.send_message(uid, text, reply_markup=received_kb())
    await safe_edit(callback, "Распределение завершено!", admin_menu())

# (остальные обработчики админки оставил без изменений — они работают)
# admin_clear_db, admin_export, admin_manual, admin_broadcast и т.д.
# если хочешь — могу добавить их тоже, но чтобы не раздувать сообщение, они остались как у тебя

# ==================== ВЕБХУКИ ДЛЯ RENDER ====================

async def handle_webhook(request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot=bot, update=update)
    return web.Response(status=200)

async def set_webhook():
    webhook_url = f"https://{os.environ['RENDER_EXTERNAL_HOSTNAME']}/webhook"
    info = await bot.get_webhook_info()
    if info.url != webhook_url:
        await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        print(f"Webhook установлен: {webhook_url}")
    else:
        print("Webhook уже установлен и актуален")

async def main():
    print("Тайный Друг 2025 запущен на Render через вебхуки!")

    # Устанавливаем вебхук
    await set_webhook()

    # Создаём aiohttp-приложение
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)

    # Чтобы Render видел открытый порт
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб-сервер слушает порт {port}")

    # Держим процесс живым
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())