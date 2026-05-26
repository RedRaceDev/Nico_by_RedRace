import asyncio
import os
import time
import sqlite3
from datetime import datetime, timedelta
from aiohttp import web
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from scraper import generate_posts_pack, get_f1_calendar, chat_with_nico, search_web
from database import init_db, get_stats, save_post, get_conversation_history, save_conversation

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set")

# === КОНФИГ ===
ADMIN_IDS = [7025868617]  # Твой Telegram ID

STATE = {
    "pub_mode": "DIRECT",
    "start_time": time.time(),
    "auto_interval": 14400,
    "chat_mode": False
}

DIGEST_BUFFER = []
ADMIN_CHAT_ID = None
bot = None

# Инициализируем базу данных
init_db()

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ========== HTTP СЕРВЕР ==========
async def health_check(request):
    return web.Response(text="Nico 3.0 is alive", status=200)

async def start_keep_alive_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Keep-alive server on port {port}")

# ========== ОТПРАВКА ПОСТОВ ==========
async def send_crafted_post(target_chat, text, photo_url=None, with_publish_button=False):
    if not bot:
        return
    kb = None
    if with_publish_button:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🚀 ОПУБЛИКОВАТЬ В КАНАЛ", callback_data="pub_direct_action"))
    try:
        if photo_url:
            await bot.send_photo(target_chat, photo_url, caption=text, parse_mode="HTML", reply_markup=kb)
        else:
            await bot.send_message(target_chat, text, parse_mode="HTML", reply_markup=kb)
    except:
        try:
            await bot.send_message(target_chat, text, parse_mode="HTML", reply_markup=kb)
        except:
            pass

# ========== АДМИНСКАЯ КОНСОЛЬ (ПОЛНАЯ) ==========
async def admin_panel(m):
    if not is_admin(m.chat.id):
        await bot.send_message(m.chat.id, "⛔ Эта команда только для администратора.")
        return
    
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = m.chat.id
    uptime = time.time() - STATE["start_time"]
    stats = get_stats()
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📰 Сделать пост", callback_data="auto_post"),
        InlineKeyboardButton("🔍 Ручной скан", callback_data="force_scan"),
        InlineKeyboardButton("📅 Календарь", callback_data="calendar"),
        InlineKeyboardButton("💬 Режим чата", callback_data="chat_mode"),
        InlineKeyboardButton("📦 Дайджест", callback_data="rel_dig"),
        InlineKeyboardButton("📊 Статистика", callback_data="show_stats"),
        InlineKeyboardButton("👥 Пользователи", callback_data="show_users"),
        InlineKeyboardButton("📜 История", callback_data="show_history"),
        InlineKeyboardButton("🧠 Очистить БД", callback_data="forget_all"),
        InlineKeyboardButton("⚙️ Настройки", callback_data="settings")
    )
    
    status = (
        f"<b>👑 NICO ADMIN CONSOLE v3.0</b>\n"
        f"<code>═══════════════════════════</code>\n"
        f"├ 🕐 Аптайм: <code>{int(uptime//3600)}ч {int((uptime%3600)//60)}м</code>\n"
        f"├ 🎯 Режим: <b>{'Чат' if STATE['chat_mode'] else 'Авто'}</b>\n"
        f"├ ⏱ Интервал: <b>{STATE['auto_interval']//3600}ч</b>\n"
        f"├ 📦 Буфер: <b>{len(DIGEST_BUFFER)}</b> постов\n"
        f"├ 📝 Постов в БД: <b>{stats['posts']}</b>\n"
        f"├ 💬 Диалогов: <b>{stats['chats']}</b>\n"
        f"└ 👑 Админ: <b>Активен</b>\n"
        f"<code>═══════════════════════════</code>\n"
        f"<i>Nico 2.9 | Code by: RedRace Development</i>"
    )
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=kb)

# ========== ПОЛЬЗОВАТЕЛЬСКАЯ КОНСОЛЬ (УПРОЩЁННАЯ) ==========
async def user_panel(m):
    uptime = time.time() - STATE["start_time"]
    stats = get_stats()
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🏁 Старт", callback_data="user_start"),
        InlineKeyboardButton("ℹ️ О боте", callback_data="user_about"),
        InlineKeyboardButton("📅 Календарь", callback_data="user_calendar"),
        InlineKeyboardButton("🧠 Очистить память", callback_data="user_forget")
    )
    
    status = (
        f"<b>🏎️ NICO F1 ASSISTANT</b>\n"
        f"<code>─────────────────────</code>\n"
        f"├ 🤖 Я — Нико, твой гоночный инженер\n"
        f"├ 📊 Сервер работает: <code>{int(uptime//3600)}ч</code>\n"
        f"├ 💬 Диалогов сегодня: <b>{stats['chats']}</b>\n"
        f"└ 🔧 Версия: <b>2.9</b>\n"
        f"<code>─────────────────────</code>\n"
        f"<i>Просто напиши мне что-нибудь про F1!</i>\n\n"
        f"<code>Nico 2.9 | RedRace Development</code>"
    )
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=kb)

# ========== ПОЛЬЗОВАТЕЛЬСКИЕ КОМАНДЫ ==========
async def user_start(m):
    await bot.send_message(m.chat.id, 
        "🏎️ <b>Привет! Я Нико — твой гоночный инженер.</b>\n\n"
        "📌 <b>Что я умею:</b>\n"
        "• Отвечать на вопросы про F1\n"
        "• Рассказывать технические детали\n"
        "• Показывать календарь гонок\n"
        "• Искать новости (команда /ask)\n\n"
        "💬 <b>Просто напиши свой вопрос!</b>\n\n"
        "<code>Nico 2.9 | RedRace Development</code>", 
        parse_mode="HTML")

async def user_about(m):
    await bot.send_message(m.chat.id,
        "ℹ️ <b>О боте:</b>\n\n"
        "🤖 <b>Имя:</b> Nico\n"
        "👨‍💻 <b>Создатель:</b> RedRace Development\n"
        "📅 <b>Версия:</b> 2.9\n"
        "🎯 <b>Назначение:</b> Гоночный инженер и эксперт F1\n"
        "🧠 <b>Особенности:</b> Помнит диалоги, ищет в интернете\n\n"
        "<b>Команды:</b>\n"
        "/start — Главное меню\n"
        "/ask [вопрос] — Поиск в интернете\n"
        "/stats — Статистика\n"
        "/forget — Очистить историю\n\n"
        "<code>Nico 2.9 | RedRace Development</code>",
        parse_mode="HTML")

# ========== АДМИНСКИЕ ФУНКЦИИ ==========
async def show_users(m):
    if not is_admin(m.chat.id):
        return
    conn = sqlite3.connect("nico_bot.db")
    c = conn.cursor()
    c.execute("SELECT DISTINCT user_id, COUNT(*) FROM chat_history GROUP BY user_id ORDER BY COUNT(*) DESC")
    users = c.fetchall()
    conn.close()
    if not users:
        await bot.send_message(m.chat.id, "📭 Нет данных")
        return
    text = "👥 <b>Пользователи:</b>\n<code>─────────────</code>\n"
    for uid, count in users:
        text += f"🆔 <code>{uid}</code> — {count} сообщ.\n"
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def show_full_history(m):
    if not is_admin(m.chat.id):
        return
    conn = sqlite3.connect("nico_bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id, message, response, timestamp FROM chat_history ORDER BY timestamp DESC LIMIT 30")
    history = c.fetchall()
    conn.close()
    if not history:
        await bot.send_message(m.chat.id, "📭 История пуста")
        return
    text = "📜 <b>Последние диалоги:</b>\n<code>─────────────</code>\n\n"
    for uid, msg, resp, ts in history:
        text += f"<b>👤 {uid}</b> | {ts[5:16]}\n❓ {msg[:80]}\n✅ {resp[:80]}\n<code>─────────</code>\n"
        if len(text) > 3500:
            await bot.send_message(m.chat.id, text, parse_mode="HTML")
            text = ""
    if text:
        await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def clear_all_history(m):
    if not is_admin(m.chat.id):
        return
    conn = sqlite3.connect("nico_bot.db")
    c = conn.cursor()
    c.execute("DELETE FROM chat_history")
    conn.commit()
    conn.close()
    await bot.send_message(m.chat.id, "🧠 Вся история очищена!")

async def settings_panel(m):
    if not is_admin(m.chat.id):
        return
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📊 Установить интервал", callback_data="set_interval"),
        InlineKeyboardButton("⏰ Установить время дайджеста", callback_data="set_morning"),
        InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")
    )
    await bot.send_message(m.chat.id, "⚙️ <b>Настройки бота</b>\n\nВыбери параметр:", parse_mode="HTML", reply_markup=kb)

# ========== ОБРАБОТЧИК СООБЩЕНИЙ ==========
async def manual_trigger(m):
    if m.text and m.text.startswith('/'):
        return
    
    user_text = m.text if m.text else ""
    status_msg = await bot.send_message(m.chat.id, "🤔 <i>Думаю...</i>", parse_mode="HTML")
    
    try:
        if any(word in user_text.lower() for word in ["новости", "что нового"]):
            posts = await generate_posts_pack("")
            if posts:
                for post in posts[:2]:
                    await send_crafted_post(m.chat.id, post["text"], post.get("photo_url"), 
                                           with_publish_button=is_admin(m.chat.id))
            else:
                await bot.send_message(m.chat.id, "📭 Свежих новостей нет")
        
        elif any(word in user_text.lower() for word in ["календарь", "гонки", "расписание"]):
            cal = await get_f1_calendar(14)
            await bot.send_message(m.chat.id, cal, parse_mode="HTML")
        
        else:
            answer = await chat_with_nico(m.chat.id, user_text, use_web_search=True)
            await bot.send_message(m.chat.id, answer, parse_mode="HTML")
            
    except Exception as e:
        await bot.send_message(m.chat.id, f"❌ Ошибка: {e}")
    
    await bot.delete_message(m.chat.id, status_msg.message_id)

# ========== ОБРАБОТЧИК КНОПОК ==========
async def handle_callbacks(call):
    global DIGEST_BUFFER
    
    # Пользовательские кнопки
    if call.data == "user_start":
        await user_start(call.message)
    elif call.data == "user_about":
        await user_about(call.message)
    elif call.data == "user_calendar":
        cal = await get_f1_calendar(14)
        await bot.send_message(call.message.chat.id, cal, parse_mode="HTML")
    elif call.data == "user_forget":
        conn = sqlite3.connect("nico_bot.db")
        c = conn.cursor()
        c.execute("DELETE FROM chat_history WHERE user_id = ?", (call.message.chat.id,))
        conn.commit()
        conn.close()
        await bot.send_message(call.message.chat.id, "🧠 История очищена!")
    
    # Админские кнопки
    elif call.data == "back_to_admin":
        await admin_panel(call.message)
    elif call.data == "settings":
        await settings_panel(call.message)
    elif call.data == "show_users":
        await show_users(call.message)
    elif call.data == "show_history":
        await show_full_history(call.message)
    elif call.data == "forget_all":
        await clear_all_history(call.message)
    elif call.data == "show_stats":
        stats = get_stats()
        uptime = time.time() - STATE["start_time"]
        await bot.send_message(call.message.chat.id,
            f"📊 <b>Статистика</b>\n"
            f"📝 Постов: {stats['posts']}\n"
            f"💬 Диалогов: {stats['chats']}\n"
            f"⏱ Аптайм: {int(uptime//3600)}ч", parse_mode="HTML")
    elif call.data == "auto_post":
        await bot.answer_callback_query(call.id, "📰 Генерирую...")
        posts = await generate_posts_pack("Сделай аналитический пост о F1")
        for post in posts:
            await send_crafted_post(call.message.chat.id, post["text"], post.get("photo_url"), with_publish_button=True)
    elif call.data == "force_scan":
        await bot.answer_callback_query(call.id, "🔍 Сканирую...")
        posts = await generate_posts_pack("")
        for post in posts:
            await send_crafted_post(call.message.chat.id, post["text"], post.get("photo_url"), with_publish_button=True)
    elif call.data == "calendar":
        cal = await get_f1_calendar(14)
        await bot.send_message(call.message.chat.id, cal, parse_mode="HTML")
    elif call.data == "chat_mode":
        STATE["chat_mode"] = not STATE["chat_mode"]
        await bot.send_message(call.message.chat.id, f"💬 Режим чата: {'Вкл' if STATE['chat_mode'] else 'Выкл'}")
    elif call.data == "rel_dig":
        if DIGEST_BUFFER:
            for txt, pic in DIGEST_BUFFER:
                await send_crafted_post("@RedRaceF1", txt, pic)
                await asyncio.sleep(2)
            DIGEST_BUFFER = []
            await bot.send_message(call.message.chat.id, "📦 Дайджест отправлен!")
        else:
            await bot.send_message(call.message.chat.id, "Буфер пуст")
    elif call.data == "pub_direct_action":
        try:
            if call.message.caption:
                await bot.send_photo("@RedRaceF1", call.message.photo[-1].file_id, caption=call.message.caption, parse_mode="HTML")
            else:
                await bot.send_message("@RedRaceF1", call.message.text, parse_mode="HTML")
            await bot.answer_callback_query(call.id, "Опубликовано!")
            await bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception as e:
            print(f"Publish error: {e}")
    
    await bot.answer_callback_query(call.id)

# ========== КОМАНДЫ ==========
async def stats_command(m):
    stats = get_stats()
    uptime = time.time() - STATE["start_time"]
    await bot.reply_to(m,
        f"📊 <b>Статистика Nico</b>\n"
        f"📝 Постов: {stats['posts']}\n"
        f"💬 Диалогов: {stats['chats']}\n"
        f"⏱ Аптайм: {int(uptime//3600)}ч\n"
        f"<code>Nico 2.9 | RedRace Development</code>", parse_mode="HTML")

async def forget_command(m):
    conn = sqlite3.connect("nico_bot.db")
    c = conn.cursor()
    c.execute("DELETE FROM chat_history WHERE user_id = ?", (m.chat.id,))
    conn.commit()
    conn.close()
    await bot.reply_to(m, "🧠 История диалога очищена!")

async def ask_command(m):
    args = m.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(m, "❓ Пример: /ask последние новости Ferrari")
        return
    status_msg = await bot.send_message(m.chat.id, "🔍 Ищу...")
    result = await search_web(f"F1 {args[1]}", max_results=3)
    await bot.delete_message(m.chat.id, status_msg.message_id)
    await bot.send_message(m.chat.id, f"🌐 <b>Результаты:</b>\n\n{result}", parse_mode="HTML")

async def start_command(m):
    if is_admin(m.chat.id):
        await admin_panel(m)
    else:
        await user_panel(m)

# ========== АВТОПОСТИНГ ==========
async def auto_post_worker():
    while True:
        await asyncio.sleep(STATE['auto_interval'])
        if STATE.get("kill_switch") or STATE['chat_mode']:
            continue
        try:
            posts = await generate_posts_pack("")
            for post in posts:
                if STATE["pub_mode"] == "DIRECT":
                    await send_crafted_post("@RedRaceF1", post["text"], post.get("photo_url"))
                    if post.get("text"):
                        save_post(post["text"], post.get("photo_url"))
                await asyncio.sleep(3)
        except Exception as e:
            print(f"Auto post error: {e}")

async def polling_worker():
    while True:
        try:
            await bot.infinity_polling(timeout=10, request_timeout=20)
        except Exception as e:
            print(f"Polling error: {e}, reconnect in 5s")
            await asyncio.sleep(5)

def register_handlers(bot_instance):
    bot_instance.register_message_handler(start_command, commands=['start'])
    bot_instance.register_message_handler(admin_panel, commands=['admin'])
    bot_instance.register_message_handler(stats_command, commands=['stats'])
    bot_instance.register_message_handler(forget_command, commands=['forget'])
    bot_instance.register_message_handler(ask_command, commands=['ask'])
    bot_instance.register_message_handler(manual_trigger, func=lambda m: True, content_types=['text'])
    bot_instance.register_callback_query_handler(handle_callbacks, func=lambda call: True)

# ========== MAIN ==========
async def main():
    global bot
    bot = AsyncTeleBot(BOT_TOKEN)
    register_handlers(bot)
    await start_keep_alive_server()
    asyncio.create_task(auto_post_worker())
    asyncio.create_task(polling_worker())
    print("🚀 Nico 3.0 started!")
    print("👑 Admin ID:", ADMIN_IDS)
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
