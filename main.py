import asyncio
import os
import time
import random
import sqlite3
from datetime import datetime, timedelta
from telebot.async_telebot import AsyncTeleBot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web

from scraper import (
    monitor, post_on_topic, random_post, get_f1_calendar, chat_reply,
    search_f1, mark_posted, get_morning_digest
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"

bot = None
monitoring = True
posts_cnt = 0
dialogs_cnt = 0
start_time = time.time()
wait_search = False
wait_topic = False
wait_broadcast = False
wait_post = False

def inc_posts(): global posts_cnt; posts_cnt += 1
def inc_dialogs(): global dialogs_cnt; dialogs_cnt += 1

# === РЕДРЕЙС ПЕРСОНАЖИ ===
REDRACE_CHARACTERS = {
    "Псиникс": "Ебланище конченное. Работает в РедРейзе. Роман с Райконненом. Проебал 10кк поставив на Пиастри.",
    "Вхуй": "Уебище жирное. Сирота, лучший дизайнер которого знает Кими, но который нихуя не делает. Вообщем ДОЛБАЕБ.",
    "Кими": "Создатель канала РедРейз. Муж Псиникса и уебанище. Топ 1 по заглатыванию))))!!!!",
    "Макс_Это_Скам": "я хз кто он. Он влиятельный хуй какой-то. Что ещё сказать.",
    "Пьер Гасли": "нормальный тип не придраться, но он хуесос т.к. не скинул мне свой писюн в ЛС и общается с ДЕВУШКОЙ!!! ФУУУУ",
    "Пиастри": "Уебище из за которого Псиникс проебал 10кк. Хуесос и спермобак. Не оставил сурка в обиде и проторанил Албона на 12 круге гранд при Канады.",
    "Берман": "Нытик и конченное уебище которое ездит по гравию больше чем по дороге. Не умеет играть. Понял и съебался в ужасе бездарь.",
    "Хирошима": "ООООО ФЕРНАНДО АЛООООНСО. Ничего сказать не могу. Долбаеб.",
    "СанРайз": "жирное уебище, конченный психопат.",
    "Акира": "котакбас. Главное хуйло чата. Животное тупое, но умеет контрить. Живет в штрафостане, не понимает животный язык.",
    "Артур¹¹": "тип на которого надеялся весь чат Монопосто, но в итоге так позорно проебал во Франции.",
    "МохмедАлл": "Съебись с чата и хватит просить у всех подряд Ливреи на то или иную хуйню. Всем ПОХУЙ. Чат Руссифицирован.",
    "Ghinok": "Горшочек петушочек, сладкий пирожочек, подрабатывает ершиком на зоне."
}

def get_random_character():
    name, desc = random.choice(list(REDRACE_CHARACTERS.items()))
    return f"🎭 <b>Ты — {name}</b>\n\n{desc}\n\n#RedRace #WhoAreYou"

# === КЛАВИАТУРЫ ===
def get_admin_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, one_time_keyboard=False)
    markup.add(
        KeyboardButton("📝 Пост на тему"),
        KeyboardButton("🎲 Рандом"),
        KeyboardButton("🔍 Поиск"),
        KeyboardButton("📅 Календарь"),
        KeyboardButton("📊 Статистика"),
        KeyboardButton("📜 История диалогов"),
        KeyboardButton("👥 Пользователи"),
        KeyboardButton("📨 Рассылка"),
        KeyboardButton("📤 Пост в канал"),
        KeyboardButton("🎭 Кто ты из RedRace?"),
        KeyboardButton("🛑 Стоп"),
        KeyboardButton("▶️ Старт"),
        KeyboardButton("🧠 Очистить историю"),
        KeyboardButton("⚙️ Настройки"),
        KeyboardButton("ℹ️ О системе")
    )
    return markup

def get_user_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, one_time_keyboard=False)
    markup.add(
        KeyboardButton("📅 Календарь"),
        KeyboardButton("ℹ️ О боте"),
        KeyboardButton("🎭 Кто ты из RedRace?")
    )
    return markup

# === HEALTHCHECK ===
async def health_check(request):
    return web.Response(text="Nico is alive", status=200)

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("✅ Health check server on port 8080")

# === ОБРАБОТЧИК ПОСТОВ ===
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

# === АДМИН ФУНКЦИИ ===
async def show_history(m):
    conn = sqlite3.connect("nico_bot.db")
    c = conn.cursor()
    c.execute("SELECT user_id, message, response, timestamp FROM chat_history ORDER BY timestamp DESC LIMIT 20")
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        await bot.send_message(m.chat.id, "📭 История пуста")
        return
    
    text = "📜 **Последние диалоги:**\n\n"
    for uid, msg, resp, ts in rows:
        text += f"**👤 {uid}** | {ts[:16]}\n❓ {msg[:80]}\n✅ {resp[:80]}\n\n---\n\n"
        if len(text) > 3500:
            await bot.send_message(m.chat.id, text, parse_mode="HTML")
            text = ""
    if text:
        await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def show_users(m):
    conn = sqlite3.connect("nico_bot.db")
    c = conn.cursor()
    c.execute("SELECT DISTINCT user_id, COUNT(*) FROM chat_history GROUP BY user_id ORDER BY COUNT(*) DESC")
    users = c.fetchall()
    conn.close()
    
    if not users:
        await bot.send_message(m.chat.id, "📭 Нет пользователей")
        return
    
    text = "👥 **Пользователи бота:**\n\n"
    for uid, count in users:
        text += f"🆔 `{uid}` — {count} сообщений\n"
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def clear_history(m):
    conn = sqlite3.connect("nico_bot.db")
    c = conn.cursor()
    c.execute("DELETE FROM chat_history")
    conn.commit()
    conn.close()
    await bot.send_message(m.chat.id, "🧠 Вся история диалогов очищена")

async def extended_stats(m):
    conn = sqlite3.connect("nico_bot.db")
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM chat_history")
    total_msgs = c.fetchone()[0]
    
    c.execute("SELECT COUNT(DISTINCT user_id) FROM chat_history")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT user_id, COUNT(*) FROM chat_history GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 1")
    top_user = c.fetchone()
    
    conn.close()
    
    uptime = time.time() - start_time
    stats = (
        f"📊 **Расширенная статистика**\n\n"
        f"📝 Всего сообщений: {total_msgs}\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🏆 Топ пользователь: `{top_user[0]}` ({top_user[1]} сообщ.)\n"
        f"⏱ Аптайм: {int(uptime//3600)}ч {int((uptime%3600)//60)}м\n"
        f"📡 Мониторинг: {'Активен' if monitoring else 'Остановлен'}\n"
        f"📊 Постов в канале: {posts_cnt}\n"
        f"💬 Диалогов: {dialogs_cnt}"
    )
    await bot.send_message(m.chat.id, stats, parse_mode="HTML")

async def broadcast_message(m):
    global wait_broadcast
    await bot.send_message(m.chat.id, "📨 Введите текст для рассылки всем пользователям:")
    wait_broadcast = True

async def send_broadcast(msg_text):
    conn = sqlite3.connect("nico_bot.db")
    c = conn.cursor()
    c.execute("SELECT DISTINCT user_id FROM chat_history")
    users = c.fetchall()
    conn.close()
    
    sent = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, f"📢 **Рассыл**\n\n{msg_text}", parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    
    await bot.send_message(ADMIN_IDS[0], f"✅ Рассылка отправлена {sent} пользователям")

async def post_to_channel_prompt(m):
    global wait_post
    await bot.send_message(m.chat.id, "📤 Отправь текст, фото или видео для публикации в канал.\nЕсли фото/видео — добавь подпись.")
    wait_post = True

async def publish_to_channel(m):
    global wait_post
    wait_post = False
    
    if m.text:
        await bot.send_message(CHANNEL_ID, m.text, parse_mode="HTML")
        await bot.send_message(m.chat.id, "✅ Текст опубликован в канале")
    elif m.photo:
        caption = m.caption if m.caption else None
        await bot.send_photo(CHANNEL_ID, m.photo[-1].file_id, caption=caption, parse_mode="HTML")
        await bot.send_message(m.chat.id, "✅ Фото опубликовано в канале")
    elif m.video:
        caption = m.caption if m.caption else None
        await bot.send_video(CHANNEL_ID, m.video.file_id, caption=caption, parse_mode="HTML")
        await bot.send_message(m.chat.id, "✅ Видео опубликовано в канале")
    else:
        await bot.send_message(m.chat.id, "❌ Неподдерживаемый тип медиа")

# === АДМИН ПАНЕЛЬ ===
async def admin_panel(m):
    if m.chat.id not in ADMIN_IDS:
        await bot.send_message(m.chat.id, "⛔ Доступ запрещен")
        return
    
    global monitoring
    uptime = time.time() - start_time
    
    status = (
        f"<b>Nico 1.0 Global</b>\n\n"
        f"<code>─────────────────────</code>\n"
        f"⚡️ Статус: {int(uptime//3600)}ч {int((uptime%3600)//60)}м\n"
        f"🎯 Мониторинг: {'Активен' if monitoring else 'Приостановлен'}\n"
        f"📊 Постов: {posts_cnt}\n"
        f"💬 Диалогов: {dialogs_cnt}\n"
        f"<code>─────────────────────</code>\n\n"
        f"<b>RedRace Development</b> | Apache 2.0"
    )
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_admin_keyboard())

# === ПОЛЬЗОВАТЕЛЬСКАЯ ПАНЕЛЬ ===
async def user_panel(m):
    status = f"<b>Nico 1.0 Global</b>\n\nПривет. Задавай вопросы про Формулу-1.\n\n<code>Nico | RedRace Development</code>"
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_user_keyboard())

# === ОБРАБОТЧИК СООБЩЕНИЙ ===
async def handle_msg(m):
    global monitoring, wait_search, wait_topic, wait_broadcast, wait_post
    
    if m.text and m.text.startswith('/'):
        return
    
    # Рассылка
    if wait_broadcast:
        await send_broadcast(m.text)
        wait_broadcast = False
        return
    
    # Пост в канал
    if wait_post:
        await publish_to_channel(m)
        return
    
    # Кнопка персонажа
    if m.text == "🎭 Кто ты из RedRace?":
        result = get_random_character()
        await bot.send_message(m.chat.id, result, parse_mode="HTML")
        return
    
    # Админ команды
    if m.chat.id in ADMIN_IDS:
        if m.text == "📜 История диалогов":
            await show_history(m)
            return
        elif m.text == "👥 Пользователи":
            await show_users(m)
            return
        elif m.text == "📨 Рассылка":
            await broadcast_message(m)
            return
        elif m.text == "📤 Пост в канал":
            await post_to_channel_prompt(m)
            return
        elif m.text == "📊 Статистика":
            await extended_stats(m)
            return
        elif m.text == "🧠 Очистить историю":
            await clear_history(m)
            return
        elif m.text == "🛑 Стоп":
            monitoring = False
            await bot.send_message(m.chat.id, "⛔ Мониторинг остановлен")
            return
        elif m.text == "▶️ Старт":
            monitoring = True
            await bot.send_message(m.chat.id, "✅ Мониторинг запущен")
            return
        elif m.text == "ℹ️ О системе":
            info = (
                f"<b>Nico 1.0 Global</b>\n\n"
                f"Версия: 1.0\n"
                f"Разработчик: RedRace Development\n"
                f"Лицензия: Apache 2.0\n\n"
                f"<b>Технологии:</b>\n"
                f"• LLM: OpenRouter\n"
                f"• Поиск: DuckDuckGo\n"
                f"• Парсинг: Newspaper3k\n\n"
                f"<code>RedRace Development 2026</code>"
            )
            await bot.send_message(m.chat.id, info, parse_mode="HTML")
            return
        elif m.text == "📝 Пост на тему":
            wait_topic = True
            await bot.send_message(m.chat.id, "📝 Тема поста:")
            return
        elif m.text == "🎲 Рандом":
            await bot.send_message(m.chat.id, "🎲 Генерирую...")
            post = await random_post()
            await bot.send_message(m.chat.id, post, parse_mode="HTML")
            inc_posts()
            return
        elif m.text == "🔍 Поиск":
            wait_search = True
            await bot.send_message(m.chat.id, "🔍 Поисковый запрос:")
            return
        elif m.text == "📅 Календарь":
            cal = await get_f1_calendar()
            await bot.send_message(m.chat.id, cal, parse_mode="HTML")
            return
        elif m.text == "⚙️ Настройки":
            await bot.send_message(m.chat.id, "⚙️ Настройки в разработке")
            return
    
    # Пользовательские команды
    if m.text == "📅 Календарь":
        cal = await get_f1_calendar()
        await bot.send_message(m.chat.id, cal, parse_mode="HTML")
        return
    elif m.text == "ℹ️ О боте":
        info = f"<b>Nico 1.0 Global</b>\n\nВерсия: 1.0\nРазработчик: RedRace Development\nЛицензия: Apache 2.0"
        await bot.send_message(m.chat.id, info, parse_mode="HTML")
        return
    
    # Ожидание поиска
    if wait_search:
        wait_search = False
        await bot.send_message(m.chat.id, "🔍 Ищу...")
        res = await search_f1(m.text)
        await bot.send_message(m.chat.id, f"🌐 Результаты:\n\n{res[:3000]}")
        return
    
    # Ожидание темы поста
    if wait_topic:
        wait_topic = False
        await bot.send_message(m.chat.id, "📝 Генерирую...")
        post = await post_on_topic(m.text)
        await bot.send_message(m.chat.id, post, parse_mode="HTML")
        inc_posts()
        return
    
    # Обычный чат
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

async def whoami_cmd(m):
    result = get_random_character()
    await bot.send_message(m.chat.id, result, parse_mode="HTML")

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
            print(f"☀️ Дайджест отправлен")
        except Exception as e:
            print(f"Digest error: {e}")

async def main():
    global bot
    bot = AsyncTeleBot(BOT_TOKEN)
    
    asyncio.create_task(start_health_server())
    
    @bot.message_handler(commands=['start', 'admin'])
    async def start_handler(m):
        await start_cmd(m)
    
    @bot.message_handler(commands=['whoami'])
    async def whoami_handler(m):
        await whoami_cmd(m)
    
    @bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video'])
    async def msg_handler(m):
        await handle_msg(m)
    
    asyncio.create_task(monitor(on_post))
    asyncio.create_task(morning_digest_worker())
    
    print("🌍 NICO 1.0 by RedRace Development")
    print("🧠 Модели: OpenRouter/free, NVIDIA Nemotron 3, GPT-OSS-120B, Gemma 2")
    print("📡 RSS: Autosport, Motorsport, The Race, PlanetF1, F1News")
    print("📅 Фильтр свежести: только новости до 7 дней")
    print("📝 Посты с правильными абзацами")
    print("🎭 Кнопка 'Кто ты из RedRace' + команда /whoami")
    print("Code by RedRace")
    
    await bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())
