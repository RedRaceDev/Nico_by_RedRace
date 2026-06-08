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
import google.generativeai as genai

# === GOOGLE AI STUDIO ===
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    print("✅ Google AI Studio (Gemma 4 31B) готов")
else:
    print("⚠️ GEMINI_API_KEY не найден")

# === КОНФИГ ===
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"
MEMORY_FILE = "memory.json"
HASH_FILE = "posted_hashes.json"

RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
    "https://www.autosport.com/rss/feed/f1",
]

# === API КЛЮЧИ ===
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
AGNES_KEY = os.environ.get("AGNES_API_KEY")

# === МОДЕЛИ ===
OPENROUTER_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter/free"
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

# === GOOGLE AI ===
async def ask_google(prompt: str) -> str:
    if not GEMINI_KEY:
        return None
    try:
        model = genai.GenerativeModel(
            "gemma-4-31b-it",
            generation_config={
                "temperature": 0.4,
                "max_output_tokens": 1000,
            }
        )
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: model.generate_content(prompt)
        )
        return response.text
    except Exception as e:
        print(f"Google error: {e}")
        return None

# === OPENROUTER ===
async def ask_openrouter(prompt: str) -> str:
    if not OPENROUTER_KEY:
        return None
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
                temperature=0.4,
                timeout=25
            )
            return response.choices[0].message.content
        except:
            continue
    return None

# === AGNES ===
async def ask_agnes(prompt: str) -> str:
    if not AGNES_KEY:
        return None
    try:
        client = openai.OpenAI(
            api_key=AGNES_KEY,
            base_url="https://apihub.agnes-ai.com/v1"
        )
        response = client.chat.completions.create(
            model="agnes-2.0-flash",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.4
        )
        return response.choices[0].message.content
    except:
        return None

# === ГЛАВНАЯ AI ЦЕПОЧКА ===
async def ask_ai(prompt: str) -> str:
    result = await ask_google(prompt)
    if result and "❌" not in result:
        return result
    result = await ask_openrouter(prompt)
    if result:
        return result
    result = await ask_agnes(prompt)
    if result:
        return result
    return "❌ Все AI сервисы временно недоступны"

# === F1 ДАННЫЕ ===
async def get_driver_standings(year=2026):
    if "standings_2026" in standings_cache:
        return standings_cache["standings_2026"]
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.openf1.org/v1/drivers", timeout=10) as resp:
                if resp.status == 200:
                    standings_cache["standings_2026"] = FALLBACK_STANDINGS
                    return FALLBACK_STANDINGS
    except:
        pass
    
    return FALLBACK_STANDINGS.copy()

async def get_next_race(year=2026):
    return {"name": "Гран-при Испании", "date": "14 июня 2026", "circuit": "Барселона"}

async def get_race_schedule(year=2026):
    return [
        {"round": 1, "name": "Гран-при Австралии", "date": "06.03.2026", "circuit": "Мельбурн"},
        {"round": 2, "name": "Гран-при Китая", "date": "20.03.2026", "circuit": "Шанхай"},
        {"round": 8, "name": "Гран-при Монако", "date": "05.06.2026", "circuit": "Монако"},
    ]

# === ГЕНЕРАЦИЯ КАРТИНОК ===
async def generate_image(prompt: str) -> str:
    if not AGNES_KEY:
        return None
    try:
        client = openai.OpenAI(
            api_key=AGNES_KEY,
            base_url="https://apihub.agnes-ai.com/v1"
        )
        response = client.images.generate(
            model="agnes-image-2.0-flash",
            prompt=prompt,
            size="1024x1024",
            n=1
        )
        return response.data[0].url
    except:
        return None

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
    prompt = f"""Напиши пост о Формуле-1 для Telegram канала (3-5 предложений) на русском языке.

НОВОСТЬ: {title}
ДЕТАЛИ: {summary[:500]}

ПРАВИЛА:
1. Заголовок жирным
2. Только факты
3. В конце #F1

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
    "Пиастри": "Уебище из-за которого Псиникс проебал 10кк.",
    "СанРайз": "Жирное уебище, конченный психопат.",
}

def get_random_character():
    name, desc = random.choice(list(CHARACTERS.items()))
    return f"🎭 **Ты — {name}**\n\n{desc}\n\n#RedRace"

def get_system_info():
    return f"""🏎️ **Nico™ 3.3 — Гоночный инженер RedRace**

**🤝 Стратегический партнёр: Google**

RedRace Development использует технологии Google AI:
• **Gemma 4 31B** — основная модель ИИ (256K контекста)
• **Google AI Studio** — бесплатный доступ

**📊 Технологический стек:**
• AI Core: Google Gemma 4 31B
• Резерв: NVIDIA Nemotron 3 Ultra
• Генерация картинок: Agnes AI
• Данные F1: OpenF1 + RSS

**👨‍💻 RedRace Development:**
• Кими Райкконен — Product Owner
• Франц Герман — Lead Engineer
• Вхуй — Design

**© 2026 RedRace. Все права защищены.**
#RedRace #NicoBot #Google #Gemma #F1"""
