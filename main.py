import asyncio
import os
import time
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from scraper import monitor, post_on_topic, random_post, calendar, chat_reply, search_f1, mark_posted

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
        print(f"✅ {title[:50]}")
    except Exception as e:
        print(f"❌ {e}")

async def admin_panel(m):
    if m.chat.id not in ADMIN_IDS:
        await bot.send_message(m.chat.id, "⛔ Только админ")
        return
    
    global monitoring
    uptime = time.time() - start_time
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Пост на тему", callback_data="topic"),
        InlineKeyboardButton("🎲 Рандом", callback_data="random"),
        InKeyboardButton("🔍 Поиск", callback_data="search"),
        InlineKeyboardButton("📅 Календарь", callback_data="calendar"),
        InlineKeyboardButton("📊 Статистика", callback_data="status"),
        InlineKeyboardButton("🛑 Стоп", callback_data="stop"),
        InlineKeyboardButton("▶️ Старт", callback_data="start")
    )
    
    await bot.send_message(m.chat.id,
        f"👑 **NICO**\n\n⚡️ {int(uptime//3600)}ч\n📡 Мониторинг: {'✅' if monitoring else '⛔'}\n📝 {posts_cnt}\n💬 {dialogs_cnt}",
        parse_mode="HTML", reply_markup=kb)

async def user_panel(m):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📅 Календарь", callback_data="calendar"),
        InlineKeyboardButton("🏁 О боте", callback_data="about")
    )
    await bot.send_message(m.chat.id,
        f"🏎️ **NICO**\n\nПривет! Я Нико.",
        parse_mode="HTML", reply_markup=kb)

wait_search = False
wait_topic = False

async def handle_calls(call):
    global monitoring, wait_search, wait_topic
    
    if call.data == "topic":
        wait_topic = True
        await bot.send_message(call.message.chat.id, "📝 Тема:")
    elif call.data == "random":
        await bot.answer_callback_query(call.id, "Генерирую...")
        post = await random_post()
        await bot.send_message(call.message.chat.id, post, parse_mode="HTML")
        inc_posts()
    elif call.data == "search":
        wait_search = True
        await bot.send_message(call.message.chat.id, "🔍 Запрос:")
    elif call.data == "calendar":
        await bot.send_message(call.message.chat.id, await calendar(), parse_mode="HTML")
    elif call.data == "status":
        uptime = time.time() - start_time
        await bot.send_message(call.message.chat.id, f"⚡️ {int(uptime//3600)}ч\n📝 {posts_cnt}\n💬 {dialogs_cnt}")
    elif call.data == "stop":
        monitoring = False
        await bot.answer_callback_query(call.id, "Мониторинг остановлен")
    elif call.data == "start":
        monitoring = True
        await bot.answer_callback_query(call.id, "Мониторинг запущен")
    elif call.data == "about":
        await bot.send_message(call.message.chat.id, "🏎️ **NICO**\nГоночный инженер.\nRedRace Development")
    await bot.answer_callback_query(call.id)

async def handle_msg(m):
    global wait_search, wait_topic
    
    if m.text.startswith('/'):
        return
    if wait_search:
        wait_search = False
        status = await bot.send_message(m.chat.id, "🔍 Ищу...")
        res = await search_f1(m.text)
        await bot.delete_message(m.chat.id, status.message_id)
        await bot.send_message(m.chat.id, f"🌐 **Результаты:**\n\n{res[:3000]}")
        return
    if wait_topic:
        wait_topic = False
        status = await bot.send_message(m.chat.id, "📝 Генерирую...")
        post = await post_on_topic(m.text)
        await bot.delete_message(m.chat.id, status.message_id)
        await bot.send_message(m.chat.id, post, parse_mode="HTML")
        inc_posts()
        return
    status = await bot.send_message(m.chat.id, "🤔 Думаю...")
    ans = await chat_reply(m.text)
    await bot.delete_message(m.chat.id, status.message_id)
    await bot.send_message(m.chat.id, ans, parse_mode="HTML")
    inc_dialogs()

async def start_cmd(m):
    if m.chat.id in ADMIN_IDS:
        await admin_panel(m)
    else:
        await user_panel(m)

async def main():
    global bot
    bot = AsyncTeleBot(BOT_TOKEN)
    bot.register_message_handler(start_cmd, commands=['start', 'admin'])
    bot.register_message_handler(handle_msg, func=lambda m: True, content_types=['text'])
    bot.register_callback_query_handler(handle_calls, func=lambda call: True)
    asyncio.create_task(monitor(on_post))
    print("🚀 NICO STARTED")
    await bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())
