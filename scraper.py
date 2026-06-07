import asyncio
import os
import json
import re
import hashlib
import random
import aiohttp
import feedparser
from datetime import datetime
from typing import Optional, List, Dict
from cachetools import TTLCache
import openai

# === FASTF1 ===
try:
    import fastf1
    FASTF1_AVAILABLE = True
    os.makedirs('f1_cache', exist_ok=True)
    fastf1.Cache.enable_cache('f1_cache')
    fastf1.set_log_level('WARNING')
    print("✅ FastF1 загружен")
except ImportError:
    FASTF1_AVAILABLE = False
    print("⚠️ FastF1 не установлен")

# === КОНФИГ ===
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"
MEMORY_FILE = "memory.json"
HASH_FILE = "posted_hashes.json"

RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
    "https://www.championat.com/rss/feed/f1/news.xml",
    "https://www.sport-express.ru/f1/rss/",
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
]

JINA_PROXY = "http://r.jina.ai"

# === OPENROUTER ===
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter/free"
]

# === КЕШ ===
standings_cache = TTLCache(maxsize=1, ttl=3600)
race_cache = TTLCache(maxsize=1, ttl=3600)

# === FALLBACK ===
FALLBACK_STANDINGS = [
    {"pos": 1, "driver": "Kimi Antonelli", "points": 156, "team": "Mercedes"},
    {"pos": 2, "driver": "George Russell", "points": 88, "team": "Mercedes"},
    {"pos": 3, "driver": "Charles Leclerc", "points": 75, "team": "Ferrari"},
    {"pos": 4, "driver": "Lewis Hamilton", "points": 72, "team": "Ferrari"},
    {"pos": 5, "driver": "Lando Norris", "points": 58, "team": "McLaren"}
]

FALLBACK_RACE = {
    "name": "Гран-при Монако 2026",
    "results": [
        {"pos": 1, "driver": "Kimi Antonelli", "points": 25},
        {"pos": 2, "driver": "Lewis Hamilton", "points": 18},
        {"pos": 3, "driver": "Isack Hadjar", "points": 15},
    ]
}

# === AI ===
async def ask_ai(prompt: str, image_url: str = None) -> str:
    if not OPENROUTER_KEY:
        return "❌ Ключ OpenRouter не найден"
    
    client = openai.AsyncOpenAI(
        api_key=OPENROUTER_KEY,
        base_url="https://openrouter.ai/api/v1"
    )
    
    messages = []
    if image_url:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]
        })
    else:
        messages.append({"role": "user", "content": prompt})
    
    for model in OPENROUTER_MODELS:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=1000,
                temperature=0.4,
                timeout=30
            )
            if response and response.choices:
                return response.choices[0].message.content
        except Exception as e:
            print(f"AI error: {e}")
            continue
    
    return "❌ AI временно недоступен"

# === F1 ДАННЫЕ ===
async def get_driver_standings(year=2026):
    if "standings_2026" in standings_cache:
        return standings_cache["standings_2026"]
    
    if not FASTF1_AVAILABLE:
        return FALLBACK_STANDINGS.copy()
    
    try:
        schedule = fastf1.get_event_schedule(year)
        if schedule.empty:
            return FALLBACK_STANDINGS.copy()
        
        last_round = schedule['RoundNumber'].iloc[-1]
        session = fastf1.get_session(year, last_round, 'R')
        session.load()
        results = session.results[['Position', 'Abbreviation', 'Points', 'TeamName']]
        
        standings = []
        for idx, row in results.head(10).iterrows():
            standings.append({
                "pos": int(row['Position']) if row['Position'] not in ['\\N', None] else idx+1,
                "driver": row['Abbreviation'],
                "points": int(row['Points']) if row['Points'] not in ['\\N', None] else 0,
                "team": row['TeamName']
            })
        standings_cache["standings_2026"] = standings
        return standings
    except Exception as e:
        print(f"FastF1 error: {e}")
        return FALLBACK_STANDINGS.copy()

async def get_last_race_results(year=2026):
    if "race_2026" in race_cache:
        return race_cache["race_2026"]
    
    if not FASTF1_AVAILABLE:
        return FALLBACK_RACE.copy()
    
    try:
        schedule = fastf1.get_event_schedule(year)
        if schedule.empty:
            return FALLBACK_RACE.copy()
        
        last_round = schedule['RoundNumber'].iloc[-1]
        session = fastf1.get_session(year, last_round, 'R')
        session.load()
        results = session.results[['Position', 'Abbreviation', 'Points']]
        
        race_results = []
        for idx, row in results.head(5).iterrows():
            race_results.append({
                "pos": int(row['Position']) if row['Position'] not in ['\\N', None] else idx+1,
                "driver": row['Abbreviation'],
                "points": int(row['Points']) if row['Points'] not in ['\\N', None] else 0
            })
        
        race_name = schedule[schedule['RoundNumber'] == last_round]['EventName'].values[0]
        result = {"name": race_name, "results": race_results}
        race_cache["race_2026"] = result
        return result
    except Exception as e:
        return FALLBACK_RACE.copy()

async def get_next_race(year=2026):
    if not FASTF1_AVAILABLE:
        return {"name": "Гран-при Испании", "date": "14 июня 2026", "circuit": "Барселона"}
    
    try:
        schedule = fastf1.get_event_schedule(year)
        if schedule.empty:
            return {"name": "TBD", "date": "TBD", "circuit": "TBD"}
        
        now = datetime.now()
        for _, row in schedule.iterrows():
            race_date = row['EventDate']
            if race_date > now:
                return {
                    "name": row['EventName'],
                    "date": race_date.strftime('%d.%m.%Y'),
                    "circuit": row['Location']
                }
        return {"name": "Сезон завершён", "date": "-", "circuit": "-"}
    except Exception as e:
        return {"name": "Гран-при Испании", "date": "14 июня 2026", "circuit": "Барселона"}

async def get_race_schedule(year=2026):
    if not FASTF1_AVAILABLE:
        return None
    
    try:
        schedule = fastf1.get_event_schedule(year)
        races = []
        for _, row in schedule.iterrows():
            races.append({
                "round": int(row['RoundNumber']),
                "name": row['EventName'],
                "date": row['EventDate'].strftime('%d.%m.%Y'),
                "circuit": row['Location']
            })
        return races
    except Exception as e:
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

# === RSS И JINA.AI ===
async def fetch_via_jina(url: str) -> Optional[str]:
    try:
        proxy_url = f"{JINA_PROXY}/{url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(proxy_url, timeout=25) as resp:
                if resp.status == 200:
                    content = await resp.text()
                    clean_md = re.sub(r'^.*?---\s*', '', content, flags=re.DOTALL)
                    return clean_md[:2500]
    except Exception as e:
        print(f"Jina error: {e}")
    return None

async def generate_post_from_news(title: str, link: str, summary: str) -> str:
    full_content = await fetch_via_jina(link) if link else None
    
    if full_content:
        prompt = f"""Ты — Нико. Напиши пост для Telegram канала.

СТАТЬЯ (через Jina.ai):
{full_content}

ЗАГОЛОВОК: {title}

Правила: заголовок жирным, 3-5 предложений, только факты, в конце #F1"""
    else:
        prompt = f"""Ты — Нико. Напиши пост.

НОВОСТЬ: {title}
ДЕТАЛИ: {summary[:500]}

Правила: заголовок жирным, 3-5 предложений, #F1 в конце"""
    
    post = await ask_ai(prompt)
    post = re.sub(r'\*\*', '', post)
    if link:
        post += f"\n\n🔗 [Источник]({link})"
    post += "\n\nRed Race | Подписаться"
    return post

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
                                    link,
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
REDRACE_CHARACTERS = {
    "Псиникс": "Ебланище конченное. Роман с Райконненом. Проебал 10кк на Пиастри.",
    "Вхуй": "Уебище жирное, дизайнер который нихуя не делает.",
    "Кими": "Создатель канала. Муж Псиникса.",
    "Пиастри": "Уебище из-за которого Псиникс проебал 10кк.",
    "СанРайз": "Жирное уебище, конченный психопат.",
}

def get_random_character() -> str:
    name, desc = random.choice(list(REDRACE_CHARACTERS.items()))
    return f"🎭 **Ты — {name}**\n\n{desc}\n\n#RedRace"

def get_system_info() -> str:
    return f"""ℹ️ **Нико 3.1**

**AI:** NVIDIA Nemotron 3 Ultra
**Данные:** FastF1 + RSS + Jina.ai

**Режимы:**
/short — короткий ответ
/long — развёрнутый
/expert — технический
/meme — дерзкий

**Команды:**
/start, /standings, /race, /next, /mode, /help

#RedRace #F1 #NicoBot"""
