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

# === RSS ИСТОЧНИКИ ===
RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
]

# === OPENROUTER AI ===
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter/free"
]

# === КЕШ ===
standings_cache = TTLCache(maxsize=1, ttl=3600)

# === FALLBACK ДАННЫЕ ===
FALLBACK_STANDINGS = [
    {"pos": 1, "driver": "Kimi Antonelli", "points": 156, "team": "Mercedes"},
    {"pos": 2, "driver": "George Russell", "points": 88, "team": "Mercedes"},
    {"pos": 3, "driver": "Charles Leclerc", "points": 75, "team": "Ferrari"},
    {"pos": 4, "driver": "Lewis Hamilton", "points": 72, "team": "Ferrari"},
    {"pos": 5, "driver": "Lando Norris", "points": 58, "team": "McLaren"}
]

# === AI ФУНКЦИЯ ===
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
                max_tokens=500,
                temperature=0.4,
                timeout=25
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
    prompt = f"""Напиши короткий пост о Формуле-1 для Telegram канала (3-5 предложений) на русском языке.

Новость: {title}
Детали: {summary[:300]}

Пост должен быть:
1. С заголовком жирным шрифтом
2. Только факты
3. В конце #F1
4. Язык — русский

Пост:"""
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
    return f"""🏎️ **Nico™ — твой гоночный инженер**

**Разработка:** RedRace Development
**Авторские права:** © 2026 RedRace. Все права защищены.

**Доступные команды:**
• /standings — чемпионат
• /race — последняя гонка
• /next — следующая гонка
• /mode — выбрать стиль ответа
• /help — справка

**Технологии:**
• AI: NVIDIA Nemotron 3 Ultra
• Данные: FastF1 + Jolpica
• Новости: RSS + Jina.ai

#RedRace #NicoBot #F1"""

# === ЭКСПОРТ ===
__all__ = [
    'get_driver_standings', 'get_next_race', 'get_race_schedule',
    'get_random_character', 'get_system_info', 'ask_ai',
    'get_pending_posts', 'clear_pending_posts', 'monitor_rss', 'pending_posts',
    'mark_posted', 'load_memory', 'save_memory', 'get_memory', 'save_to_memory'
]
