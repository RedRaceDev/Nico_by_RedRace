import asyncio
import aiohttp
import feedparser
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta
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

# === РАБОЧИЕ БЕСПЛАТНЫЕ МОДЕЛИ ===
FREE_MODELS = [
    "openrouter/free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "deepseek/deepseek-v4-flash:free",
    "qwen/qwen3.6-plus-preview:free"
]

current_model_index = 0
working_models = FREE_MODELS.copy()

# === КЭШ ===
cache = TTLCache(maxsize=100, ttl=300)
ua = UserAgent()

# === ПУЛ ПОТОКОВ ===
executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

# === RSS ИСТОЧНИКИ ===
RSS_SOURCES = [
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.the-race.com/feed/",
    "https://www.planetf1.com/feed",
    "https://www.f1news.ru/export/news.xml"
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

# === ПРОВЕРКА СВЕЖЕСТИ ===
def is_fresh_news(entry) -> bool:
    published = entry.get('published_parsed')
    if not published:
        title = entry.get('title', '')
        old_years = ['2024', '2025', '2023', '2022']
        for y in old_years:
            if y in title:
                return False
        return True
    pub_date = datetime(*published[:6])
    days_ago = (datetime.now() - pub_date).days
    return days_ago <= 7

def has_old_date(text: str) -> bool:
    old_years = ['2024', '2025', '2023', '2022']
    for y in old_years:
        if y in text:
            return True
    return False

# === NEWSPAPER3K ===
def extract_article_sync(url: str) -> dict:
    try:
        article = Article(url)
        article.download()
        article.parse()
        return {"text": article.text[:2000] if article.text else ""}
    except:
        return {"text": ""}

async def fetch_full_article(url: str) -> dict:
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(executor, extract_article_sync, url)
    except:
        return {"text": ""}

# === ПРОВЕРКИ ===
def is_valid_entry(entry) -> bool:
    title = entry.get('title', '').lower()
    banned = ['403', 'error', 'blocked', '404', '503']
    return not any(w in title for w in banned) and len(title) > 10

def clean_post(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'\*', '', text)
    text = re.sub(r'_{2,}', '', text)
    text = re.sub(r'_', '', text)
    if len(text) > 1800:
        text = text[:text.rfind('.', 0, 1800)+1]
    return text.strip()

def fix_html(text: str) -> str:
    for tag in ['b', 'i']:
        open_count = text.count(f'<{tag}>')
        close_count = text.count(f'</{tag}>')
        if open_count > close_count:
            text += f'</{tag}>' * (open_count - close_count)
    return text

# === LLM ===
async def ask_llm(prompt: str) -> str:
    global current_model_index
    
    for attempt in range(len(working_models)):
        model = working_models[current_model_index % len(working_models)]
        current_model_index += 1
        
        if openrouter_client:
            try:
                resp = await openrouter_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=600,
                    temperature=0.4
                )
                if resp and resp.choices and resp.choices[0].message:
                    content = resp.choices[0].message.content
                    if content and len(content) > 20:
                        return content
            except Exception as e:
                print(f"Модель {model} упала: {e}")
                continue
    
    return "❌ ИИ временно недоступен"

# === ПЕРЕВОД ===
async def translate_text(text: str) -> str:
    if any(ru in text for ru in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"):
        return text
    prompt = f"Переведи на русский (только перевод): {text}"
    return await ask_llm(prompt)

# === ГЕНЕРАЦИЯ ПОСТА ===
async def gen_post(title: str, content: str, source_url: str) -> str:
    title_ru = await translate_text(title)
    current_year = datetime.now().year
    
    prompt = f"""Ты Нико — бывший гоночный инженер. Теперь ты ведешь канал RedRace.

СЕГОДНЯ: {datetime.now().strftime('%d.%m.%Y')}

НОВОСТЬ: {title_ru}
ДЕТАЛИ: {content[:1000]}

ТВОЙ СТИЛЬ:
- Экспертный, живой, с характером
- Называй вещи своими именами
- Добавь инженерных деталей (шины, аэродинамика, стратегия, настройки)

ПРАВИЛА:
- Заголовок: <b>жирный, короткий</b>
- Текст: 4-6 предложений
- Факты + твое экспертное мнение
- В конце: #F1

ПОСТ:"""
    
    post = await ask_llm(prompt)
    post = clean_post(post)
    post = fix_html(post)
    return post + "\n\nRed Race | Подписаться"

# === ОЦЕНКА КАЧЕСТВА ===
async def rate_post(post: str, title: str) -> bool:
    if not post or len(post) < 100:
        return False
    if has_old_date(post):
        return False
    return True

# === УТРЕННИЙ ДАЙДЖЕСТ ===
async def get_morning_digest() -> str:
    news = []
    for src in RSS_SOURCES[:3]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(src, timeout=15, headers={'User-Agent': ua.random}) as resp:
                    if resp.status == 200:
                        feed = feedparser.parse(await resp.text())
                        for entry in feed.entries[:1]:
                            if is_fresh_news(entry):
                                news.append({"title": entry.get('title', '')})
        except:
            continue
    
    news_text = ""
    for i, item in enumerate(news[:5], 1):
        title_ru = await translate_text(item['title'])
        news_text += f"{i}. {title_ru}\n"
    
    return (
        f"☀️ Доброе утро, RedRace!\n\n"
        f"📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
        f"🏆 Топ новостей дня:\n{news_text}\n"
        f"📅 Ближайшие гонки:\n• Гран-при Монако — 07.06\n\n"
        f"Nico 1.0 Global | RedRace Development"
    )

# === КАЛЕНДАРЬ ===
async def get_f1_calendar() -> str:
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

# === РАНДОМНЫЙ ПОСТ ===
async def random_post() -> str:
    prompt = "Ты Нико. Напиши пост о Формуле-1. Заголовок жирным. 5-7 предложений. Только про 2026 год."
    post = await ask_llm(prompt)
    post = clean_post(post)
    return post + "\n\nRed Race | Подписаться"

# === ПОСТ НА ТЕМУ ===
async def post_on_topic(topic: str) -> str:
    prompt = f"Ты Нико. Напиши пост о Формуле-1 на тему: {topic}. Заголовок жирным. 4-6 предложений. Только про 2026 год."
    post = await ask_llm(prompt)
    post = clean_post(post)
    return post + "\n\nRed Race | Подписаться"

# === ЧАТ ===
async def chat_reply(msg: str) -> str:
    prompt = f"Ты Нико, эксперт по Формуле-1. Ответь кратко, по делу.\n\nВопрос: {msg}"
    return await ask_llm(prompt)

# === ПОИСК ===
async def search_f1(query: str) -> str:
    try:
        with DDGS(headers={'User-Agent': ua.random}) as ddgs:
            results = ddgs.text(f"{query} formula 1", max_results=3)
            context = ""
            for r in results:
                context += f"🔍 **{r.get('title', '')}**\n📝 {r.get('body', '')[:500]}\n🔗 {r.get('href', '')}\n\n"
            return context if context else "Ничего не найдено"
    except Exception as e:
        return f"Ошибка поиска: {e}"

# === МОНИТОРИНГ ===
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
                                
                                if not is_fresh_news(entry):
                                    mark_posted(entry.get('title', ''), link)
                                    continue
                                
                                article = await fetch_full_article(link)
                                content = article.get("text", "") or entry.get('summary', '')
                                
                                if not content or len(content) < 100:
                                    mark_posted(entry.get('title', ''), link)
                                    continue
                                
                                post = await gen_post(entry.get('title', ''), content, link)
                                
                                if await rate_post(post, entry.get('title', '')):
                                    await callback(post, entry.get('title', ''), link)
                                else:
                                    mark_posted(entry.get('title', ''), link)
            except:
                continue
        
        await asyncio.sleep(60)
