import asyncio
import aiohttp
import feedparser
import hashlib
import json
import random
import re
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

# === Sports Skills ===
try:
    from sports_skills.fastf1 import get_race_results, get_race_schedule, get_session_data
    from sports_skills.sports_news import get_news as get_sports_news
    SPORTS_SKILLS_AVAILABLE = True
    print("✅ sports-skills загружен")
except:
    SPORTS_SKILLS_AVAILABLE = False
    print("❌ sports-skills не загружен")

# === RSS источники (топ, не банят) ===
RSS_SOURCES = [
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.the-race.com/feed/",
    "https://www.planetf1.com/feed",
    "https://www.crash.net/f1/rss",
    "https://www.grandprix247.com/feed/",
    "https://www.formel1.de/rss/news/feed.xml",
    "https://www.motorsport-magazin.com/rss"
]

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

# === Pollinations AI (основной) ===
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
                timeout=30
            ) as resp:
                if resp.status == 200:
                    return await resp.text()
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

# === Поиск в интернете ===
async def search_web(query: str, max_results: int = 3) -> str:
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
            context = ""
            for r in results:
                context += f"🔍 **{r.get('title', '')}**\n"
                context += f"📝 {r.get('body', '')[:500]}\n"
                context += f"🔗 {r.get('href', '')}\n\n"
            return context if context else "Ничего не найдено"
    except Exception as e:
        return f"Ошибка поиска: {e}"

# === Парсинг статьи из HTML ===
async def fetch_article_text(url: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                    tag.decompose()
                text = soup.get_text()
                text = re.sub(r'\s+', ' ', text)
                return text[:1500]
    except Exception as e:
        print(f"Fetch error: {e}")
        return ""

# === Сбор новостей ===
async def fetch_news_from_rss():
    news = []
    async with aiohttp.ClientSession() as session:
        for url in RSS_SOURCES:
            try:
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        feed = feedparser.parse(await resp.text())
                        for entry in feed.entries[:3]:
                            news.append({
                                "title": entry.get('title', ''),
                                "link": entry.get('link', ''),
                                "summary": entry.get('summary', '')[:500],
                                "published": entry.get('published', ''),
                                "source": url.split('/')[2]
                            })
            except Exception as e:
                print(f"RSS error {url}: {e}")
    return news

async def fetch_news_from_sports_skills():
    if not SPORTS_SKILLS_AVAILABLE:
        return []
    try:
        news = get_sports_news(sport="F1", limit=5)
        return news if news else []
    except:
        return []

async def get_all_news():
    rss_news = await fetch_news_from_rss()
    sports_news = await fetch_news_from_sports_skills()
    all_news = rss_news + sports_news
    seen = set()
    unique_news = []
    for item in all_news:
        title = item.get('title', '')
        if title and title not in seen:
            seen.add(title)
            unique_news.append(item)
    return unique_news[:10]

# === Генерация поста ===
async def generate_post_from_news(title: str, summary: str, link: str) -> str:
    prompt = f"""Сделай пост на РУССКОМ языке в Telegram канал о Формуле-1.

НОВОСТЬ:
Заголовок: {title}
Содержание: {summary[:800]}

ЖЁСТКИЕ ПРАВИЛА:
1. ПИШИ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ
2. Не выдумывай факты — только то, что в новости
3. 3-5 предложений
4. Хештеги #F1 в конце
5. Без воды, по делу

ОТВЕТЬ ТОЛЬКО ПОСТОМ НА РУССКОМ:"""
    
    return await ask_pollinations(prompt)

async def generate_post_on_topic(topic: str) -> str:
    prompt = f"""Напиши пост на РУССКОМ языке в Telegram канал о Формуле-1 на тему: {topic}

ПРАВИЛА:
1. Только русский язык
2. Экспертный стиль, как у гоночного инженера
3. 4-6 предложений
4. Хештеги #F1 в конце

ПОСТ:"""
    return await ask_pollinations(prompt)

async def generate_random_post() -> str:
    prompt = """Напиши интересный пост о Формуле-1 для Telegram канала. 
Можешь написать о технике, стратегии, пилотах или последних новостях.
Пиши на русском, экспертным тоном, 5-7 предложений.
В конце добавь хештеги #F1.

ПОСТ:"""
    return await ask_pollinations(prompt)

# === Очистка поста ===
def clean_post(text: str) -> str:
    if len(text) > 1500:
        text = text[:1500]
    last_dot = text.rfind('.')
    if last_dot > len(text) - 100:
        text = text[:last_dot + 1]
    return text

def is_valid_post(text: str) -> bool:
    if len(text) < 50:
        return False
    if "aufmerksamkeit" in text.lower() or "f1-strafpunkte" in text.lower():
        return False
    return True

# === F1 данные ===
async def get_f1_results_2026(grand_prix: str) -> str:
    if not SPORTS_SKILLS_AVAILABLE:
        return await search_web(f"результаты гонки {grand_prix} 2026")
    
    rounds = {"монако": 7, "монте-карло": 7, "майами": 6}
    round_num = rounds.get(grand_prix.lower(), 7)
    
    try:
        results = get_race_results(year=2026, round=round_num)
        if results:
            text = f"🏁 **Гран-при {grand_prix} 2026 — результаты**\n\n"
            for i, r in enumerate(results[:5], 1):
                text += f"{i}. {r.get('driver', 'Unknown')} ({r.get('team', '')})\n"
            return text
        return "Данные временно недоступны"
    except:
        return await search_web(f"результаты гонки {grand_prix} 2026")

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
    news = await get_all_news()
    news_text = ""
    for n in news[:5]:
        news_text += f"• **{n.get('title', '')[:80]}**\n"
    
    quotes = [
        "«Если ты не идёшь на риск, ты не выиграешь» — Айртон Сенна",
        "«Гонки — это единственный вид спорта, где ты платишь миллионы, чтобы рисковать жизнью» — Фернандо Алонсо",
        "«Когда ты перестаёшь мечтать, ты перестаёшь жить» — Михаэль Шумахер"
    ]
    
    digest = f"☀️ **Доброе утро, Red Race!**\n\n"
    digest += f"📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
    digest += f"🏆 **Топ новостей:**\n{news_text}\n"
    digest += f"📅 **Ближайшие гонки:**\n• 7 июня — Монако\n• 14 июня — Барселона\n\n"
    digest += f"💭 {random.choice(quotes)}\n\n"
    digest += f"<i>Хорошего дня! 🏁</i>"
    
    return digest

# === Чат с ИИ ===
async def chat_with_nico(user_message: str) -> str:
    system = "Ты — Нико, гоночный инженер и эксперт Формулы-1. Отвечай кратко, по делу, с характером. Используй эмодзи. Пиши на русском."
    return await ask_pollinations(user_message, system)

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
                                        if is_valid_post(post):
                                            await callback(post, latest.get('title', ''), latest.get('link', ''))
                                        else:
                                            print(f"⚠️ Пост отфильтрован: {latest.get('title', '')}")
            except Exception as e:
                print(f"RSS error {source}: {e}")
        
        await asyncio.sleep(60)
