#!/usr/bin/env python3
"""
Nico™ 3.3 - Гоночный инженер RedRace
"""

import asyncio
import os
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from database import init_db, save_conversation, get_stats, get_all_users, clear_all_history, save_post
from scraper import (
    get_driver_standings, get_next_race, get_race_schedule,
    get_random_character, get_system_info, ask_ai,
    get_pending_posts, clear_pending_posts, monitor_rss, mark_posted,
    generate_image, save_to_memory, get_memory
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

# === FSM ===
class Form(StatesGroup):
    waiting_for_post = State()
    waiting_for_image_prompt = State()

# === КЛАВИАТУРЫ ===
def get_user_keyboard():
    buttons = [
        [KeyboardButton(text="🏆 Чемпионат"), KeyboardButton(text="📅 Календарь")],
        [KeyboardButton(text="🏁 Следующая гонка"), KeyboardButton(text="🎭 Персонаж")],
        [KeyboardButton(text="🎨 Сгенерировать картинку"), KeyboardButton(text="ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_keyboard():
    buttons = [
        [KeyboardButton(text="🏆 Чемпионат"), KeyboardButton(text="📅 Календарь")],
        [KeyboardButton(text="🏁 Следующая гонка"), KeyboardButton(text="🎭 Персонаж")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Пользователи")],
        [KeyboardButton(text="📝 Пост в канал"), KeyboardButton(text="🎨 Сгенерировать картинку")],
        [KeyboardButton(text="📰 Новости"), KeyboardButton(text="✅ Опубликовать всё")],
        [KeyboardButton(text="🧹 Очистить БД"), KeyboardButton(text="ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# === ПУБЛИКАЦИЯ ===
async def publish_to_channel(text: str, media_type: str = None, media_id: str = None):
    try:
        if media_type == "photo":
            await bot.send_photo(CHANNEL_ID, media_id, caption=text, parse_mode="HTML")
        else:
            await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
        save_post(text, media_type, media_id)
        return True
    except Exception as e:
        logger.error(f"Publish error: {e}")
        return False

# === КОМАНДЫ ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    save_conversation(message.from_user.id, "/start", "Бот запущен", 
                      message.from_user.username, message.from_user.first_name)
    
    if message.from_user.id in ADMIN_IDS:
        await message.answer(
            "👑 **Nico™ 3.3 — Админ-панель**\n\n"
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
async def cmd_standings(message: types.Message):
    standings = await get_driver_standings(2026)
    text = "🏆 **Чемпионат F1 2026:**\n\n"
    for s in standings[:5]:
        text += f"{s['pos']}. **{s['driver']}** — {s['points']} очков ({s['team']})\n"
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

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    stats = get_stats()
    await message.answer(
        f"📊 **Статистика**\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"💬 Диалогов: {stats['dialogs']}\n"
        f"📝 Постов: {stats['posts']}",
        parse_mode="HTML"
    )

# === ГЕНЕРАЦИЯ КАРТИНКИ ===
@dp.message(Command("image"))
async def cmd_image(message: types.Message):
    await message.answer("🎨 Напиши промпт для генерации картинки:")
    await Form.waiting_for_image_prompt.set()

@dp.message(Form.waiting_for_image_prompt)
async def process_image_prompt(message: types.Message, state: FSMContext):
    await state.clear()
    status = await message.answer("🎨 Генерирую картинку, подожди...")
    url = await generate_image(message.text)
    if url:
        await bot.send_photo(message.chat.id, url, caption=f"🎨 Промпт: {message.text}")
        await status.delete()
    else:
        await status.edit_text("❌ Не удалось сгенерировать картинку")

# === ПОСТ В КАНАЛ ===
@dp.message(Command("post"))
async def cmd_post(message: types.Message):
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
async def cmd_publish(message: types.Message):
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
async def cmd_clear(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    clear_all_history()
    await message.answer("🧹 База данных очищена")

@dp.message(Command("users"))
async def cmd_users(message: types.Message):
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

# === КНОПКИ ===
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

@dp.message(lambda m: m.text == "🏁 Следующая гонка")
async def btn_next(message: types.Message):
    await cmd_next(message)

@dp.message(lambda m: m.text == "🎭 Персонаж")
async def btn_character(message: types.Message):
    await cmd_character(message)

@dp.message(lambda m: m.text == "🎨 Сгенерировать картинку")
async def btn_image(message: types.Message):
    await cmd_image(message)

@dp.message(lambda m: m.text == "📊 Статистика")
async def btn_stats(message: types.Message):
    await cmd_stats(message)

@dp.message(lambda m: m.text == "👥 Пользователи")
async def btn_users(message: types.Message):
    await cmd_users(message)

@dp.message(lambda m: m.text == "📝 Пост в канал")
async def btn_post(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await Form.waiting_for_post.set()
    await message.answer("📝 Отправь текст для публикации в канал:")

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
    await cmd_publish(message)

@dp.message(lambda m: m.text == "🧹 Очистить БД")
async def btn_clear(message: types.Message):
    await cmd_clear(message)

@dp.message(lambda m: m.text == "ℹ️ Помощь")
async def btn_help(message: types.Message):
    await cmd_help(message)

# === FSM ДЛЯ ПОСТА ===
@dp.message(Form.waiting_for_post)
async def process_post_text(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    await state.clear()
    success = await publish_to_channel(message.text)
    await message.answer("✅ Пост опубликован в канале" if success else "❌ Ошибка публикации")

# === ОБЫЧНЫЙ ЧАТ ===
@dp.message()
async def chat_handler(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    
    if not text or text.startswith('/'):
        return
    
    if text in ["🏆 Чемпионат", "📅 Календарь", "🏁 Следующая гонка", "🎭 Персонаж", "🎨 Сгенерировать картинку", "📊 Статистика", "👥 Пользователи", "📝 Пост в канал", "📰 Новости", "✅ Опубликовать всё", "🧹 Очистить БД", "ℹ️ Помощь"]:
        return
    
    status = await message.answer("🤔 Думаю...")
    
    memory = get_memory(user_id, 5)
    context = ""
    for m in memory[-3:]:
        context += f"Пользователь: {m['message']}\nНико: {m['response']}\n"
    
    prompt = f"""Ты — Nico, гоночный инженер RedRace. Отвечай кратко, 1-2 предложения, на русском.

История:
{context}

Пользователь: {text}
Ответ:"""
    
    answer = await ask_ai(prompt)
    if len(answer) > 500:
        answer = answer[:500] + "..."
    
    await status.delete()
    await message.answer(answer, parse_mode="HTML")
    
    save_conversation(user_id, text, answer, message.from_user.username, message.from_user.first_name)
    save_to_memory(user_id, text, answer)

# === ЗАПУСК ===
async def main():
    init_db()
    logger.info("🚀 Nico™ 3.3 запускается...")
    logger.info("🤖 AI: Google Gemma 4 31B + OpenRouter + Agnes")
    
    asyncio.create_task(monitor_rss())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
