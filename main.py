import asyncio
import os
import time
from datetime import datetime, timedelta
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from scraper import (
    chat_with_nico, generate_post_on_topic, generate_random_post,
    get_f1_calendar, get_morning_digest, search_web, get_f1_results_2026,
    monitor_rss, mark_as_posted, get_all_news, ask_pollinations
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"

STATE = {"start_time": time.time()}
MONITORING_ACTIVE = True
bot = None

# === Счетчики ===
posts_count = 0
dialogs_count = 0

def get_posts_count():
    return posts_count

def get_dialogs_count():
    return dialogs_count

def inc_posts():
    global posts_count
    posts_count += 1

def inc_dialogs():
    global dialogs_count
    dialogs_count += 1

# === Обработчик новых новостей ===
async def on_new_post(post_text: str, title: str, link: str):
    global MONITORING_ACTIVE
    if not MONITORING_ACTIVE:
        return
    
    try:
        await bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML")
        mark_as_posted(title, link)
        inc_posts()
        print(f"✅ Пост опубликован: {title[:50]}... в {datetime.now()}")
        
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, f"📰 Новый пост:\n{title[:100]}...")
            except:
                pass
    except Exception as e:
        print(f"Ошибка публикации: {e}")

# === Админ панель ===
async def admin_panel(m):
    if m.chat.id not in ADMIN_IDS:
        await bot.send_message(m.chat.id, "⛔ Только для админа")
        return
    
    global MONITORING_ACTIVE
    uptime = time.time() - STATE["start_time"]
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Пост на тему", callback_data="make_post"),
        InlineKeyboardButton("🎲 Случайный пост", callback_data="random_post"),
        InlineKeyboardButton("🔍 Поиск", callback_data="search"),
        InlineKeyboardButton("📅 Календарь", callback_data="calendar"),
        InlineKeyboardButton("📰 Результаты Монако", callback_data="results_monaco"),
        InlineKeyboardButton("📨 Утренний дайджест", callback_data="morning_digest"),
        InlineKeyboardButton("📊 Статистика", callback_data="status"),
        InlineKeyboardButton("🛑 Стоп мониторинг", callback_data="stop_monitor"),
        InlineKeyboardButton("▶️ Старт мониторинг", callback_data="start_monitor")
    )
    
    status = (
        f"👑 **NICO 3.0 — Админ-панель**\n\n"
        f"⚡️ Аптайм: {int(uptime//3600)}ч\n"
        f"📡 RSS мониторинг: {'✅ активен' if MONITORING_ACTIVE else '⛔ остановлен'}\n"
        f"📝 Постов в канале: {get_posts_count()}\n"
        f"💬 Диалогов: {get_dialogs_count()}\n"
        f"🤖 ИИ: Pollinations + OpenRouter\n\n"
        f"<i>Новости появляются — пост через 1-2 минуты</i>"
    )
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=kb)

# === Пользовательская панель ===
async def user_panel(m):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📅 Календарь", callback_data="calendar"),
        InlineKeyboardButton("🏁 О боте", callback_data="about")
    )
    
    await bot.send_message(m.chat.id,
        f"🏎️ **NICO 3.0 — Гоночный инженер**\n\n"
        f"Привет! Я Нико. Задавай любые вопросы про F1.\n\n"
        f"<i>Просто напиши сообщение</i>",
        parse_mode="HTML", reply_markup=kb)

# === Обработчики ===
async def handle_callbacks(call):
    if call.data == "make_post":
        await bot.answer_callback_query(call.id, "Введи тему поста")
        await bot.send_message(call.message.chat.id, "📝 Напиши тему для поста:")
    
    elif call.data == "random_post":
        await bot.answer_callback_query(call.id, "Генерирую случайный пост...")
        post = await generate_random_post()
        post = clean_post(post)
        await bot.send_message(call.message.chat.id, post, parse_mode="HTML")
        await bot.send_message(CHANNEL_ID, post, parse_mode="HTML")
        inc_posts()
    
    elif call.data == "search":
        await bot.answer_callback_query(call.id)
        await bot.send_message(call.message.chat.id, "🔍 Напиши поисковый запрос:")
    
    elif call.data == "calendar":
        cal = await get_f1_calendar()
        await bot.send_message(call.message.chat.id, cal, parse_mode="HTML")
    
    elif call.data == "results_monaco":
        await bot.answer_callback_query(call.id, "Загружаю результаты...")
        results = await get_f1_results_2026("Монако")
        await bot.send_message(call.message.chat.id, results, parse_mode="HTML")
    
    elif call.data == "morning_digest":
        await bot.answer_callback_query(call.id, "Генерирую дайджест...")
        digest = await get_morning_digest()
        await bot.send_message(call.message.chat.id, digest, parse_mode="HTML")
    
    elif call.data == "status":
        await bot.answer_callback_query(call.id)
        uptime = time.time() - STATE["start_time"]
        await bot.send_message(call.message.chat.id,
            f"📊 **Статус Нико**\n\n"
            f"✅ RSS мониторинг: {'активен' if MONITORING_ACTIVE else 'выключен'}\n"
            f"📡 Источников: {len(RSS_SOURCES)} RSS\n"
            f"⏱ Интервал проверки: 60 сек\n"
            f"🎯 Режим: мгновенная публикация\n"
            f"🤖 ИИ: Pollinations + OpenRouter\n"
            f"⚡️ Аптайм: {int(uptime//3600)}ч\n"
            f"📝 Постов: {get_posts_count()}\n"
            f"💬 Диалогов: {get_dialogs_count()}",
            parse_mode="HTML")
    
    elif call.data == "stop_monitor":
        global MONITORING_ACTIVE
        MONITORING_ACTIVE = False
        await bot.answer_callback_query(call.id, "Мониторинг остановлен")
        await admin_panel(call.message)
    
    elif call.data == "start_monitor":
        MONITORING_ACTIVE = True
        await bot.answer_callback_query(call.id, "Мониторинг запущен")
        await admin_panel(call.message)
    
    elif call.data == "about":
        await bot.send_message(call.message.chat.id,
            f"🏎️ **NICO 3.0**\n\n"
            f"Гоночный инженер и эксперт Формулы-1.\n\n"
            f"<code>Nico 3.0 | RedRace Development</code>",
            parse_mode="HTML")

async def handle_search(m):
    query = m.text
    status = await bot.send_message(m.chat.id, f"🔍 Ищу: {query}...")
    results = await search_web(query)
    await bot.delete_message(m.chat.id, status.message_id)
    await bot.send_message(m.chat.id, f"🌐 **Результаты:**\n\n{results[:3000]}", parse_mode="HTML")

async def handle_topic_post(m):
    topic = m.text
    status = await bot.send_message(m.chat.id, f"📝 Генерирую пост на тему: {topic}...")
    post = await generate_post_on_topic(topic)
    post = clean_post(post)
    await bot.delete_message(m.chat.id, status.message_id)
    await bot.send_message(m.chat.id, post, parse_mode="HTML")
    await bot.send_message(CHANNEL_ID, post, parse_mode="HTML")
    inc_posts()

async def handle_message(m):
    if m.text.startswith('/'):
        return
    
    # Ожидание поиска
    if hasattr(handle_message, 'waiting_for_search') and handle_message.waiting_for_search:
        handle_message.waiting_for_search = False
        await handle_search(m)
        return
    
    # Ожидание темы поста
    if hasattr(handle_message, 'waiting_for_topic') and handle_message.waiting_for_topic:
        handle_message.waiting_for_topic = False
        await handle_topic_post(m)
        return
    
    # Обычный чат
    status = await bot.send_message(m.chat.id, "🤔 Думаю...")
    answer = await chat_with_nico(m.text)
    await bot.delete_message(m.chat.id, status.message_id)
    await bot.send_message(m.chat.id, answer, parse_mode="HTML")
    inc_dialogs()

async def morning_digest_worker():
    while True:
        now = datetime.now()
        target = now.replace(hour=9, minute=0, second=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        
        try:
            digest = await get_morning_digest()
            await bot.send_message(CHANNEL_ID, digest, parse_mode="HTML")
            print(f"☀️ Утренний дайджест отправлен в {datetime.now()}")
        except Exception as e:
            print(f"Digest error: {e}")

async def start_command(m):
    if m.chat.id in ADMIN_IDS:
        await admin_panel(m)
    else:
        await user_panel(m)

# === Запуск ===
async def main():
    global bot
    bot = AsyncTeleBot(BOT_TOKEN)
    
    bot.register_message_handler(start_command, commands=['start', 'admin'])
    bot.register_message_handler(handle_message, func=lambda m: True, content_types=['text'])
    bot.register_callback_query_handler(handle_callbacks, func=lambda call: True)
    
    # Запускаем мониторинг RSS
    asyncio.create_task(monitor_rss(on_new_post))
    asyncio.create_task(morning_digest_worker())
    
    print("🚀 NICO 3.0 STARTED")
    print("📡 RSS мониторинг активен (проверка каждые 60 сек)")
    print("🤖 ИИ: Pollinations AI + OpenRouter fallback")
    print("👑 Админ: @RedRaceDev")
    
    await bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())
