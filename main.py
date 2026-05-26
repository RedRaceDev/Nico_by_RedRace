import asyncio
import os
import time
import sqlite3
from datetime import datetime, timedelta
from aiohttp import web
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

from scraper import (
    generate_posts_pack, 
    get_f1_calendar, 
    chat_with_nico, 
    get_top_news, 
    get_weather_for_track, 
    get_quote_of_the_day, 
    smart_search,
    get_last_race_result
)
from database import init_db, get_stats, save_post

# === КОНФИГ ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set")

ADMIN_IDS = [7025868617]  # Твой Telegram ID

STATE = {
    "pub_mode": "DIRECT",
    "start_time": time.time(),
    "auto_interval": 7200,  # 2 часа
    "chat_mode": False
}

DIGEST_BUFFER = []
ADMIN_CHAT_ID = None
bot = None

# Инициализируем базу данных
init_db()

def is_admin(user_id):
    return user_id in ADMIN_IDS

# === МЕНЮ С КНОПКАМИ ===
def get_main_menu(user_id):
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    
    # Основные кнопки для всех
    markup.add(
        KeyboardButton("🏁 О боте"),
        KeyboardButton("📅 Календарь"),
        KeyboardButton("🏆 Топ новостей"),
        KeyboardButton("🌦️ Погода"),
        KeyboardButton("💬 Чат"),
        KeyboardButton("🏎️ Цитата дня"),
        KeyboardButton("🏁 Результаты")
    )
    
    # Админские кнопки
    if is_admin(user_id):
        markup.add(
            KeyboardButton("📝 Сделать пост"),
            KeyboardButton("📊 Статистика"),
            KeyboardButton("📦 Дайджест"),
            KeyboardButton("🧠 Очистить БД"),
            KeyboardButton("👥 Пользователи"),
            KeyboardButton("📜 История"),
            KeyboardButton("⚙️ Настройки")
        )
    
    return markup

# === HTTP СЕРВЕР ===
async def health_check(request):
    return web.Response(text="Nico 4.0 is alive", status=200)

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

# === ОТПРАВКА ПОСТОВ ===
async def send_crafted_post(target_chat, text, photo_url=None, with_publish_button=False):
    if not bot:
        return
    kb = None
    if with_publish_button:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🚀 В КАНАЛ", callback_data="pub_direct_action"))
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

# === АДМИН-КОНСОЛЬ ===
async def admin_panel(m):
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = m.chat.id
    
    uptime = time.time() - STATE["start_time"]
    stats = get_stats()
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📰 Пост", callback_data="auto_post"),
        InlineKeyboardButton("🔍 Скан", callback_data="force_scan"),
        InlineKeyboardButton("📅 Календарь", callback_data="calendar"),
        InlineKeyboardButton("💬 Режим чата", callback_data="chat_mode"),
        InlineKeyboardButton("📦 Дайджест", callback_data="rel_dig"),
        InlineKeyboardButton("📊 Статистика", callback_data="show_stats"),
        InlineKeyboardButton("👥 Пользователи", callback_data="show_users"),
        InlineKeyboardButton("📜 История", callback_data="show_history"),
        InlineKeyboardButton("🧠 Очистить БД", callback_data="forget_all"),
        InlineKeyboardButton("⚙️ Интервал", callback_data="set_interval")
    )
    
    status = (
        f"<b>👑 NICO 4.0 | ADMIN CONSOLE</b>\n"
        f"<code>═══════════════════════════</code>\n"
        f"├ 🕐 Аптайм: <code>{int(uptime//3600)}ч {int((uptime%3600)//60)}м</code>\n"
        f"├ 🎯 Режим: <b>{'Чат' if STATE['chat_mode'] else 'Авто'}</b>\n"
        f"├ ⏱ Интервал: <b>{STATE['auto_interval']//3600}ч</b>\n"
        f"├ 📦 Буфер: <b>{len(DIGEST_BUFFER)}</b>\n"
        f"├ 📝 Постов: <b>{stats['posts']}</b>\n"
        f"├ 💬 Диалогов: <b>{stats['chats']}</b>\n"
        f"└ 👑 Админ: <b>Активен</b>\n"
        f"<code>═══════════════════════════</code>\n"
        f"<i>Nico 4.0 | Code by: RedRace Development, Google Cloud</i>"
    )
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=kb)

# === ПОЛЬЗОВАТЕЛЬСКАЯ КОНСОЛЬ ===
async def user_panel(m):
    uptime = time.time() - STATE["start_time"]
    stats = get_stats()
    
    status = (
        f"<b>🏎️ NICO 4.0 | F1 ASSISTANT</b>\n"
        f"<code>─────────────────────</code>\n"
        f"├ 🤖 <i>Твой гоночный инженер</i>\n"
        f"├ 📊 Сервер: <code>{int(uptime//3600)}ч</code>\n"
        f"├ 💬 Диалогов: <b>{stats['chats']}</b>\n"
        f"├ 📝 Постов: <b>{stats['posts']}</b>\n"
        f"└ 🔧 Версия: <b>4.0</b>\n"
        f"<code>─────────────────────</code>\n"
        f"<i>Просто напиши вопрос про F1!</i>\n\n"
        f"<code>Nico 4.0 | Code by: RedRace Development, Google Cloud</code>"
    )
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_main_menu(m.chat.id))

# === ОБРАБОТКА КНОПОК МЕНЮ ===
async def handle_menu_buttons(m):
    text = m.text
    
    if text == "🏁 О боте":
        await bot.send_message(m.chat.id,
            "🏎️ <b>NICO 4.0 — Гоночный инженер</b>\n\n"
            "📌 <b>Что умею:</b>\n"
            "• Отвечаю на вопросы про F1\n"
            "• Ищу новости в интернете\n"
            "• Показываю календарь гонок\n"
            "• Рассказываю погоду на трассе\n"
            "• Делаю посты по запросу\n"
            "• Помню историю диалогов\n\n"
            "💡 <b>Команды:</b>\n"
            "• /ask [вопрос] — поиск в сети\n"
            "• /stats — статистика\n"
            "• /forget — очистить память\n\n"
            "<code>Nico 4.0 | Code by: RedRace Development, Google Cloud</code>",
            parse_mode="HTML")
    
    elif text == "📅 Календарь":
        cal = await get_f1_calendar(21)
        await bot.send_message(m.chat.id, cal, parse_mode="HTML")
    
    elif text == "🏆 Топ новостей":
        status_msg = await bot.send_message(m.chat.id, "🔍 Собираю новости...")
        top = await get_top_news(5)
        await bot.delete_message(m.chat.id, status_msg.message_id)
        await bot.send_message(m.chat.id, top, parse_mode="HTML")
    
    elif text == "🌦️ Погода":
        status_msg = await bot.send_message(m.chat.id, "🌍 Ищу погоду...")
        weather = await get_weather_for_track()
        await bot.delete_message(m.chat.id, status_msg.message_id)
        await bot.send_message(m.chat.id, weather, parse_mode="HTML")
    
    elif text == "💬 Чат":
        await bot.send_message(m.chat.id,
            "💬 <b>Гоночный инженер на связи!</b>\n\n"
            "Просто напиши свой вопрос про F1.\n"
            "Я отвечу с характером и найду инфу в интернете.\n\n"
            "🏁 <i>Задавай вопрос!</i>\n\n"
            "<code>Nico 4.0 | Code by: RedRace Development, Google Cloud</code>",
            parse_mode="HTML")
    
    elif text == "🏎️ Цитата дня":
        quote = await get_quote_of_the_day()
        await bot.send_message(m.chat.id, f"📜 <b>Цитата дня</b>\n\n{quote}\n\n<code>Nico 4.0</code>", parse_mode="HTML")
    
    elif text == "🏁 Результаты":
        status_msg = await bot.send_message(m.chat.id, "🏁 Получаю результаты последней гонки...")
        results = await get_last_race_result()
        await bot.delete_message(m.chat.id, status_msg.message_id)
        await bot.send_message(m.chat.id, results, parse_mode="HTML")
    
    # === АДМИНСКИЕ КНОПКИ ===
    elif text == "📝 Сделать пост" and is_admin(m.chat.id):
        await bot.send_message(m.chat.id,
            "📝 <b>Напиши тему для поста</b>\n\n"
            "Примеры:\n"
            "- сделай пост про Ferrari\n"
            "- пост о Red Bull Racing\n"
            "- аналитика по шинам\n\n"
            "Жду тему...",
            parse_mode="HTML")
    
    elif text == "📊 Статистика" and is_admin(m.chat.id):
        stats = get_stats()
        uptime = time.time() - STATE["start_time"]
        await bot.send_message(m.chat.id,
            f"📊 <b>Статистика Nico 4.0</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📝 Постов: {stats['posts']}\n"
            f"💬 Диалогов: {stats['chats']}\n"
            f"⏱ Аптайм: {int(uptime//3600)}ч\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"<code>Nico 4.0 | RedRace Development</code>",
            parse_mode="HTML")
    
    elif text == "📦 Дайджест" and is_admin(m.chat.id):
        global DIGEST_BUFFER
        if DIGEST_BUFFER:
            for txt, pic in DIGEST_BUFFER:
                await send_crafted_post("@RedRaceF1", txt, pic)
                await asyncio.sleep(2)
            DIGEST_BUFFER = []
            await bot.send_message(m.chat.id, "📦 Дайджест отправлен в канал!")
        else:
            await bot.send_message(m.chat.id, "Буфер пуст")
    
    elif text == "👥 Пользователи" and is_admin(m.chat.id):
        conn = sqlite3.connect("nico_bot.db")
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id, COUNT(*) FROM chat_history GROUP BY user_id ORDER BY COUNT(*) DESC")
        users = c.fetchall()
        conn.close()
        if users:
            msg = "👥 <b>Пользователи бота:</b>\n<code>─────────────────────</code>\n"
            for uid, count in users:
                msg += f"🆔 <code>{uid}</code> — {count} сообщ.\n"
            await bot.send_message(m.chat.id, msg, parse_mode="HTML")
        else:
            await bot.send_message(m.chat.id, "📭 Нет пользователей")
    
    elif text == "📜 История" and is_admin(m.chat.id):
        conn = sqlite3.connect("nico_bot.db")
        c = conn.cursor()
        c.execute("SELECT user_id, message, response, timestamp FROM chat_history ORDER BY timestamp DESC LIMIT 15")
        history = c.fetchall()
        conn.close()
        if history:
            msg = "📜 <b>Последние диалоги:</b>\n<code>─────────────────────</code>\n\n"
            for uid, msg_txt, resp, ts in history:
                msg += f"<b>👤 {uid}</b> | {ts[5:16]}\n❓ {msg_txt[:60]}\n✅ {resp[:60]}\n<code>─────────────</code>\n"
                if len(msg) > 3500:
                    await bot.send_message(m.chat.id, msg, parse_mode="HTML")
                    msg = ""
            if msg:
                await bot.send_message(m.chat.id, msg, parse_mode="HTML")
        else:
            await bot.send_message(m.chat.id, "📭 История пуста")
    
    elif text == "🧠 Очистить БД" and is_admin(m.chat.id):
        conn = sqlite3.connect("nico_bot.db")
        c = conn.cursor()
        c.execute("DELETE FROM chat_history")
        conn.commit()
        conn.close()
        await bot.send_message(m.chat.id, "🧠 <b>Вся история диалогов очищена!</b>\n\n<code>Nico 4.0</code>", parse_mode="HTML")
    
    elif text == "⚙️ Настройки" and is_admin(m.chat.id):
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("⏱ Интервал постинга", callback_data="set_interval"),
            InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")
        )
        await bot.send_message(m.chat.id, "⚙️ <b>Настройки бота</b>\n\nВыбери параметр:", parse_mode="HTML", reply_markup=kb)

# === ОБРАБОТЧИК СООБЩЕНИЙ ===
async def manual_trigger(m):
    if m.text and m.text.startswith('/'):
        return
    
    # Если это кнопка меню — обрабатываем отдельно
    menu_buttons = ["🏁 О боте", "📅 Календарь", "🏆 Топ новостей", "🌦️ Погода", "💬 Чат", "🏎️ Цитата дня", "🏁 Результаты",
                    "📝 Сделать пост", "📊 Статистика", "📦 Дайджест", "🧠 Очистить БД", "👥 Пользователи", "📜 История", "⚙️ Настройки"]
    if m.text in menu_buttons:
        await handle_menu_buttons(m)
        return
    
    user_text = m.text if m.text else ""
    status_msg = await bot.send_message(m.chat.id, "🤔 <i>Анализирую...</i>", parse_mode="HTML")
    
    try:
        if any(word in user_text.lower() for word in ["пост", "сделай пост", "выложи", "опубликуй", "создай пост"]):
            if not is_admin(m.chat.id):
                await bot.send_message(m.chat.id, "⛔ Только администратор может делать посты")
            else:
                posts = await generate_posts_pack(user_text)
                if posts:
                    for post in posts[:2]:
                        await send_crafted_post(m.chat.id, post["text"], post.get("photo_url"), with_publish_button=True)
                        if post.get("text"):
                            save_post(post["text"], post.get("photo_url"))
                else:
                    await bot.send_message(m.chat.id, "❌ Не удалось сгенерировать пост")
        
        elif any(word in user_text.lower() for word in ["новости", "что нового", "свежие новости"]):
            posts = await generate_posts_pack("")
            if posts:
                for post in posts[:2]:
                    await send_crafted_post(m.chat.id, post["text"], post.get("photo_url"), with_publish_button=is_admin(m.chat.id))
                    if post.get("text") and is_admin(m.chat.id):
                        save_post(post["text"], post.get("photo_url"))
            else:
                await bot.send_message(m.chat.id, "📭 Свежих новостей пока нет")
        
        elif any(word in user_text.lower() for word in ["календарь", "гонки", "расписание"]):
            cal = await get_f1_calendar(21)
            await bot.send_message(m.chat.id, cal, parse_mode="HTML")
        
        else:
            answer = await chat_with_nico(m.chat.id, user_text, use_web_search=True)
            await bot.send_message(m.chat.id, answer, parse_mode="HTML")
            
    except Exception as e:
        await bot.send_message(m.chat.id, f"❌ Ошибка: {e}")
    
    await bot.delete_message(m.chat.id, status_msg.message_id)

# === ОБРАБОТЧИК КНОПОК ===
async def handle_callbacks(call):
    global DIGEST_BUFFER
    
    if call.data == "back_to_admin":
        await admin_panel(call.message)
    elif call.data == "set_interval":
        await bot.send_message(call.message.chat.id, "Введи интервал в часах (1-24):")
        await bot.answer_callback_query(call.id)
    elif call.data == "force_scan":
        await bot.answer_callback_query(call.id, "🔍 Сканирую...")
        posts = await generate_posts_pack("")
        for post in posts:
            await send_crafted_post(call.message.chat.id, post["text"], post.get("photo_url"), with_publish_button=True)
    elif call.data == "auto_post":
        await bot.answer_callback_query(call.id, "📰 Генерирую...")
        posts = await generate_posts_pack("Сделай аналитический пост о последних событиях в F1")
        for post in posts:
            await send_crafted_post(call.message.chat.id, post["teawai, post.get("photo_url"), with_publish_button=True)
    elif call.data == "calendar":
        cal = await get_f1_calendar(21)
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
    elif call.data == "show_stats":
        stats = get_stats()
        uptime = time.time() - STATE["start_time"]
        await bot.send_message(call.message.chat.idteawai        f"📊 Статистика\nПостов: {stats['posts']}\nДиалогов: {stats['chats']}\nАптайм: {int(uptime//3600)}ч")
    elif call.data == "show_users":
        conn = sqlite3.connect("nico_bot.db")
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id, COUNT(*) FROM chat_history GROUP BY user_id")
        users = c.fetchall()
        conn.close()
        if users:
            msg = "👥 Пользователи:\n"
            for uid, count in users:
                msg += f"🆔 {uid} — {count} сообщ.\n"
            await bot.send_message(call.message.chat.id, msg)
    elif call.data == "show_history":
        conn = sqlite3.connect("nico_bot.db")
        c = conn.cursor()
        c.execute("SELECT user_id, message, response, timestamp FROM chat_history ORDER BY timestamp DESC LIMIT 10")
        history = c.fetchall()
        conn.close()
        if history:
            msg = "📜 Последние диалоги:\n\n"
            for uid, msg_txt, resp, ts in history:
                msg += f"{uid} | {ts[5:16]}\n❓ {msg_txt[:50]}\n✅ {resp[:50]}\n---\n"
            await bot.send_message(call.message.chat.id, msg[:4000])
    elif call.data == "forget_all":
        conn = sqlite3.connect("nico_bot.db")
        c = conn.cursor()
        c.execute("DELETE FROM chat_history")
        conn.commit()
        conn.close()
        await bot.send_message(call.message.chat.id, "🧠 Вся история очищена!")
    elif call.data == "pub_direct_action":
        try:
            if call.message.caption:
                await bot.send_photo("@RedRaceF1", call.message.photo[-1].file_id, caption=call.message.caption, parse_mode="HTML")
            else:
                await bot.send_message("@RedRaceF1", call.message.text, parse_mode="HTML")
            await bot.answer_callback_query(call.id, "Опубликовано!")
        except Exception as e:
            print(f"Publish error: {e}")
    
    await bot.answer_callback_query(call.id)

# === КОМАНДЫ ===
async def start_command(m):
    if is_admin(m.chat.id):
        await bot.send_message(m.chat.id, "👑 Добро пожаловать, Админ!", reply_markup=get_main_menu(m.chat.id))
        await admin_panel(m)
    else:
        await bot.send_message(m.chat.id, "🏎️ Добро пожаловать в Nico 4.0!", reply_markup=get_main_menu(m.chat.id))
        await user_panel(m)

async def ask_command(m):
    args = m.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(m, "❓ Пример: /ask последние новости Ferrari")
        return
    status_msg = await bot.send_message(m.chat.id, "🔍 Ищу...")
    result = await smart_search(f"F1 {args[1]} 2026")
    await bot.delete_message(m.chat.id, status_msg.message_id)
    await bot.send_message(m.chat.id, f"🌐 <b>Результаты:</b>\n\n{result[:3000]}", parse_mode="HTML")

async def stats_command(m):
    stats = get_stats()
    uptime = time.time() - STATE["start_time"]
    await bot.reply_to(m,
        f"📊 <b>Статистика Nico 4.0</b>\n"
        f"📝 Постов: {stats['posts']}\n"
        f"💬 Диалогов: {stats['chats']}\n"
        f"⏱ Аптайм: {int(uptime//3600)}ч\n"
        f"<code>Nico 4.0 | RedRace Development, Google Cloud</code>", parse_mode="HTML")

async def forget_command(m):
    conn = sqlite3.connect("nico_bot.db")
    c = conn.cursor()
    c.execute("DELETE FROM chat_history WHERE user_id = ?", (m.chat.id,))
    conn.commit()
    conn.close()
    await bot.reply_to(m, "🧠 История диалога очищена!\n\n<code>Nico 4.0</code>", parse_mode="HTML")

async def handle_interval_input(m):
    if not is_admin(m.chat.id):
        return
    try:
        hours = int(m.text.strip())
        if 1 <= hours <= 24:
            STATE["auto_interval"] = hours * 3600
            await bot.send_message(m.chat.id, f"✅ Интервал установлен на {hours} часа(ов)")
        else:
            await bot.send_message(m.chat.id, "❌ Введи число от 1 до 24")
    except:
        await bot.send_message(m.chat.id, "❌ Введи целое число часов")

# === АВТОПОСТИНГ ===
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

# === ПОЛЛИНГ ===
async def polling_worker():
    while True:
        try:
            await bot.infinity_polling(timeout=10, request_timeout=20)
        except Exception as e:
            print(f"Polling error: {e}, reconnect in 5s")
            await asyncio.sleep(5)

# === РЕГИСТРАЦИЯ ===
def register_handlers(bot_instance):
    bot_instance.register_message_handler(start_command, commands=['start'])
    bot_instance.register_message_handler(admin_panel, commands=['admin'])
    bot_instance.register_message_handler(ask_command, commands=['ask'])
    bot_instance.register_message_handler(stats_command, commands=['stats'])
    bot_instance.register_message_handler(forget_command, commands=['forget'])
    bot_instance.register_message_handler(handle_interval_input, func=lambda m: m.text and m.text.isdigit() and is_admin(m.chat.id))
    bot_instance.register_message_handler(manual_trigger, func=lambda m: True, content_types=['text'])
    bot_instance.register_callback_query_handler(handle_callbacks, func=lambda call: True)

# === MAIN ===
async def main():
    global bot
    bot = AsyncTeleBot(BOT_TOKEN)
    register_handlers(bot)
    await start_keep_alive_server()
    asyncio.create_task(auto_post_worker())
    asyncio.create_task(polling_worker())
    print("🚀 NICO 4.0 STARTED!")
    print(f"👑 Admin ID: {ADMIN_IDS}")
    print("💬 Чат-бот с поиском в интернете активен")
    print("📊 База данных подключена")
    print("🔘 Меню с кнопками включено")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
