import asyncio
import os
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from scraper import (
    chat_reply, get_driver_standings, get_last_race_results, get_next_race,
    get_race_schedule, get_random_character, get_system_info,
    get_pending_posts, clear_pending_posts, monitor, morning_digest
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"

# === КЛАВИАТУРЫ ===
def get_user_keyboard():
    buttons = [
        [KeyboardButton(text="🏆 Чемпионат"), KeyboardButton(text="📅 Календарь")],
        [KeyboardButton(text="🏁 Последняя гонка"), KeyboardButton(text="⏩ Следующая гонка")],
        [KeyboardButton(text="🎭 Персонаж"), KeyboardButton(text="ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard():
    buttons = [
        [KeyboardButton(text="🏆 Чемпионат"), KeyboardButton(text="📅 Календарь")],
        [KeyboardButton(text="🏁 Последняя гонка"), KeyboardButton(text="⏩ Следующая гонка")],
        [KeyboardButton(text="🎭 Персонаж"), KeyboardButton(text="ℹ️ Помощь")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Пользователи")],
        [KeyboardButton(text="📨 Рассылка"), KeyboardButton(text="📤 Пост в канал")],
        [KeyboardButton(text="📰 Новости"), KeyboardButton(text="✅ Опубликовать")],
        [KeyboardButton(text="🧠 Очистить кеш")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# === КОМАНДЫ ===
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    logging.info(f"👤 Start from {user_id}")
    if user_id in ADMIN_IDS:
        await message.answer(
            "👑 **Нико 3.1 — Админ-панель**\n\n"
            "Доступны все функции бота и управление.",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            "🏎️ **Я Нико — твой гоночный инженер**\n\n"
            "**Доступные команды:**\n"
            "• 🏆 Чемпионат — таблица лидеров\n"
            "• 📅 Календарь — расписание гонок\n"
            "• 🏁 Последняя гонка — результаты\n"
            "• ⏩ Следующая гонка\n"
            "• 🎭 Персонаж — случайный мем\n"
            "• ℹ️ Помощь — справка\n\n"
            "**Пример:** `сравни VER LEC`\n\n"
            "Данные из FastF1 (Jolpica)",
            parse_mode="HTML",
            reply_markup=get_user_keyboard()
        )

@dp.message(Command("info"))
async def info_cmd(message: types.Message):
    await message.answer(get_system_info(), parse_mode="HTML")

@dp.message(Command("health"))
async def health_cmd(message: types.Message):
    try:
        standings = await get_driver_standings(2026)
        status = "✅ API работает" if standings else "⚠️ API не отвечает, используется fallback"
        uptime = datetime.now().strftime("%H:%M:%S")
        await message.answer(
            f"🩺 **Диагностика Нико 3.1**\n\n"
            f"📡 FastF1: {status}\n"
            f"📊 Данные: {'доступны' if standings else 'fallback'}\n"
            f"⏱ Время работы бота: {uptime}\n"
            f"🔧 Кеш: активен (1 час)",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("reload"))
async def reload_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    
    from scraper import standings_cache, race_cache
    standings_cache.clear()
    race_cache.clear()
    await message.answer("🔄 Кеш очищен. Данные будут загружены заново.")

@dp.message(Command("test"))
async def test_cmd(message: types.Message):
    await message.answer("✅ Бот работает!")

# === КНОПКИ ===
@dp.message(lambda m: m.text == "🏆 Чемпионат")
async def standings_cmd(message: types.Message):
    status = await message.answer("🔍 Загружаю данные...")
    standings = await get_driver_standings(2026)
    if not standings:
        await status.edit_text("❌ Данные чемпионата недоступны")
        return
    text = "🏆 **Чемпионат F1 2026:**\n\n"
    for s in standings[:5]:
        text += f"{s['pos']}. **{s['driver']}** — {s['points']} очков ({s['team']})\n"
    await status.edit_text(text, parse_mode="HTML")

@dp.message(lambda m: m.text == "📅 Календарь")
async def calendar_cmd(message: types.Message):
    status = await message.answer("🔍 Загружаю календарь...")
    races = await get_race_schedule(2026)
    if not races:
        await status.edit_text("❌ Календарь недоступен")
        return
    text = "📅 **Календарь F1 2026:**\n\n"
    for r in races[:8]:
        text += f"**{r['round']}.** {r['name']} — {r['date']} ({r['circuit']})\n"
    await status.edit_text(text, parse_mode="HTML")

@dp.message(lambda m: m.text == "🏁 Последняя гонка")
async def last_race_cmd(message: types.Message):
    status = await message.answer("🔍 Загружаю результаты...")
    race = await get_last_race_results(2026)
    text = f"🏁 **{race['name']}**\n\n"
    for r in race['results'][:5]:
        text += f"{r['pos']}. {r['driver']} — {r['points']} очков\n"
    await status.edit_text(text, parse_mode="HTML")

@dp.message(lambda m: m.text == "⏩ Следующая гонка")
async def next_race_cmd(message: types.Message):
    next_race = await get_next_race(2026)
    await message.answer(
        f"⏩ **Следующая гонка:**\n\n"
        f"🏎️ {next_race['name']}\n"
        f"📅 {next_race['date']}\n"
        f"🏁 {next_race['circuit']}",
        parse_mode="HTML"
    )

@dp.message(lambda m: m.text == "🎭 Персонаж")
async def character_cmd(message: types.Message):
    await message.answer(get_random_character(), parse_mode="HTML")

@dp.message(lambda m: m.text == "ℹ️ Помощь")
async def help_cmd(message: types.Message):
    await message.answer(get_system_info(), parse_mode="HTML")

# === АДМИН-КНОПКИ ===
@dp.message(lambda m: m.text == "📊 Статистика")
async def stats_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("📊 **Статистика**\n\n👥 Пользователей: ~112\n💬 Диалогов: ~2300\n🏁 Постов: ~150", parse_mode="HTML")

@dp.message(lambda m: m.text == "👥 Пользователи")
async def users_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("👥 Функция в разработке")

@dp.message(lambda m: m.text == "📨 Рассылка")
async def broadcast_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("📨 Функция в разработке")

@dp.message(lambda m: m.text == "📤 Пост в канал")
async def post_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("📤 Функция в разработке")

@dp.message(lambda m: m.text == "📰 Новости")
async def news_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    posts = get_pending_posts()
    if not posts:
        await message.answer("📭 Новостей нет")
    else:
        text = f"📰 Готово к публикации ({len(posts)}):\n"
        for i, p in enumerate(posts[:5], 1):
            text += f"{i}. {p['title'][:50]}\n"
        await message.answer(text)

@dp.message(lambda m: m.text == "✅ Опубликовать")
async def publish_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    posts = get_pending_posts()
    if not posts:
        await message.answer("📭 Нет новостей")
        return
    await message.answer(f"📤 Публикую {len(posts)}...")
    for p in posts:
        await bot.send_message(CHANNEL_ID, p['post'], parse_mode="HTML")
        await asyncio.sleep(2)
    clear_pending_posts()
    await message.answer(f"✅ Опубликовано {len(posts)}")

@dp.message(lambda m: m.text == "🧠 Очистить кеш")
async def clear_cache_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    from scraper import standings_cache, race_cache
    standings_cache.clear()
    race_cache.clear()
    await message.answer("🧠 Кеш очищен")

# === ОБРАБОТЧИК ТЕКСТА ===
@dp.message()
async def chat_handler(message: types.Message):
    answer = await chat_reply(message.from_user.id, message.text)
    await message.answer(answer, parse_mode="HTML")

# === ЗАПУСК ===
async def main():
    logging.info("🚀 Нико 3.1 запускается...")
    logging.info(f"👑 Админ: {ADMIN_IDS}")
    logging.info(f"📡 Канал: {CHANNEL_ID}")
    
    # Тест API
    standings = await get_driver_standings(2026)
    if standings:
        logging.info("✅ FastF1 работает")
    else:
        logging.warning("⚠️ FastF1 не отвечает, использую fallback")
    
    # Фоновые задачи
    asyncio.create_task(monitor())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
