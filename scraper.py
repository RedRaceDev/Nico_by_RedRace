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
from newspaper import Article
import concurrent.futures

load_dotenv()

# === КОНФИГ ===
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
openrouter_client = AsyncOpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1") if OPENROUTER_KEY else None

# === КЭШ ===
cache = TTLCache(maxsize=100, ttl=300)
ua = UserAgent()

# === ПУЛ ПОТОКОВ ДЛЯ NEWSPAPER ===
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# === RSS ИСТОЧНИКИ ===
RSS_SOURCES = [
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.the-race.com/feed/",
    "https://www.planetf1.com/feed",
    "https://www.crash.net/f1/rss",
    "https://www.f1news.ru/export/news.xml"
]

# === СПОРТИВНЫЕ САЙТЫ ДЛЯ ПОИСКА ===
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

# === NEWSPAPER3K - ВЫТАСКИВАНИЕ ПОЛНОГО ТЕКСТА ===
def extract_article_sync(url: str) -> dict:
    try:
        article = Article(url)
        article.download()
        article.parse()
        article.nlp()
        
        return {
            "title": article.title,
            "text": article.text[:3000] if article.text else "",
            "summary": article.summary[:800] if article.summary else "",
            "keywords": article.keywords[:5] if article.keywords else [],
            "top_image": article.top_image if article.top_image else None
        }
    except Exception as e:
        print(f"Newspaper error: {e}")
        return {"title": "", "text": "", "summary": "", "keywords": [], "top_image": None}

async def fetch_full_article(url: str) -> dict:
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, extract_article_sync, url)
        return result
    except Exception as e:
        print(f"Fetch article error: {e}")
        return {"title": "", "text": "", "summary": "", "keywords": [], "top_image": None}

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

# === ПРОВЕРКА НОВОСТИ ===
def is_valid_entry(entry) -> bool:
    title = entry.get('title', '').lower()
    banned = ['403', 'error', 'blocked', 'access denied', '404', '503']
    for w in banned:
        if w in title:
            return False
    return len(title) > 10

def is_real_news(text: str) -> bool:
    trash_markers = [
        "смотрите также", "читайте также", "список десяти лучших",
        "вопросы о применении", "также затрагиваются"
    ]
    text_lower = text.lower()
    for marker in trash_markers:
        if marker in text_lower:
            return False
    return True

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
        "sainz": "#Sainz", "alonso": "#Alonso", "perez": "#Perez"
    }
    for k, v in drivers.items():
        if k in lower:
            tags.append(v)
    
    if "гонк" in lower:
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
                return "❌ ИИ недоступен"
        return "❌ ИИ недоступен"

# === ГЕНЕРАЦИЯ ПОСТА ===
async def gen_post(title: str, content: str, source_url: str) -> str:
    prompt = f"""Ты Нико, гоночный инженер. Перескажи новость ТОЛЬКО ФАКТАМИ.

НОВОСТЬ: {title}
СОДЕРЖАНИЕ: {content[:1500]}

ПРАВИЛА:
- Только факты. Без "я считаю", "возможно"
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
- Нет ошибок (30)
- Есть конкретные факты (30)
- Нет воды (20)
- Нет мнения (20)

НАЗВАНИЕ: {title}
ПОСТ: {post[:600]}

ОЦЕНКА:"""
    
    resp = await ask_llm(prompt)
    try:
        score = int(re.search(r'\d+', resp).group())
        print(f"📊 Оценка: {score}/100")
        return score >= 65
    except:
        return True

# === МОНИТОРИНГ RSS ===
async def monitor(callback):
    last = {}
    while True:
        for src in RSS_SOURCES:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(src, timeout=15, headers={'User-Agent': ua.random}) as resp:
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
                                
                                article = await fetch_full_article(link)
                                content = article.get("text", "") or article.get("summary", "") or entry.get('summary', '')
                                
                                if not content or not is_real_news(content):
                                    print(f"❌ Мусор: {entry.get('title', '')[:50]}")
                                    mark_posted(entry.get('title', ''), link)
                                    continue
                                
                                post = await gen_post(entry.get('title', ''), content, link)
                                
                                if await rate_post(post, entry.get('title', '')):
                                    await callback(post, entry.get('title', ''), link)
                                else:
                                    print(f"❌ Забракован: {entry.get('title', '')[:50]}")
                                    mark_posted(entry.get('title', ''), link)
            except Exception as e:
                print(f"RSS error {src}: {e}")
        
        await asyncio.sleep(60)

# === ОБЩИЕ ФУНКЦИИ ===
async def chat_reply(msg: str) -> str:
    prompt = f"""Ты Нико, гоночный инженер. Ответь кратко, по делу.

Вопрос: {msg}"""
    return await ask_llm(prompt)

async def post_on_topic(topic: str) -> str:
    prompt = f"""Ты Нико. Напиши пост о Формуле-1 на тему: {topic}

Правила:
- Только факты
- 4-6 предложений
- Не добавляй хештеги"""
    post = await ask_llm(prompt)
    post = clean_post(post)
    return post + "\n\n" + gen_hashtags(topic, post)

async def random_post() -> str:
    prompt = """Ты Нико. Напиши интересный пост о Формуле-1.

Правила:
- 5-7 предложений
- Не добавляй хештеги"""
    post = await ask_llm(prompt)
    post = clean_post(post)
    return post + "\n\n" + gen_hashtags("F1", post)

async def calendar() -> str:
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
