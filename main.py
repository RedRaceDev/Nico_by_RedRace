import asyncio
import os
import time
import random
from datetime import datetime, timedelta
from telebot.async_telebot import AsyncTeleBot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

from scraper import (
    monitor, post_on_topic, random_post, get_calendar, chat_reply,
    mark_posted, morning_digest, ask_gemini, switch_model, get_current_model_id,
    get_pending_posts, clear_pending_posts, set_pending_posts
)
from search_engine import search_web
from database import init_db, save_conversation, get_stats, get_all_users, get_last_dialogs, clear_all_history, get_user_message_count

# === КОНФИГ ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"
BETA_USERS = {7076945880: "sunrise"}

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
test_mode_active = False
waiting_photo_analysis = False
MY_BOT_ID = None
BOT_USERNAME = "RedNico_bot"

def inc_posts(): 
    global posts_cnt
    posts_cnt += 1

def inc_dialogs(): 
    global dialogs_cnt
    dialogs_cnt += 1

def is_admin(user_id): 
    return user_id in ADMIN_IDS

def is_beta(user_id): 
    return user_id in BETA_USERS

def get_beta_name(user_id): 
    return BETA_USERS.get(user_id, "Бета-тестер")

# === ПЕРСОНАЖИ ===
REDRACE_CHARACTERS = {
    "Псиникс": "Ебланище конченное. Роман с Райконненом. Проебал 10кк на Пиастри.",
    "Вхуй": "Уебище жирное, дизайнер который нихуя не делает.",
    "Кими": "Создатель канала. Муж Псиникса. Топ 1 по заглатыванию.",
    "Макс_Это_Скам": "Влиятельный хуй.",
    "Пьер Гасли": "Нормальный тип, но не скинул писюн в ЛС.",
    "Пиастри": "Уебище из-за которого Псиникс проебал 10кк.",
    "Берман": "Нытик, ездит по гравию.",
    "Хирошима": "ФЕРНАНДО АЛОНСО. Долбаеб.",
    "СанРайз": "Жирное уебище, психопат.",
    "Акира": "Котакбас. Главное хуйло чата.",
    "Артур": "Позорно проебал во Франции.",
    "Мохмед": "Перестань просить ливреи.",
    "Ghinok": "Горшочек петушочек, подрабатывает ершиком на зоне."
}

def get_random_character():
    name, desc = random.choice(list(REDRACE_CHARACTERS.items()))
    return f"🎭 <b>Ты — {name}</b>\n\n{desc}\n\n#RedRace"

# === КЛАВИАТУРЫ ===
def get_admin_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton("📝 Пост на тему"), KeyboardButton("🎲 Рандом"),
        KeyboardButton("🔍 Поиск"), KeyboardButton("📅 Календарь"),
        KeyboardButton("📊 Статистика"), KeyboardButton("📜 История"),
        KeyboardButton("👥 Пользователи"), KeyboardButton("📨 Рассылка"),
        KeyboardButton("📤 Пост в канал"), KeyboardButton("🎭 Случайный персонаж"),
        KeyboardButton("🛑 Стоп"), KeyboardButton("▶️ Старт"),
        KeyboardButton("📰 Новости"), KeyboardButton("✅ Опубликовать"),
        KeyboardButton("🧠 Очистить"), KeyboardButton("🎛️ Сменить модель"),
        KeyboardButton("🔬 Анализ фото"), KeyboardButton("ℹ️ О системе")
    )
    return markup

def get_beta_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton("📝 Пост на тему"), KeyboardButton("🎲 Рандом"),
        KeyboardButton("🔍 Поиск"), KeyboardButton("📅 Календарь"),
        KeyboardButton("📊 Статистика"), KeyboardButton("🎭 Случайный персонаж"),
        KeyboardButton("🐞 Сообщить о баге"), KeyboardButton("👤 Мой профиль"),
        KeyboardButton("🔬 Режим отладки"), KeyboardButton("📈 Телеметрия"),
        KeyboardButton("🎮 Тестовый режим"), KeyboardButton("🔐 Бета-консоль"),
        KeyboardButton("📖 Документация"), KeyboardButton("🎛️ Сменить модель"),
        KeyboardButton("🔬 Анализ фото")
    )
    return markup

def get_user_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton("📅 Календарь"),
        KeyboardButton("🎭 Случайный персонаж"),
        KeyboardButton("🎮 Карточная игра"),
        KeyboardButton("🔬 Анализ фото")
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
    print(f"✅ Health check on port {port}")

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

# === АНАЛИЗ ФОТО ===
async def analyze_photo_command(m):
    global waiting_photo_analysis
    waiting_photo_analysis = True
    await bot.send_message(m.chat.id, "📸 Отправь фото болида или трассы")

async def handle_photo_analysis(m):
    global waiting_photo_analysis
    if not waiting_photo_analysis:
        return
    waiting_photo_analysis = False
    
    if not m.photo:
        await bot.reply_to(m, "❌ Отправь фото")
        return
    
    status = await bot.reply_to(m, "🔍 Анализирую...")
    prompt = "Ты гоночный инженер. Проанализируй это фото: что за машина, какие технические особенности?"
    analysis = await ask_gemini(prompt)
    await bot.edit_message_text(f"📸 **Анализ:**\n\n{analysis}", 
                                chat_id=m.chat.id, 
                                message_id=status.message_id, 
                                parse_mode="HTML")

# === АДМИН ФУНКЦИИ ===
async def show_history(m):
    rows = get_last_dialogs(20)
    if not rows:
        await bot.send_message(m.chat.id, "📭 Пусто")
        return
    text = "📜 Последние диалоги:\n\n"
    for uid, msg, resp, ts in rows:
        text += f"👤 {uid} | {ts[:16]}\n❓ {msg[:80]}\n✅ {resp[:80]}\n\n---\n\n"
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
    text = "👥 Пользователи:\n\n"
    for uid, count in users[:50]:
        text += f"🆔 {uid} — {count} сообщений\n"
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def extended_stats(m):
    stats = get_stats()
    uptime = time.time() - start_time
    text = f"""📊 Статистика

📝 Постов: {stats['posts']}
💬 Диалогов: {stats['dialogs']}
👥 Пользователей: {stats['users']}
📡 Мониторинг: {'✅' if monitoring else '⛔'}
⏱ Аптайм: {int(uptime//3600)}ч
🤖 Модель: {get_current_model_id()}"""
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def clear_history(m):
    clear_all_history()
    await bot.send_message(m.chat.id, "🧠 История очищена")

async def show_pending_posts(m):
    posts = get_pending_posts()
    if not posts:
        await bot.send_message(m.chat.id, "📭 Новостей нет")
        return
    text = f"📰 Готово ({len(posts)}):\n\n"
    for i, p in enumerate(posts[:10], 1):
        text += f"{i}. {p['title'][:70]}\n"
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def publish_all_posts(m):
    posts = get_pending_posts()
    if not posts:
        await bot.send_message(m.chat.id, "📭 Нет новостей")
        return
    await bot.send_message(m.chat.id, f"📤 Публикую {len(posts)} постов...")
    for p in posts:
        await on_post(p['post'], p['title'], p['link'])
        await asyncio.sleep(3)
    clear_pending_posts()
    await bot.send_message(m.chat.id, f"✅ Опубликовано {len(posts)} постов")

# === УПРАВЛЕНИЕ МОДЕЛЯМИ ===
async def model_selector(m):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🚀 Gemini 3.5", callback_data="model_gemini_35"),
        InlineKeyboardButton("🔥 Gemini 2.0", callback_data="model_gemini_20"),
        InlineKeyboardButton("⚡ Gemini 1.5", callback_data="model_gemini_lite"),
        InlineKeyboardButton("🌐 OpenRouter", callback_data="model_openrouter"),
        InlineKeyboardButton("💪 Nemotron", callback_data="model_nemotron"),
        InlineKeyboardButton("🎯 GPT-OSS", callback_data="model_gpt_oss")
    )
    current = get_current_model_id()
    await bot.send_message(m.chat.id, f"🎛️ **Модель:** `{current}`", 
                          parse_mode="HTML", reply_markup=kb)

# === БЕТА ФУНКЦИИ ===
async def beta_doc(m):
    doc = """📖 Документация

🔬 Отладка — техническая инфа
📈 Телеметрия — статистика
🎮 Тестовый режим — сырые ответы
🔐 Консоль — личный кабинет
🐞 Баг — отправить админу
👤 Профиль — твоя статистика"""
    await bot.send_message(m.chat.id, doc, parse_mode="HTML")

async def beta_console(m):
    stats = get_stats()
    msgs = get_user_message_count(m.chat.id)
    text = f"""🔐 Бета-консоль

Роль: бета-тестер
Сообщений: {msgs}
Постов: {stats['posts']}
Диалогов: {stats['dialogs']}
Модель: {get_current_model_id()}"""
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def debug_mode(m):
    text = f"""🔬 Отладка

Бот ID: {MY_BOT_ID}
Мониторинг: {'✅' if monitoring else '❌'}
Аптайм: {int((time.time()-start_time)//3600)}ч
Модель: {get_current_model_id()}"""
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def show_telemetry(m):
    stats = get_stats()
    text = f"""📈 Телеметрия

Постов: {stats['posts']}
Диалогов: {stats['dialogs']}
Пользователей: {stats['users']}"""
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def test_mode_cmd(m):
    global test_mode_active
    test_mode_active = True
    await bot.send_message(m.chat.id, "🎮 Тестовый режим. Напиши запрос.")

async def handle_test_mode(m):
    global test_mode_active
    if not test_mode_active:
        return
    test_mode_active = False
    status = await bot.send_message(m.chat.id, "🔬 Генерирую...")
    raw = await ask_gemini(m.text)
    await bot.delete_message(m.chat.id, status.message_id)
    await bot.send_message(m.chat.id, f"**Ответ:**\n\n{raw[:2000]}")

async def bug_report(m):
    global wait_bug
    await bot.send_message(m.chat.id, "🐞 Опиши баг:")
    wait_bug = True

async def save_bug_report(m):
    global wait_bug
    wait_bug = False
    report = f"🐞 БАГ\nОт: {m.chat.id}\n{m.text}"
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, report)
        except:
            pass
    await bot.send_message(m.chat.id, "✅ Баг отправлен")

async def show_profile(m):
    msgs = get_user_message_count(m.chat.id)
    stats = get_stats()
    role = "Бета" if is_beta(m.chat.id) else "Пользователь"
    text = f"""👤 Профиль

Сообщений: {msgs}
Постов: {stats['posts']}
Роль: {role}"""
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

# === ОБЩИЕ ФУНКЦИИ ===
async def broadcast_message(m):
    global wait_broadcast
    await bot.send_message(m.chat.id, "📨 Текст рассылки:")
    wait_broadcast = True

async def send_broadcast(msg_text):
    users = get_all_users()
    sent = 0
    for uid, _ in users:
        try:
            await bot.send_message(int(uid), f"📢 **Рассылка**\n\n{msg_text}", parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await bot.send_message(ADMIN_IDS[0], f"✅ Отправлено {sent}")

async def post_to_channel_prompt(m):
    global wait_post
    await bot.send_message(m.chat.id, "📤 Отправь в канал (30 сек):")
    wait_post = True
    asyncio.create_task(reset_post_timeout())

async def reset_post_timeout():
    global wait_post
    await asyncio.sleep(30)
    if wait_post:
        wait_post = False

async def publish_to_channel(m):
    global wait_post
    if not wait_post:
        return
    wait_post = False
    try:
        if m.text:
            await bot.send_message(CHANNEL_ID, m.text, parse_mode="HTML")
        elif m.photo:
            caption = m.caption or ""
            await bot.send_photo(CHANNEL_ID, m.photo[-1].file_id, caption=caption, parse_mode="HTML")
        elif m.video:
            caption = m.caption or ""
            await bot.send_video(CHANNEL_ID, m.video.file_id, caption=caption, parse_mode="HTML")
        await bot.send_message(m.chat.id, "✅ Опубликовано")
    except Exception as e:
        await bot.send_message(m.chat.id, f"❌ Ошибка: {e}")

async def cancel_action(m):
    global wait_post, wait_broadcast, wait_search, wait_topic, test_mode_active, wait_bug, waiting_photo_analysis
    wait_post = False
    wait_broadcast = False
    wait_search = False
    wait_topic = False
    test_mode_active = False
    wait_bug = False
    waiting_photo_analysis = False
    await bot.send_message(m.chat.id, "❌ Отменено")

async def handle_ask(m):
    query = m.text.replace('/ask', '').strip()
    if not query:
        await bot.reply_to(m, "❓ Напиши вопрос")
        return
    status_msg = await bot.reply_to(m, "🔍 Ищу...")
    result = await search_web(query)
    await bot.edit_message_text(result, chat_id=m.chat.id, message_id=status_msg.message_id, parse_mode="HTML")

# === ПАНЕЛИ ===
async def admin_panel(m):
    if not is_admin(m.chat.id):
        await bot.send_message(m.chat.id, "⛔ Доступ запрещен")
        return
    uptime = time.time() - start_time
    status = f"""👑 Нико онлайн

Аптайм: {int(uptime//3600)}ч
Мониторинг: {'✅' if monitoring else '⛔'}
Постов: {posts_cnt}
Диалогов: {dialogs_cnt}
Новостей: {len(get_pending_posts())}
Модель: {get_current_model_id()}"""
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_admin_keyboard())

async def beta_panel(m):
    if not is_beta(m.chat.id):
        await bot.send_message(m.chat.id, "⛔ Доступ запрещен")
        return
    stats = get_stats()
    msgs = get_user_message_count(m.chat.id)
    uptime = time.time() - start_time
    status = f"""🤖 Привет, {get_beta_name(m.chat.id)}

Аптайм: {int(uptime//3600)}ч
Постов: {stats['posts']}
Твоих сообщений: {msgs}
Модель: {get_current_model_id()}"""
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_beta_keyboard())

async def user_panel(m):
    status = """🏎️ Я Нико 3.0 — твой гоночный инженер.

• Отвечаю на вопросы про F1
• Анализирую фото
• Ищу новости
• Помню диалоги

🎮 Карточная игра: @sipmly_flag_bot"""
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_user_keyboard())

# === ОСНОВНОЙ ОБРАБОТЧИК ===
async def handle_msg(m):
    global wait_search, wait_topic, wait_broadcast, wait_post, wait_bug, test_mode_active, MY_BOT_ID, waiting_photo_analysis
    
    if m.text and m.text.startswith('/ask'):
        await handle_ask(m)
        return
    
    if m.text and m.text.startswith('/'):
        return
    
    if m.photo and waiting_photo_analysis:
        await handle_photo_analysis(m)
        return
    
    is_group = m.chat.type in ['group', 'supergroup']
    if is_group:
        if MY_BOT_ID is None:
            me = await bot.get_me()
            MY_BOT_ID = me.id
            global BOT_USERNAME
            BOT_USERNAME = me.username
        if m.text:
            if not (f'@{BOT_USERNAME}' in m.text or (m.reply_to_message and m.reply_to_message.from_user.id == MY_BOT_ID)):
                return
            m.text = m.text.replace(f'@{BOT_USERNAME}', '').strip()
    
    if wait_bug:
        await save_bug_report(m)
        return
    if wait_broadcast:
        await send_broadcast(m.text)
        wait_broadcast = False
        return
    if wait_post:
        await publish_to_channel(m)
        return
    if test_mode_active:
        await handle_test_mode(m)
        return
    
    # Админ команды
    if is_admin(m.chat.id) and m.text:
        if m.text == "📜 История":
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
        elif m.text == "🧠 Очистить":
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
            await bot.send_message(m.chat.id, "Nico 3.0 | Red Race")
            return
        elif m.text == "📝 Пост на тему":
            wait_topic = True
            await bot.send_message(m.chat.id, "📝 Тема:")
            return
        elif m.text == "🎲 Рандом":
            post = await random_post()
            await bot.send_message(m.chat.id, post, parse_mode="HTML")
            inc_posts()
            return
        elif m.text == "🔍 Поиск":
            wait_search = True
            await bot.send_message(m.chat.id, "🔍 Запрос:")
            return
        elif m.text == "📅 Календарь":
            await bot.send_message(m.chat.id, await get_calendar(), parse_mode="HTML")
            return
        elif m.text == "🎭 Случайный персонаж":
            await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")
            return
        elif m.text == "📰 Новости":
            await show_pending_posts(m)
            return
        elif m.text == "✅ Опубликовать":
            await publish_all_posts(m)
            return
        elif m.text == "🎛️ Сменить модель":
            await model_selector(m)
            return
        elif m.text == "🔬 Анализ фото":
            await analyze_photo_command(m)
            return
    
    # Бета команды
    if is_beta(m.chat.id) and m.text:
        if m.text == "📖 Документация":
            await beta_doc(m)
            return
        elif m.text == "🔐 Бета-консоль":
            await beta_console(m)
            return
        elif m.text == "🔬 Режим отладки":
            await debug_mode(m)
            return
        elif m.text == "📈 Телеметрия":
            await show_telemetry(m)
            return
        elif m.text == "🎮 Тестовый режим":
            await test_mode_cmd(m)
            return
        elif m.text == "🐞 Сообщить о баге":
            await bug_report(m)
            return
        elif m.text == "👤 Мой профиль":
            await show_profile(m)
            return
        elif m.text == "📝 Пост на тему":
            wait_topic = True
            await bot.send_message(m.chat.id, "📝 Тема:")
            return
        elif m.text == "🎲 Рандом":
            post = await random_post()
            await bot.send_message(m.chat.id, post, parse_mode="HTML")
            inc_posts()
            return
        elif m.text == "🔍 Поиск":
            wait_search = True
            await bot.send_message(m.chat.id, "🔍 Запрос:")
            return
        elif m.text == "📅 Календарь":
            await bot.send_message(m.chat.id, await get_calendar(), parse_mode="HTML")
            return
        elif m.text == "📊 Статистика":
            await extended_stats(m)
            return
        elif m.text == "🎭 Случайный персонаж":
            await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")
            return
        elif m.text == "🎛️ Сменить модель":
            await model_selector(m)
            return
        elif m.text == "🔬 Анализ фото":
            await analyze_photo_command(m)
            return
    
    # Пользовательские команды
    if m.text == "📅 Календарь":
        await bot.send_message(m.chat.id, await get_calendar(), parse_mode="HTML")
        return
    elif m.text == "🎭 Случайный персонаж":
        await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")
        return
    elif m.text == "🎮 Карточная игра":
        await bot.send_message(m.chat.id, "🎴 @sipmly_flag_bot\n\nRed Race", parse_mode="HTML")
        return
    elif m.text == "🔬 Анализ фото":
        await analyze_photo_command(m)
        return
    
    # Поиск
    if wait_search:
        wait_search = False
        await bot.send_message(m.chat.id, "🔍 Ищу...")
        res = await search_web(m.text)
        await bot.send_message(m.chat.id, res, parse_mode="HTML")
        return
    
    # Пост на тему
    if wait_topic:
        wait_topic = False
        await bot.send_message(m.chat.id, "📝 Генерирую...")
        post = await post_on_topic(m.text)
        await bot.send_message(m.chat.id, post, parse_mode="HTML")
        inc_posts()
        return
    
    # Обычный чат
    status = await bot.send_message(m.chat.id, "🤔 Думаю...")
    ans = await chat_reply(m.chat.id, m.text, use_search=True)
    await bot.delete_message(m.chat.id, status.message_id)
    await bot.send_message(m.chat.id, ans, parse_mode="HTML")
    inc_dialogs()
    save_conversation(str(m.chat.id), m.text, ans)

async def start_cmd(m):
    if is_admin(m.chat.id):
        await admin_panel(m)
    elif is_beta(m.chat.id):
        await beta_panel(m)
    else:
        await user_panel(m)

async def whoami_cmd(m):
    await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")

async def cancel_cmd(m):
    await cancel_action(m)

async def model_callback(call):
    model_map = {
        "model_gemini_35": "gemini_35",
        "model_gemini_20": "gemini_20",
        "model_gemini_lite": "gemini_lite",
        "model_openrouter": "openrouter",
        "model_nemotron": "nemotron",
        "model_gpt_oss": "gpt_oss"
    }
    model_key = model_map.get(call.data)
    if model_key and switch_model(model_key):
        await bot.answer_callback_query(call.id, f"✅ Переключено")
        await bot.edit_message_text(f"✅ Модель: {model_key}", 
                                    chat_id=call.message.chat.id, 
                                    message_id=call.message.message_id)
    else:
        await bot.answer_callback_query(call.id, "❌ Ошибка")

async def morning_digest_worker():
    while True:
        now = datetime.now()
        target = now.replace(hour=9, minute=0, second=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            digest = await morning_digest()
            await bot.send_message(CHANNEL_ID, digest, parse_mode="HTML")
            print("☀️ Дайджест отправлен")
        except Exception as e:
            print(f"Digest error: {e}")

async def main():
    global bot, MY_BOT_ID
    
    init_db()
    await start_health_server()
    
    bot = AsyncTeleBot(BOT_TOKEN)
    
    me = await bot.get_me()
    MY_BOT_ID = me.id
    global BOT_USERNAME
    BOT_USERNAME = me.username
    print(f"🤖 @{BOT_USERNAME} | ID: {MY_BOT_ID}")
    
    @bot.message_handler(commands=['start', 'admin'])
    async def start_handler(m): await start_cmd(m)
    
    @bot.message_handler(commands=['whoami'])
    async def whoami_handler(m): await whoami_cmd(m)
    
    @bot.message_handler(commands=['cancel'])
    async def cancel_handler(m): await cancel_cmd(m)
    
    @bot.message_handler(commands=['model'])
    async def model_handler(m):
        if is_admin(m.chat.id) or is_beta(m.chat.id):
            await model_selector(m)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("model_"))
    async def model_callback_handler(call): await model_callback(call)
    
    @bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video'])
    async def msg_handler(m): await handle_msg(m)
    
    asyncio.create_task(monitor())
    asyncio.create_task(morning_digest_worker())
    
    print("🚀 NICO 3.0 STARTED")
    print(f"👑 Админ: {ADMIN_IDS}")
    print(f"🔧 Бета: {list(BETA_USERS.keys())}")
    print(f"🤖 Модель: {get_current_model_id()}")
    
    await bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())
