import asyncio
import aiohttp
import feedparser
import hashlib
import json
import os
import re
import time
import random
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from fake_useragent import UserAgent
from cachetools import TTLCache
from dotenv import load_dotenv
from newspaper import Article
import concurrent.futures
import google.generativeai as genai

from search_engine import search_web

load_dotenv()

# === КЛЮЧИ ===
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
openrouter_client = AsyncOpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1") if OPENROUTER_KEY else None

GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    # Основная модель — Gemini 3.5 Flash
    gemini_model = genai.GenerativeModel('gemini-3.5-flash')
    print("✅ Gemini 3.5 Flash подключен")
else:
    gemini_model = None

# === СПИСОК МОДЕЛЕЙ ДЛЯ ПЕРЕКЛЮЧЕНИЯ ===
AVAILABLE_MODELS = {
    "gemini": "gemini-3.5-flash",
    "gemini_lite": "gemini-3.1-flash-lite",
    "openrouter": "openrouter/free",
    "nemotron": "nvidia/nemotron-3-super-120b-a12b:free",
    "gpt_oss": "openai/gpt-oss-120b:free"
}

current_model = "gemini"  # Модель по умолчанию

def switch_model(model_name: str):
    """Переключает модель по имени"""
    global current_model
    if model_name in AVAILABLE_MODELS:
        current_model = model_name
        print(f"🔄 Модель переключена на: {model_name}")
        return True
    return False

def get_current_model_id():
    """Возвращает ID текущей модели для API"""
    return AVAILABLE_MODELS.get(current_model, "gemini-3.5-flash")

# === КЭШ ===
ua = UserAgent()
executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

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
MEMORY_FILE = "memory.json"

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

def is_news_from_this_year(entry) -> bool:
    published = entry.get('published_parsed')
    if not published:
        return True
    pub_year = published.tm_year
    current_year = datetime.now().year
    return pub_year >= current_year

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

def fix_html(text: str) -> str:
    for tag in ['b', 'i']:
        open_c = text.count(f'<{tag}>')
        close_c = text.count(f'</{tag}>')
        if open_c > close_c:
            text += f'</{tag}>' * (open_c - close_c)
    return text

def extract_article_sync(url: str) -> str:
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text[:2000] if article.text else ""
    except:
        return ""

async def fetch_article(url: str) -> str:
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(executor, extract_article_sync, url)
    except:
        return ""

async def ask_gemini_with_search(prompt: str) -> str:
    """Запрос к Gemini с поиском в интернете"""
    if not gemini_model:
        return await ask_fallback(prompt)
    try:
        from google.genai import types
        search_tool = types.Tool(google_search=types.GoogleSearch())
        config = types.GenerateContentConfig(tools=[search_tool])
        
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: gemini_model.generate_content(prompt, generation_config=config)
        )
        if response and response.text:
            return response.text
        return await ask_fallback(prompt)
    except Exception as e:
        print(f"Gemini search error: {e}")
        return await ask_fallback(prompt)

async def ask_gemini(prompt: str) -> str:
    """Обычный запрос к Gemini без поиска"""
    if not gemini_model:
        return await ask_fallback(prompt)
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: gemini_model.generate_content(prompt)
        )
        if response and response.text:
            return response.text
        return await ask_fallback(prompt)
    except Exception as e:
        print(f"Gemini error: {e}")
        return await ask_fallback(prompt)

async def ask_fallback(prompt: str) -> str:
    """Резервный вызов через OpenRouter"""
    if not openrouter_client:
        return "❌ ИИ недоступен"
    try:
        resp = await openrouter_client.chat.completions.create(
            model=get_current_model_id(),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.4
        )
        if resp and resp.choices and resp.choices[0].message:
            return resp.choices[0].message.content
        return "❌ Пустой ответ"
    except Exception as e:
        print(f"Fallback error: {e}")
        return f"❌ Ошибка: {e}"

async def translate_text(text: str) -> str:
    if any(ru in text for ru in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"):
        return text
    return await ask_gemini(f"Переведи на русский (только перевод): {text}")

async def gen_post(title: str, content: str) -> str:
    title_ru = await translate_text(title)
    today = datetime.now().strftime('%d.%m.%Y')
    current_year = datetime.now().year
    
    prompt = f"""Ты Нико, гоночный инженер. Сегодня {today}.
ВАЖНО: СЕЙЧАС {current_year} ГОД! Пиши только про события {current_year} года.

НОВОСТЬ: {title_ru}
ДЕТАЛИ: {content[:1500]}

ПРАВИЛА:
- Заголовок: <b>жирный</b>
- 3-5 абзацев
- Только факты
- В конце: #F1

ПОСТ:"""
    post = await ask_gemini(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

async def chat_reply(user_id: int, msg: str, use_search: bool = True) -> str:
    memory = get_memory(user_id, 10)
    context = ""
    for m in memory[-5:]:
        context += f"Пользователь: {m['message']}\nНико: {m['response']}\n"
    
    prompt = f"""Ты Нико, эксперт по Формуле-1.
История:
{context}
Пользователь: {msg}
Ответь кратко, по делу, в {datetime.now().year} году."""
    
    if use_search:
        answer = await ask_gemini_with_search(prompt)
    else:
        answer = await ask_gemini(prompt)
    
    save_memory(user_id, msg, answer)
    return answer

async def get_calendar() -> str:
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

async def random_post() -> str:
    prompt = f"Ты Нико. Напиши пост о Формуле-1. Заголовок жирным. 5-7 предложений. Сейчас {datetime.now().year} год."
    return clean_post(await ask_gemini(prompt)) + "\n\nRed Race | Подписаться"

async def post_on_topic(topic: str) -> str:
    prompt = f"Ты Нико. Напиши пост о Формуле-1 на тему: {topic}. Заголовок жирным. 4-6 предложений. Сейчас {datetime.now().year} год."
    return clean_post(await ask_gemini(prompt)) + "\n\nRed Race | Подписаться"

async def morning_digest() -> str:
    news = []
    for src in RSS_SOURCES[:3]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(src, timeout=15) as resp:
                    if resp.status == 200:
                        feed = feedparser.parse(await resp.text())
                        for entry in feed.entries[:1]:
                            if is_fresh_news(entry) and is_news_from_this_year(entry):
                                news.append(entry.get('title', ''))
        except:
            continue
    news_text = ""
    for i, title in enumerate(news[:5], 1):
        news_text += f"{i}. {await translate_text(title)}\n"
    return f"""☀️ Доброе утро, RedRace!

📅 {datetime.now().strftime('%d.%m.%Y')}

🏆 Топ новостей дня:
{news_text}
📅 Ближайшие гонки:
• 7 июня — Монако
• 14 июня — Барселона

Red Race | Подписаться"""

# === МОНИТОРИНГ RSS ===
pending_posts = []

async def monitor(callback):
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
                                if not is_fresh_news(entry) or not is_news_from_this_year(entry):
                                    mark_posted(entry.get('title', ''), link)
                                    continue
                                text = await fetch_article(link)
                                content = text or entry.get('summary', '')[:500]
                                if not content or len(content) < 100:
                                    mark_posted(entry.get('title', ''), link)
                                    continue
                                post = await gen_post(entry.get('title', ''), content)
                                pending_posts.append({"post": post, "title": entry.get('title', ''), "link": link})
                                print(f"📰 Новая новость: {entry.get('title', '')[:50]}...")
            except:
                continue
        await asyncio.sleep(60)

def get_pending_posts():
    return pending_posts

def clear_pending_posts():
    global pending_posts
    pending_posts = []

def set_pending_posts(posts):
    global pending_posts
    pending_posts = posts
