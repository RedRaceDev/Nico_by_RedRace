import asyncio
import aiohttp
import feedparser
import hashlib
import json
import random
import re
from datetime import datetime
from duckduckgo_search import DDGS
from openai import AsyncOpenAI
import os

# === OpenRouter fallback ===
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
openrouter_client = None
if OPENROUTER_API_KEY:
    openrouter_client = AsyncOpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")

# === MCP News для BBC Sport ===
try:
    from mcp_news import get_sports_news
    MCP_AVAILABLE = True
except:
    MCP_AVAILABLE = False
    print("⚠️ mcp-news не установлен, BBC Sport недоступен")

# === RSS источники ===
RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.motorsport-magazin.com/rss",
    "https://www.formel1.de/rss/news/feed.xml",
    "https://www.the-race.com/feed/",
    "https://www.planetf1.com/feed",
    "https://www.gpblog.com/en/rss/news",
    "https://www.racefans.net/feed/",
    "https://www.crash.net/f1/rss",
    "https://www.grandprix247.com/feed/"
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
                json={"messages": messages, "model": "openai"},
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
    except:
        return "❌ Ошибка генерации"

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

# === Новости через BBC Sport ===
async def get_bbc_news():
    """Новости F1 через BBC Sport — не банит"""
    if not MCP_AVAILABLE:
        return []
    try:
        news = await get_sports_news(sport="formula1", limit=5)
        return news if news else []
    except:
        return []

# === Парсинг RSS ===
async def fetch_rss_news():
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
                                "published": entry.get('published', '')
                            })
            except:
                continue
    return news

# === F1 данные через sports-skills ===
async def get_f1_results(grand_prix: str, year: int = 2026) -> str:
    try:
        from sports_skills.fastf1 import get_race_results
        rounds = {"монако": 7, "монте-карло": 7, "майами": 6}
        round_num = rounds.get(grand_prix.lower(), 7)
        
        results = get_race_results(year=year, round=round_num)
        if results:
            text = f"🏁 **Гран-при {grand_prix} {year} — результаты**\n\n"
            for i, r in enumerate(results[:5], 1):
                text += f"{i}. {r.get('driver', 'Unknown')} ({r.get('team', '')})\n"
            return text
        return "Данные временно недоступны"
    except:
        return await search_web(f"результаты гонки {grand_prix} {year}")

# === Генерация поста ===
async def generate_post(topic: str = "") -> str:
    if topic:
        prompt = f"Напиши пост для Telegram-канала о Формуле-1 на тему: {topic}. Используй эмодзи, разбивай на абзацы. В конце добавь хештеги #F1."
    else:
        # Собираем новости из всех источников
        bbc_news = await get_bbc_news()
        rss_news = await fetch_rss_news()
        
        all_news = []
        for n in bbc_news[:2]:
            all_news.append(f"BBC: {n.get('title', '')}")
        for n in rss_news[:3]:
            all_news.append(f"{n.get('title', '')}")
        
        if all_news:
            news_text = "\n\n".join(all_news[:5])
            prompt = f"На основе этих новостей напиши пост для Telegram-канала о Формуле-1:\n\n{news_text}\n\nИспользуй эмодзи, разбивай на абзацы. В конце добавь хештеги #F1 #Новости."
        else:
            prompt = "Напиши интересный пост о Формуле-1 для Telegram-канала: последние новости, интриги, технические новинки. Используй эмодзи, разбивай на абзацы. В конце добавь хештеги #F1."
    
    return await ask_pollinations(prompt)

# === Генерация поста из конкретной новости ===
async def generate_post_from_news(title: str, summary: str, link: str) -> str:
    prompt = f"""Напиши пост для Telegram-канала о Формуле-1 на основе этой новости:

Заголовок: {title}
Содержание: {summary[:1000]}

Требования:
- Пиши как Нико — гоночный инженер, дерзкий, экспертный
- Разбивай на абзацы
- Используй эмодзи 🏎️
- В конце добавь хештеги #F1

Пост:"""
    return await ask_pollinations(prompt)

# === Чат с ИИ ===
async def chat_with_nico(user_message: str) -> str:
    system = "Ты — Нико, гоночный инженер и эксперт Формулы-1. Отвечай кратко, по делу, с характером. Используй эмодзи. Пиши на русском."
    return await ask_pollinations(user_message, system)

# === Календарь ===
async def get_calendar() -> str:
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
    bbc_news = await get_bbc_news()
    rss_news = await fetch_rss_news()
    
    news_text = ""
    for n in bbc_news[:2]:
        news_text += f"• **BBC**: {n.get('title', '')}\n"
    for n in rss_news[:2]:
        news_text += f"• **{n.get('title', '')}**\n"
    
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

# === Мониторинг RSS ===
async def monitor_rss(callback):
    """Постоянно мониторит RSS и вызывает callback при новых новостях"""
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
                                        # Получаем полный текст
                                        full_text = await fetch_article_text(latest.get('link', ''))
                                        summary = latest.get('summary', '')[:500]
                                        
                                        post = await generate_post_from_news(
                                            latest.get('title', ''),
                                            full_text[:1000] if full_text else summary,
                                            latest.get('link', '')
                                        )
                                        
                                        await callback(post, latest.get('title', ''), latest.get('link', ''))
            except Exception as e:
                print(f"RSS error {source}: {e}")
        
        await asyncio.sleep(60)

async def fetch_article_text(url: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                html = await resp.text()
                text = re.sub(r'<[^>]+>', ' ', html)
                text = re.sub(r'\s+', ' ', text)
                return text[:2000]
    except:
        return ""
