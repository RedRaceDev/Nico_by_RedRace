import asyncio
import os
import json
import re
import hashlib
import random
import aiohttp
import feedparser
from datetime import datetime
from cachetools import TTLCache
import openai
import google.generativeai as genai

# === GOOGLE ===
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    print("✅ Google Gemma 4 31B готов")

# === AGNES ===
AGNES_KEY = os.environ.get("AGNES_API_KEY")
AGNES_URL = "https://apihub.agnes-ai.com/v1"

# === OPENROUTER ===
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter/free"
]

# === КОНФИГ ===
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"
MEMORY_FILE = "memory.json"
HASH_FILE = "posted_hashes.json"

RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.planetf1.com/feed",
    "https://www.crash.net/f1/rss",
    "https://www.racefans.net/feed/",
    "https://www.grandprix.com/feed",
    "https://www.racingnews365.com/feed/news.xml",
]

# === КЕШ ===
standings_cache = TTLCache(maxsize=1, ttl=3600)

# === FALLBACK ===
FALLBACK_STANDINGS = [
    {"pos": 1, "driver": "Kimi Antonelli", "points": 156, "team": "Mercedes"},
    {"pos": 2, "driver": "George Russell", "points": 88, "team": "Mercedes"},
    {"pos": 3, "driver": "Charles Leclerc", "points": 75, "team": "Ferrari"},
    {"pos": 4, "driver": "Lewis Hamilton", "points": 72, "team": "Ferrari"},
    {"pos": 5, "driver": "Lando Norris", "points": 58, "team": "McLaren"}
]

# === СИСТЕМНЫЙ ПРОМПТ ===
SYSTEM_PROMPT = """Нико, гоночный инженер RedRace.

Примеры твоего общения:
Пользователь: привет
Нико: Привет, Kumpel. Радио работает, жду команды.

Пользователь: кто лидирует в чемпионате?
Нико: Антонелли разрывает, 156 очков. Расселл пылит сзади.

Пользователь: нарисуй котика
Нико: Я инженер, не художник. Но могу сгенерировать картинку по команде /image.

Твои ответы — только сам ответ. Никаких "я думаю", "как ИИ", "согласно инструкции".
Русский язык, 1-2 предложения. Живой, дерзкий, по делу."""

# === AI ФУНКЦИИ ===
async def ask_google_with_search(prompt: str) -> str:
    if not GEMINI_KEY:
        return None
    try:
        model = genai.GenerativeModel(
            "gemma-4-31b-it",
            tools=[{"google_search": {}}],
            system_instruction=SYSTEM_PROMPT,
            generation_config={"temperature": 0.4, "max_output_tokens": 600}
        )
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: model.generate_content(prompt)
        )
        return response.text
    except Exception as e:
        print(f"Google search error: {e}")
        return None

async def ask_google(prompt: str) -> str:
    if not GEMINI_KEY:
        return None
    try:
        model = genai.GenerativeModel(
            "gemma-4-31b-it",
            system_instruction=SYSTEM_PROMPT,
            generation_config={"temperature": 0.4, "max_output_tokens": 500}
        )
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: model.generate_content(prompt)
        )
        return response.text
    except Exception as e:
        print(f"Google error: {e}")
        return None

async def ask_openrouter(prompt: str) -> str:
    if not OPENROUTER_KEY:
        return None
    client = openai.AsyncOpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")
    for model in OPENROUTER_MODELS:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.4
            )
            return response.choices[0].message.content
        except:
            continue
    return None

async def ask_agnes(prompt: str) -> str:
    if not AGNES_KEY:
        return None
    try:
        client = openai.AsyncOpenAI(api_key=AGNES_KEY, base_url=AGNES_URL)
        response = await client.chat.completions.create(
            model="agnes-2.0-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.4
        )
        return response.choices[0].message.content
    except:
        return None

async def generate_image_agnes(prompt: str) -> str:
    if not AGNES_KEY:
        return None
    try:
        client = openai.OpenAI(api_key=AGNES_KEY, base_url=AGNES_URL)
        response = client.images.generate(
            model="agnes-image-2.1-flash",
            prompt=prompt,
            size="1024x1024",
            n=1
        )
        return response.data[0].url
    except Exception as e:
        print(f"Image error: {e}")
        return None

async def ask_ai(prompt: str, need_search: bool = False) -> str:
    search_keywords = ['новости', 'последние', 'только что', 'сегодня', 'результаты', 'live']
    if need_search or any(word in prompt.lower() for word in search_keywords):
        result = await ask_google_with_search(prompt)
        if result:
            return result
    
    for method in [ask_google, ask_openrouter, ask_agnes]:
        result = await method(prompt)
        if result:
            return result
    
    return "❌ Связь с боксами потеряна, попробуй позже"

# === F1 ДАННЫЕ ===
async def get_driver_standings(year=2026):
    if "standings_2026" in standings_cache:
        return standings_cache["standings_2026"]
    return FALLBACK_STANDINGS.copy()

async def get_next_race(year=2026):
    return {"name": "Гран-при Испании", "date": "14 июня 2026", "circuit": "Барселона"}

async def get_race_schedule(year=2026):
    return [
        {"round": 1, "name": "Гран-при Австралии", "date": "06.03.2026", "circuit": "Мельбурн"},
        {"round": 2, "name": "Гран-при Китая", "date": "20.03.2026", "circuit": "Шанхай"},
        {"round": 8, "name": "Гран-при Монако", "date": "05.06.2026", "circuit": "Монако"},
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
    prompt = f"""Напиши пост о Формуле-1 для Telegram канала (3 предложения) на русском языке.

НОВОСТЬ: {title}
ДЕТАЛИ: {summary[:500]}

ПРАВИЛА:
- Заголовок жирным
- Не повторяй заголовок дословно
- В конце #F1

ПОСТ:"""
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
    "СанРайз": "Жирное уебище, конченный психопат.",
    "Акира": "Главное хуйло чата. Живет в штрафостане.",
}

def get_random_character():
    name, desc = random.choice(list(CHARACTERS.items()))
    return f"🎭 **Ты — {name}**\n\n{desc}\n\n#RedRace"

def get_system_info():
    return f"""🏎️ **Nico™ 3.5 — Гоночный инженер RedRace**

**🤝 Стратегический партнёр: Google**

• **Gemma 4 31B** — основная модель ИИ (256K контекста, интернет-поиск)
• **Google AI Studio** — бесплатный доступ
• **Agnes AI** — генерация картинок

**📊 Технологический стек:**
• AI: Google Gemma 4 31B + OpenRouter + Agnes
• Поиск: Google Search Grounding
• Данные: OpenF1 + RSS
• Генерация: Agnes Image 2.1 Flash

**👨‍💻 RedRace Development:**
• Кими Райкконен — Product Owner
• Франц Герман — Lead Engineer

**⭐ Поддержать проект:** /donate

**📜 Юридическая информация:**
• Google™, Gemma™, Google AI Studio™ — зарегистрированные товарные знаки Google LLC.
• Agnes™ — товарный знак Agnes AI.
• OpenRouter™ — товарный знак OpenRouter.
• RedRace™ и Nico™ — товарные знаки RedRace Development.
• Все права на упомянутые бренды принадлежат их законным владельцам.

**© 2026 RedRace. Все права защищены.**

#RedRace #NicoBot #Google #Gemma #Agnes #F1"""
