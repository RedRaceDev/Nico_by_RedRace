# main.py - Полная версия
#!/usr/bin/env python3
"""
Nico™ 3.5 - Гоночный инженер RedRace
"""

import asyncio
import os
import logging
import random
import sqlite3
from datetime import datetime
from typing import Dict

from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery, Message, CallbackQuery
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from database import init_db, save_conversation, get_stats, get_all_users, clear_all_history, save_post, save_donation
from scraper import (
    get_driver_standings, get_next_race, get_race_schedule,
    get_random_character, get_system_info, ask_ai,
    get_pending_posts, clear_pending_posts, monitor_rss, mark_posted,
    save_to_memory, get_memory
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"

# ========== FSM ==========
class Form(StatesGroup):
    waiting_for_post = State()
    waiting_for_donate_amount = State()

# ========== THROTTLING ==========
class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit: int = 2, period: float = 1.0):
        self.limit = limit
        self.period = period
        self.users: Dict[int, list] = {}
        super().__init__()

    async def __call__(self, handler, event: Message, data: dict):
        user_id = event.from_user.id
        now = datetime.now().timestamp()

        if user_id not in self.users:
            self.users[user_id] = []

        self.users[user_id] = [t for t in self.users[user_id] if now - t < self.period]

        if len(self.users[user_id]) >= self.limit:
            await event.answer("⏳ Слишком часто! Подожди секунду.")
            return

        self.users[user_id].append(now)
        return await handler(event, data)

dp.message.middleware(ThrottlingMiddleware(limit=2))

# ========== КЛАВИАТУРЫ ==========
def get_user_keyboard():
    buttons = [
        [KeyboardButton(text="🏆 Чемпионат"), KeyboardButton(text="📅 Календарь")],
        [KeyboardButton(text="🏁 Следующая гонка"), KeyboardButton(text="🎭 Персонаж")],
        [KeyboardButton(text="⭐ Поддержать проект"), KeyboardButton(text="ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard():
    buttons = [
        [KeyboardButton(text="🏆 Чемпионат"), KeyboardButton(text="📅 Календарь")],
        [KeyboardButton(text="🏁 Следующая гонка"), KeyboardButton(text="🎭 Персонаж")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Пользователи")],
        [KeyboardButton(text="📝 Пост в канал"), KeyboardButton(text="✅ Опубликовать всё")],
        [KeyboardButton(text="⭐ Донаты"), KeyboardButton(text="🧹 Очистить БД")],
        [KeyboardButton(text="ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== ПУБЛИКАЦИЯ ==========
async def publish_to_channel(text: str, media_type: str = None, media_id: str = None):
    try:
        if media_type == "photo":
            await bot.send_photo(CHANNEL_ID, media_id, caption=text, parse_mode="HTML")
        else:
            await bot.send_message(CHANNEL_ID, text, parse_mode="HTML", disable_web_page_preview=True)
        save_post(text, media_type, media_id)
        return True
    except Exception as e:
        logger.error(f"Publish error: {e}")
        return False

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    save_conversation(message.from_user.id, "/start", "Бот запущен",
                      message.from_user.username, message.from_user.first_name)

    if message.from_user.id in ADMIN_IDS:
        await message.answer(
            "👑 **Nico™ 3.5 — Админ-панель**\n\n"
            f"📡 Мониторинг RSS: активен\n"
            f"📰 Новостей в очереди: {len(get_pending_posts())}",
            parse_mode="HTML", reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            "🏎️ **Nico™ — твой гоночный инженер**\n\n"
            "Используй кнопки ниже 👇",
            parse_mode="HTML", reply_markup=get_user_keyboard()
        )

@dp.message(Command("standings"))
async def cmd_standings(message: Message):
    standings = await get_driver_standings(2026)
    text = "🏆 **Чемпионат F1 2026:**\n\n"
    for s in standings[:5]:
        text += f"{s['pos']}. **{s['driver']}** — {s['points']} очков ({s['team']})\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("next"))
async def cmd_next(message: Message):
    next_race = await get_next_race(2026)
    text = f"⏩ **Следующая гонка:**\n\n🏎️ {next_race['name']}\n📅 {next_race['date']}\n🏁 {next_race['circuit']}"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("character"))
async def cmd_character(message: Message):
    await message.answer(get_random_character(), parse_mode="HTML")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(get_system_info(), parse_mode="HTML")

@dp.message(Command("info"))
async def cmd_info(message: Message):
    await message.answer(get_system_info(), parse_mode="HTML")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    stats = get_stats()
    await message.answer(
        f"📊 **Статистика**\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"💬 Диалогов: {stats['dialogs']}\n"
        f"📝 Постов: {stats['posts']}\n"
        f"⭐ Получено Stars: {stats['donations']}",
        parse_mode="HTML"
    )

@dp.message(Command("donate"))
async def cmd_donate(message: Message):
    await message.answer(
        "💰 Введи количество звезд (от 1 до 2500):\n\n"
        "Например: 50",
        parse_mode="HTML"
    )
    await Form.waiting_for_donate_amount.set()

@dp.message(Command("post"))
async def cmd_post(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    text = message.text.replace("/post", "").strip()
    if not text:
        await message.answer("📝 Напиши текст после команды: /post Твой текст")
        return
    success = await publish_to_channel(text)
    await message.answer("✅ Пост опубликован" if success else "❌ Ошибка")

@dp.message(Command("publish"))
async def cmd_publish(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    posts = get_pending_posts()
    if not posts:
        await message.answer("📭 Нет новостей")
        return
    await message.answer(f"📤 Публикую {len(posts)} постов...")
    for p in posts:
        await publish_to_channel(p['post'])
        mark_posted(p['title'], p['link'])
        await asyncio.sleep(2)
    clear_pending_posts()
    await message.answer(f"✅ Опубликовано {len(posts)}")

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    clear_all_history()
    await message.answer("🧹 База данных очищена")

@dp.message(Command("users"))
async def cmd_users(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    users = get_all_users(20)
    if not users:
        await message.answer("📭 Нет пользователей")
        return
    text = "👥 **Топ пользователей:**\n\n"
    for uid, username, first_name, msgs in users[:10]:
        name = first_name or username or uid[:8]
        text += f"• {name} — {msgs} сообщений\n"
    await message.answer(text[:4000], parse_mode="HTML")

@dp.message(Command("donation_stats"))
async def cmd_donation_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    total = c.execute("SELECT SUM(amount) FROM donations").fetchone()[0] or 0
    top = c.execute("""
        SELECT user_id, amount, MAX(created_at) 
        FROM donations 
        GROUP BY user_id 
        ORDER BY amount DESC 
        LIMIT 5
    """).fetchall()
    conn.close()
    
    text = f"⭐ **Статистика донатов**\n\n"
    text += f"💰 Всего получено звезд: {total}\n\n"
    text += f"🏆 **Топ донатеров:**\n"
    for i, (uid, amount, _) in enumerate(top, 1):
        text += f"{i}. Пользователь {uid[:6]} — {amount} ⭐\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Form.waiting_for_donate_amount)
async def process_donate_amount(message: Message, state: FSMContext):
    await state.clear()
    
    if not message.text.isdigit():
        await message.answer("❌ Введи число, Kumpel. Например: 50")
        return
    
    amount = int(message.text)
    
    if amount < 1 or amount > 2500:
        await message.answer("❌ Сумма должна быть от 1 до 2500 звезд")
        return
    
    prices = [LabeledPrice(label="XTR", amount=amount)]
    
    await message.answer_invoice(
        title="Поддержка RedRace Development",
        description=f"Пожертвование {amount} звезд",
        prices=prices,
        provider_token="",
        payload=f"donate_{amount}",
        currency="XTR"
    )

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    stars_count = message.successful_payment.total_amount // 100
    save_donation(message.from_user.id, stars_count)

    await message.answer(
        f"⭐ Спасибо за поддержку, {message.from_user.first_name}!\n\n"
        f"Ты подарил {stars_count} звезд.\n"
        f"Эти средства пойдут на развитие RedRace.\n\n"
        f"Спасибо! 🏎️💨",
        parse_mode="HTML"
    )

# ========== КНОПКИ ==========
@dp.message(lambda m: m.text == "🏆 Чемпионат")
async def btn_standings(message: Message):
    await cmd_standings(message)

@dp.message(lambda m: m.text == "📅 Календарь")
async def btn_calendar(message: Message):
    races = await get_race_schedule(2026)
    if races:
        text = "📅 **Календарь F1 2026:**\n\n"
        for r in races[:10]:
            text += f"**{r['round']}.** {r['name']} — {r['date']} ({r['circuit']})\n"
        await message.answer(text, parse_mode="HTML")
    else:
        await message.answer("📅 Календарь временно недоступен")

@dp.message(lambda m: m.text == "🏁 Следующая гонка")
async def btn_next(message: Message):
    await cmd_next(message)

@dp.message(lambda m: m.text == "🎭 Персонаж")
async def btn_character(message: Message):
    await cmd_character(message)

@dp.message(lambda m: m.text == "ℹ️ Помощь")
async def btn_help(message: Message):
    await cmd_help(message)

@dp.message(lambda m: m.text == "📊 Статистика")
async def btn_stats(message: Message):
    await cmd_stats(message)

@dp.message(lambda m: m.text == "👥 Пользователи")
async def btn_users(message: Message):
    await cmd_users(message)

@dp.message(lambda m: m.text == "📝 Пост в канал")
async def btn_post(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await Form.waiting_for_post.set()
    await message.answer("📝 Отправь текст для публикации в канал:")

@dp.message(lambda m: m.text == "✅ Опубликовать всё")
async def btn_publish_all(message: Message):
    await cmd_publish(message)

@dp.message(lambda m: m.text == "🧹 Очистить БД")
async def btn_clear(message: Message):
    await cmd_clear(message)

@dp.message(lambda m: m.text == "⭐ Донаты")
async def btn_donation_stats(message: Message):
    await cmd_donation_stats(message)

@dp.message(Form.waiting_for_post)
async def process_post_text(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    await state.clear()
    success = await publish_to_channel(message.text)
    await message.answer("✅ Пост опубликован" if success else "❌ Ошибка")

# ========== ОБЫЧНЫЙ ЧАТ ==========
@dp.message()
async def chat_handler(message: Message):
    user_id = message.from_user.id
    text = message.text

    if not text or text.startswith('/'):
        return

    buttons = ["🏆 Чемпионат", "📅 Календарь", "🏁 Следующая гонка", "🎭 Персонаж",
               "⭐ Поддержать проект", "📊 Статистика", "👥 Пользователи", "📝 Пост в канал",
               "✅ Опубликовать всё", "🧹 Очистить БД", "ℹ️ Помощь", "⭐ Донаты"]
    if text in buttons:
        return

    answer = await ask_ai(text)
    if len(answer) > 500:
        answer = answer[:500] + "..."

    await message.answer(answer, parse_mode="HTML")
    save_conversation(user_id, text, answer, message.from_user.username, message.from_user.first_name)
    save_to_memory(user_id, text, answer)

# ========== ЗАПУСК ==========
async def main():
    init_db()
    logger.info("🚀 Nico™ 3.5 запускается...")
    logger.info("🤖 AI: Nex-N2-Pro + Nemotron 3 Ultra")
    logger.info("⭐ Поддержка: Telegram Stars")
    asyncio.create_task(monitor_rss())
    await dp.start_polling(bot, tasks_concurrency_limit=5)

if __name__ == "__main__":
    asyncio.run(main())
