import asyncio
import os
import time
import random
import hashlib
import json
import re
from datetime import datetime, timedelta
import aiohttp
import feedparser
from search_engine import search_web

# === КОНФИГ ===
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"
MEMORY_FILE = "memory.json"
HASH_FILE = "posted_hashes.json"

# === RSS ИСТОЧНИКИ ===
RSS_SOURCES = [
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.planetf1.com/feed",
    "https://www.crash.net/f1/rss",
    "https://www.f1news.ru/export/news.xml"
]

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

# === МОДЕЛИ ИИ ===
CURRENT_MODEL = "gemini_35"

AVAILABLE_MODELS = {
    "gemini_35": {
        "id": "gemini-3.5-flash",
        "provider": "google",
        "name": "🚀 Gemini 3.5 Flash"
    },
    "gemini_20": {
        "id": "gemini-2.0-flash-exp",
        "provider": "google",
        "name": "🔥 Gemini 2.0 Flash"
    },
    "gemini_lite": {
        "id": "gemini-1.5-flash",
        "provider": "google",
        "name": "⚡ Gemini 1.5 Flash"
    },
    "openrouter": {
        "id": "openrouter/free",
        "provider": "openrouter",
        "name": "🌐 OpenRouter Free"
    },
    "nemotron": {
        "id": "nvidia/nemotron-3-super-120b-a12b:free",
        "provider": "openrouter",
        "name": "💪 NVIDIA Nemotron"
    },
    "gpt_oss": {
        "id": "openai/gpt-oss-120b:free",
        "provider": "openrouter",
        "name": "🎯 GPT-OSS-120B"
    }
}

def get_current_model():
    return AVAILABLE_MODELS.get(CURRENT_MODEL, AVAILABLE_MODELS["gemini_35"])

def get_current_model_id():
    return get_current_model()["id"]

def switch_model(model_key):
    global CURRENT_MODEL
    if model_key in AVAILABLE_MODELS:
        CURRENT_MODEL = model_key
        return True
    return False

# === GOOGLE API С RETRY ===
async def ask_google_with_retry(prompt: str, model_id: str, retries: int = 3) -> str:
    import google.generativeai as genai
    
    GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
    if not GEMINI_KEY:
        print("❌ GEMINI_API_KEY не найден")
        return None
    
    genai.configure(api_key=GEMINI_KEY)
    
    for attempt in range(retries):
        try:
            model = genai.GenerativeModel(model_id)
            response = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: model.generate_content(prompt)
            )
            if response and response.text:
                return response.text
            return None
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "Resource exhausted" in error_str:
                wait = (attempt + 1) * 2
                print(f"⚠️ Rate limit, ждем {wait} сек...")
                await asyncio.sleep(wait)
                continue
            elif "404" in error_str:
                print(f"❌ Модель {model_id} не найдена")
                return None
            else:
                print(f"❌ Ошибка Google API: {e}")
                if attempt == retries - 1:
                    return None
                await asyncio.sleep(1)
    return None

async def ask_openrouter_with_retry(prompt: str, model_id: str, retries: int = 2) -> str:
    import openai
    
    OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
    if not OPENROUTER_KEY:
        print("❌ OPENROUTER_API_KEY не найден")
        return None
    
    client = openai.AsyncOpenAI(
        api_key=OPENROUTER_KEY,
        base_url="https://openrouter.ai/api/v1"
    )
    
    for attempt in range(retries):
        try:
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.4
            )
            if resp and resp.choices:
                return resp.choices[0].message.content
        except Exception as e:
            print(f"❌ OpenRouter error: {e}")
            if attempt == retries - 1:
                return None
            await asyncio.sleep(1)
    return None

async def ask_gemini(prompt: str) -> str:
    model = get_current_model()
    
    if model["provider"] == "google":
        result = await ask_google_with_retry(prompt, model["id"])
        if result:
            return result
    
    if model["provider"] == "openrouter":
        result = await ask_openrouter_with_retry(prompt, model["id"])
        if result:
            return result
    
    fallback_models = ["gemini-1.5-flash", "gemini-2.0-flash-exp"]
    for fb_model in fallback_models:
        if fb_model != model["id"]:
            result = await ask_google_with_retry(prompt, fb_model)
            if result:
                return result
    
    return "❌ ИИ временно недоступен. Попробуй позже."

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

# === ОСНОВНЫЕ ФУНКЦИИ ===
async def chat_reply(user_id: int, message: str, use_search: bool = False) -> str:
    memory = get_memory(user_id, 10)
    context = ""
    for m in memory[-5:]:
        context += f"Пользователь: {m['message']}\nНико: {m['response']}\n"
    
    search_context = ""
    if use_search:
        try:
            search_result = await search_web(message, max_results=2)
            if search_result and "❌" not in search_result:
                search_context = f"\n\nДанные из интернета:\n{search_result[:1000]}\n"
        except Exception as e:
            print(f"Search error: {e}")
    
    prompt = f"""Ты Нико, гоночный инженер и эксперт по Формуле-1.
Год сейчас 2026.

История диалога:
{context}

{search_context}

Пользователь: {message}

Ответь кратко, по делу, без воды. Используй факты. Будь живым, дерзким."""
    
    answer = await ask_gemini(prompt)
    save_to_memory(user_id, message, answer)
    return answer

async def post_on_topic(topic: str) -> str:
    prompt = f"""Ты Нико. Напиши пост о Формуле-1 на тему: {topic}

Правила:
- Заголовок жирным шрифтом
- 4-6 предложений
- Только факты
- В конце добавь #F1

Пост:"""
    post = await ask_gemini(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

async def random_post() -> str:
    prompt = """Ты Нико. Напиши пост о Формуле-1 на любую актуальную тему.
Заголовок жирным шрифтом. 5-7 предложений. Добавь #F1 в конце."""
    post = await ask_gemini(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

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

async def morning_digest() -> str:
    news = []
    for src in RSS_SOURCES[:3]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(src, timeout=10) as resp:
                    if resp.status == 200:
                        feed = feedparser.parse(await resp.text())
                        for entry in feed.entries[:1]:
                            news.append(entry.get('title', ''))
        except Exception as e:
            print(f"RSS error: {e}")
    
    news_text = ""
    for i, title in enumerate(news[:5], 1):
        news_text += f"{i}. {title}\n"
    
    return f"""☀️ Доброе утро, RedRace!

📅 {datetime.now().strftime('%d.%m.%Y')}

🏆 Топ новостей дня:
{news_text}

📅 Ближайшие гонки:
• 7 июня — Монако
• 14 июня — Барселона

Red Race | Подписаться"""

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

def is_posted(title, link):
    h = hashlib.md5(f"{title}{link}".encode()).hexdigest()
    return h in posted_hashes

def mark_posted(title, link):
    h = hashlib.md5(f"{title}{link}".encode()).hexdigest()
    save_hash(h)

async def generate_post_from_news(title: str, content: str) -> str:
    prompt = f"""Ты Нико. Напиши пост о Формуле-1.

НОВОСТЬ: {title}
ДЕТАЛИ: {content[:1000]}

ПРАВИЛА:
- Заголовок жирным
- 3-5 абзацев
- Только факты
- В конце: #F1

ПОСТ:"""
    post = await ask_gemini(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

async def monitor():
    global pending_posts
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
                                post = await generate_post_from_news(
                                    entry.get('title', ''), 
                                    entry.get('summary', '')[:500]
                                )
                                pending_posts.append({
                                    "post": post, 
                                    "title": entry.get('title', ''), 
                                    "link": link
                                })
                                print(f"📰 Новая новость: {entry.get('title', '')[:50]}...")
            except Exception as e:
                print(f"Monitor error for {src}: {e}")
        await asyncio.sleep(60)

def get_pending_posts():
    return pending_posts

def clear_pending_posts():
    global pending_posts
    pending_posts = []

def set_pending_posts(posts):
    global pending_posts
    pending_posts = posts
