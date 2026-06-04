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
    gemini_model = genai.GenerativeModel('gemini-3.5-flash')
    print("✅ Gemini 3.5 Flash подключен")
else:
    gemini_model = None

# === СПИСОК МОДЕЛЕЙ ===
AVAILABLE_MODELS = {
    "gemini": "gemini-3.5-flash",
    "gemini_lite": "gemini-3.1-flash-lite",
    "openrouter": "openrouter/free",
    "nemotron": "nvidia/nemotron-3-super-120b-a12b:free",
    "gpt_oss": "openai/gpt-oss-120b:free"
}

_current_model = "openrouter"  # По умолчанию OpenRouter, чтобы не падать

def get_current_model_id():
    """Возвращает ID текущей модели для API"""
    return AVAILABLE_MODELS.get(_current_model, "openrouter/free")

def get_current_model_key():
    return _current_model

def switch_model(model_key: str) -> bool:
    """Переключает модель по ключу"""
    global _current_model
    if model_key in AVAILABLE_MODELS:
        _current_model = model_key
        print(f"🔄 Модель переключена на: {model_key} ({AVAILABLE_MODELS[model_key]})")
        return True
    return False

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

# === ОСНОВНЫЕ ВЫЗОВЫ ИИ ===
async def ask_gemini(prompt: str, image_url: str = None) -> str:
    """Запрос к Gemini (с поддержкой фото)"""
    if not gemini_model:
        return await ask_fallback(prompt)
    try:
        from google.genai import types
        if image_url:
            search_tool = types.Tool(google_search=types.GoogleSearch())
            config = types.GenerateContentConfig(tools=[search_tool])
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: gemini_model.generate_content(
                    [
                        {"text": prompt},
                        {"image_url": image_url}
                    ],
                    generation_config=config
                )
            )
        else:
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: gemini_model.generate_content(prompt)
            )
        if response and response.text:
            if "429" in response.text or "quota" in response.text.lower():
                print("Gemini quota exceeded, switching to fallback")
                return await ask_fallback(prompt)
            return response.text
        return await ask_fallback(prompt)
    except Exception as e:
        print(f"Gemini error: {e}")
        return await ask_fallback(prompt)

async def ask_fallback(prompt: str) -> str:
    """Резервный вызов через OpenRouter"""
    if not openrouter_client:
        return "❌ ИИ недоступен. Попробуй позже."
    
    model = get_current_model_id()
    # Если модель gemini — используем openrouter/free
    if model.startswith("gemini"):
        model = "openrouter/free"
    
    try:
        resp = await openrouter_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.4
        )
        if resp and resp.choices and resp.choices[0].message:
            return resp.choices[0].message.content
        return "❌ Пустой ответ от ИИ"
    except Exception as e:
        print(f"Fallback error: {e}")
        return f"❌ Ошибка: {e}"

async def ask_ai(prompt: str, image_url: str = None) -> str:
    """Универсальный вызов — сам выбирает модель по текущей"""
    current_key = get_current_model_key()
    
    if current_key.startswith("gemini"):
        return await ask_gemini(prompt, image_url)
    else:
        return await ask_fallback(prompt)

async def translate_text(text: str) -> str:
    if any(ru in text for ru in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"):
        return text
    prompt = f"Переведи на русский (только перевод): {text}"
    return await ask_ai(prompt)

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
    post = await ask_ai(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

async def chat_reply(user_id: int, msg: str, image_url: str = None) -> str:
    """Основной чат — поддерживает текст и фото"""
    memory = get_memory(user_id, 10)
    context = ""
    for m in memory[-5:]:
        context += f"Пользователь: {m['message']}\nНико: {m['response']}\n"
    
    if image_url:
        prompt = f"""Ты Нико, гоночный инженер. Проанализируй это фото.
        
Подпись к фото: {msg if msg else 'Нет описания'}

Опиши:
- Что за машина/деталь/трасса
- Технические особенности
- Что можно заметить

История диалога:
{context}"""
        answer = await ask_ai(prompt, image_url)
    else:
        prompt = f"""Ты Нико, эксперт по Формуле-1.
История:
{context}
Пользователь: {msg}
Ответь кратко, по делу, в {datetime.now().year} году."""
        answer = await ask_ai(prompt)
    
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
    return clean_post(await ask_ai(prompt)) + "\n\nRed Race | Подписаться"

async def post_on_topic(topic: str) -> str:
    prompt = f"Ты Нико. Напиши пост о Формуле-1 на тему: {topic}. Заголовок жирным. 4-6 предложений. Сейчас {datetime.now().year} год."
    return clean_post(await ask_ai(prompt)) + "\n\nRed Race | Подписаться"

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
