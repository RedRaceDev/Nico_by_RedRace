import asyncio
import os
import time
import random
from datetime import datetime, timedelta
from telebot.async_telebot import AsyncTeleBot
from telebot.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton,
    InlineQueryResultPhoto
)
from aiohttp import web

from scraper import (
    monitor, post_on_topic, random_post, get_calendar, chat_reply,
    morning_digest, ask_ai, get_pending_posts, clear_pending_posts,
    get_driver_standings, get_last_race_results, get_next_race,
    get_telemetry_comparison, analyze_photo, search_brave_images
)
from database import (
    init_db, save_conversation, get_stats, get_all_users,
    get_last_dialogs, clear_all_history, get_user_message_count,
    save_bug_report, get_bug_reports, update_bug_status
)

# === КОНФИГ ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"
BETA_USERS = {7076945880: "sunrise"}

# === ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ===
bot = None
monitoring = True
posts_cnt = 0
dialogs_cnt = 0
start_time = time.time()
wait_topic = False
wait_broadcast = False
wait_post = False
wait_bug = False
waiting_photo = False
MY_BOT_ID = None
BOT_USERNAME = "RedNico_bot"

# === ПРОВЕРКА ТОКЕНА ===
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в переменных окружения!")

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
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
    "Кими": "Создатель канала. Муж Псиникса.",
    "Пиастри": "Уебище из-за которого Псиникс проебал 10кк.",
    "СанРайз": "Жирное уебище, психопат.",
    "Акира": "Котакбас. Главное хуйло чата."
}

def get_random_character():
    name, desc = random.choice(list(REDRACE_CHARACTERS.items()))
    return f"🎭 <b>Ты — {name}</b>\n\n{desc}\n\n#RedRace"

# === КЛАВИАТУРЫ ===
def get_admin_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton("📝 Пост на тему"), KeyboardButton("🎲 Рандом"),
        KeyboardButton("📊 Статистика"), KeyboardButton("📜 История"),
        KeyboardButton("👥 Пользователи"), KeyboardButton("📨 Рассылка"),
        KeyboardButton("📤 Пост в канал"), KeyboardButton("🎭 Персонаж"),
        KeyboardButton("🛑 Стоп"), KeyboardButton("▶️ Старт"),
        KeyboardButton("📰 Новости"), KeyboardButton("✅ Опубликовать"),
        KeyboardButton("🧠 Очистить"), KeyboardButton("🔬 Анализ фото"),
        KeyboardButton("📅 Календарь"), KeyboardButton("🏆 Чемпионат"),
        KeyboardButton("🏁 Последняя гонка"), KeyboardButton("⏩ Следующая гонка")
    )
    return markup

def get_beta_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton("📝 Пост на тему"), KeyboardButton("🎲 Рандом"),
        KeyboardButton("📊 Статистика"), KeyboardButton("🎭 Персонаж"),
        KeyboardButton("🐞 Баг"), KeyboardButton("👤 Профиль"),
        KeyboardButton("🔬 Отладка"), KeyboardButton("📈 Телеметрия"),
        KeyboardButton("📅 Календарь"), KeyboardButton("🏆 Чемпионат"),
        KeyboardButton("🏁 Последняя гонка")
    )
    return markup

def get_user_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton("📅 Календарь"),
        KeyboardButton("🏆 Чемпионат"),
        KeyboardButton("🏁 Последняя гонка"),
        KeyboardButton("🎭 Персонаж"),
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

# === F1 КОМАНДЫ ===
async def send_standings(chat_id):
    standings = await get_driver_standings(2026)
    if not standings:
        await bot.send_message(chat_id, "❌ Не удалось получить данные")
        return
    text = "🏆 **Чемпионат F1 2026 (пилоты)**\n\n"
    for s in standings[:10]:
        text += f"{s['pos']}. **{s['driver']}** — {s['points']} очков ({s['team']})\n"
    await bot.send_message(chat_id, text, parse_mode="HTML")

async def send_last_race(chat_id):
    race = await get_last_race_results(2026)
    if not race:
        await bot.send_message(chat_id, "❌ Не удалось получить данные")
        return
    text = f"🏁 **{race['name']}**\n\nРезультаты:\n"
    for r in race['results'][:10]:
        text += f"{r['pos']}. {r['driver']} — {r['points']} очков\n"
    await bot.send_message(chat_id, text, parse_mode="HTML")

async def send_next_race(chat_id):
    race = await get_next_race(2026)
    if not race:
        await bot.send_message(chat_id, "❌ Не удалось получить данные")
        return
    text = f"⏩ **Следующая гонка**\n\n"
    text += f"🏎️ {race['name']}\n"
    text += f"📅 {race['date']}\n"
    text += f"🏁 {race['circuit']}\n"
    await bot.send_message(chat_id, text, parse_mode="HTML")

# === ОБРАБОТЧИКИ ===
async def handle_photo(m):
    global waiting_photo
    if not waiting_photo:
        return
    waiting_photo = False
    file_id = m.photo[-1].file_id
    file_info = await bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
    status = await bot.reply_to(m, "🔍 Анализирую...")
    analysis = await analyze_photo(file_url)
    await bot.edit_message_text(analysis, chat_id=m.chat.id, message_id=status.message_id, parse_mode="HTML")

async def handle_bug_report(m):
    global wait_bug
    if not wait_bug:
        return
    wait_bug = False
    save_bug_report(m.chat.id, m.text)
    await bot.reply_to(m, "✅ Баг отправлен админу")
    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, f"🐞 Баг от {m.chat.id}:\n{m.text}")

async def handle_broadcast(m):
    global wait_broadcast
    if not wait_broadcast:
        return
    wait_broadcast = False
    users = get_all_users()
    sent = 0
    for uid, _, _, _, _ in users:
        try:
            await bot.send_message(int(uid), f"📢 {m.text}", parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await bot.send_message(m.chat.id, f"✅ Отправлено {sent}")

async def handle_post_to_channel(m):
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
        await bot.send_message(m.chat.id, "✅ Опубликовано")
    except Exception as e:
        await bot.send_message(m.chat.id, f"❌ Ошибка: {e}")

async def reset_post_timeout():
    global wait_post
    await asyncio.sleep(30)
    wait_post = False

async def process_chat(m):
    status = await bot.send_message(m.chat.id, "🤔 Думаю...")
    answer = await chat_reply(m.chat.id, m.text)
    await bot.delete_message(m.chat.id, status.message_id)
    await bot.send_message(m.chat.id, answer, parse_mode="HTML")
    inc_dialogs()
    save_conversation(str(m.chat.id), m.text, answer, username=m.from_user.username, first_name=m.from_user.first_name)

# === ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ ===
async def handle_msg(m):
    global wait_topic, wait_broadcast, wait_post, wait_bug, waiting_photo
    
    # Guest mode
    if hasattr(m, 'guest_query_id') and m.guest_query_id:
        await bot.send_chat_action(m.chat.id, 'typing')
        answer = await chat_reply(m.chat.id, m.text)
        await bot.answer_guest_query(m.guest_query_id, text=answer, parse_mode="HTML")
        return
    
    # Команды
    if m.text and m.text.startswith('/'):
        if m.text == '/start':
            await start_cmd(m)
        elif m.text == '/whoami':
            await whoami_cmd(m)
        elif m.text == '/cancel':
            await cancel_cmd(m)
        return
    
    # Ожидания
    if wait_bug:
        await handle_bug_report(m)
        return
    if wait_broadcast:
        await handle_broadcast(m)
        return
    if wait_post:
        await handle_post_to_channel(m)
        return
    if waiting_photo:
        await handle_photo(m)
        return
    
    # Кнопки админа
    if is_admin(m.chat.id) and m.text:
        if m.text == "📝 Пост на тему":
            wait_topic = True
            await bot.send_message(m.chat.id, "📝 Тема:")
        elif m.text == "🎲 Рандом":
            post = await random_post()
            await bot.send_message(m.chat.id, post, parse_mode="HTML")
            inc_posts()
        elif m.text == "📊 Статистика":
            stats = get_stats()
            uptime = time.time() - start_time
            text = f"📊 **Статистика**\n\n📝 Постов: {stats['posts']}\n💬 Диалогов: {stats['dialogs']}\n👥 Пользователей: {stats['users']}\n🐞 Багов: {stats['bugs']}\n⏱ Аптайм: {int(uptime//3600)}ч\n📡 Мониторинг: {'✅' if monitoring else '⛔'}"
            await bot.send_message(m.chat.id, text, parse_mode="HTML")
        elif m.text == "📜 История":
            rows = get_last_dialogs(20)
            if not rows:
                await bot.send_message(m.chat.id, "📭 Пусто")
            else:
                text = "📜 **Последние диалоги**\n\n"
                for uid, msg, resp, ts in rows:
                    text += f"👤 {uid} | {ts[:16]}\n❓ {msg[:80]}\n✅ {resp[:80]}\n\n---\n"
                    if len(text) > 3500:
                        await bot.send_message(m.chat.id, text, parse_mode="HTML")
                        text = ""
                if text:
                    await bot.send_message(m.chat.id, text, parse_mode="HTML")
        elif m.text == "👥 Пользователи":
            users = get_all_users(50)
            if not users:
                await bot.send_message(m.chat.id, "📭 Нет пользователей")
            else:
                text = "👥 **Пользователи**\n\n"
                for uid, username, first_name, msgs, _ in users:
                    name = first_name or username or uid
                    text += f"• {name} — {msgs} сообщений\n"
                await bot.send_message(m.chat.id, text, parse_mode="HTML")
        elif m.text == "📨 Рассылка":
            wait_broadcast = True
            await bot.send_message(m.chat.id, "📨 Введите текст рассылки:")
        elif m.text == "📤 Пост в канал":
            wait_post = True
            await bot.send_message(m.chat.id, "📤 Отправьте контент в канал (30 сек):")
            asyncio.create_task(reset_post_timeout())
        elif m.text == "🎭 Персонаж":
            await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")
        elif m.text == "🛑 Стоп":
            monitoring = False
            await bot.send_message(m.chat.id, "⛔ Мониторинг остановлен")
        elif m.text == "▶️ Старт":
            monitoring = True
            await bot.send_message(m.chat.id, "✅ Мониторинг запущен")
        elif m.text == "📰 Новости":
            posts = get_pending_posts()
            if not posts:
                await bot.send_message(m.chat.id, "📭 Новостей нет")
            else:
                text = f"📰 **Готово к публикации ({len(posts)})**\n\n"
                for i, p in enumerate(posts[:10], 1):
                    text += f"{i}. {p['title'][:70]}\n"
                await bot.send_message(m.chat.id, text, parse_mode="HTML")
        elif m.text == "✅ Опубликовать":
            posts = get_pending_posts()
            if not posts:
                await bot.send_message(m.chat.id, "📭 Нет новостей")
            else:
                await bot.send_message(m.chat.id, f"📤 Публикую {len(posts)} постов...")
                for p in posts:
                    await bot.send_message(CHANNEL_ID, p['post'], parse_mode="HTML")
                    inc_posts()
                    await asyncio.sleep(2)
                clear_pending_posts()
                await bot.send_message(m.chat.id, f"✅ Опубликовано {len(posts)}")
        elif m.text == "🧠 Очистить":
            clear_all_history()
            await bot.send_message(m.chat.id, "🧠 История диалогов очищена")
        elif m.text == "🔬 Анализ фото":
            waiting_photo = True
            await bot.send_message(m.chat.id, "📸 Отправь фото болида или трассы")
        elif m.text == "📅 Календарь":
            await bot.send_message(m.chat.id, await get_calendar(), parse_mode="HTML")
        elif m.text == "🏆 Чемпионат":
            await send_standings(m.chat.id)
        elif m.text == "🏁 Последняя гонка":
            await send_last_race(m.chat.id)
        elif m.text == "⏩ Следующая гонка":
            await send_next_race(m.chat.id)
        else:
            # Обычный чат для админа (если не нажал кнопку)
            await process_chat(m)
        return
    
    # Кнопки бета-тестера
    if is_beta(m.chat.id) and m.text:
        if m.text == "🐞 Баг":
            wait_bug = True
            await bot.send_message(m.chat.id, "🐞 Опиши баг:")
        elif m.text == "👤 Профиль":
            msgs = get_user_message_count(m.chat.id)
            await bot.send_message(m.chat.id, f"👤 **Профиль**\n\nСообщений: {msgs}\nРоль: Бета-тестер", parse_mode="HTML")
        elif m.text == "🔬 Отладка":
            uptime = time.time() - start_time
            text = f"🔬 **Отладка**\n\nБот ID: {MY_BOT_ID}\nМониторинг: {'✅' if monitoring else '❌'}\nАптайм: {int(uptime//3600)}ч\nПостов: {posts_cnt}\nДиалогов: {dialogs_cnt}"
            await bot.send_message(m.chat.id, text, parse_mode="HTML")
        elif m.text == "📈 Телеметрия":
            stats = get_stats()
            text = f"📈 **Телеметрия**\n\nПостов: {stats['posts']}\nДиалогов: {stats['dialogs']}\nПользователей: {stats['users']}\nБагов: {stats['bugs']}"
            await bot.send_message(m.chat.id, text, parse_mode="HTML")
        elif m.text == "📝 Пост на тему":
            wait_topic = True
            await bot.send_message(m.chat.id, "📝 Тема:")
        elif m.text == "🎲 Рандом":
            post = await random_post()
            await bot.send_message(m.chat.id, post, parse_mode="HTML")
            inc_posts()
        elif m.text == "📊 Статистика":
            stats = get_stats()
            text = f"📊 Постов: {stats['posts']}\n💬 Диалогов: {stats['dialogs']}\n👥 Пользователей: {stats['users']}"
            await bot.send_message(m.chat.id, text, parse_mode="HTML")
        elif m.text == "📅 Календарь":
            await bot.send_message(m.chat.id, await get_calendar(), parse_mode="HTML")
        elif m.text == "🏆 Чемпионат":
            await send_standings(m.chat.id)
        elif m.text == "🏁 Последняя гонка":
            await send_last_race(m.chat.id)
        elif m.text == "🎭 Персонаж":
            await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")
        else:
            await process_chat(m)
        return
    
    # Кнопки обычного пользователя
    if m.text and m.text in ["📅 Календарь", "🏆 Чемпионат", "🏁 Последняя гонка", "🎭 Персонаж", "🔬 Анализ фото"]:
        if m.text == "📅 Календарь":
            await bot.send_message(m.chat.id, await get_calendar(), parse_mode="HTML")
        elif m.text == "🏆 Чемпионат":
            await send_standings(m.chat.id)
        elif m.text == "🏁 Последняя гонка":
            await send_last_race(m.chat.id)
        elif m.text == "🎭 Персонаж":
            await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")
        elif m.text == "🔬 Анализ фото":
            waiting_photo = True
            await bot.send_message(m.chat.id, "📸 Отправь фото болида или трассы")
        return
    
    # Пост на тему (ожидание)
    if wait_topic:
        wait_topic = False
        await bot.send_message(m.chat.id, "📝 Генерирую...")
        post = await post_on_topic(m.text)
        await bot.send_message(m.chat.id, post, parse_mode="HTML")
        inc_posts()
        return
    
    # Обычный чат
    await process_chat(m)

# === INLINE MODE ===
@bot.inline_handler(func=lambda query: True)
async def inline_search(inline_query):
    query_text = inline_query.query.strip()
    
    if not query_text:
        await bot.answer_inline_query(
            inline_query.id, [],
            switch_pm_text="🔍 Напиши что найти (пилота, команду или фото)",
            switch_pm_parameter="start"
        )
        return
    
    # Поиск пилотов в данных F1
    standings = await get_driver_standings(2026)
    results = []
    
    if standings:
        for s in standings:
            if query_text.lower() in s['driver'].lower():
                results.append(
                    InlineQueryResultPhoto(
                        id=f"driver_{s['pos']}",
                        photo_url="https://cdn-8.motorsport.com/images/mgl/6Qv0KXj0/s1000/ferrari-sf-25-1-.jpg",
                        thumbnail_url="https://cdn-8.motorsport.com/images/mgl/6Qv0KXj0/s100/ferrari-sf-25-1-.jpg",
                        title=s['driver'],
                        description=f"{s['points']} очков, {s['team']}",
                        caption=f"🏎️ {s['driver']} — {s['points']} очков\n{s['team']}\n#F1"
                    )
                )
    
    # Если не нашли — поиск картинок через Brave
    if not results:
        images = await search_brave_images(query_text, max_results=10)
        for img in images:
            results.append(
                InlineQueryResultPhoto(
                    id=img['id'],
                    photo_url=img['url'],
                    thumbnail_url=img['thumbnail'],
                    title=img['title'][:60],
                    caption=f"🖼️ {img['title'][:100]}\n🔗 {img['source']}\n#Search"
                )
            )
    
    if results:
        await bot.answer_inline_query(inline_query.id, results[:20], cache_time=300, is_personal=True)
    else:
        await bot.answer_inline_query(inline_query.id, [], cache_time=60)

# === СТАРТОВЫЕ ПАНЕЛИ ===
async def start_cmd(m):
    if is_admin(m.chat.id):
        uptime = time.time() - start_time
        pending = len(get_pending_posts())
        status = f"👑 **Нико онлайн**\n\n⏱ Аптайм: {int(uptime//3600)}ч\n📡 Мониторинг: {'✅' if monitoring else '⛔'}\n📝 Постов: {posts_cnt}\n💬 Диалогов: {dialogs_cnt}\n📰 Новостей: {pending}"
        await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_admin_keyboard())
    elif is_beta(m.chat.id):
        stats = get_stats()
        msgs = get_user_message_count(m.chat.id)
        status = f"🤖 Привет, {get_beta_name(m.chat.id)}\n\n📝 Постов: {stats['posts']}\n💬 Диалогов: {stats['dialogs']}\n📊 Твоих сообщений: {msgs}"
        await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_beta_keyboard())
    else:
        status = """🏎️ **Я Нико 3.0 — твой гоночный инженер.**

• Отвечаю на вопросы про F1
• Анализирую фото болидов
• Знаю таблицу чемпионата
• Показываю результаты гонок
• Помню историю диалогов

🎮 **Карточная игра:** @sipmly_flag_bot

Просто напиши вопрос или нажми на кнопку."""
        await bot.send_message(m.chat.id, status, parse_mode="HTML", reply_markup=get_user_keyboard())

async def whoami_cmd(m):
    await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")

async def cancel_cmd(m):
    global wait_topic, wait_broadcast, wait_post, wait_bug, waiting_photo
    wait_topic = wait_broadcast = wait_post = wait_bug = waiting_photo = False
    await bot.send_message(m.chat.id, "❌ Действие отменено")

# === УТРЕННИЙ ДАЙДЖЕСТ ===
async def morning_digest_worker():
    while True:
        now = datetime.now()
        target = now.replace(hour=4, minute=0, second=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            digest = await morning_digest()
            await bot.send_message(CHANNEL_ID, digest, parse_mode="HTML")
            print("☀️ Дайджест отправлен")
        except Exception as e:
            print(f"Digest error: {e}")

# === ОСНОВНОЙ ЗАПУСК ===
async def main():
    global bot, MY_BOT_ID
    
    # Инициализация
    init_db()
    await start_health_server()
    
    # Создание бота
    bot = AsyncTeleBot(BOT_TOKEN)
    
    # Получение информации о боте
    me = await bot.get_me()
    MY_BOT_ID = me.id
    global BOT_USERNAME
    BOT_USERNAME = me.username
    print(f"🤖 Бот: @{BOT_USERNAME} | ID: {MY_BOT_ID}")
    
    # Регистрация обработчиков
    @bot.message_handler(commands=['start', 'admin'])
    async def start_handler(m): await start_cmd(m)
    
    @bot.message_handler(commands=['whoami'])
    async def whoami_handler(m): await whoami_cmd(m)
    
    @bot.message_handler(commands=['cancel'])
    async def cancel_handler(m): await cancel_cmd(m)
    
    @bot.message_handler(func=lambda m: True, content_types=['text', 'photo'])
    async def msg_handler(m): await handle_msg(m)
    
    # Инлайн режим
    @bot.inline_handler(func=lambda query: True)
    async def inline_handler(inline_query): await inline_search(inline_query)
    
    # Запуск фоновых задач
    asyncio.create_task(monitor())
    asyncio.create_task(morning_digest_worker())
    
    print("🚀 NICO 3.0 ЗАПУЩЕН")
    print(f"👑 Админ: {ADMIN_IDS}")
    print(f"🔧 Бета-тестеры: {list(BETA_USERS.keys())}")
    print(f"📡 Мониторинг RSS: {'включен' if monitoring else 'выключен'}")
    
    await bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())
