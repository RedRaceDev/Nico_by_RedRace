#!/usr/bin/env python3
"""
Нико 3.1 - Полный контроль над ботом + публикация в канал
"""

import asyncio
import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

from database import init_db, save_conversation, get_stats, get_all_users, clear_all_history
from scraper import (
    get_driver_standings, get_last_race_results, get_next_race, get_race_schedule,
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

# Глобальные флаги
monitoring_active = True
waiting_for_post_text = {}
waiting_for_post_photo = {}
waiting_for_post_video = {}

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
        [KeyboardButton(text="📰 Просмотр новостей"), KeyboardButton(text="✅ Опубликовать всё")],
        [KeyboardButton(text="📝 Пост в канал"), KeyboardButton(text="🖼️ Фото в канал")],
        [KeyboardButton(text="🎥 Видео в канал"), KeyboardButton(text="⏹️ Остановить мониторинг")],
        [KeyboardButton(text="▶️ Запустить мониторинг"), KeyboardButton(text="🗑 Очистить очередь")],
        [KeyboardButton(text="🧹 Очистить БД")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ========== ПУБЛИКАЦИЯ В КАНАЛ ==========
async def publish_to_channel(chat_id, content_type, content, caption=None):
    """Публикация контента в канал от имени бота"""
    try:
        if content_type == "text":
            await bot.send_message(CHANNEL_ID, content, parse_mode="HTML")
        elif content_type == "photo":
            await bot.send_photo(CHANNEL_ID, content, caption=caption, parse_mode="HTML")
        elif content_type == "video":
            await bot.send_video(CHANNEL_ID, content, caption=caption, parse_mode="HTML")
        elif content_type == "audio":
            await bot.send_audio(CHANNEL_ID, content, caption=caption)
        elif content_type == "document":
            await bot.send_document(CHANNEL_ID, content, caption=caption)
        return True
    except Exception as e:
        logger.error(f"Publish error: {e}")
        return False

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    save_conversation(message.from_user.id, "/start", "Бот запущен", 
                      message.from_user.username, message.from_user.first_name)
    
    if message.from_user.id in ADMIN_IDS:
        await message.answer(
            "👑 **Админ-панель Нико 3.1**\n\n"
            f"📡 Мониторинг: {'✅ ВКЛЮЧЕН' if monitoring_active else '⛔ ВЫКЛЮЧЕН'}\n"
            f"📰 Новостей в очереди: {len(get_pending_posts())}\n\n"
            "**Что можно делать:**\n"
            "• Отправить текст — Нико опубликует в канал\n"
            "• Отправить фото/видео — Нико опубликует\n"
            "• Нажать кнопку — управление ботом",
            parse_mode="HTML", reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            "🏎️ **Нико — твой гоночный инженер**\n\n"
            "Используй кнопки или команды:\n"
            "• /standings — таблица чемпионата\n"
            "• /race — результаты последней гонки\n"
            "• /next — следующая гонка\n"
            "• /mode — выбрать режим ответа\n"
            "• /help — справка",
            parse_mode="HTML", reply_markup=get_main_keyboard()
        )

@dp.message(Command("post"))
async def cmd_post(message: types.Message):
    """Отправить текст в канал"""
    if message.from_user.id not in ADMIN_IDS:
        return
    text = message.text.replace("/post", "").strip()
    if not text:
        await message.answer("❌ Напиши текст после команды: /post Твой текст")
        return
    success = await publish_to_channel(None, "text", text)
    if success:
        await message.answer("✅ Пост опубликован в канале")
    else:
        await message.answer("❌ Ошибка публикации")

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

# ========== КНОПКИ ПОЛЬЗОВАТЕЛЯ ==========
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

@dp.message(lambda m: m.text == "⚙️ Сменить режим")
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
        f"📊 **Статистика бота**\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"💬 Диалогов: {stats['dialogs']}\n"
        f"📝 Постов: {stats['posts']}\n"
        f"🐞 Багов: {stats['bugs']}\n\n"
        f"📡 Мониторинг: {'✅ ВКЛЮЧЕН' if monitoring_active else '⛔ ВЫКЛЮЧЕН'}\n"
        f"📰 Новостей в очереди: {len(get_pending_posts())}",
        parse_mode="HTML"
    )

@dp.message(lambda m: m.text == "👥 Пользователи")
async def btn_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    users = get_all_users(20)
    text = "👥 **Топ пользователей:**\n\n"
    for uid, username, first_name, msgs, _ in users[:10]:
        name = first_name or username or uid[:8]
        text += f"• {name} — {msgs} сообщений\n"
    await message.answer(text[:4000], parse_mode="HTML")

@dp.message(lambda m: m.text == "📰 Просмотр новостей")
async def btn_view_news(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    posts = get_pending_posts()
    if not posts:
        await message.answer("📭 Новостей нет")
        return
    
    for i, p in enumerate(posts[:5], 1):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🗑 Удалить #{i}", callback_data=f"delete_news_{i-1}")]
        ])
        await message.answer(
            f"📰 **{i}. {p['title'][:60]}**\n\n{p['post'][:200]}...\n🔗 [Источник]({p['link']})",
            parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb
        )
    
    if len(posts) > 5:
        await message.answer(f"... и ещё {len(posts) - 5} новостей")

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
        success = await publish_to_channel(None, "text", p['post'])
        if success:
            mark_posted(p['title'], p['link'])
        await asyncio.sleep(2)
    clear_pending_posts()
    await message.answer(f"✅ Опубликовано {len(posts)} постов")

@dp.message(lambda m: m.text == "📝 Пост в канал")
async def btn_post_text(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    waiting_for_post_text[message.from_user.id] = True
    await message.answer("📝 Отправь текст для публикации в канал:")

@dp.message(lambda m: m.text == "🖼️ Фото в канал")
async def btn_post_photo(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    waiting_for_post_photo[message.from_user.id] = True
    await message.answer("🖼️ Отправь фото для публикации в канал (можно с подписью):")

@dp.message(lambda m: m.text == "🎥 Видео в канал")
async def btn_post_video(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    waiting_for_post_video[message.from_user.id] = True
    await message.answer("🎥 Отправь видео для публикации в канал (можно с подписью):")

@dp.message(lambda m: m.text == "⏹️ Остановить мониторинг")
async def btn_stop_monitoring(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    global monitoring_active
    monitoring_active = False
    await message.answer("⏹️ Мониторинг RSS остановлен")

@dp.message(lambda m: m.text == "▶️ Запустить мониторинг")
async def btn_start_monitoring(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    global monitoring_active
    monitoring_active = True
    await message.answer("▶️ Мониторинг RSS запущен")

@dp.message(lambda m: m.text == "🗑 Очистить очередь")
async def btn_clear_queue(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    clear_pending_posts()
    await message.answer("🗑 Очередь новостей очищена")

@dp.message(lambda m: m.text == "🧹 Очистить БД")
async def btn_clear_db(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    clear_all_history()
    await message.answer("🧹 База данных очищена")

# ========== ОБРАБОТЧИКИ ПУБЛИКАЦИИ ==========
@dp.message(lambda m: waiting_for_post_text.get(m.from_user.id, False))
async def handle_post_text(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    waiting_for_post_text[message.from_user.id] = False
    success = await publish_to_channel(None, "text", message.text)
    if success:
        await message.answer("✅ Текст опубликован в канале")
    else:
        await message.answer("❌ Ошибка публикации")

@dp.message(lambda m: waiting_for_post_photo.get(m.from_user.id, False) and m.photo)
async def handle_post_photo(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    waiting_for_post_photo[message.from_user.id] = False
    photo = message.photo[-1].file_id
    caption = message.caption
    success = await publish_to_channel(None, "photo", photo, caption)
    if success:
        await message.answer("✅ Фото опубликовано в канале")
    else:
        await message.answer("❌ Ошибка публикации")

@dp.message(lambda m: waiting_for_post_video.get(m.from_user.id, False) and m.video)
async def handle_post_video(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    waiting_for_post_video[message.from_user.id] = False
    video = message.video.file_id
    caption = message.caption
    success = await publish_to_channel(None, "video", video, caption)
    if success:
        await message.answer("✅ Видео опубликовано в канале")
    else:
        await message.answer("❌ Ошибка публикации")

# ========== ОБРАБОТЧИК УДАЛЕНИЯ НОВОСТЕЙ ==========
@dp.callback_query(lambda c: c.data.startswith("delete_news_"))
async def delete_news_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет прав")
        return
    
    index = int(callback.data.split("_")[2])
    posts = get_pending_posts()
    
    if 0 <= index < len(posts):
        deleted = posts.pop(index)
        # Обновляем глобальный список
        global pending_posts
        pending_posts[:] = posts
        await callback.answer(f"🗑 Удалено: {deleted['title'][:50]}")
        await callback.message.edit_text(f"✅ Новость удалена: {deleted['title'][:50]}")
    else:
        await callback.answer("❌ Новость не найдена")

# ========== ОБРАБОТЧИК РЕЖИМОВ ==========
@dp.callback_query(lambda c: c.data.startswith("mode_"))
async def process_mode_callback(callback: types.CallbackQuery):
    mode_map = {
        "mode_short": "short",
        "mode_long": "long",
        "mode_expert": "expert",
        "mode_meme": "meme",
    }
    mode = mode_map.get(callback.data, "short")
    user_modes[callback.from_user.id] = mode
    await callback.answer(f"Режим изменён на {mode}")
    await callback.message.edit_text(f"✅ Режим **{mode}** включён")

# ========== ОБРАБОТЧИК ТЕКСТА ==========
user_modes = {}

@dp.message()
async def chat_handler(message: types.Message):
    user_id = message.from_user.id
    
    # Пропускаем, если в режиме ожидания публикации
    if waiting_for_post_text.get(user_id, False):
        return
    if waiting_for_post_photo.get(user_id, False):
        return
    if waiting_for_post_video.get(user_id, False):
        return
    
    text = message.text
    if not text:
        return
    
    if text.startswith('/'):
        return
    
    # Обработка обычных вопросов
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
    else:
        mode = user_modes.get(user_id, "short")
        prompt = f"Ты Нико. Ответь кратко, 1-2 предложения. Пользователь: {text}"
        answer = await ask_ai(prompt)
        await message.answer(answer, parse_mode="HTML")

# ========== ЗАПУСК ==========
async def main():
    init_db()
    logger.info("🚀 Нико 3.1 запускается...")
    
    # Запускаем мониторинг
    global monitoring_task
    monitoring_task = asyncio.create_task(monitor_rss())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
