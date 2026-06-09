# scraper.py
import asyncio
import os
import json
import re
import hashlib
import random
import aiohttp
import feedparser
from datetime import datetime
from cachetools import TTLCache
import openai

# === OPENROUTER ===
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")

OPENROUTER_MODELS = [
    "nex-agi/nex-n2-pro:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter/free"
]

# === TINYFISH API ===
TINYFISH_KEY = os.environ.get("TINYFISH_API_KEY")
TINYFISH_SEARCH_URL = "https://api.tinyfish.ai/v1/search"

# === КОНФИГ ===
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"
MEMORY_FILE = "memory.json"
HASH_FILE = "posted_hashes.json"

RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
]

# === КЕШ ===
standings_cache = TTLCache(maxsize=1, ttl=3600)

# === FALLBACK ===
FALLBACK_STANDINGS = [
    {"pos": 1, "driver": "Kimi Antonelli", "points": 156, "team": "Mercedes"},
    {"pos": 2, "driver": "George Russell", "points": 88, "team": "Mercedes"},
    {"pos": 3, "driver": "Charles Leclerc", "points": 75, "team": "Ferrari"},
    {"pos": 4, "driver": "Lewis Hamilton", "points": 72, "team": "Ferrari"},
    {"pos": 5, "driver": "Lando Norris", "points": 58, "team": "McLaren"}
]

# === AI ===
async def ask_ai(prompt: str) -> str:
    if not OPENROUTER_KEY:
        return "❌ Ключ OpenRouter не найден"
    
    client = openai.AsyncOpenAI(
        api_key=OPENROUTER_KEY,
        base_url="https://openrouter.ai/api/v1"
    )
    
    for model in OPENROUTER_MODELS:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.3,
                timeout=25
            )
            if response and response.choices:
                return response.choices[0].message.content
        except Exception as e:
            print(f"AI error: {e}")
            continue
    
    return "❌ AI временно недоступен"

# === TINYFISH ФУНКЦИИ ===
async def tinyfish_search(query: str, limit: int = 6) -> str:
    """Поиск через TinyFish Search API"""
    if not TINYFISH_KEY:
        return None
    
    headers = {"Authorization": f"Bearer {TINYFISH_KEY}"}
    params = {"q": query, "limit": limit}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(TINYFISH_SEARCH_URL, headers=headers, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])
                    
                    if not results:
                        return None
                    
                    text = f"🔍 **Результаты поиска: {query}**\n\n"
                    for i, r in enumerate(results[:limit], 1):
                        title = r.get("title", "")
                        url = r.get("url", "")
                        text += f"{i}. **{title[:80]}**\n"
                        text += f"   🔗 {url}\n\n"
                    return text
    except Exception as e:
        print(f"TinyFish error: {e}")
    
    return None

async def get_f1_news(limit: int = 6) -> str:
    """Получить свежие новости F1 через TinyFish"""
    return await tinyfish_search("Formula 1 latest news 2026", limit)

async def get_f1_news_fallback(limit: int = 6) -> str:
    """Резервный RSS-канал для новостей"""
    posts = get_pending_posts()
    if not posts:
        return None
    
    text = f"📰 **Свежие новости F1 (RSS)**\n\n"
    for i, p in enumerate(posts[:limit], 1):
        text += f"{i}. **{p['title'][:80]}**\n"
        if p.get('link'):
            text += f"   🔗 {p['link']}\n"
        text += "\n"
    return text

# === F1 ДАННЫЕ ===
async def get_driver_standings(year=2026):
    if "standings_2026" in standings_cache:
        return standings_cache["standings_2026"]
    return FALLBACK_STANDINGS.copy()

async def get_next_race(year=2026):
    return {"name": "Гран-при Испании", "date": "14 июня 2026", "circuit": "Барселона"}

async def get_race_schedule(year=2026):
    return [
        {"round": 1, "name": "Гран-при Австралии", "date": "06.03.2026", "circuit": "Мельбурн"},
        {"round": 2, "name": "Гран-при Китая", "date": "20.03.2026", "circuit": "Шанхай"},
        {"round": 3, "name": "Гран-при Японии", "date": "03.04.2026", "circuit": "Судзука"},
        {"round": 4, "name": "Гран-при Бахрейна", "date": "17.04.2026", "circuit": "Сахир"},
        {"round": 5, "name": "Гран-при Саудовской Аравии", "date": "24.04.2026", "circuit": "Джидда"},
        {"round": 6, "name": "Гран-при Майами", "date": "08.05.2026", "circuit": "Майами"},
        {"round": 7, "name": "Гран-при Канады", "date": "22.05.2026", "circuit": "Монреаль"},
        {"round": 8, "name": "Гран-при Монако", "date": "05.06.2026", "circuit": "Монако"},
        {"round": 9, "name": "Гран-при Испании", "date": "14.06.2026", "circuit": "Барселона"},
        {"round": 10, "name": "Гран-при Австрии", "date": "28.06.2026", "circuit": "Шпильберг"},
    ]

# === ПАМЯТЬ ===
def load_memory():
    try:
        with open(MEMORY_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_memory(memory):
    with open(MEMORY_FILE, 'w') as f:
        json.dump(memory, f, indent=2)

def get_memory(user_id, limit=10):
    memory = load_memory()
    return memory.get(str(user_id), [])[-limit:]

def save_to_memory(user_id, message, response):
    memory = load_memory()
    uid = str(user_id)
    if uid not in memory:
        memory[uid] = []
    memory[uid].append({
        "message": message,
        "response": response,
        "timestamp": datetime.now().isoformat()
    })
    if len(memory[uid]) > 50:
        memory[uid] = memory[uid][-50:]
    save_memory(memory)

# === RSS МОНИТОРИНГ ===
pending_posts = []
posted_hashes = set()

def load_hashes():
    global posted_hashes
    try:
        with open(HASH_FILE, 'r') as f:
            posted_hashes = set(json.load(f))
    except:
        posted_hashes = set()

def save_hash(h):
    posted_hashes.add(h)
    with open(HASH_FILE, 'w') as f:
        json.dump(list(posted_hashes), f)

def mark_posted(title, link):
    h = hashlib.md5(f"{title}{link}".encode()).hexdigest()
    save_hash(h)

def is_posted(title, link):
    h = hashlib.md5(f"{title}{link}".encode()).hexdigest()
    return h in posted_hashes

async def generate_post_from_news(title, summary):
    prompt = f"""Напиши пост о Формуле-1 для Telegram канала (3 предложения) на русском языке.

НОВОСТЬ: {title}
ДЕТАЛИ: {summary[:500]}

ПРАВИЛА:
- Заголовок жирным
- Не повторяй заголовок дословно
- В конце #F1

ПОСТ:"""
    post = await ask_ai(prompt)
    post = re.sub(r'\*\*', '', post)
    post += "\n\nRed Race | Подписаться"
    return post

async def monitor_rss():
    load_hashes()
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
                                print(f"📰 Новость: {entry.get('title', '')[:50]}...")
                                post = await generate_post_from_news(
                                    entry.get('title', ''),
                                    entry.get('summary', '')[:500]
                                )
                                pending_posts.append({
                                    "post": post,
                                    "title": entry.get('title', ''),
                                    "link": link
                                })
            except Exception as e:
                print(f"Monitor error: {e}")
        await asyncio.sleep(60)

def get_pending_posts():
    return pending_posts

def clear_pending_posts():
    global pending_posts
    pending_posts = []

# === ПЕРСОНАЖИ ===
CHARACTERS = {
    "Псиникс": "Ебланище конченное. Роман с Райконненом. Проебал 10кк на Пиастри.",
    "Вхуй": "Уебище жирное, дизайнер который нихуя не делает.",
    "Кими": "Создатель канала. Муж Псиникса.",
    "СанРайз": "Жирное уебище, конченный психопат.",
    "Акира": "Главное хуйло чата. Живет в штрафостане.",
}

def get_random_character():
    name, desc = random.choice(list(CHARACTERS.items()))
    return f"🎭 **Ты — {name}**\n\n{desc}\n\n#RedRace"

def get_system_info():
    return f"""🏎️ **Nico™ 3.5 — Гоночный инженер RedRace**

**📋 О боте:**
Nico™ — Telegram-бот с актуальной информацией о Формуле-1

**🤖 Искусственный интеллект:**
• **Nex-N2-Pro** — основная модель (262K контекста)
• **NVIDIA Nemotron 3 Ultra** — резерв

**🔍 Поиск новостей:**
• **TinyFish Search API** — свежие новости F1
• **RSS** — резервный канал

**📊 Технологический стек:**
• AI: OpenRouter (Nex + Nemotron)
• Поиск: TinyFish
• Платформа: Telegram Bot API

**👨‍💻 RedRace Development:**
• Кими Райкконен — Product Owner
• Франц Герман — Lead Engineer

**⭐ Поддержать проект:** кнопка в меню

**© 2026 RedRace. Все права защищены.**

#RedRace #NicoBot #F1
"""

# === ЭКСПОРТ ===
__all__ = [
    'ask_ai',
    'get_driver_standings',
    'get_next_race',
    'get_race_schedule',
    'get_random_character',
    'get_system_info',
    'get_pending_posts',
    'clear_pending_posts',
    'monitor_rss',
    'mark_posted',
    'save_to_memory',
    'get_memory',
    'get_f1_news',
    'get_f1_news_fallback'
]
