import asyncio
import aiohttp
import feedparser
import hashlib
import json
import random
import re
import time
import os
from datetime import datetime
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from openai import AsyncOpenAI

# === OpenRouter fallback ===
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
openrouter_client = None
if OPENROUTER_API_KEY:
    openrouter_client = AsyncOpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")

# === RSS источники ===
RSS_SOURCES = [
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.the-race.com/feed/",
    "https://www.planetf1.com/feed",
    "https://www.crash.net/f1/rss",
    "https://www.grandprix247.com/feed/",
    "https://www.formel1.de/rss/news/feed.xml",
    "https://www.motorsport-magazin.com/rss",
    "https://www.f1news.ru/export/news.xml"
]

# === Кэш ===
search_cache = {}
SEARCH_CACHE_TTL = 60
f1_cache = {}
F1_CACHE_TTL = 600

def get_cached_search(query):
    if query in search_cache:
        data, timestamp = search_cache[query]
        if time.time() - timestamp < SEARCH_CACHE_TTL:
            return data
    return None

def set_cached_search(query, data):
    search_cache[query] = (data, time.time())

# === Память о выложенных постах ===
POSTED_HASHES_FILE = "posted_hashes.json"

def load_posted_hashes():
    if os.path.exists(POSTED_HASHES_FILE):
        with open(POSTED_HASHES_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_posted_hash(post_hash):
    posted = load_posted_hashes()
    posted.add(post_hash)
    with open(POSTED_HASHES_FILE, 'w') as f:
        json.dump(list(posted), f)

def is_already_posted(title, link):
    post_hash = hashlib.md5(f"{title}{link}".encode()).hexdigest()
    return post_hash in load_posted_hashes()

def mark_as_posted(title, link):
    post_hash = hashlib.md5(f"{title}{link}".encode()).hexdigest()
    save_posted_hash(post_hash)

# === Pollinations AI ===
async def ask_pollinations(prompt: str, system: str = "") -> str:
    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://text.pollinations.ai/",
                json={"messages": messages, "model": "openai", "max_tokens": 800},
                timeout=15
            ) as resp:
                if resp.status == 200:
                    return await resp.text()
                return await ask_openrouter_fallback(prompt, system)
    except asyncio.TimeoutError:
        return await ask_openrouter_fallback(prompt, system)
    except:
        return await ask_openrouter_fallback(prompt, system)

async def ask_openrouter_fallback(prompt: str, system: str = "") -> str:
    if not openrouter_client:
        return "❌ ИИ временно недоступен"
    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = await openrouter_client.chat.completions.create(
            model="openrouter/free",
            messages=messages,
            temperature=0.7,
            max_tokens=600
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ Ошибка: {e}"

# === Автооценка поста ===
async def evaluate_post_quality(post_text: str, title: str) -> dict:
    prompt = f"""Оцени пост от 0 до 100.

КРИТЕРИИ:
- Нет ошибок (30 баллов)
- Есть конкретика (30 баллов)
- Стиль эксперта (20 баллов)
- Есть хештеги (10 баллов)
- Длина норм (10 баллов)

НАЗВАНИЕ: {title}
ПОСТ: {post_text[:500]}

ОТВЕТЬ ТОЛЬКО ЧИСЛОМ:"""

    response = await ask_pollinations(prompt)
    try:
        score = int(re.search(r'\d+', response).group())
        score = min(max(score, 0), 100)
        return {"score": score, "verdict": "auto" if score >= 70 else "reject"}
    except:
        return {"score": 50, "verdict": "reject"}

# === Поиск в интернете ===
async def search_web(query: str, max_results: int = 3) -> str:
    cached = get_cached_search(query)
    if cached:
        return cached
    
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
            context = ""
            for r in results:
                context += f"🔍 **{r.get('title', '')}**\n📝 {r.get('body', '')[:500]}\n🔗 {r.get('href', '')}\n\n"
            result = context if context else "Ничего не найдено"
            set_cached_search(query, result)
            return result
    except Exception as e:
        return f"Ошибка поиска: {e}"

# === Парсинг статьи ===
async def fetch_article_text(url: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
                    tag.decompose()
                text = soup.get_text()
                text = re.sub(r'\s+', ' ', text)
                return text[:1500]
    except:
        return ""

# === Валидация ===
def is_valid_news_entry(entry) -> bool:
    title = entry.get('title', '').lower()
    banned = ['403', 'error', 'blocked', 'access denied', '404', '503']
    for word in banned:
        if word in title:
            return False
    return len(title) > 5

def clean_post(text: str) -> str:
    if len(text) > 1500:
        text = text[:1500]
    last_dot = text.rfind('.')
    if last_dot > len(text) - 100:
        text = text[:last_dot + 1]
    return text

# === Генерация постов ===
async def generate_post_from_news(title: str, summary: str, link: str) -> str:
    prompt = f"""Сделай пост о Формуле-1.

НОВОСТЬ:
Заголовок: {title}
Содержание: {summary[:800]}

ПРАВИЛА:
1. Только русский язык
2. Пиши как Нико — гоночный инженер
3. 3-5 предложений
4. Хештеги #F1 в конце

ПОСТ:"""
    return await ask_pollinations(prompt)

async def generate_post_on_topic(topic: str) -> str:
    prompt = f"""Напиши пост о Формуле-1 на тему: {topic}

ПРАВИЛА:
1. Только русский язык
2. Экспертный стиль
3. 4-6 предложений
4. Хештеги #F1 в конце

ПОСТ:"""
    return await ask_pollinations(prompt)

async def generate_random_post() -> str:
    prompt = """Напиши интересный пост о Формуле-1.
Пиши на русском, экспертным тоном, 5-7 предложений.
В конце добавь хештеги #F1.

ПОСТ:"""
    return await ask_pollinations(prompt)

# === Чат ===
async def chat_with_nico(user_message: str) -> str:
    system = "Ты — Нико, гоночный инженер. Отвечай кратко, по делу, с характером. Пиши на русском."
    return await ask_pollinations(user_message, system)

# === Календарь ===
async def get_f1_calendar() -> str:
    calendar_data = {
        "Май": ["03 — Майами", "24 — Канада"],
        "Июнь": ["07 — Монако", "14 — Барселона", "28 — Австрия"],
        "Июль": ["05 — Великобритания", "19 — Бельгия", "26 — Венгрия"],
        "Август": ["23 — Нидерланды"],
        "Сентябрь": ["06 — Италия", "13 — Испания (Мадрид)", "26 — Азербайджан"],
        "Октябрь": ["11 — Сингапур", "25 — США (Остин)"],
        "Ноябрь": ["01 — Мексика", "08 — Бразилия", "21 — Лас-Вегас", "29 — Катар"],
        "Декабрь": ["06 — Абу-Даби"]
    }
    text = "📅 **Календарь F1 2026**\n\n"
    for month, races in calendar_data.items():
        text += f"**{month}**\n"
        for race in races:
            text += f"• {race}\n"
        text += "\n"
    return text

# === Утренний дайджест ===
async def get_morning_digest() -> str:
    return f"☀️ **Доброе утро!**\n\n📅 {datetime.now().strftime('%d.%m.%Y')}\n\n📅 Ближайшие гонки:\n• 7 июня — Монако\n• 14 июня — Барселона\n\nХорошего дня! 🏁"

# === Мониторинг RSS ===
async def monitor_rss(callback):
    last_entries = {}
    
    while True:
        for source in RSS_SOURCES:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(source, timeout=15) as resp:
                        if resp.status == 200:
                            feed = feedparser.parse(await resp.text())
                            if feed.entries:
                                latest = feed.entries[0]
                                if not is_valid_news_entry(latest):
                                    continue
                                entry_key = f"{source}_{latest.get('link', '')}"
                                if entry_key != last_entries.get(source):
                                    last_entries[source] = entry_key
                                    if not is_already_posted(latest.get('title', ''), latest.get('link', '')):
                                        full_text = await fetch_article_text(latest.get('link', ''))
                                        summary = full_text[:1000] if full_text else latest.get('summary', '')[:500]
                                        post = await generate_post_from_news(
                                            latest.get('title', ''),
                                            summary,
                                            latest.get('link', '')
                                        )
                                        post = clean_post(post)
                                        eval_result = await evaluate_post_quality(post, latest.get('title', ''))
                                        if eval_result['verdict'] == "auto":
                                            await callback(post, latest.get('title', ''), latest.get('link', ''))
                                        else:
                                            print(f"🗑️ Пост отклонен: {eval_result['score']} - {latest.get('title', '')[:50]}")
                                            mark_as_posted(latest.get('title', ''), latest.get('link', ''))
            except Exception as e:
                print(f"RSS error {source}: {e}")
        
        await asyncio.sleep(30)
