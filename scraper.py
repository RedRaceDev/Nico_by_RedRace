import asyncio
import aiohttp
import feedparser
import hashlib
import json
import os
import re
import time
from datetime import datetime
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from openai import AsyncOpenAI
from fake_useragent import UserAgent
from cachetools import TTLCache
from dotenv import load_dotenv

load_dotenv()

# === КОНФИГ ===
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
openrouter_client = AsyncOpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1") if OPENROUTER_KEY else None

# === КЭШ ===
cache = TTLCache(maxsize=100, ttl=300)
ua = UserAgent()

# === RSS ИСТОЧНИКИ ===
RSS_SOURCES = [
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.the-race.com/feed/",
    "https://www.planetf1.com/feed",
    "https://www.crash.net/f1/rss",
    "https://www.f1news.ru/export/news.xml"
]

# === СПОРТИВНЫЕ САЙТЫ ===
SPORTS_SITES = [
    "autosport.com", "motorsport.com", "the-race.com",
    "planetf1.com", "crash.net", "f1news.ru", "formula1.com"
]

# === ПАМЯТЬ О ПОСТАХ ===
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

# === ПОИСК ===
async def search_f1(query: str) -> str:
    try:
        with DDGS(headers={'User-Agent': ua.random}) as ddgs:
            site_query = " OR ".join([f"site:{s}" for s in SPORTS_SITES])
            results = ddgs.text(f"{query} ({site_query})", max_results=3)
            context = ""
            for r in results:
                context += f"🔍 **{r.get('title', '')}**\n"
                context += f"📝 {r.get('body', '')[:500]}\n"
                context += f"🔗 {r.get('href', '')}\n\n"
            return context if context else "Ничего не найдено"
    except Exception as e:
        return f"Ошибка поиска: {e}"

# === ИЗВЛЕЧЕНИЕ ТЕКСТА ===
async def fetch_article(url: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15, headers={'User-Agent': ua.random}) as resp:
                html = await resp.text()
                soup = BeautifulSoup(html, 'lxml')
                for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                    tag.decompose()
                text = soup.get_text()
                text = re.sub(r'\s+', ' ', text)
                return text[:2000]
    except Exception as e:
        print(f"Fetch error: {e}")
        return ""

# === ПРОВЕРКА НОВОСТИ ===
def is_valid_entry(entry) -> bool:
    title = entry.get('title', '').lower()
    banned = ['403', 'error', 'blocked', 'access denied', '404', '503']
    for w in banned:
        if w in title:
            return False
    return len(title) > 10

# === ЧИСТКА ПОСТА ===
def clean_post(text: str) -> str:
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'\*', '', text)
    text = re.sub(r'_{2,}', '', text)
    text = re.sub(r'_', '', text)
    if len(text) > 2000:
        text = text[:text.rfind('.', 0, 2000)+1]
    return text.strip()

# === ГЕНЕРАЦИЯ ХЕШТЕГОВ ===
def gen_hashtags(title: str, text: str) -> str:
    lower = (title + " " + text).lower()
    tags = ["#F1"]
    
    teams = {
        "ferrari": "#Ferrari", "red bull": "#RedBull", "mercedes": "#Mercedes",
        "mclaren": "#McLaren", "aston martin": "#AstonMartin", "alpine": "#Alpine",
        "williams": "#Williams", "haas": "#Haas", "rb": "#RB", "sauber": "#Sauber"
    }
    for k, v in teams.items():
        if k in lower:
            tags.append(v)
    
    drivers = {
        "verstappen": "#Verstappen", "hamilton": "#Hamilton", "leclerc": "#Leclerc",
        "norris": "#Norris", "piastri": "#Piastri", "russell": "#Russell",
        "sainz": "#Sainz", "alonso": "#Alonso", "perez": "#Perez", "ocon": "#Ocon",
        "gasly": "#Gasly", "bottas": "#Bottas", "tsunoda": "#Tsunoda"
    }
    for k, v in drivers.items():
        if k in lower:
            tags.append(v)
    
    if "гонк" in lower or "race" in lower:
        tags.append("#Race")
    if "квалификаци" in lower:
        tags.append("#Qualifying")
    if "шин" in lower:
        tags.append("#Tyres")
    if "стратег" in lower:
        tags.append("#Strategy")
    
    tags = list(dict.fromkeys(tags))
    return " " + " ".join(tags[:6])

# === LLM ===
async def ask_llm(prompt: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://text.pollinations.ai/",
                json={"messages": [{"role": "user", "content": prompt}], "model": "openai"},
                timeout=20
            ) as resp:
                if resp.status == 200:
                    return await resp.text()
                raise Exception("Pollinations failed")
    except Exception as e:
        print(f"Pollinations error: {e}")
        if openrouter_client:
            try:
                resp = await openrouter_client.chat.completions.create(
                    model="openrouter/free",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=800,
                    temperature=0.7
                )
                return resp.choices[0].message.content
            except Exception as e2:
                print(f"OpenRouter error: {e2}")
                return "❌ ИИ временно недоступен"
        return "❌ ИИ временно недоступен"

# === ГЕНЕРАЦИЯ ПОСТА ===
async def gen_post(title: str, summary: str) -> str:
    prompt = f"""Ты Нико, гоночный инженер. Перескажи новость ТОЛЬКО ФАКТАМИ, БЕЗ МНЕНИЯ.

ЗАГОЛОВОК: {title}
СОДЕРЖАНИЕ: {summary[:1000]}

ПРАВИЛА:
- Только факты. Никаких "я считаю", "возможно", "наверное"
- Никакой воды. Конкретика: цифры, имена, детали
- 4-6 предложений
- Не добавляй хештеги

ПОСТ:"""
    
    post = await ask_llm(prompt)
    post = clean_post(post)
    hashtags = gen_hashtags(title, post)
    return post + "\n\n" + hashtags

# === ОЦЕНКА КАЧЕСТВА ===
async def rate_post(post: str, title: str) -> bool:
    prompt = f"""Оцени пост от 0 до 100. Только число.

КРИТЕРИИ:
- Нет ошибок, мусора, странных символов (30 баллов)
- Есть конкретные факты, цифры, имена (30 баллов)
- Нет воды, общих фраз (20 баллов)
- Нет личного мнения (20 баллов)

НАЗВАНИЕ: {title}
ПОСТ: {post[:600]}

ОЦЕНКА (ТОЛЬКО ЧИСЛО):"""
    
    resp = await ask_llm(prompt)
    try:
        score = int(re.search(r'\d+', resp).group())
        print(f"📊 Оценка поста: {score}/100")
        return score >= 65
    except:
        print(f"⚠️ Не удалось оценить пост, публикуем")
        return True

# === ПАРСИНГ RSS ===
async def parse_rss(url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15, headers={'User-Agent': ua.random}) as resp:
                if resp.status == 200:
                    feed = feedparser.parse(await resp.text())
                    if feed.entries:
                        return feed.entries[0]
    except Exception as e:
        print(f"RSS error {url}: {e}")
    return None

# === МОНИТОРИНГ ===
async def monitor(callback):
    last = {}
    while True:
        for src in RSS_SOURCES:
            entry = await parse_rss(src)
            if not entry or not is_valid_entry(entry):
                continue
            
            key = f"{src}_{entry.get('link', '')}"
            if key == last.get(src):
                continue
            
            last[src] = key
            
            if is_posted(entry.get('title', ''), entry.get('link', '')):
                continue
            
            # Получаем полный текст статьи
            article_text = await fetch_article(entry.get('link', ''))
            summary = article_text[:1500] if article_text else entry.get('summary', '')[:800]
            
            # Генерируем пост
            post = await gen_post(entry.get('title', ''), summary)
            
            # Оцениваем качество
            if await rate_post(post, entry.get('title', '')):
                await callback(post, entry.get('title', ''), entry.get('link', ''))
            else:
                print(f"❌ Пост забракован: {entry.get('title', '')[:50]}...")
                mark_posted(entry.get('title', ''), entry.get('link', ''))
        
        await asyncio.sleep(60)

# === ОБЩИЕ ФУНКЦИИ ===
async def chat_reply(msg: str) -> str:
    prompt = f"""Ты Нико, гоночный инженер. Ответь кратко, по делу, с характером.

Вопрос: {msg}

Правила: без воды, без лишних эмодзи, только суть."""
    return await ask_llm(prompt)

async def post_on_topic(topic: str) -> str:
    prompt = f"""Ты Нико, гоночный инженер. Напиши пост о Формуле-1 на тему: {topic}

Правила:
- Только факты, без мнения
- 4-6 предложений
- Не добавляй хештеги"""
    post = await ask_llm(prompt)
    post = clean_post(post)
    return post + "\n\n" + gen_hashtags(topic, post)

async def random_post() -> str:
    prompt = """Ты Нико, гоночный инженер. Напиши интересный пост о Формуле-1.

Правила:
- Только факты, без мнения
- 5-7 предложений
- Не добавляй хештеги"""
    post = await ask_llm(prompt)
    post = clean_post(post)
    return post + "\n\n" + gen_hashtags("F1", post)

async def calendar() -> str:
    return """📅 **Календарь F1 2026**

**Май**
03 — Майами
24 — Канада

**Июнь**
07 — Монако
14 — Барселона
28 — Австрия

**Июль**
05 — Великобритания
19 — Бельгия
26 — Венгрия

**Август**
23 — Нидерланды

**Сентябрь**
06 — Италия
13 — Испания (Мадрид)
26 — Азербайджан

**Октябрь**
11 — Сингапур
25 — США (Остин)

**Ноябрь**
01 — Мексика
08 — Бразилия
21 — Лас-Вегас
29 — Катар

**Декабрь**
06 — Абу-Даби

#F1 #Calendar2026"""
