import asyncio
import os
import json
import re
import hashlib
import aiohttp
import feedparser
from datetime import datetime, timedelta
import openai
import google.generativeai as genai

# === F1 DATA ===
try:
    import fastf1
    FASTF1_AVAILABLE = True
    fastf1.Cache.enable_cache('f1_cache')
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
]

# === API КЛЮЧИ ===
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
BRAVE_KEY = os.environ.get("BRAVE_API_KEY")

# === AI МОДЕЛИ ===
GEMINI_MODEL = "gemini-2.5-flash"
OPENROUTER_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"

# === AI ФУНКЦИИ ===
async def ask_gemini(prompt: str, image_url: str = None) -> str:
    if not GEMINI_KEY:
        return await ask_openrouter(prompt, image_url)
    
    try:
        genai.configure(api_key=GEMINI_KEY)
        if image_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    image_data = await resp.read()
            from PIL import Image
            import io
            image = Image.open(io.BytesIO(image_data))
            model = genai.GenerativeModel(GEMINI_MODEL)
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: model.generate_content([prompt, image]))
        else:
            model = genai.GenerativeModel(GEMINI_MODEL)
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: model.generate_content(prompt))
        
        if response and response.text:
            return response.text
        return await ask_openrouter(prompt, image_url)
    except Exception as e:
        print(f"Gemini error: {e}")
        return await ask_openrouter(prompt, image_url)

async def ask_openrouter(prompt: str, image_url: str = None) -> str:
    if not OPENROUTER_KEY:
        return "❌ Нет доступных AI сервисов"
    
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
    
    try:
        response = await client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=messages,
            max_tokens=1000,
            temperature=0.4
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"OpenRouter error: {e}")
        return f"❌ Ошибка AI: {e}"

async def ask_ai(prompt: str, image_url: str = None) -> str:
    return await ask_gemini(prompt, image_url)

# === F1 DATA FUNCTIONS ===
async def get_driver_standings(year=2026):
    url = f"https://api.jolpica.f1/api/v1/{year}/driverstandings.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            standings = data['MRData']['StandingsTable']['StandingsLists'][0]['DriverStandings']
            result = []
            for i, s in enumerate(standings[:10], 1):
                driver = f"{s['Driver']['givenName']} {s['Driver']['familyName']}"
                result.append({
                    "pos": i,
                    "driver": driver,
                    "points": s['points'],
                    "team": s['Constructors'][0]['name']
                })
            return result

async def get_last_race_results(year=2026):
    url = f"https://api.jolpica.f1/api/v1/{year}/last/results.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            race = data['MRData']['RaceTable']['Races'][0]
            results = []
            for r in race['Results'][:10]:
                driver = f"{r['Driver']['givenName']} {r['Driver']['familyName']}"
                results.append({
                    "pos": r.get('position', 'DNF'),
                    "driver": driver,
                    "points": r.get('points', '0')
                })
            return {"name": race['raceName'], "results": results}

async def get_next_race(year=2026):
    url = f"https://api.jolpica.f1/api/v1/{year}/next.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            race = data['MRData']['RaceTable']['Races'][0]
            return {
                "name": race['raceName'],
                "date": race['date'],
                "circuit": race['Circuit']['circuitName']
            }

async def get_telemetry_comparison(driver1, driver2, year=2026):
    if not FASTF1_AVAILABLE:
        return None
    try:
        schedule = fastf1.get_event_schedule(year)
        round_num = schedule['RoundNumber'].iloc[-1]
        session = fastf1.get_session(year, round_num, 'R')
        session.load()
        laps1 = session.laps.pick_driver(driver1.upper()).pick_fastest()
        laps2 = session.laps.pick_driver(driver2.upper()).pick_fastest()
        if laps1 is None or laps2 is None:
            return None
        tele1 = laps1.get_telemetry()
        tele2 = laps2.get_telemetry()
        return {
            "driver1": driver1.upper(),
            "time1": laps1['LapTime'].total_seconds(),
            "max_speed1": tele1['Speed'].max(),
            "driver2": driver2.upper(),
            "time2": laps2['LapTime'].total_seconds(),
            "max_speed2": tele2['Speed'].max()
        }
    except Exception as e:
        print(f"Telemetry error: {e}")
        return None

async def search_brave_images(query: str, max_results: int = 10) -> list:
    if not BRAVE_KEY:
        return []
    url = f"https://api.search.brave.com/res/v1/images/search?q={query}&count={max_results}"
    headers = {"X-Subscription-Token": BRAVE_KEY, "Accept": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                results = []
                for i, img in enumerate(data.get('results', [])):
                    results.append({
                        'id': f"img_{i}",
                        'url': img.get('url'),
                        'thumbnail': img.get('thumbnail', {}).get('src'),
                        'title': img.get('title', ''),
                        'source': img.get('page', '')
                    })
                return results
    return []

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

# === ОСНОВНЫЕ ФУНКЦИИ БОТА ===
async def chat_reply(user_id: int, message: str, photo_url: str = None) -> str:
    memory = get_memory(user_id, 10)
    context = ""
    for m in memory[-5:]:
        context += f"Пользователь: {m['message']}\nНико: {m['response']}\n"
    
    standings = None
    if any(word in message.lower() for word in ['чемпионат', 'лидирует', 'очки', 'таблица']):
        standings = await get_driver_standings(2026)
    
    f1_context = ""
    if standings:
        f1_context = "Таблица чемпионата 2026:\n"
        for s in standings[:5]:
            f1_context += f"{s['pos']}. {s['driver']} — {s['points']} очков ({s['team']})\n"
    
    prompt = f"""Ты Нико, гоночный инженер RedRace. Год 2026.
История: {context}
{('Данные F1: ' + f1_context) if f1_context else ''}
Пользователь: {message}
Ответь кратко, по делу, используя данные выше. Будь дерзким, но полезным. Не выдумывай цифры."""
    
    answer = await ask_ai(prompt, image_url=photo_url)
    save_to_memory(user_id, message, answer)
    return answer

def clean_post(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    if len(text) > 1800:
        text = text[:text.rfind('.', 0, 1800)+1]
    return text.strip()

async def random_post() -> str:
    prompt = "Напиши случайный пост о Формуле-1 (заголовок жирным, 5-7 предложений)."
    post = await ask_ai(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

async def post_on_topic(topic: str) -> str:
    prompt = f"Напиши пост о Формуле-1 на тему: {topic}. Заголовок жирным, 4-6 предложений."
    post = await ask_ai(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

async def get_calendar() -> str:
    return """📅 Календарь F1 2026
7 июня — Монако
14 июня — Барселона
28 июня — Австрия
5 июля — Великобритания
19 июля — Бельгия
26 июля — Венгрия
23 августа — Нидерланды
#F1 #Calendar2026"""

async def analyze_photo(photo_url: str) -> str:
    prompt = "Ты гоночный инженер. Проанализируй это фото: что за машина, технические особенности?"
    return await ask_ai(prompt, image_url=photo_url)

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

async def generate_post_from_news(title, content):
    prompt = f"Напиши пост о Формуле-1. Новость: {title}. Детали: {content[:500]}. Заголовок жирным, 3-5 абзацев, только факты. В конце #F1"
    post = await ask_ai(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

async def monitor():
    load_hashes()
    last = {}
    while True:
        for src in RSS_SOURCES:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(src, timeout=10) as resp:
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
                                post = await generate_post_from_news(
                                    entry.get('title', ''),
                                    entry.get('summary', '')[:500]
                                )
                                pending_posts.append({
                                    "post": post,
                                    "title": entry.get('title', ''),
                                    "link": link
                                })
                                print(f"📰 Новость: {entry.get('title', '')[:50]}...")
            except Exception as e:
                print(f"Monitor error: {e}")
        await asyncio.sleep(60)

def get_pending_posts():
    return pending_posts

def clear_pending_posts():
    global pending_posts
    pending_posts = []

def set_pending_posts(posts):
    global pending_posts
    pending_posts = posts

async def morning_digest() -> str:
    news = []
    for src in RSS_SOURCES[:1]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(src, timeout=10) as resp:
                    if resp.status == 200:
                        feed = feedparser.parse(await resp.text())
                        for entry in feed.entries[:3]:
                            news.append(entry.get('title', ''))
        except:
            pass
    news_text = "\n".join([f"{i+1}. {title}" for i, title in enumerate(news[:3])]) if news else "Нет свежих новостей"
    return f"""☀️ Доброе утро, RedRace!
📅 {datetime.now().strftime('%d.%m.%Y')}
🏆 Топ новостей дня:
{news_text}
Red Race | Подписаться"""
