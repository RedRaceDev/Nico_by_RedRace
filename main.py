import asyncio
import os
import time
from datetime import datetime, timedelta
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from scraper import (
    chat_with_nico, generate_post, get_calendar, 
    get_morning_digest, search_web, get_f1_results,
    monitor_rss, mark_as_posted, get_bbc_news
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"

STATE = {"start_time": time.time()}
bot = None
MONITORING_ACTIVE = True

# === Обработчик новых новостей ===
async def on_new_post(post_text: str, title: str, link: str):
    """Когда появляется новость — сразу публикуем в канал"""
    try:
        await bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML")
        mark_as_posted(title, link)
        print(f"✅ Пост опубликован: {title} в {datetime.now()}")
        
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
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Сделать пост", callback_data="make_post"),
        InlineKeyboardButton("🔍 Поиск", callback_data="search"),
        InlineKeyboardButton("📅 Календарь", callback_data="calendar"),
        InlineKeyboardButton("📰 Результаты Монако", callback_data="results_monaco"),
        InlineKeyboardButton("📨 Утренний дайджест", callback_data="morning_digest"),
        InlineKeyboardButton("📊 Статус", callback_data="status")
    )
    
    uptime = time.time() - STATE["start_time"]
    await bot.send_message(m.chat.id,
        f"👑 **NICO 3.0 — Гоночный инженер**\n\n"
        f"⚡️ Работаю {int(uptime//3600)}ч\n"
        f"🎯 Режим: Мгновенный автопостинг\n"
        f"📡 RSS: 11 источников\n"
        f"🌐 BBC Sport: {'✅' if MCP_AVAILABLE else '❌'}\n\n"
        f"<i>Новости появляются — сразу в канал</i>",
        parse_mode="HTML", reply_markup=kb)

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
        await bot.answer_callback_query(call.id, "Генерирую пост...")
        post = await generate_post()
        await bot.send_message(call.message.chat.id, post, parse_mode="HTML")
    
    elif call.data == "search":
        await bot.answer_callback_query(call.id)
        await bot.send_message(call.message.chat.id, "🔍 Напиши поисковый запрос:")
    
    elif call.data == "calendar":
        cal = await get_calendar()
        await bot.send_message(call.message.chat.id, cal, parse_mode="HTML")
    
    elif call.data == "results_monaco":
        await bot.answer_callback_query(call.id, "Загружаю результаты...")
        results = await get_f1_results("Монако", 2026)
        await bot.send_message(call.message.chat.id, results, parse_mode="HTML")
    
    elif call.data == "morning_digest":
        await bot.answer_callback_query(call.id, "Генерирую дайджест...")
        digest = await get_morning_digest()
        await bot.send_message(call.message.chat.id, digest, parse_mode="HTML")
    
    elif call.data == "status":
        await bot.answer_callback_query(call.id)
        await bot.send_message(call.message.chat.id,
            f"📊 **Статус Нико**\n\n"
            f"✅ RSS мониторинг: {'активен' if MONITORING_ACTIVE else 'выключен'}\n"
            f"📡 Источников: 11 RSS + BBC Sport\n"
            f"⏱ Интервал проверки: 60 сек\n"
            f"🎯 Режим: мгновенная публикация\n"
            f"🤖 ИИ: Pollinations + OpenRouter",
            parse_mode="HTML")
    
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

async def handle_message(m):
    if m.text.startswith('/'):
        return
    
    if hasattr(handle_message, 'waiting_for_search') and handle_message.waiting_for_search:
        handle_message.waiting_for_search = False
        await handle_search(m)
        return
    
    status = await bot.send_message(m.chat.id, "🤔 Думаю...")
    answer = await chat_with_nico(m.text)
    await bot.delete_message(m.chat.id, status.message_id)
    await bot.send_message(m.chat.id, answer, parse_mode="HTML")

async def morning_digest_worker():
    """Утренний дайджест в 9:00"""
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
    print("🌐 BBC Sport подключён")
    print("🤖 ИИ: Pollinations + OpenRouter")
    
    await bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())
