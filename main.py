import asyncio
import os
import time
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from scraper import (
    monitor, post_on_topic, random_post, calendar, chat_reply, search_f1, mark_posted
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"

bot = None
monitoring = True
posts_cnt = 0
dialogs_cnt = 0
start_time = time.time()

def inc_posts():
    global posts_cnt
    posts_cnt += 1

def inc_dialogs():
    global dialogs_cnt
    dialogs_cnt += 1

async def on_post(text, title, link):
    global monitoring
    if not monitoring:
        return
    try:
        await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
        mark_posted(title, link)
        inc_posts()
        print(f"✅ Пост опубликован: {title[:50]}...")
    except Exception as e:
        print(f"❌ Ошибка публикации: {e}")

async def admin_panel(m):
    if m.chat.id not in ADMIN_IDS:
        await bot.send_message(m.chat.id, "⛔ Только для админа")
        return
    
    global monitoring
    uptime = time.time() - start_time
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Пост на тему", callback_data="topic"),
        InlineKeyboardButton("🎲 Случайный пост", callback_data="random"),
        InlineKeyboardButton("🔍 Поиск", callback_data="search"),
        InlineKeyboardButton("📅 Календарь", callback_data="calendar"),
        InlineKeyboardButton("📊 Статистика", callback_data="status"),
        InlineKeyboardButton("🛑 Остановить", callback_data="stop"),
        InlineKeyboardButton("▶️ Запустить", callback_data="start")
    )
    
    status_text = (
        f"👑 **NICO 4.0 — Админ-панель**\n\n"
        f"⚡️ Аптайм: {int(uptime//3600)}ч {int((uptime%3600)//60)}м\n"
        f"📡 Мониторинг: {'✅ Активен' if monitoring else '⛔ Остановлен'}\n"
        f"📝 Постов в канале: {posts_cnt}\n"
        f"💬 Диалогов: {dialogs_cnt}\n"
        f"🤖 ИИ: Pollinations + OpenRouter\n\n"
        f"<i>Новости проверяются ИИ перед публикацией</i>"
    )
    await bot.send_message(m.chat.id, status_text, parse_mode="HTML", reply_markup=kb)

async def user_panel(m):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📅 Календарь", callback_data="calendar"),
        InlineKeyboardButton("🏁 О боте", callback_data="about")
    )
    await bot.send_message(m.chat.id,
        f"🏎️ **NICO 4.0 — Гоночный инженер**\n\n"
        f"Привет! Я Нико. Задавай любые вопросы про F1.\n\n"
        f"<i>Просто напиши сообщение</i>",
        parse_mode="HTML", reply_markup=kb)

waiting_for_search = False
waiting_for_topic = False

async def handle_calls(call):
    global monitoring, waiting_for_search, waiting_for_topic
    
    if call.data == "topic":
        waiting_for_topic = True
        await bot.send_message(call.message.chat.id, "📝 Напиши тему для поста:")
        await bot.answer_callback_query(call.id)
    
    elif call.data == "random":
        await bot.answer_callback_query(call.id, "Генерирую случайный пост...")
        post = await random_post()
        await bot.send_message(call.message.chat.id, post, parse_mode="HTML")
        inc_posts()
    
    elif call.data == "search":
        waiting_for_search = True
        await bot.send_message(call.message.chat.id, "🔍 Напиши поисковый запрос:")
        await bot.answer_callback_query(call.id)
    
    elif call.data == "calendar":
        cal = await calendar()
        await bot.send_message(call.message.chat.id, cal, parse_mode="HTML")
        await bot.answer_callback_query(call.id)
    
    elif call.data == "status":
        uptime = time.time() - start_time
        await bot.send_message(call.message.chat.id,
            f"📊 **Статистика**\n\n"
            f"⚡️ Аптайм: {int(uptime//3600)}ч\n"
            f"📝 Постов: {posts_cnt}\n"
            f"💬 Диалогов: {dialogs_cnt}\n"
            f"🎯 Мониторинг: {'Активен' if monitoring else 'Остановлен'}",
            parse_mode="HTML")
        await bot.answer_callback_query(call.id)
    
    elif call.data == "stop":
        monitoring = False
        await bot.answer_callback_query(call.id, "✅ Мониторинг остановлен")
        await admin_panel(call.message)
    
    elif call.data == "start":
        monitoring = True
        await bot.answer_callback_query(call.id, "✅ Мониторинг запущен")
        await admin_panel(call.message)
    
    elif call.data == "about":
        await bot.send_message(call.message.chat.id,
            f"🏎️ **NICO 4.0**\n\n"
            f"Гоночный инженер и эксперт Формулы-1.\n\n"
            f"<code>Nico 4.0 | RedRace Development</code>",
            parse_mode="HTML")
        await bot.answer_callback_query(call.id)

async def handle_msg(m):
    global waiting_for_search, waiting_for_topic
    
    if m.text.startswith('/'):
        return
    
    if waiting_for_search:
        waiting_for_search = False
        status_msg = await bot.send_message(m.chat.id, f"🔍 Ищу: {m.text}...")
        results = await search_f1(m.text)
        await bot.delete_message(m.chat.id, status_msg.message_id)
        await bot.send_message(m.chat.id, f"🌐 **Результаты поиска:**\n\n{results[:3000]}", parse_mode="HTML")
        return
    
    if waiting_for_topic:
        waiting_for_topic = False
        status_msg = await bot.send_message(m.chat.id, f"📝 Генерирую пост на тему: {m.text}...")
        post = await post_on_topic(m.text)
        await bot.delete_message(m.chat.id, status_msg.message_id)
        await bot.send_message(m.chat.id, post, parse_mode="HTML")
        inc_posts()
        return
    
    status_msg = await bot.send_message(m.chat.id, "🤔 Думаю...")
    answer = await chat_reply(m.text)
    await bot.delete_message(m.chat.id, status_msg.message_id)
    await bot.send_message(m.chat.id, answer, parse_mode="HTML")
    inc_dialogs()

async def start_cmd(m):
    if m.chat.id in ADMIN_IDS:
        await admin_panel(m)
    else:
        await user_panel(m)

async def main():
    global bot
    bot = AsyncTeleBot(BOT_TOKEN)
    
    @bot.message_handler(commands=['start', 'admin'])
    async def start_handler(m):
        await start_cmd(m)
    
    @bot.message_handler(func=lambda m: True, content_types=['text'])
    async def msg_handler(m):
        await handle_msg(m)
    
    @bot.callback_query_handler(func=lambda call: True)
    async def callback_handler(call):
        await handle_calls(call)
    
    asyncio.create_task(monitor(on_post))
    
    print("🚀 NICO 4.0 STARTED")
    print("📡 RSS мониторинг активен")
    print("🤖 ИИ: Pollinations AI + OpenRouter fallback")
    print("👑 Админ: @RedRaceDev")
    
    await bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())
