# main.py
import asyncio
import logging
import random
import sqlite3
import pandas as pd
from io import BytesIO
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BufferedInputFile

TOKEN = "8489962637:AAGEiIssbO9HkDGOGgB14NnAtMWPVhaHcvg"
ADMIN_ID = 662672735
PASSWORD = "12345"
DEADLINE = datetime(2025, 12, 9, 23, 59)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
logging.basicConfig(level=logging.INFO)

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

class Form(StatesGroup):
    name = State()
    wish = State()

class AdminStates(StatesGroup):
    password = State()
    broadcast = State()
    manual_from = State()
    manual_to = State()

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
    kb.button(text="🗑 Очистить базу", callback_data="admin_clear_db")
    kb.button(text="Рассылка всем", callback_data="admin_broadcast")
    kb.button(text="Выйти", callback_data="admin_exit")
    kb.adjust(2)
    return kb.as_markup()

# === СТАРТ ===
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

# === РЕГИСТРАЦИЯ ===
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
    await message.answer("За какие нужды можно помолиться?\nЧто хочешь получить в подарок (до 30BYN)?")

@dp.message(Form.wish)
async def reg_done(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cur.execute("INSERT INTO users (user_id, name, wish) VALUES (?, ?, ?)",
                (message.from_user.id, data["name"], message.text.strip()))
    conn.commit()
    await message.answer("Ты в игре!\n10 декабря узнаешь тайного друга  🎁")
    await state.clear()

# === ПОЛУЧИЛ ПОДАРОК ===
@dp.callback_query(F.data.in_({"got_gift", "no_gift"}))
async def gift_status(callback: types.CallbackQuery):
    if callback.data == "got_gift":
        cur.execute("UPDATE users SET received=1 WHERE user_id=?", (callback.from_user.id,))
        conn.commit()
        await callback.answer("Спасибо за радость!", show_alert=True)

# === АДМИН-ПАНЕЛЬ ===
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
    await callback.message.edit_text(text, reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_list")
async def admin_list(callback: types.CallbackQuery):
    users = cur.execute("SELECT name, wish, user_id, target_id FROM users").fetchall()
    if not users:
        return await callback.message.edit_text("Пока никого", reply_markup=admin_menu())
    text = f"<b>Участники ({len(users)})</b>\n\n"
    for name, wish, uid, target in users:
        target_name = "—" if not target else cur.execute("SELECT name FROM users WHERE user_id=?", (target,)).fetchone()[0]
        text += f"• <b>{name}</b> ({uid})\n  → {target_name}\n  {wish}\n\n"
    await callback.message.edit_text(text, reply_markup=admin_menu())

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
    await callback.message.edit_text("Распределение завершено!", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_clear_db")
async def admin_clear_db(callback: types.CallbackQuery):
    cur.execute("DELETE FROM users")
    cur.execute("DELETE FROM sqlite_sequence WHERE name='users'")  # сброс автоинкремента
    conn.commit()
    await callback.message.edit_text("🗑 База данных полностью очищена!\nТеперь можно начинать заново 🎄", reply_markup=admin_menu())
    await callback.answer("Готово!", show_alert=True)
    
@dp.callback_query(F.data == "admin_export")
async def admin_export(callback: types.CallbackQuery):
    data = cur.execute("SELECT user_id, name, wish, target_id, received FROM users").fetchall()
    df = pd.DataFrame(data, columns=["ID", "Имя", "Пожелание", "Дарит (ID)", "Получил"])
    df["Дарит (Имя)"] = df["Дарит (ID)"].apply(lambda x: cur.execute("SELECT name FROM users WHERE user_id=?", (x,)).fetchone()[0] if x else "—")
    bio = BytesIO()
    df.to_excel(bio, index=False, engine="openpyxl")
    bio.seek(0)
    file = BufferedInputFile(bio.read(), filename="Тайный_Друг_2025.xlsx")
    await callback.message.answer_document(file, caption="Экспорт участников")
    await callback.answer()

@dp.callback_query(F.data == "admin_manual")
async def admin_manual_start(callback: types.CallbackQuery, state: FSMContext):
    users = cur.execute("SELECT user_id, name FROM users").fetchall()
    kb = InlineKeyboardBuilder()
    for uid, name in users:
        kb.button(text=f"{name} ({uid})", callback_data=f"from_{uid}")
    kb.adjust(1)
    await callback.message.edit_text("Кто будет дарить?", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("from_"))
async def admin_manual_from(callback: types.CallbackQuery, state: FSMContext):
    from_id = int(callback.data.split("_")[1])
    await state.update_data(from_id=from_id)
    name = cur.execute("SELECT name FROM users WHERE user_id=?", (from_id,)).fetchone()[0]
    users = cur.execute("SELECT user_id, name FROM users WHERE user_id != ?", (from_id,)).fetchall()
    kb = InlineKeyboardBuilder()
    for uid, n in users:
        kb.button(text=f"{n} ({uid})", callback_data=f"to_{uid}")
    kb.button(text="Отмена", callback_data="admin_cancel")
    kb.adjust(1)
    await state.set_state(AdminStates.manual_to)
    await callback.message.edit_text(f"<b>{name}</b> будет дарить кому?", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("to_"))
async def admin_manual_to(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    from_id = data["from_id"]
    to_id = int(callback.data.split("_")[1])
    cur.execute("UPDATE users SET target_id=? WHERE user_id=?", (to_id, from_id))
    conn.commit()
    from_name = cur.execute("SELECT name FROM users WHERE user_id=?", (from_id,)).fetchone()[0]
    to_name = cur.execute("SELECT name FROM users WHERE user_id=?", (to_id,)).fetchone()[0]
    wish = cur.execute("SELECT wish FROM users WHERE user_id=?", (to_id,)).fetchone()[0]
    await bot.send_message(from_id, f"Теперь ты даришь <b>{to_name}</b>\n\nПожелание:\n{wish}", reply_markup=received_kb())
    await callback.message.edit_text(f"Готово!\n<b>{from_name}</b> → <b>{to_name}</b>", reply_markup=admin_menu())
    await state.clear()

@dp.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Отменено", reply_markup=admin_menu())

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.broadcast)
    await callback.message.edit_text("Напиши сообщение для рассылки:")

@dp.message(AdminStates.broadcast)
async def admin_broadcast_send(message: types.Message, state: FSMContext):
    users = cur.execute("SELECT user_id FROM users").fetchall()
    sent = 0
    for (uid,) in users:
        try:
            await bot.copy_message(uid, message.from_user.id, message.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"Рассылка завершена! Отправлено: {sent}", reply_markup=admin_menu())
    await state.clear()

@dp.callback_query(F.data == "admin_exit")
async def admin_exit(callback: types.CallbackQuery):
    await callback.message.edit_text("Вы вышли из админки")

import uvicorn
from aiohttp import web

async def health(request):
    return web.Response(text="Бот живёт ❤️")

async def main():
    # Запускаем и polling, и фейковый веб-сервер одновременно
    app = web.Application()
    app.router.add_get('/', health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10000)  # любой порт
    await site.start()
    
    print("Бот запущен 24/7 + веб-порт для Render")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
