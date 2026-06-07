import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from database import init_db, save_conversation, get_stats, get_all_users, clear_all_history
from scraper import (
    get_driver_standings, get_last_race_results, get_next_race, get_race_schedule,
    get_random_character, get_system_info, ask_ai,
    get_pending_posts, clear_pending_posts, monitor_rss
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard():
    buttons = [
        [KeyboardButton(text="🏆 Чемпионат"), KeyboardButton(text="📅 Календарь")],
        [KeyboardButton(text="🏁 Последняя гонка"), KeyboardButton(text="⏩ Следующая гонка")],
        [KeyboardButton(text="🎭 Персонаж"), KeyboardButton(text="⚙️ Сменить режим")],
        [KeyboardButton(text="ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard():
    buttons = [
        [KeyboardButton(text="🏆 Чемпионат"), KeyboardButton(text="📅 Календарь")],
        [KeyboardButton(text="🏁 Последняя гонка"), KeyboardButton(text="⏩ Следующая гонка")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Пользователи")],
        [KeyboardButton(text="📰 Новости"), KeyboardButton(text="✅ Опубликовать")],
        [KeyboardButton(text="🧹 Очистить БД")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    save_conversation(message.from_user.id, "/start", "Бот запущен", 
                      message.from_user.username, message.from_user.first_name)
    
    if message.from_user.id in ADMIN_IDS:
        await message.answer("👑 **Админ-панель**", parse_mode="HTML", reply_markup=get_admin_keyboard())
    else:
        await message.answer(
            "🏎️ **Нико — твой гоночный инженер**\n\n"
            "**Режимы:** /short, /long, /expert, /meme\n"
            "**Команды:** /standings, /race, /next, /mode, /help",
            parse_mode="HTML", reply_markup=get_main_keyboard()
        )

@dp.message(Command("standings"))
async def cmd_standings(message: types.Message):
    standings = await get_driver_standings(2026)
    text = "🏆 **Чемпионат F1 2026:**\n\n"
    for s in standings[:5]:
        text += f"{s['pos']}. **{s['driver']}** — {s['points']} очков ({s['team']})\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("race"))
async def cmd_race(message: types.Message):
    race = await get_last_race_results(2026)
    text = f"🏁 **{race['name']}**\n\n"
    for r in race['results'][:5]:
        text += f"{r['pos']}. {r['driver']} — {r['points']} очков\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("next"))
async def cmd_next(message: types.Message):
    next_race = await get_next_race(2026)
    text = f"⏩ **Следующая гонка:**\n\n🏎️ {next_race['name']}\n📅 {next_race['date']}\n🏁 {next_race['circuit']}"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("character"))
async def cmd_character(message: types.Message):
    await message.answer(get_random_character(), parse_mode="HTML")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(get_system_info(), parse_mode="HTML")

@dp.message(Command("mode"))
async def cmd_mode(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Коротко", callback_data="mode_short")],
        [InlineKeyboardButton(text="📄 Развёрнуто", callback_data="mode_long")],
        [InlineKeyboardButton(text="🔬 Эксперт", callback_data="mode_expert")],
        [InlineKeyboardButton(text="😂 Мемный", callback_data="mode_meme")],
    ])
    await message.answer("🎯 **Выбери режим ответа:**", reply_markup=kb)

# ========== АДМИН-КОМАНДЫ ==========
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    stats = get_stats()
    await message.answer(
        f"📊 **Статистика**\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"💬 Диалогов: {stats['dialogs']}\n"
        f"📝 Постов: {stats['posts']}\n"
        f"🐞 Багов: {stats['bugs']}",
        parse_mode="HTML"
    )

# ========== КНОПКИ ==========
@dp.message(lambda m: m.text == "🏆 Чемпионат")
async def btn_standings(message: types.Message):
    await cmd_standings(message)

@dp.message(lambda m: m.text == "📅 Календарь")
async def btn_calendar(message: types.Message):
    races = await get_race_schedule(2026)
    if races:
        text = "📅 **Календарь F1 2026:**\n\n" + "\n".join([
            f"**{r['round']}.** {r['name']} — {r['date']} ({r['circuit']})" 
            for r in races[:8]
        ])
        await message.answer(text, parse_mode="HTML")

@dp.message(lambda m: m.text == "🏁 Последняя гонка")
async def btn_race(message: types.Message):
    await cmd_race(message)

@dp.message(lambda m: m.text == "⏩ Следующая гонка")
async def btn_next(message: types.Message):
    await cmd_next(message)

@dp.message(lambda m: m.text == "🎭 Персонаж")
async def btn_character(message: types.Message):
    await cmd_character(message)

@dp.message(lambda m: m.text == "ℹ️ Помощь")
async def btn_help(message: types.Message):
    await cmd_help(message)

@dp.message(lambda m: m.text == "📊 Статистика")
async def btn_stats(message: types.Message):
    await cmd_stats(message)

# ========== ЗАПУСК ==========
async def main():
    init_db()
    logger.info("🚀 Нико 3.1 запускается...")
    asyncio.create_task(monitor_rss())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
