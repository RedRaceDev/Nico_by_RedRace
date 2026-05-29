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
from database import init_db, save_conversation, get_stats, get_all_users, get_last_dialogs, clear_all_history, get_user_message_count

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"

# === БЕТА-ТЕСТЕРЫ ===
BETA_USERS = {
    7076945880: "sunrise"
}

bot = None
monitoring = True
posts_cnt = 0
dialogs_cnt = 0
start_time = time.time()
wait_search = False
wait_topic = False
wait_broadcast = False
wait_post = False
wait_bug = False
MY_BOT_ID = None
BOT_USERNAME = "Nico_by_RR_bot"

def inc_posts(): global posts_cnt; posts_cnt += 1
def inc_dialogs(): global dialogs_cnt; dialogs_cnt += 1

def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_beta(user_id):
    return user_id in BETA_USERS

def get_beta_name(user_id):
    return BETA_USERS.get(user_id, "Бета-тестер")

# === ПЕРСОНАЖИ ===
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
        KeyboardButton("📝 Пост на тему"), KeyboardButton("🎲 Рандом"),
        KeyboardButton("🔍 Поиск"), KeyboardButton("📅 Календарь"),
        KeyboardButton("📊 Статистика"), KeyboardButton("📜 История диалогов"),
        KeyboardButton("👥 Пользователи"), KeyboardButton("📨 Рассылка"),
        KeyboardButton("📤 Пост в канал"), KeyboardButton("🎭 Кто ты из RedRace?"),
        KeyboardButton("🛑 Стоп"), KeyboardButton("▶️ Старт"),
        KeyboardButton("🧠 Очистить историю"), KeyboardButton("ℹ️ О системе")
    )
    return markup

def get_beta_keyboard(user_name):
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, one_time_keyboard=False)
    markup.add(
        KeyboardButton("📝 Пост на тему"),
        KeyboardButton("🎲 Рандом"),
        KeyboardButton("🔍 Поиск"),
        KeyboardButton("📅 Календарь"),
        KeyboardButton("📊 Статистика"),
        KeyboardButton("🎭 Кто ты из RedRace?"),
        KeyboardButton("🐞 Сообщить о баге"),
        KeyboardButton(f"👤 Мой профиль")
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
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Health check server on port {port}")

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
    rows = get_last_dialogs(20)
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
    users = get_all_users()
    if not users:
        await bot.send_message(m.chat.id, "📭 Нет пользователей")
        return
    text = "👥 **Пользователи бота:**\n\n"
    for uid, count, last in users:
        text += f"🆔 `{uid}` — {count} сообщений\n"
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def clear_history(m):
    clear_all_history()
    await bot.send_message(m.chat.id, "🧠 Вся история диалогов очищена")

async def extended_stats(m):
    stats = get_stats()
    uptime = time.time() - start_time
    text = (
        f"📊 **Статистика**\n\n"
        f"📝 Постов: {stats['posts']}\n"
        f"💬 Диалогов: {stats['dialogs']}\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"📡 Мониторинг: {'Активен' if monitoring else 'Остановлен'}\n"
        f"⏱ Аптайм: {int(uptime//3600)}ч {int((uptime%3600)//60)}м"
    )
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def broadcast_message(m):
    global wait_broadcast
    await bot.send_message(m.chat.id, "📨 Введите текст для рассылки всем пользователям:")
    wait_broadcast = True

async def send_broadcast(msg_text):
    users = get_all_users()
    sent = 0
    for (uid, _, _) in users:
        try:
            await bot.send_message(uid, f"📢 **Рассылка от администрации**\n\n{msg_text}", parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await bot.send_message(ADMIN_IDS[0], f"✅ Рассылка отправлена {sent} пользователям")

async def post_to_channel_prompt(m):
    global wait_post
    await bot.send_message(m.chat.id, "📤 Отправь текст, фото или видео для публикации в канал.\nУ тебя 30 секунд. Для отмены нажми /cancel")
    wait_post = True
    asyncio.create_task(reset_wait_post_after_timeout(30))

async def reset_wait_post_after_timeout(seconds):
    global wait_post
    await asyncio.sleep(seconds)
    if wait_post:
        wait_post = False
        print("⚠️ Режим публикации автоматически отключен")

async def publish_to_channel(m):
    global wait_post
    if not wait_post:
        return
    wait_post = False
    try:
        if m.text:
            await bot.send_message(CHANNEL_ID, m.text, parse_mode="HTML")
            await bot.send_message(m.chat.id, "✅ Текст опубликован")
        elif m.photo:
            caption = m.caption if m.caption else None
            await bot.send_photo(CHANNEL_ID, m.photo[-1].file_id, caption=caption, parse_mode="HTML")
            await bot.send_message(m.chat.id, "✅ Фото опубликовано")
        elif m.video:
            caption = m.caption if m.caption else None
            await bot.send_video(CHANNEL_ID, m.video.file_id, caption=caption, parse_mode="HTML")
            await bot.send_message(m.chat.id, "✅ Видео опубликовано")
        else:
            await bot.send_message(m.chat.id, "❌ Неподдерживаемый тип")
    except Exception as e:
        await bot.send_message(m.chat.id, f"❌ Ошибка: {e}")

# === БЕТА-ФУНКЦИИ ===
async def beta_panel(m):
    user_id = m.chat.id
    user_name = get_beta_name(user_id)
    uptime = time.time() - start_time
    stats = get_stats()
    user_msgs = get_user_message_count(user_id)
    
    status = (
        f"<b>🤖 NICO 1.0 | {user_name}</b>\n\n"
        f"<code>─────────────────────</code>\n"
        f"👤 <b>Имя:</b> {user_name}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"⚡️ <b>Статус:</b> {int(uptime//3600)}ч {int((uptime%3600)//60)}м\n"
        f"📊 <b>Постов:</b> {stats['posts']}\n"
        f"💬 <b>Диалогов:</b> {stats['dialogs']}\n"
        f"💬 <b>Твоих сообщений:</b> {user_msgs}\n"
        f"🎖 <b>Роль:</b> Бета-тестер\n"
        f"<code>─────────────────────</code>\n\n"
        f"<i>Твой личный кабинет. Тестируй, находи баги, помогай проекту!</i>"
    )
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_beta_keyboard(user_name))

async def show_beta_profile(m):
    user_id = m.chat.id
    user_name = get_beta_name(user_id)
    user_msgs = get_user_message_count(user_id)
    
    profile = (
        f"👤 <b>Профиль пользователя</b>\n\n"
        f"<code>─────────────────────</code>\n"
        f"📛 <b>Имя:</b> {user_name}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"🎖 <b>Роль:</b> 🔧 Бета-тестер\n"
        f"💬 <b>Сообщений боту:</b> {user_msgs}\n"
        f"<code>─────────────────────</code>\n\n"
        f"<i>У тебя есть доступ к тестовым функциям. Помогай находить баги!</i>\n\n"
        f"<code>RedRace Development 2026</code>"
    )
    await bot.send_message(m.chat.id, profile, parse_mode="HTML")

async def bug_report(m):
    global wait_bug
    await bot.send_message(m.chat.id, "🐞 Опиши баг подробно. Приложи скриншот если есть.")
    wait_bug = True

async def save_bug_report(m):
    global wait_bug
    wait_bug = False
    bug_text = m.text
    timestamp = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
    user_id = m.chat.id
    user_name = get_beta_name(user_id)
    
    report = (
        f"🐞 **НОВЫЙ БАГ**\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"👤 Пользователь: `{user_id}` ({user_name})\n"
        f"📅 Время: {timestamp}\n"
        f"📝 Описание:\n{bug_text}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"<code>Бета-тестер сообщил об ошибке</code>"
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, report, parse_mode="HTML")
        except:
            pass
    
    await bot.send_message(m.chat.id, "✅ Баг отправлен администратору. Спасибо!")

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

# === ОСНОВНОЙ ОБРАБОТЧИК ===
async def handle_msg(m):
    global monitoring, wait_search, wait_topic, wait_broadcast, wait_post, wait_bug, MY_BOT_ID
    
    if m.text and m.text.startswith('/'):
        return
    
    # === ЛОГИКА ДЛЯ ГРУППОВЫХ ЧАТОВ ===
    is_group = m.chat.type in ['group',
