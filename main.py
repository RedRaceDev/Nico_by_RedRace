import asyncio
import os
import time
from datetime import datetime
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from scraper import (
    chat_with_nico, generate_post_on_topic, generate_random_post,
    get_f1_calendar, get_morning_digest, search_web,
    monitor_rss, mark_as_posted
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"

STATE = {"start_time": time.time()}
MONITORING_ACTIVE = True
bot = None

posts_count = 0
dialogs_count = 0

def get_posts_count(): return posts_count
def get_dialogs_count(): return dialogs_count
def inc_posts(): global posts_count; posts_count += 1
def inc_dialogs(): global dialogs_count; dialogs_count += 1

async def on_new_post(post_text: str, title: str, link: str):
    if not MONITORING_ACTIVE:
        return
    try:
        await bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML")
        mark_as_posted(title, link)
        inc_posts()
        print(f"✅ Пост: {title[:50]}...")
    except Exception as e:
        print(f"Ошибка: {e}")

async def admin_panel(m):
    if m.chat.id not in ADMIN_IDS:
        await bot.send_message(m.chat.id, "⛔ Только для админа")
        return
    
    uptime = time.time() - STATE["start_time"]
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Пост на тему", callback_data="make_post"),
        InlineKeyboardButton("🎲 Случайный пост", callback_data="random_post"),
        InlineKeyboardButton("🔍 Поиск", callback_data="search"),
        InlineKeyboardButton("📅 Календарь", callback_data="calendar"),
        InlineKeyboardButton("📨 Дайджест", callback_data="morning_digest"),
        InlineKeyboardButton("📊 Статус", callback_data="status"),
        InlineKeyboardButton("🛑 Стоп", callback_data="stop_monitor"),
        InlineKeyboardButton("▶️ Старт", callback_data="start_monitor")
    )
    
    await bot.send_message(m.chat.id,
        f"👑 **NICO 4.0**\n\n"
        f"⚡️ Аптайм: {int(uptime//3600)}ч\n"
        f"📡 Мониторинг: {'✅' if MONITORING_ACTIVE else '⛔'}\n"
        f"📝 Постов: {get_posts_count()}\n"
        f"💬 Диалогов: {get_dialogs_count()}",
        parse_mode="HTML", reply_markup=kb)

async def user_panel(m):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📅 Календарь", callback_data="calendar"),
        InlineKeyboardButton("🏁 О боте", callback_data="about")
    )
    await bot.send_message(m.chat.id,
        f"🏎️ **NICO 4.0**\n\nПривет! Я Нико. Задавай вопросы про F1.\n\n<i>Просто напиши сообщение</i>",
        parse_mode="HTML", reply_markup=kb)

waiting_for_search = False
waiting_for_topic = False

async def handle_callbacks(call):
    global waiting_for_search, waiting_for_topic, MONITORING_ACTIVE
    
    if call.data == "make_post":
        waiting_for_topic = True
        await bot.send_message(call.message.chat.id, "📝 Тема:")
    
    elif call.data == "random_post":
        await bot.answer_callback_query(call.id, "Генерирую...")
        post = await generate_random_post()
        await bot.send_message(call.message.chat.id, post, parse_mode="HTML")
        inc_posts()
    
    elif call.data == "search":
        waiting_for_search = True
        await bot.send_message(call.message.chat.id, "🔍 Запрос:")
    
    elif call.data == "calendar":
        cal = await get_f1_calendar()
        await bot.send_message(call.message.chat.id, cal, parse_mode="HTML")
    
    elif call.data == "morning_digest":
        await bot.answer_callback_query(call.id, "Генерирую...")
        digest = await get_morning_digest()
        await bot.send_message(call.message.chat.id, digest, parse_mode="HTML")
    
    elif call.data == "status":
        uptime = time.time() - STATE["start_time"]
        await bot.send_message(call.message.chat.id,
            f"⚡️ Аптайм: {int(uptime//3600)}ч\n📝 Постов: {get_posts_count()}\n💬 Диалогов: {get_dialogs_count()}")
    
    elif call.data == "stop_monitor":
        MONITORING_ACTIVE = False
        await bot.answer_callback_query(call.id, "Мониторинг остановлен")
    
    elif call.data == "start_monitor":
        MONITORING_ACTIVE = True
        await bot.answer_callback_query(call.id, "Мониторинг запущен")
    
    elif call.data == "about":
        await bot.send_message(call.message.chat.id, "🏎️ **NICO 4.0**\n\nГоночный инженер.\n\nRedRace Development")

async def handle_message(m):
    global waiting_for_search, waiting_for_topic
    if m.text.startswith('/'):
        return
    
    if waiting_for_search:
        waiting_for_search = False
        status = await bot.send_message(m.chat.id, f"🔍 Ищу...")
        results = await search_web(m.text)
        await bot.delete_message(m.chat.id, status.message_id)
        await bot.send_message(m.chat.id, f"🌐 **Результаты:**\n\n{results[:3000]}", parse_mode="HTML")
        return
    
    if waiting_for_topic:
        waiting_for_topic = False
        status = await bot.send_message(m.chat.id, f"📝 Генерирую...")
        post = await generate_post_on_topic(m.text)
        await bot.delete_message(m.chat.id, status.message_id)
        await bot.send_message(m.chat.id, post, parse_mode="HTML")
        inc_posts()
        return
    
    status = await bot.send_message(m.chat.id, "🤔 Думаю...")
    answer = await chat_with_nico(m.text)
    await bot.delete_message(m.chat.id, status.message_id)
    await bot.send_message(m.chat.id, answer, parse_mode="HTML")
    inc_dialogs()

async def start_command(m):
    if m.chat.id in ADMIN_IDS:
        await admin_panel(m)
    else:
        await user_panel(m)

async def main():
    global bot
    bot = AsyncTeleBot(BOT_TOKEN)
    
    @bot.message_handler(commands=['start', 'admin'])
    async def start_cmd(m):
        await start_command(m)
    
    @bot.message_handler(func=lambda m: True, content_types=['text'])
    async def msg_handler(m):
        await handle_message(m)
    
    @bot.callback_query_handler(func=lambda call: True)
    async def callback_handler(call):
        await handle_callbacks(call)
    
    asyncio.create_task(monitor_rss(on_new_post))
    
    print("🚀 NICO 4.0 STARTED")
    print("📡 RSS мониторинг активен")
    
    await bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())
