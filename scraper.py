import asyncio
import os
import time
import random
import sqlite3
import aiohttp
import feedparser
import hashlib
import json
import re
from datetime import datetime, timedelta
from telebot.async_telebot import AsyncTeleBot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# === КОНФИГ ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"
BETA_USERS = {7076945880: "sunrise"}

# === СОСТОЯНИЯ ===
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

# === БАЗА ДАННЫХ ===
DB_PATH = "nico_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT,
                  message TEXT,
                  response TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS posts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  text TEXT,
                  photo_url TEXT,
                  published_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_stats
                 (user_id TEXT PRIMARY KEY,
                  first_seen DATETIME,
                  last_seen DATETIME,
                  messages_count INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

def save_conversation(user_id, message, response):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO chat_history (user_id, message, response) VALUES (?, ?, ?)",
              (str(user_id), message, response))
    c.execute('''INSERT INTO user_stats (user_id, first_seen, last_seen, messages_count)
                 VALUES (?, ?, ?, 1)
                 ON CONFLICT(user_id) DO UPDATE SET
                 last_seen = ?,
                 messages_count = messages_count + 1''',
              (str(user_id), datetime.now(), datetime.now(), datetime.now()))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    posts = c.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    dialogs = c.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0]
    users = c.execute("SELECT COUNT(*) FROM user_stats").fetchone()[0]
    conn.close()
    return {"posts": posts, "dialogs": dialogs, "users": users}

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, messages_count FROM user_stats ORDER BY messages_count DESC")
    return c.fetchall()

def get_user_message_count(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT messages_count FROM user_stats WHERE user_id = ?", (str(user_id),))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def get_last_dialogs(limit=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT user_id, message, response, timestamp FROM chat_history
                 ORDER BY timestamp DESC LIMIT ?''', (limit,))
    return c.fetchall()

def clear_all_history():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM chat_history")
    c.execute("DELETE FROM user_stats")
    conn.commit()
    conn.close()

init_db()

# === ПАМЯТЬ ===
MEMORY_FILE = "memory.json"

def save_memory(user_id, message, response):
    try:
        with open(MEMORY_FILE, 'r') as f:
            memory = json.load(f)
    except:
        memory = {}
    if str(user_id) not in memory:
        memory[str(user_id)] = []
    memory[str(user_id)].append({"message": message, "response": response, "timestamp": datetime.now().isoformat()})
    if len(memory[str(user_id)]) > 50:
        memory[str(user_id)] = memory[str(user_id)][-50:]
    with open(MEMORY_FILE, 'w') as f:
        json.dump(memory, f, indent=2)

def get_memory(user_id, limit=10):
    try:
        with open(MEMORY_FILE, 'r') as f:
            memory = json.load(f)
        return memory.get(str(user_id), [])[-limit:]
    except:
        return []

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

# === ФУНКЦИИ ===
def inc_posts(): global posts_cnt; posts_cnt += 1
def inc_dialogs(): global dialogs_cnt; dialogs_cnt += 1
def is_admin(user_id): return user_id in ADMIN_IDS
def is_beta(user_id): return user_id in BETA_USERS
def get_beta_name(user_id): return BETA_USERS.get(user_id, "Бета-тестер")

def clean_post(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'\*', '', text)
    text = re.sub(r'_{2,}', '', text)
    text = re.sub(r'_', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    if len(text) > 1800:
        text = text[:text.rfind('.', 0, 1800)+1]
    return text.strip()

# === RSS ===
RSS_SOURCES = [
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.the-race.com/feed/",
    "https://www.planetf1.com/feed",
    "https://www.crash.net/f1/rss",
    "https://www.f1news.ru/export/news.xml"
]

HASH_FILE = "posted_hashes.json"

def load_hashes():
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_hash(h):
    hashes = load_hashes()
    hashes.add(h)
    with open(HASH_FILE, 'w') as f:
        json.dump(list(hashes), f)

def is_posted(title, link):
    h = hashlib.md5(f"{title}{link}".encode()).hexdigest()
    return h in load_hashes()

def mark_posted(title, link):
    h = hashlib.md5(f"{title}{link}".encode()).hexdigest()
    save_hash(h)

def is_fresh_news(entry) -> bool:
    published = entry.get('published_parsed')
    if not published:
        return True
    pub_date = datetime(*published[:6])
    return (datetime.now() - pub_date).days <= 7

# === КЛАВИАТУРЫ ===
def get_admin_keyboard():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        KeyboardButton("📝 Пост на тему"), KeyboardButton("🎲 Рандом"),
        KeyboardButton("🔍 Поиск"), KeyboardButton("📅 Календарь"),
        KeyboardButton("📊 Статистика"), KeyboardButton("📜 История"),
        KeyboardButton("👥 Пользователи"), KeyboardButton("📨 Рассылка"),
        KeyboardButton("📤 Пост в канал"), KeyboardButton("🎭 Персонаж"),
        KeyboardButton("🛑 Стоп"), KeyboardButton("▶️ Старт"),
        KeyboardButton("📰 Новости"), KeyboardButton("✅ Опубликовать"),
        KeyboardButton("🧠 Очистить"), KeyboardButton("ℹ️ О системе")
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
        KeyboardButton("🎭 Персонаж"),
        KeyboardButton("🎮 Карточная игра")
    )
    return markup

# === ИИ ФУНКЦИИ ===
async def ask_gemini_simple(prompt: str) -> str:
    """Простой вызов Gemini через API"""
    import google.generativeai as genai
    GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
    if not GEMINI_KEY:
        return await ask_fallback_simple(prompt)
    try:
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel('gemini-3.5-flash')
        response = await asyncio.get_event_loop().run_in_executor(None, lambda: model.generate_content(prompt))
        if response and response.text:
            return response.text
        return await ask_fallback_simple(prompt)
    except Exception as e:
        print(f"Gemini error: {e}")
        return await ask_fallback_simple(prompt)

async def ask_fallback_simple(prompt: str) -> str:
    """Резервный вызов через OpenRouter"""
    import openai
    OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
    if not OPENROUTER_KEY:
        return "❌ ИИ недоступен"
    client = openai.AsyncOpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")
    try:
        resp = await client.chat.completions.create(
            model="openrouter/free",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.4
        )
        if resp and resp.choices:
            return resp.choices[0].message.content
        return "❌ Пустой ответ"
    except Exception as e:
        return f"❌ Ошибка: {e}"

async def chat_reply_simple(user_id: int, msg: str) -> str:
    memory = get_memory(user_id, 10)
    context = ""
    for m in memory[-5:]:
        context += f"Пользователь: {m['message']}\nНико: {m['response']}\n"
    prompt = f"""Ты Нико, эксперт по Формуле-1.
История:
{context}
Пользователь: {msg}
Ответь кратко, по делу, в 2026 году."""
    answer = await ask_gemini_simple(prompt)
    save_memory(user_id, msg, answer)
    return answer

async def gen_post_simple(title: str, content: str) -> str:
    prompt = f"""Ты Нико. Напиши пост о Формуле-1.

НОВОСТЬ: {title}
ДЕТАЛИ: {content[:1000]}

ПРАВИЛА:
- Заголовок: <b>жирный</b>
- 3-5 абзацев
- Только факты
- В конце: #F1

ПОСТ:"""
    post = await ask_gemini_simple(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

async def random_post_simple() -> str:
    prompt = "Ты Нико. Напиши пост о Формуле-1. Заголовок жирным. 5-7 предложений."
    return clean_post(await ask_gemini_simple(prompt)) + "\n\nRed Race | Подписаться"

async def post_on_topic_simple(topic: str) -> str:
    prompt = f"Ты Нико. Напиши пост о Формуле-1 на тему: {topic}. Заголовок жирным. 4-6 предложений."
    return clean_post(await ask_gemini_simple(prompt)) + "\n\nRed Race | Подписаться"

async def search_f1_simple(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = ddgs.text(f"{query} formula 1", max_results=3)
            context = "🔍 **Результаты поиска:**\n\n"
            for r in results:
                context += f"📌 **{r.get('title', '')}**\n📄 {r.get('body', '')[:500]}\n🔗 {r.get('href', '')}\n\n"
            return context if context else "Ничего не найдено"
    except Exception as e:
        return f"Ошибка поиска: {e}"

async def get_calendar_simple() -> str:
    return """📅 **Календарь F1 2026**

Май: 03 Майами, 24 Канада
Июнь: 07 Монако, 14 Барселона, 28 Австрия
Июль: 05 Великобритания, 19 Бельгия, 26 Венгрия
Август: 23 Нидерланды
Сентябрь: 06 Италия, 13 Испания, 26 Азербайджан
Октябрь: 11 Сингапур, 25 США
Ноябрь: 01 Мексика, 08 Бразилия, 21 Лас-Вегас, 29 Катар
Декабрь: 06 Абу-Даби

#F1 #Calendar2026"""

async def morning_digest_simple() -> str:
    news = []
    for src in RSS_SOURCES[:3]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(src, timeout=15) as resp:
                    if resp.status == 200:
                        feed = feedparser.parse(await resp.text())
                        for entry in feed.entries[:1]:
                            news.append(entry.get('title', ''))
        except:
            continue
    news_text = ""
    for i, title in enumerate(news[:5], 1):
        news_text += f"{i}. {title}\n"
    return f"""☀️ Доброе утро, RedRace!

📅 {datetime.now().strftime('%d.%m.%Y')}

🏆 Топ новостей дня:
{news_text}
📅 Ближайшие гонки:
• 7 июня — Монако
• 14 июня — Барселона

Red Race | Подписаться"""

# === МОНИТОРИНГ ===
pending_posts = []

async def monitor_simple(callback):
    global pending_posts
    last = {}
    while True:
        for src in RSS_SOURCES:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(src, timeout=15) as resp:
                        if resp.status == 200:
                            feed = feedparser.parse(await resp.text())
                            if feed.entries:
                                entry = feed.entries[0]
                                link = entry.get('link', '')
                                key = f"{src}_{link}"
                                if key == last.get(src):
                                    continue
                                last[src] = key
                                if is_posted(entry.get('title', ''), link):
                                    continue
                                post = await gen_post_simple(entry.get('title', ''), entry.get('summary', '')[:500])
                                pending_posts.append({"post": post, "title": entry.get('title', ''), "link": link})
                                print(f"📰 Новая новость: {entry.get('title', '')[:50]}...")
            except:
                continue
        await asyncio.sleep(60)

def get_pending():
    return pending_posts

def clear_pending():
    global pending_posts
    pending_posts = []

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

# === ОБРАБОТЧИКИ ===
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
📡 Мониторинг: {'✅' if monitoring else '⛔'}
⏱ Аптайм: {int(uptime//3600)}ч

Red Race | Подписаться"""
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def clear_history(m):
    clear_all_history()
    await bot.send_message(m.chat.id, "🧠 История очищена")

async def show_pending(m):
    posts = get_pending()
    if not posts:
        await bot.send_message(m.chat.id, "📭 Новостей нет")
        return
    text = f"📰 Готово ({len(posts)}):\n\n"
    for i, p in enumerate(posts, 1):
        text += f"{i}. {p['title'][:70]}\n"
    await bot.send_message(m.chat.id, text, parse_mode="HTML")

async def publish_all(m):
    posts = get_pending()
    if not posts:
        await bot.send_message(m.chat.id, "📭 Нет новостей")
        return
    await bot.send_message(m.chat.id, f"📤 Публикую {len(posts)} постов...")
    for p in posts:
        await on_post(p['post'], p['title'], p['link'])
        await asyncio.sleep(3)
    clear_pending()
    await bot.send_message(m.chat.id, f"✅ Опубликовано {len(posts)} постов")

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
    raw = await ask_gemini_simple(m.text)
    await bot.delete_message(m.chat.id, status.message_id)
    await bot.send_message(m.chat.id, f"**Сырой ответ:**\n\n{raw[:2000]}")

async def bug_report(m):
    global wait_bug
    await bot.send_message(m.chat.id, "🐞 Опиши баг:")
    wait_bug = True

async def save_bug_report(m):
    global wait_bug
    wait_bug = False
    report = f"🐞 НОВЫЙ БАГ\nОт: {m.chat.id}\nВремя: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n{m.text}"
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

# === ПАНЕЛИ ===
async def admin_panel(m):
    if not is_admin(m.chat.id):
        await bot.send_message(m.chat.id, "⛔ Доступ запрещен")
        return
    uptime = time.time() - start_time
    pending = len(get_pending())
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
async def handle_ask(m):
    query = m.text.replace('/ask', '').strip()
    if not query:
        await bot.reply_to(m, "❓ Напиши вопрос после команды /ask")
        return
    status_msg = await bot.reply_to(m, "🔍 Ищу...")
    res = await search_f1_simple(query)
    await bot.edit_message_text(res, chat_id=m.chat.id, message_id=status_msg.message_id, parse_mode="HTML")

async def handle_msg(m):
    global wait_search, wait_topic, wait_broadcast, wait_post, wait_bug, test_mode_active, MY_BOT_ID
    
    if m.text and m.text.startswith('/'):
        return
    
    if m.text and m.text.startswith('/ask'):
        await handle_ask(m)
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
            await bot.send_message(m.chat.id, "Nico 3.0\nRed Race | Подписаться", parse_mode="HTML")
            return
        elif m.text == "📝 Пост на тему":
            wait_topic = True
            await bot.send_message(m.chat.id, "📝 Тема:")
            return
        elif m.text == "🎲 Рандом":
            post = await random_post_simple()
            await bot.send_message(m.chat.id, post, parse_mode="HTML")
            inc_posts()
            return
        elif m.text == "🔍 Поиск":
            wait_search = True
            await bot.send_message(m.chat.id, "🔍 Запрос:")
            return
        elif m.text == "📅 Календарь":
            await bot.send_message(m.chat.id, await get_calendar_simple(), parse_mode="HTML")
            return
        elif m.text == "🎭 Персонаж":
            await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")
            return
        elif m.text == "📰 Новости":
            await show_pending(m)
            return
        elif m.text == "✅ Опубликовать":
            await publish_all(m)
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
            post = await random_post_simple()
            await bot.send_message(m.chat.id, post, parse_mode="HTML")
            inc_posts()
            return
        elif m.text == "🔍 Поиск":
            wait_search = True
            await bot.send_message(m.chat.id, "🔍 Запрос:")
            return        elif m.text == "📅 Календарь":
            await bot.send_message(m.chat.id, await get_calendar_simple(), parse_mode="HTML")
            return
        elif m.text == "📊 Статистика":
            await extended_stats(m)
            return
        elif m.text == "🎭 Персонаж":
            await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")
            return
    
    if m.text == "📅 Календарь":
        await bot.send_message(m.chat.id, await get_calendar_simple(), parse_mode="HTML")
        return
    elif m.text == "ℹ️ О боте":
        await bot.send_message(m.chat.id, "Nico 3.0\nRed Race | Подписаться", parse_mode="HTML")
        return
    elif m.text == "🎭 Персонаж":
        await bot.send_message(m.chat.id, get_random_character(), parse_mode="HTML")
        return
    elif m.text == "🎮 Карточная игра":
        await bot.send_message(m.chat.id, "🎴 **Карточная игра**\n\n🎲 @sipmly_flag_bot\n\nRed Race | Подписаться", parse_mode="HTML")
        return
    
    if wait_search:
        wait_search = False
        await bot.send_message(m.chat.id, "🔍 Ищу...")
        res = await search_f1_simple(m.text)
        await bot.send_message(m.chat.id, res, parse_mode="HTML")
        return
    
    if wait_topic:
        wait_topic = False
        await bot.send_message(m.chat.id, "📝 Генерирую...")
        post = await post_on_topic_simple(m.text)
        await bot.send_message(m.chat.id, post, parse_mode="HTML")
        inc_posts()
        return
    
    status = await bot.send_message(m.chat.id, "🤔 Думаю...")
    ans = await chat_reply_simple(m.chat.id, m.text)
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
            digest = await morning_digest_simple()
            await bot.send_message(CHANNEL_ID, digest, parse_mode="HTML")
            print(f"☀️ Дайджест отправлен")
        except Exception as e:
            print(f"Digest error: {e}")

async def main():
    global bot, MY_BOT_ID
    
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
    
    asyncio.create_task(monitor_simple(on_post))
    asyncio.create_task(morning_digest_worker())
    
    print("🚀 NICO 3.0 STARTED")
    print(f"👑 Админ: {ADMIN_IDS}")
    print(f"🔧 Бета: {list(BETA_USERS.keys())}")
    
    await bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())
