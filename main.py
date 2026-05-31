import asyncio
import os
import time
import random
from datetime import datetime, timedelta
from telebot.async_telebot import AsyncTeleBot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web

from scraper import (
    monitor, post_on_topic, random_post, get_calendar, chat_reply,
    search_f1, mark_posted, morning_digest, ask_gemini,
    get_pending_posts, clear_pending_posts, set_pending_posts
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
test_mode_active = False
MY_BOT_ID = None
BOT_USERNAME = "RedNico_bot"

def inc_posts(): global posts_cnt; posts_cnt += 1
def inc_dialogs(): global dialogs_cnt; dialogs_cnt += 1

def is_admin(user_id): return user_id in ADMIN_IDS
def is_beta(user_id): return user_id in BETA_USERS
def get_beta_name(user_id): return BETA_USERS.get(user_id, "Бета-тестер")

# === ПЕРСОНАЖИ ===
REDRACE_CHARACTERS = {
    "Псиникс": "Ебланище конченное. Работает в РедРейзе. Роман с Райконненом. Проебал 10кк поставив на Пиастри.",
    "Вхуй": "Уебище жирное. Сирота, лучший дизайнер которого знает Кими, но который нихуя не делает.",
    "Кими": "Создатель канала РедРейз. Муж Псиникса. Топ 1 по заглатыванию.",
    "Макс_Это_Скам": "влиятельный хуй. Что ещё сказать.",
    "Пьер Гасли": "нормальный тип, но не скинул писюн в ЛС. ФУУУУ",
    "Пиастри": "Уебище из-за которого Псиникс проебал 10кк.",
    "Берман": "Нытик, ездит по гравию. Съебался в ужасе.",
    "Хирошима": "ОООО ФЕРНАНДО АЛОНСО. Долбаеб.",
    "СанРайз": "жирное уебище, психопат.",
    "Акира": "котакбас. Главное хуйло чата.",
    "Артур¹¹": "позорно проебал во Франции.",
    "МохмедАлл": "перестань просить ливреи. Всем ПОХУЙ.",
    "Ghinok": "Горшочек петушочек, подрабатывает ершиком на зоне."
}

def get_random_character():
    name, desc = random.choice(list(REDRACE_CHARACTERS.items()))
    return f"🎭 <b>Ты — {name}</b>\n\n{desc}\n\n#RedRace"

# === КЛАВИАТУРЫ ===
def get_admin_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton("📝 Пост на тему"),
        KeyboardButton("🎲 Рандом"),
        KeyboardButton("🔍 Поиск"),
        KeyboardButton("📅 Календарь"),
        KeyboardButton("📊 Статистика"),
        KeyboardButton("📜 История"),
        KeyboardButton("👥 Пользователи"),
        KeyboardButton("📨 Рассылка"),
        KeyboardButton("📤 Пост в канал"),
        KeyboardButton("🎭 Персонаж"),
        KeyboardButton("🛑 Стоп"),
        KeyboardButton("▶️ Старт"),
        KeyboardButton("📰 Новости"),
        KeyboardButton("✅ Опубликовать"),
        KeyboardButton("🧠 Очистить"),
        KeyboardButton("ℹ️ О системе")
    )
    return markup

def get_beta_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton("📝 Пост на тему"), KeyboardButton("🎲 Рандом"),
        KeyboardButton("🔍 Поиск"), KeyboardButton("📅 Календарь"),
        KeyboardButton("📊 Статистика"), KeyboardButton("🎭 Персонаж"),
        KeyboardButton("🐞 Баг"), KeyboardButton("👤 Профиль"),
        KeyboardButton("🔬 Отладка"), KeyboardButton("📈 Телеметрия"),
        KeyboardButton("🎮 Тест"), KeyboardButton("🔐 Консоль"),
        KeyboardButton("📖 Документация")
    )
    return markup

def get_user_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton("📅 Календарь"),
        KeyboardButton("ℹ️ О боте"),
        KeyboardButton("🎭 Персонаж"),
        KeyboardButton("🎮 Карточная игра")
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
    for uid, count in users:
        text += f"🆔 {uid} — {count} сообщений\n"
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def extended_stats(m):
    stats = get_stats()
    uptime = time.time() - start_time
    text = f"""📊 Статистика

📝 Постов: {stats['posts']}
💬 Диалогов: {stats['dialogs']}
👥 Пользователей: {stats['users']}
📡 Мониторинг: {'Активен' if monitoring else 'Остановлен'}
⏱ Аптайм: {int(uptime//3600)}ч

Red Race | Подписаться"""
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def clear_history(m):
    clear_all_history()
    await bot.send_message(m.chat.id, "🧠 История очищена")

async def show_pending_posts(m):
    posts = get_pending_posts()
    if not posts:
        await bot.send_message(m.chat.id, "📭 Новых новостей нет")
        return
    text = f"📰 Готово к публикации ({len(posts)}):\n\n"
    for i, p in enumerate(posts, 1):
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

# === БЕТА ФУНКЦИИ ===
async def beta_doc(m):
    doc = """📖 Документация

🔬 Отладка — тех. информация
📈 Телеметрия — статистика
🎮 Тест — сырые ответы ИИ
🔐 Консоль — личный кабинет
🐞 Баг — отправить баг
👤 Профиль — твоя статистика

Red Race | Подписаться"""
    await bot.send_message(m.chat.id, doc, parse_mode="HTML")

async def beta_console(m):
    stats = get_stats()
    msgs = get_user_message_count(m.chat.id)
    text = f"""🔐 Бета-консоль

Роль: бета-тестер
Твоих сообщений: {msgs}
Постов: {stats['posts']}
Диалогов: {stats['dialogs']}

Red Race | Подписаться"""
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def debug_mode(m):
    text = f"""🔬 Отладка

Бот ID: {MY_BOT_ID}
Мониторинг: {'✅' if monitoring else '❌'}
Пользователей: {len(get_all_users())}
Аптайм: {int((time.time()-start_time)//3600)}ч

Red Race | Подписаться"""
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def show_telemetry(m):
    stats = get_stats()
    text = f"""📈 Телеметрия

Постов: {stats['posts']}
Диалогов: {stats['dialogs']}
Пользователей: {stats['users']}
Источников: 6

Red Race | Подписаться"""
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def test_mode_cmd(m):
    global test_mode_active
    test_mode_active = True
    await bot.send_message(m.chat.id, "🎮 Тестовый режим включен. Напиши запрос.")

async def handle_test_mode(m):
    global test_mode_active
    if not test_mode_active:
        return
    test_mode_active = False
    status = await bot.send_message(m.chat.id, "🔬 Генерирую...")
    raw = await ask_gemini(m.text)
    await bot.delete_message(m.chat.id, status.message_id)
    await bot.send_message(m.chat.id, f"**Сырой ответ:**\n\n{raw[:2000]}")

async def bug_report(m):
    global wait_bug
    await bot.send_message(m.chat.id, "🐞 Опиши баг:")
    wait_bug = True

async def save_bug_report(m):
    global wait_bug
    wait_bug = False
    report = f"🐞 БАГ\nОт: {m.chat.id}\nВремя: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n{m.text}"
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, report, parse_mode="HTML")
        except:
            pass
    await bot.send_message(m.chat.id, "✅ Баг отправлен")

async def show_profile(m):
    msgs = get_user_message_count(m.chat.id)
    stats = get_stats()
    text = f"""👤 Профиль

Сообщений: {msgs}
Постов: {stats['posts']}
Роль: {'Бета' if is_beta(m.chat.id) else 'Пользователь'}

Red Race | Подписаться"""
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

# === ОБЩИЕ ФУНКЦИИ ===
async def broadcast_message(m):
    global wait_broadcast
    await bot.send_message(m.chat.id, "📨 Введите текст для рассылки:")
    wait_broadcast = True

async def send_broadcast(msg_text):
    users = get_all_users()
    sent = 0
    for (uid, _) in users:
        try:
            await bot.send_message(uid, f"📢 **Рассылка**\n\n{msg_text}", parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await bot.send_message(ADMIN_IDS[0], f"✅ Отправлено {sent}")

async def post_to_channel_prompt(m):
    global wait_post
    await bot.send_message(m.chat.id, "📤 Отправь текст/фото/видео в канал (30 сек):")
    wait_post = True
    asyncio.create_task(reset_post_timeout())

async def reset_post_timeout():
    global wait_post
    await asyncio.sleep(30)
    if wait_post:
        wait_post = False
        print("⚠️ Таймаут")

async def publish_to_channel(m):
    global wait_post
    if not wait_post:
        return
    wait_post = False
    try:
        if m.text:
            await bot.send_message(CHANNEL_ID, m.text, parse_mode="HTML")
        elif m.photo:
            caption = m.caption if m.caption else None
            await bot.send_photo(CHANNEL_ID, m.photo[-1].file_id, caption=caption, parse_mode="HTML")
        elif m.video:
            caption = m.caption if m.caption else None
            await bot.send_video(CHANNEL_ID, m.video.file_id, caption=caption, parse_mode="HTML")
        await bot.send_message(m.chat.id, "✅ Опубликовано")
    except Exception as e:
        await bot.send_message(m.chat.id, f"❌ Ошибка: {e}")

async def cancel_action(m):
    global wait_post, wait_broadcast, wait_search, wait_topic, test_mode_active, wait_bug
    wait_post = False
    wait_broadcast = False
    wait_search = False
    wait_topic = False
    test_mode_active = False
    wait_bug = False
    await bot.send_message(m.chat.id, "❌ Отменено")

# === ПАНЕЛИ ===
async def admin_panel(m):
    if not is_admin(m.chat.id):
        await bot.send_message(m.chat.id, "⛔ Доступ запрещен")
        return
    uptime = time.time() - start_time
    pending = len(get_pending_posts())
    status = f"""👑 Нико онлайн

Работаю {int(uptime//3600)}ч {int((uptime%3600)//60)}м
Мониторинг: {'✅' if monitoring else '⛔'}
Постов: {posts_cnt}
Диалогов: {dialogs_cnt}
📰 Новостей: {pending}

Red Race | Подписаться"""
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_admin_keyboard())

async def beta_panel(m):
    if not is_beta(m.chat.id):
        await bot.send_message(m.chat.id, "⛔ Доступ запрещен")
        return
    stats = get_stats()
    msgs = get_user_message_count(m.chat.id)
    uptime = time.time() - start_time
    status = f"""🤖 Привет, {get_beta_name(m.chat.id)}

Работаю {int(uptime//3600)}ч
Постов: {stats['posts']}
Твоих сообщений: {msgs}

Red Race | Подписаться"""
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_beta_keyboard())

async def user_panel(m):
    status = """🏎️ Привет! Я Нико, твой гоночный инженер.

Задавай вопросы про Формулу-1.

🎮 Карточная игра: @sipmly_flag_bot

Red Race | Подписаться"""
    await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_user_keyboard())

# === ОСНОВНОЙ ОБРАБОТЧИК ===
async def handle_msg(m):
    global wait_search, wait_topic, wait_broadcast, wait_post, wait_bug, test_mode_active, MY_BOT_ID
    
    if m.text and m.text.startswith('/'):
        return
    
    is_group = m.chat.type in ['group', 'supergroup']
    if is_group:
        if MY_BOT_ID is None:
            me = await bot.get_me()
            MY_BOT_ID = me.id
            global BOT_USERNAME
            BOT_USERNAME = me.username
        msg_text = m.text or ''
        if not (f'@{BOT_USERNAME}' in msg_text or (m.reply_to_message and m.reply_to_message.from_user.id == MY_BOT_ID)):
            return
        if m.text:
            m.text = msg_text.replace(f'@{BOT_USERNAME}', '').strip()
    
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
            await bot.send_message(m.chat.id, "Nico 2.0\nRed Race | Подписаться", parse_mode="HTML")
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
        elif m.text == "🎭 Персонаж":
            await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")
            return
        elif m.text == "📰 Новости":
            await show_pending_posts(m)
            return
        elif m.text == "✅ Опубликовать":
            await publish_all_posts(m)
            return
    
    if is_beta(m.chat.id) and m.text:
        if m.text == "📖 Документация":
            await beta_doc(m)
            return
        elif m.text == "🔐 Консоль":
            await beta_console(m)
            return
        elif m.text == "🔬 Отладка":
            await debug_mode(m)
            return
        elif m.text == "📈 Телеметрия":
            await show_telemetry(m)
            return
        elif m.text == "🎮 Тест":
            await test_mode_cmd(m)
            return
        elif m.text == "🐞 Баг":
            await bug_report(m)
            return
        elif m.text == "👤 Профиль":
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
        elif m.text == "🎭 Персонаж":
            await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")
            return
    
    if m.text == "📅 Календарь":
        await bot.send_message(m.chat.id, await get_calendar(), parse_mode="HTML")
        return
    elif m.text == "ℹ️ О боте":
        await bot.send_message(m.chat.id, "Nico 2.0\nRed Race | Подписаться", parse_mode="HTML")
        return
    elif m.text == "🎭 Персонаж":
        await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")
        return
    elif m.text == "🎮 Карточная игра":
        await bot.send_message(m.chat.id, "🎴 **Карточная игра**\n\nСобирай пилотов и трассы.\n\n🎲 @sipmly_flag_bot\n\nRed Race | Подписаться", parse_mode="HTML")
        return
    
    if wait_search:
        wait_search = False
        await bot.send_message(m.chat.id, "🔍 Ищу...")
        res = await search_f1(m.text)
        await bot.send_message(m.chat.id, f"🌐 Результаты:\n\n{res[:3000]}")
        return
    
    if wait_topic:
        wait_topic = False
        await bot.send_message(m.chat.id, "📝 Генерирую...")
        post = await post_on_topic(m.text)
        await bot.send_message(m.chat.id, post, parse_mode="HTML")
        inc_posts()
        return
    
    status = await bot.send_message(m.chat.id, "🤔 Думаю...")
    ans = await chat_reply(m.chat.id, m.text)
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
            print(f"☀️ Дайджест отправлен")
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
    print(f"🤖 Бот: @{BOT_USERNAME} | ID: {MY_BOT_ID}")
    
    @bot.message_handler(commands=['start', 'admin'])
    async def start_handler(m):
        await start_cmd(m)
    
    @bot.message_handler(commands=['whoami'])
    async def whoami_handler(m):
        await whoami_cmd(m)
    
    @bot.message_handler(commands=['cancel'])
    async def cancel_handler(m):
        await cancel_cmd(m)
    
    @bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video'])
    async def msg_handler(m):
        await handle_msg(m)
    
    asyncio.create_task(monitor(on_post))
    asyncio.create_task(morning_digest_worker())
    
    print("🚀 NICO 2.0 STARTED")
    print(f"👑 Админ: {ADMIN_IDS}")
    print(f"🔧 Бета: {list(BETA_USERS.keys())}")
    
    await bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())
