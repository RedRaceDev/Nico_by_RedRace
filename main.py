import asyncio
import os
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton
)

from database import init_db, save_conversation, get_stats, get_all_users, clear_all_history
from scraper import (
    get_driver_standings, get_next_race, get_race_schedule,
    get_random_character, get_system_info, ask_ai,
    get_pending_posts, clear_pending_posts, monitor_rss, pending_posts,
    mark_posted
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== ТОКЕН ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"

# ========== КЛАВИАТУРЫ ==========
def get_user_keyboard():
    buttons = [
        [KeyboardButton(text="🏆 Чемпионат"), KeyboardButton(text="📅 Календарь")],
        [KeyboardButton(text="🏁 Последняя гонка"), KeyboardButton(text="⏩ Следующая гонка")],
        [KeyboardButton(text="🎭 Персонаж"), KeyboardButton(text="⚙️ Режим")],
        [KeyboardButton(text="ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard():
    buttons = [
        [KeyboardButton(text="🏆 Чемпионат"), KeyboardButton(text="📅 Календарь")],
        [KeyboardButton(text="🏁 Последняя гонка"), KeyboardButton(text="⏩ Следующая гонка")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Пользователи")],
        [KeyboardButton(text="📰 Новости"), KeyboardButton(text="✅ Опубликовать всё")],
        [KeyboardButton(text="🧹 Очистить БД"), KeyboardButton(text="ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    save_conversation(message.from_user.id, "/start", "Бот запущен", 
                      message.from_user.username, message.from_user.first_name)
    
    if message.from_user.id in ADMIN_IDS:
        await message.answer(
            "👑 **Nico™ 3.1 — Админ-панель**\n\n"
            f"📡 Бот готов\n"
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
async def cmd_standings(message: types.Message):
    standings = await get_driver_standings(2026)
    if not standings:
        await message.answer("❌ Данные чемпионата временно недоступны")
        return
    text = "🏆 **Чемпионат F1 2026:**\n\n"
    for s in standings[:5]:
        text += f"{s['pos']}. **{s['driver']}** — {s['points']} очков ({s['team']})\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("race"))
async def cmd_race(message: types.Message):
    await message.answer("🏁 **Последняя гонка: Гран-при Монако**\n\n1. Kimi Antonelli — 25 очков\n2. Lewis Hamilton — 18 очков\n3. Isack Hadjar — 15 очков", parse_mode="HTML")

@dp.message(Command("next"))
async def cmd_next(message: types.Message):
    next_race = await get_next_race(2026)
    text = f"⏩ **Следующая гонка:**\n\n🏎️ {next_race['name']}\n📅 {next_race['date']}\n🏁 {next_race['circuit']}"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("mode"))
async def cmd_mode(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Коротко", callback_data="mode_short")],
        [InlineKeyboardButton(text="📄 Развёрнуто", callback_data="mode_long")],
        [InlineKeyboardButton(text="🔬 Эксперт", callback_data="mode_expert")],
        [InlineKeyboardButton(text="😂 Мемный", callback_data="mode_meme")],
    ])
    await message.answer("🎯 **Выбери режим ответа:**", reply_markup=kb)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(get_system_info(), parse_mode="HTML")

# ========== КНОПКИ ==========
@dp.message(lambda m: m.text == "🏆 Чемпионат")
async def btn_standings(message: types.Message):
    await cmd_standings(message)

@dp.message(lambda m: m.text == "📅 Календарь")
async def btn_calendar(message: types.Message):
    races = await get_race_schedule(2026)
    if races:
        text = "📅 **Календарь F1 2026:**\n\n"
        for r in races[:8]:
            text += f"**{r['round']}.** {r['name']} — {r['date']} ({r['circuit']})\n"
        await message.answer(text, parse_mode="HTML")
    else:
        await message.answer("📅 Календарь временно недоступен")

@dp.message(lambda m: m.text == "🏁 Последняя гонка")
async def btn_race(message: types.Message):
    await cmd_race(message)

@dp.message(lambda m: m.text == "⏩ Следующая гонка")
async def btn_next(message: types.Message):
    await cmd_next(message)

@dp.message(lambda m: m.text == "🎭 Персонаж")
async def btn_character(message: types.Message):
    await message.answer(get_random_character(), parse_mode="HTML")

@dp.message(lambda m: m.text == "⚙️ Режим")
async def btn_mode(message: types.Message):
    await cmd_mode(message)

@dp.message(lambda m: m.text == "ℹ️ Помощь")
async def btn_help(message: types.Message):
    await cmd_help(message)

# ========== АДМИН-КНОПКИ ==========
@dp.message(lambda m: m.text == "📊 Статистика")
async def btn_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    stats = get_stats()
    await message.answer(
        f"📊 **Статистика**\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"💬 Диалогов: {stats['dialogs']}\n"
        f"📝 Постов: {stats['posts']}",
        parse_mode="HTML"
    )

@dp.message(lambda m: m.text == "👥 Пользователи")
async def btn_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    users = get_all_users(20)
    if not users:
        await message.answer("📭 Нет пользователей")
        return
    text = "👥 **Топ пользователей:**\n\n"
    for uid, username, first_name, msgs in users[:10]:
        name = first_name or username or uid[:8]
        text += f"• {name} — {msgs} сообщений\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(lambda m: m.text == "📰 Новости")
async def btn_news(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    posts = get_pending_posts()
    if not posts:
        await message.answer("📭 Новостей нет")
        return
    text = f"📰 **Готово к публикации ({len(posts)}):**\n\n"
    for i, p in enumerate(posts[:5], 1):
        text += f"{i}. {p['title'][:50]}\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(lambda m: m.text == "✅ Опубликовать всё")
async def btn_publish_all(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    posts = get_pending_posts()
    if not posts:
        await message.answer("📭 Нет новостей")
        return
    await message.answer(f"📤 Публикую {len(posts)} постов...")
    for p in posts:
        await bot.send_message(CHANNEL_ID, p['post'], parse_mode="HTML", disable_web_page_preview=True)
        mark_posted(p['title'], p['link'])
        await asyncio.sleep(2)
    clear_pending_posts()
    await message.answer(f"✅ Опубликовано {len(posts)}")

@dp.message(lambda m: m.text == "🧹 Очистить БД")
async def btn_clear_db(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    clear_all_history()
    await message.answer("🧹 База данных очищена")

# ========== РЕЖИМЫ ОТВЕТА ==========
user_modes = {}

@dp.callback_query(lambda c: c.data.startswith("mode_"))
async def process_mode_callback(callback: types.CallbackQuery):
    mode_map = {
        "mode_short": "короткий",
        "mode_long": "развёрнутый",
        "mode_expert": "экспертный",
        "mode_meme": "мемный",
    }
    mode = mode_map.get(callback.data, "короткий")
    user_modes[callback.from_user.id] = mode
    await callback.answer(f"Режим изменён на {mode}")
    await callback.message.edit_text(f"✅ Режим **{mode}** включён")

# ========== ОБРАБОТЧИК ТЕКСТА (ЧАТ) ==========
@dp.message()
async def chat_handler(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    
    if not text or text.startswith('/'):
        return
    
    # F1 вопросы
    if "чемпионат" in text.lower() or "лидирует" in text.lower():
        await cmd_standings(message)
        return
    elif "гонка" in text.lower() and ("последняя" in text.lower() or "результат" in text.lower()):
        await cmd_race(message)
        return
    elif "следующая" in text.lower() or "ближайшая" in text.lower():
        await cmd_next(message)
        return
    elif "календарь" in text.lower():
        await btn_calendar(message)
        return
    elif "персонаж" in text.lower():
        await btn_character(message)
        return
    
    # AI ответ
    mode = user_modes.get(user_id, "короткий")
    prompt = f"""Ты — Nico, гоночный инженер. Отвечай на русском языке, кратко (1-2 предложения).

Пользователь: {text}
Ответ:"""
    
    answer = await ask_ai(prompt)
    if len(answer) > 400:
        answer = answer[:400] + "..."
    
    save_conversation(user_id, text, answer, message.from_user.username, message.from_user.first_name)
    await message.answer(answer, parse_mode="HTML")

# ========== ЗАПУСК ==========
async def main():
    init_db()
    logger.info("🚀 Nico™ 3.1 запускается...")
    logger.info(f"👑 Админ: {ADMIN_IDS}")
    logger.info("🤖 AI: NVIDIA Nemotron 3 Ultra")
    
    # Запускаем мониторинг RSS
    asyncio.create_task(monitor_rss())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
