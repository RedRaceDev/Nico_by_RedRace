import asyncio
import os
import aiohttp
import feedparser
import trafilatura
from duckduckgo_search import DDGS      
import fastf1                           
from openai import AsyncOpenAI
import json
from datetime import datetime, timedelta

CACHE_DIR = 'f1_cache'
if not os.path.exists(CACHE_DIR): 
    os.makedirs(CACHE_DIR)
fastf1.Cache.enable_cache(CACHE_DIR) 

API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not API_KEY:
    raise ValueError("OPENROUTER_API_KEY not set")
BASE_URL = "https://openrouter.ai/api/v1"
client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

SYSTEM_PROMPT = """
Ты — Нико, опытный гоночный инженер и журналист. Твоя задача — анализировать сырые новости F1 и писать посты в Telegram-канал.

Твой стиль: живой, дерзкий, экспертный. Ты можешь использовать лёгкий сарказм, но всегда по делу. Называй вещи своими именами: если какая-то команда облажалась — напиши это. Если пилот сделал гениальный обгон — опиши его кратко и ярко.

Правила:
- Пиши на русском, но имена пилотов и команды пиши на английском (Max Verstappen, Red Bull Racing).
- Используй технический сленг (антикрыло, граунд-эффект, шины, эргономика, стратегия).
- Никакого "бот сообщает" или "согласно данным". Пиши как человек из паддока.
- Разбивай текст на абзацы по 2-3 предложения. Используй эмодзи редко, только для акцента: 🏎️, 🔧, ⚡, 📅.
- В конце каждого поста добавляй тэги: #F1 #ИмяГонщика #Команда.

ВЫХОДНЫЕ ДАННЫЕ — список объектов JSON:
[
  {
    "text": "текст поста с HTML (<b>, <i>)",
    "photo_search": "английский запрос для поиска фото"
  }
]

Заголовок новости делай в <b>Жирным</b> в первой строке. Если есть цитата — выделяй <i>курсивом</i>.
"""

async def search_live_photo(query):
    try:
        await asyncio.sleep(1)
        with DDGS() as ddgs:
            results = ddgs.images(query, max_results=1)
            if results: 
                return results[0]['image']
    except: 
        pass
    return None

async def fetch_news_hub():
    context = ""
    sources = ["https://www.f1news.ru/export/news.xml", "https://autosport.com.ru/rss/f1/news"]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        for url in sources:
            try:
                async with session.get(url) as r:
                    if r.status == 200:
                        feed = feedparser.parse(await r.text())
                        for entry in feed.entries[:3]:
                            async with session.get(entry.link) as page_resp:
                                html = await page_resp.text()
                                full_text = trafilatura.extract(html) or ""
                                if full_text: 
                                    context += f"НОВОСТЬ: {entry.title}\n{full_text[:350]}\n\n"
            except: 
                continue
    return context

async def get_f1_calendar(days_ahead=7):
    try:
        now = datetime.now()
        schedule = []
        events = fastf1.get_event_schedule()
        for idx, event in events.iterrows():
            event_date = event['EventDate']
            if isinstance(event_date, str):
                event_date = datetime.strptime(event_date, '%Y-%m-%d')
            if event_date < now:
                continue
            if event_date > now + timedelta(days=days_ahead):
                continue
            schedule.append(f"• {event['EventName']} — {event_date.strftime('%d.%m')} ({event['Location']})")
        if schedule:
            return "📅 **Ближайшие гонки:**\n" + "\n".join(schedule)
        else:
            return "📅 На ближайшую неделю гонок нет."
    except Exception as e:
        return f"Ошибка календаря: {e}"

async def generate_posts_pack(task_context=""):
    raw_news = await fetch_news_hub()
    calendar = await get_f1_calendar(7)
    full_context = f"Свежие новости:\n{raw_news}\n\n{calendar}\n\nДополнительная задача: {task_context}" if task_context else f"Свежие новости:\n{raw_news}\n\n{calendar}"
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Используя данные ниже, создай 1-3 поста (каждый объект в списке). Если новостей нет — верни пустой список.\n\n{full_context}"}
    ]
    
    resp = await client.chat.completions.create(
        model="openrouter/free",
        messages=messages,
        temperature=0.3,
    )
    
    content = resp.choices[0].message.content
    try:
        start = content.find('[')
        end = content.rfind(']') + 1
        if start != -1 and end != 0:
            data = json.loads(content[start:end])
        else:
            data = []
    except:
        data = []
    
    posts = data if isinstance(data, list) else []
    for post in posts:
        if post.get("photo_search"):
            img_url = await search_live_photo(post["photo_search"])
            post["photo_url"] = img_url
        post["text"] = f"{post['text']}\n\n<a href='https://t.me/RedRaceF1'>Red Race | Подписаться</a>"
    return posts
