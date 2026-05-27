import asyncio
import os
import time
import sqlite3
import re
import random
from datetime import datetime, timedelta
from aiohttp import web
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

from scraper import (
    generate_posts_pack, get_f1_calendar, chat_with_nico, get_top_news,
    get_weather_for_track, get_quote_of_the_day, smart_search,
    get_last_race_result, set_selected_model, get_selected_model,
    generate_morning_digest, get_interesting_fact, search_web
)
from database import init_db, get_stats, save_post

# === КОНФИГ ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set")

ADMIN_IDS = [7025868617]

STATE = {
    "pub_mode": "DIRECT",
    "start_time": time.time(),
    "auto_interval": 7200,
    "chat_mode": False,
    "last_auto_post": None
}

DIGEST_BUFFER = []
ADMIN_CHAT_ID = None
bot = None

init_db()

def is_admin(user_id):
    return user_id in ADMIN_IDS

# === КРАТКОЕ МЕНЮ ===
def get_main_menu(user_id):
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton("📅 Календарь"),
        KeyboardButton("🏆 Новости"),
        KeyboardButton("🌦️ Погода"),
        KeyboardButton("💬 Чат"),
        KeyboardButton("🏁 Результаты")
    )
    if is_admin(user_id):
        markup.add(
            KeyboardButton("📝 Пост"),
            KeyboardButton("🎛️ Модель"),
            KeyboardButton("⚙️ Настройки")
        )
    return markup

async def health_check(request):
    return web.Response(text="Nico 7.0 alive", status=200)

async def start_keep_alive_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Keep-alive on port {port}")

async def send_crafted_post(target_chat, text, photo_url=None, with_publish_button=False):
    if not bot:
        return
    kb = None
    if with_publish_button:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🚀 В канал", callback_data="pub_direct_action"))
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

# === ПОИСК БЕЗ ИИ ===
async def manual_search_command(m):
    args = m.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(m, "❓ Пример: /search новости Ferrari")
        return
    
    query = args[1]
    status_msg = await bot.send_message(m.chat.id, f"🔍 Ищу: {query}")
    
    try:
        result = await search_web(query, max_results=4)
        if len(result) > 4000:
            result = result[:4000] + "\n\n... (обрезано)"
        await bot.send_message(m.chat.id, f"🌐 Результаты:\n\n{result}")
    except Exception as e:
        await bot.send_message(m.chat.id, f"❌ Ошибка: {e}")
    
    await bot.delete_message(m.chat.id, status_msg.message_id)

# === ВЫБОР МОДЕЛИ ===
async def model_command(m):
    if not is_admin(m.chat.id):
        return
    current = get_selected_model() or "auto"
    model_names = {
        "auto": "🔄 Авто",
        "openrouter/free": "🚀 OpenRouter",
        "deepseek/deepseek-v4-flash:free": "⚡ DeepSeek V4",
        "qwen/qwen3.7-max:free": "🐫 Qwen 3.7"
    }
    current_name = model_names.get(current, current.split('/')[-1].replace(':free', ''))
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🚀 OpenRouter", callback_data="model_openrouter/free"),
        InlineKeyboardButton("⚡ DeepSeek V4", callback_data="model_deepseek/deepseek-v4-flash:free"),
        InlineKeyboardButton("🐫 Qwen 3.7", callback_data="model_qwen/qwen3.7-max:free"),
        InlineKeyboardButton("🔄 Авто", callback_data="model_auto")
    )
    await bot.send_message(m.chat.id, f"🎛️ Сейчас: {current_name}\n\nВыбери модель:", reply_markup=kb)

# === АДМИН-ПАНЕЛЬ ===
async def admin_panel(m):
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = m.chat.id
    uptime = time.time() - STATE["start_time"]
    stats = get_stats()
    current_model = get_selected_model() or "авто"
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Пост", callback_data="auto_post"),
        InlineKeyboardButton("🔍 Скан", callback_data="force_scan"),
        InlineKeyboardButton("💬 Режим чата", callback_data="chat_mode"),
        InlineKeyboardButton("🎛️ Модель", callback_data="model_menu"),
        InlineKeyboardButton("📦 Дайджест", callback_data="rel_dig"),
        InlineKeyboardButton("📊 Статистика", callback_data="show_stats")
    )
    
    status = (
        f"👑 <b>Nico 7.0</b>\n\n"
        f"⚡️ Аптайм: {int(uptime//3600)}ч\n"
        f"🎯 Режим: {'Диалог' if STATE['chat_mode'] else 'Авто'}\n"
        f"🧠 Мозги: {current_model}\n"
        f"📝 Постов: {stats['posts']}\n"
        f"💬 Диалогов: {stats['chats']}\n\n"
        f"<i>{random.choice(['Всё пучком', 'Шины в норме', 'Боевая готовность'])}</i>"
    )
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=kb)

# === ПОЛЬЗОВАТЕЛЬСКАЯ ПАНЕЛЬ ===
async def user_panel(m):
    uptime = time.time() - STATE["start_time"]
    stats = get_stats()
    
    status = (
        f"🏎️ <b>Nico 7.0</b>\n\n"
        f"Привет! Я Нико, гоночный инженер.\n\n"
        f"📊 Статистика: {stats['posts']} постов, {stats['chats']} диалогов\n"
        f"⚡️ Аптайм: {int(uptime//3600)}ч\n\n"
        f"<i>Просто напиши вопрос про F1</i>"
    )
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_main_menu(m.chat.id))

# === ОБРАБОТЧИК КНОПОК МЕНЮ ===
async def handle_menu_buttons(m):
    text = m.text
    
    if text == "📅 Календарь":
        cal = await get_f1_calendar(21)
        await bot.send_message(m.chat.id, cal, parse_mode="HTML")
    
    elif text == "🏆 Новости":
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
        await bot.send_message(m.chat.id, "💬 Задавай вопрос про F1. Отвечу с характером.")
    
    elif text == "🏁 Результаты":
        status_msg = await bot.send_message(m.chat.id, "🏁 Получаю результаты...")
        results = await get_last_race_result()
        await bot.delete_message(m.chat.id, status_msg.message_id)
        await bot.send_message(m.chat.id, results, parse_mode="HTML")
    
    elif text == "📝 Пост" and is_admin(m.chat.id):
        await bot.send_message(m.chat.id, "📝 Напиши тему поста. Например: «пост про Ferrari»")
    
    elif text == "🎛️ Модель" and is_admin(m.chat.id):
        await model_command(m)
    
    elif text == "⚙️ Настройки" and is_admin(m.chat.id):
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("⏱ Интервал", callback_data="set_interval"),
            InlineKeyboardButton("🎛️ Модель", callback_data="model_menu"),
            InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")
        )
        await bot.send_message(m.chat.id, "⚙️ Настройки", reply_markup=kb)

# === ОСНОВНОЙ ОБРАБОТЧИК ===
async def manual_trigger(m):
    if m.text and m.text.startswith('/'):
        return
    
    user_text = m.text
    menu_buttons = ["📅 Календарь", "🏆 Новости", "🌦️ Погода", "💬 Чат", "🏁 Результаты", "📝 Пост", "🎛️ Модель", "⚙️ Настройки"]
    if user_text in menu_buttons:
        await handle_menu_buttons(m)
        return
    
    status_msg = await bot.send_message(m.chat.id, "🤔 Думаю...")
    
    try:
        # Быстрый поиск
        if user_text.lower().startswith(("поиск ", "найди ", "найти ")):
            query = user_text.split(maxsplit=1)[1]
            result = await search_web(query, max_results=4)
            await bot.send_message(m.chat.id, f"🌐 Результаты:\n\n{result[:3500]}")
            await bot.delete_message(m.chat.id, status_msg.message_id)
            return
        
        # Генерация поста
        if any(w in user_text.lower() for w in ["выложи", "сделай пост", "напиши пост"]):
            if not is_admin(m.chat.id):
                await bot.send_message(m.chat.id, "⛔ Только админ")
            else:
                topic = user_text
                for w in ["выложи", "сделай пост", "напиши пост", "пост про"]:
                    topic = topic.lower().replace(w, "").strip()
                if not topic:
                    topic = "новости F1"
                await bot.send_message(m.chat.id, f"📝 Генерирую пост...")
                posts = await generate_posts_pack(topic)
                for post in posts[:1]:
                    await send_crafted_post(m.chat.id, post["text"], post.get("photo_url"), with_publish_button=True)
                    save_post(post["text"], post.get("photo_url"))
                await bot.send_message(m.chat.id, "✅ Готово")
        
        # Обычный чат
        else:
            answer = await chat_with_nico(m.chat.id, user_text)
            await bot.send_message(m.chat.id, answer, parse_mode="HTML")
            
    except Exception as e:
        await bot.send_message(m.chat.id, f"❌ {e}")
    
    await bot.delete_message(m.chat.id, status_msg.message_id)

# === ОБРАБОТЧИК КНОПОК ===
async def handle_callbacks(call):
    global DIGEST_BUFFER
    
    if call.data == "back_to_admin":
        await admin_panel(call.message)
    elif call.data == "model_menu":
        await model_command(call.message)
    elif call.data.startswith("model_"):
        model = call.data.replace("model_", "")
        set_selected_model(None if model == "auto" else model)
        await bot.send_message(call.message.chat.id, f"✅ Модель изменена")
        await admin_panel(call.message)
    elif call.data == "set_interval":
        await bot.send_message(call.message.chat.id, "Введи часы (1-24):")
    elif call.data == "force_scan":
        await bot.answer_callback_query(call.id, "🔍 Сканирую...")
        posts = await generate_posts_pack("")
        for post in posts:
            await send_crafted_post(call.message.chat.id, post["text"], post.get("photo_url"), with_publish_button=True)
    elif call.data == "auto_post":
        await bot.answer_callback_query(call.id, "📝 Генерирую...")
        posts = await generate_posts_pack("сделай аналитический пост о F1")
        for post in posts:
            await send_crafted_post(call.message.chat.id, post["text"], post.get("photo_url"), with_publish_button=True)
    elif call.data == "chat_mode":
        STATE["chat_mode"] = not STATE["chat_mode"]
        await bot.send_message(call.message.chat.id, f"💬 Режим чата: {'Вкл' if STATE['chat_mode'] else 'Выкл'}")
    elif call.data == "rel_dig":
        if DIGEST_BUFFER:
            for txt, pic in DIGEST_BUFFER:
                await send_crafted_post("@RedRaceF1", txt, pic)
            DIGEST_BUFFER = []
            await bot.send_message(call.message.chat.id, "📦 Дайджест отправлен")
        else:
            await bot.send_message(call.message.chat.id, "Буфер пуст")
    elif call.data == "show_stats":
        stats = get_stats()
        uptime = time.time() - STATE["start_time"]
        await bot.send_message(call.message.chat.id, f"📊 Постов: {stats['posts']}\n💬 Диалогов: {stats['chats']}\n⏱ Аптайм: {int(uptime//3600)}ч")
    elif call.data == "pub_direct_action":
        try:
            if call.message.caption:
                await bot.send_photo("@RedRaceF1", call.message.photo[-1].file_id, caption=call.message.caption, parse_mode="HTML")
            else:
                await bot.send_message("@RedRaceF1", call.message.text, parse_mode="HTML")
            await bot.answer_callback_query(call.id, "Опубликовано")
        except Exception as e:
            print(f"Publish error: {e}")
    
    await bot.answer_callback_query(call.id)

# === КОМАНДЫ ===
async def start_command(m):
    if is_admin(m.chat.id):
        await bot.send_message(m.chat.id, "👑 Добро пожаловать", reply_markup=get_main_menu(m.chat.id))
        await admin_panel(m)
    else:
        await bot.send_message(m.chat.id, "🏎️ Добро пожаловать в Nico 7.0", reply_markup=get_main_menu(m.chat.id))
        await user_panel(m)

async def stats_command(m):
    stats = get_stats()
    uptime = time.time() - STATE["start_time"]
    await bot.reply_to(m, f"📊 {stats['posts']} постов, {stats['chats']} диалогов\n⏱ {int(uptime//3600)}ч")

async def forget_command(m):
    conn = sqlite3.connect("nico_bot.db")
    c = conn.cursor()
    c.execute("DELETE FROM chat_history WHERE user_id = ?", (m.chat.id,))
    conn.commit()
    conn.close()
    await bot.reply_to(m, "🧠 История очищена")

async def handle_interval_input(m):
    if not is_admin(m.chat.id):
        return
    try:
        hours = int(m.text.strip())
        if 1 <= hours <= 24:
            STATE["auto_interval"] = hours * 3600
            await bot.send_message(m.chat.id, f"✅ Интервал {hours}ч")
        else:
            await bot.send_message(m.chat.id, "❌ Введи число 1-24")
    except:
        await bot.send_message(m.chat.id, "❌ Введи число")

# === ПЛАНИРОВЩИКИ ===
async def morning_digest_scheduler():
    while True:
        now = datetime.now()
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            digest = await generate_morning_digest()
            await bot.send_message("@RedRaceF1", digest, parse_mode="HTML")
            print(f"☀️ Утренний дайджест отправлен")
        except Exception as e:
            print(f"Digest error: {e}")

async def auto_post_worker():
    while True:
        await asyncio.sleep(STATE['auto_interval'])
        if STATE['chat_mode']:
            continue
        try:
            print(f"🔄 Автопостинг...")
            posts = await generate_posts_pack("")
            for post in posts:
                await send_crafted_post("@RedRaceF1", post["text"], post.get("photo_url"))
                save_post(post["text"], post.get("photo_url"))
                await asyncio.sleep(3)
            STATE["last_auto_post"] = time.time()
        except Exception as e:
            print(f"Auto post error: {e}")

async def polling_worker():
    while True:
        try:
            await bot.infinity_polling(timeout=15, request_timeout=20)
        except Exception as e:
            print(f"Polling error: {e}")
            await asyncio.sleep(5)

def register_handlers(b):
    b.register_message_handler(start_command, commands=['start'])
    b.register_message_handler(admin_panel, commands=['admin'])
    b.register_message_handler(manual_search_command, commands=['search', 's'])
    b.register_message_handler(stats_command, commands=['stats'])
    b.register_message_handler(forget_command, commands=['forget'])
    b.register_message_handler(handle_interval_input, func=lambda m: m.text and m.text.isdigit() and is_admin(m.chat.id))
    b.register_message_handler(manual_trigger, func=lambda m: True, content_types=['text'])
    b.register_callback_query_handler(handle_callbacks, func=lambda call: True)

# === MAIN ===
async def main():
    global bot
    bot = AsyncTeleBot(BOT_TOKEN)
    register_handlers(bot)
    await start_keep_alive_server()
    asyncio.create_task(auto_post_worker())
    asyncio.create_task(morning_digest_scheduler())
    asyncio.create_task(polling_worker())
    print("🚀 NICO 7.0 STARTED")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
