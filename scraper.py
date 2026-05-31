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
from duckduckgo_search import DDGS
from openai import AsyncOpenAI
from fake_useragent import UserAgent
from cachetools import TTLCache
from dotenv import load_dotenv
from newspaper import Article
import concurrent.futures
import google.generativeai as genai

load_dotenv()

# === КЛЮЧИ ===
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
openrouter_client = AsyncOpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1") if OPENROUTER_KEY else None

GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    gemini_model = genai.GenerativeModel('gemini-2.0-flash-lite-preview-02-05')
    print("✅ Gemini подключен")
else:
    gemini_model = None

# === FALLBACK МОДЕЛИ ===
FALLBACK_MODELS = ["openrouter/free", "nvidia/nemotron-3-super-120b-a12b:free", "mistralai/mistral-7b-instruct:free"]
model_index = 0

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
        title = entry.get('title', '')
        for y in ['2024', '2025']:
            if y in title:
                return False
        return True
    pub_date = datetime(*published[:6])
    return (datetime.now() - pub_date).days <= 7

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

async def ask_gemini(prompt: str) -> str:
    if not gemini_model:
        return await ask_fallback(prompt)
    try:
        response = await asyncio.get_event_loop().run_in_executor(None, lambda: gemini_model.generate_content(prompt))
        if response and response.text:
            return response.text
        return await ask_fallback(prompt)
    except Exception as e:
        print(f"Gemini error: {e}")
        return await ask_fallback(prompt)

async def ask_fallback(prompt: str) -> str:
    global model_index
    for _ in range(len(FALLBACK_MODELS)):
        model = FALLBACK_MODELS[model_index % len(FALLBACK_MODELS)]
        model_index += 1
        if openrouter_client:
            try:
                resp = await openrouter_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=600,
                    temperature=0.4
                )
                if resp and resp.choices and resp.choices[0].message:
                    return resp.choices[0].message.content
            except:
                continue
    return "❌ ИИ временно недоступен"

async def translate_text(text: str) -> str:
    if any(ru in text for ru in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"):
        return text
    return await ask_gemini(f"Переведи на русский (только перевод): {text}")

async def gen_post(title: str, content: str) -> str:
    title_ru = await translate_text(title)
    prompt = f"""Ты Нико. Напиши пост о Формуле-1.

НОВОСТЬ: {title_ru}
ДЕТАЛИ: {content[:1000]}

ПРАВИЛА:
- Заголовок: <b>жирный</b>
- 3-5 абзацев
- Только факты
- В конце: #F1

ПОСТ:"""
    post = await ask_gemini(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

async def chat_reply(user_id: int, msg: str) -> str:
    memory = get_memory(user_id, 10)
    context = ""
    for m in memory[-5:]:
        context += f"Пользователь: {m['message']}\nНико: {m['response']}\n"
    prompt = f"""Ты Нико, эксперт по Формуле-1.
История диалога:
{context}
Пользователь: {msg}
Ответь кратко, по делу:"""
    answer = await ask_gemini(prompt)
    save_memory(user_id, msg, answer)
    return answer

async def search_f1(query: str) -> str:
    try:
        with DDGS() as ddgs:
            results = ddgs.text(f"{query} formula 1", max_results=3)
            context = ""
            for r in results:
                context += f"🔍 **{r.get('title', '')}**\n📝 {r.get('body', '')[:500]}\n🔗 {r.get('href', '')}\n\n"
            return context if context else "Ничего не найдено"
    except:
        return "Ошибка поиска"

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
    prompt = "Ты Нико. Напиши пост о Формуле-1. Заголовок жирным. 5-7 предложений."
    return clean_post(await ask_gemini(prompt)) + "\n\nRed Race | Подписаться"

async def post_on_topic(topic: str) -> str:
    prompt = f"Ты Нико. Напиши пост о Формуле-1 на тему: {topic}. Заголовок жирным. 4-6 предложений."
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
                            if is_fresh_news(entry):
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

async def monitor(callback):
    """Мониторинг RSS — собирает новости, но НЕ публикует автоматически"""
    last = {}
    pending_posts = []
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
                                if not is_fresh_news(entry):
                                    mark_posted(entry.get('title', ''), link)
                                    continue
                                text = await fetch_article(link)
                                content = text or entry.get('summary', '')[:500]
                                if not content or len(content) < 100:
                                    mark_posted(entry.get('title', ''), link)
                                    continue
                                post = await gen_post(entry.get('title', ''), content)
                                pending_posts.append({"post": post, "title": entry.get('title', ''), "link": link})
                                print(f"📰 Новая новость: {entry.get('title', '')[:50]}... (ждет публикации)")
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
