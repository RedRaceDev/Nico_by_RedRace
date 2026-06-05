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
from database import (
    init_db, save_conversation, get_stats, get_all_users,
    get_last_dialogs, clear_all_history, get_user_message_count,
    save_bug_report
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
        [KeyboardButton(text="🧠 Очистить кеш"), KeyboardButton(text="🗑 Очистить историю")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# === КОМАНДЫ ===
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    # Сохраняем в базу факт запуска
    save_conversation(user_id, "/start", "Бот запущен", username, first_name)
    
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
        
        # Получаем статистику из базы
        stats = get_stats()
        
        await message.answer(
            f"🩺 **Диагностика Нико 3.1**\n\n"
            f"📡 FastF1: {status}\n"
            f"📊 Данные: {'доступны' if standings else 'fallback'}\n"
            f"👥 Пользователей в базе: {stats['users']}\n"
            f"💬 Диалогов сохранено: {stats['dialogs']}\n"
            f"🐞 Багов: {stats['bugs']}\n"
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

@dp.message(Command("stats"))
async def stats_command(message: types.Message):
    """Получить статистику из базы"""
    stats = get_stats()
    await message.answer(
        f"📊 **Статистика бота**\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"💬 Диалогов: {stats['dialogs']}\n"
        f"📝 Постов в канале: {stats['posts']}\n"
        f"🐞 Баг-репортов: {stats['bugs']}",
        parse_mode="HTML"
    )

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
    
    # Сохраняем в базу
    save_conversation(message.from_user.id, "🏆 Чемпионат", text[:200], message.from_user.username, message.from_user.first_name)

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
    
    save_conversation(message.from_user.id, "📅 Календарь", text[:200], message.from_user.username, message.from_user.first_name)

@dp.message(lambda m: m.text == "🏁 Последняя гонка")
async def last_race_cmd(message: types.Message):
    status = await message.answer("🔍 Загружаю результаты...")
    race = await get_last_race_results(2026)
    text = f"🏁 **{race['name']}**\n\n"
    for r in race['results'][:5]:
        text += f"{r['pos']}. {r['driver']} — {r['points']} очков\n"
    await status.edit_text(text, parse_mode="HTML")
    
    save_conversation(message.from_user.id, "🏁 Последняя гонка", text[:200], message.from_user.username, message.from_user.first_name)

@dp.message(lambda m: m.text == "⏩ Следующая гонка")
async def next_race_cmd(message: types.Message):
    next_race = await get_next_race(2026)
    text = f"⏩ **Следующая гонка:**\n\n🏎️ {next_race['name']}\n📅 {next_race['date']}\n🏁 {next_race['circuit']}"
    await message.answer(text, parse_mode="HTML")
    
    save_conversation(message.from_user.id, "⏩ Следующая гонка", text[:200], message.from_user.username, message.from_user.first_name)

@dp.message(lambda m: m.text == "🎭 Персонаж")
async def character_cmd(message: types.Message):
    text = get_random_character()
    await message.answer(text, parse_mode="HTML")
    save_conversation(message.from_user.id, "🎭 Персонаж", text[:200], message.from_user.username, message.from_user.first_name)

@dp.message(lambda m: m.text == "ℹ️ Помощь")
async def help_cmd(message: types.Message):
    text = get_system_info()
    await message.answer(text, parse_mode="HTML")
    save_conversation(message.from_user.id, "ℹ️ Помощь", text[:200], message.from_user.username, message.from_user.first_name)

# === АДМИН-КНОПКИ ===
@dp.message(lambda m: m.text == "📊 Статистика")
async def stats_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    stats = get_stats()
    users = get_all_users(10)
    
    text = f"📊 **Статистика**\n\n"
    text += f"👥 Пользователей: {stats['users']}\n"
    text += f"💬 Диалогов: {stats['dialogs']}\n"
    text += f"📝 Постов: {stats['posts']}\n"
    text += f"🐞 Багов: {stats['bugs']}\n\n"
    text += "🏆 **Топ пользователей:**\n"
    
    for uid, username, first_name, msgs, _ in users[:5]:
        name = first_name or username or uid[:8]
        text += f"• {name} — {msgs} сообщений\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(lambda m: m.text == "👥 Пользователи")
async def users_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    users = get_all_users(50)
    if not users:
        await message.answer("📭 Нет пользователей")
        return
    
    text = "👥 **Список пользователей:**\n\n"
    for uid, username, first_name, msgs, last_seen in users[:20]:
        name = first_name or username or uid[:8]
        last_seen_str = last_seen[:16] if last_seen else "неизвестно"
        text += f"• {name} — {msgs} сообщений (последний раз: {last_seen_str})\n"
    
    if len(users) > 20:
        text += f"\n... и ещё {len(users) - 20} пользователей"
    
    await message.answer(text[:4000], parse_mode="HTML")

@dp.message(lambda m: m.text == "📨 Рассылка")
async def broadcast_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("📨 Функция рассылки в разработке")

@dp.message(lambda m: m.text == "📤 Пост в канал")
async def post_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("📤 Функция публикации в разработке")

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

@dp.message(lambda m: m.text == "🗑 Очистить историю")
async def clear_history_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    clear_all_history()
    await message.answer("🗑 Вся история диалогов очищена")

# === ОБРАБОТЧИК ТЕКСТА ===
@dp.message()
async def chat_handler(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    # Получаем ответ
    answer = await chat_reply(user_id, text)
    
    # Сохраняем в базу
    save_conversation(user_id, text, answer, username, first_name)
    
    await message.answer(answer, parse_mode="HTML")

# === ЗАПУСК ===
async def main():
    # Инициализируем базу данных
    init_db()
    
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
