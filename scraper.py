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

# === КЭШ FASTF1 ===
CACHE_DIR = 'f1_cache'
if not os.path.exists(CACHE_DIR): 
    os.makedirs(CACHE_DIR)
fastf1.Cache.enable_cache(CACHE_DIR) 

# === OPENROUTER ===
API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not API_KEY:
    raise ValueError("OPENROUTER_API_KEY not set")
BASE_URL = "https://openrouter.ai/api/v1"
client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

# === РАСШИРЕННЫЕ RSS ИСТОЧНИКИ ===
RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
    "https://autosport.com.ru/rss/f1/news",
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.planetf1.com/feed",
    "https://www.gpblog.com/en/rss/news",
    "https://www.racefans.net/feed/",
    "https://www.crash.net/f1/rss",
    "https://www.grandprix247.com/feed/",
    "https://www.the-race.com/feed/"
]

# === ПРОМПТ ДЛЯ ГЕНЕРАЦИИ ПОСТОВ ===
SYSTEM_PROMPT = """Ты — Нико, опытный гоночный инженер и журналист.

Твоя задача — анализировать сырые новости F1 и писать посты в Telegram-канал.

СТИЛЬ: живой, дерзкий, экспертный. Называй вещи своими именами: если команда облажалась — напиши это. Если пилот сделал гениальный обгон — опиши.

ПРАВИЛА:
- Пиши на русском, имена пилотов и команды на английском (Max Verstappen, Red Bull Racing)
- Используй технический сленг (антикрыло, граунд-эффект, шины, эргономика, стратегия)
- Никакого "бот сообщает" или "согласно данным"
- Разбивай текст на абзацы по 2-3 предложения
- Эмодзи редко: 🏎️, 🔧, ⚡, 📅
- В конце каждого поста тэги: #F1 #ИмяГонщика #Команда

ВЫХОДНЫЕ ДАННЫЕ — список объектов JSON:
[
  {
    "text": "текст поста с HTML (<b>, <i>)",
    "photo_search": "английский запрос для поиска фото"
  }
]

Заголовок новости — в <b>Жирном</b> в первой строке. Цитату выделяй <i>курсивом</i>.
"""

# === ПРОМПТ ДЛЯ ЧАТ-БОТА ===
CHAT_SYSTEM_PROMPT = """Ты — Нико, гоночный инженер и эксперт Формулы-1.

ТВОЯ РОЛЬ:
- Если вопрос про F1, технологии, гонки, пилотов, историю — дай развёрнутый экспертный ответ
- Если просят сделать пост — скажи, что нужно написать "сделай пост на тему ..."
- Если вопрос не про F1 — вежливо скажи, что ты эксперт только по Формуле-1
- Если просто здороваются — ответь дружелюбно

СТИЛЬ: живой, дерзкий, профессиональный. Будь полезным, но с характером. Пиши на русском, имена на английском.

ОТВЕЧАЙ КРАТКО И ПО ДЕЛУ (2-4 предложения, если не просят развёрнуто)."""

# === ФУНКЦИЯ ПОИСКА ФОТО ===
async def search_live_photo(query):
    try:
        await asyncio.sleep(0.5)
        with DDGS() as ddgs:
            results = ddgs.images(query, max_results=1)
            if results: 
                return results[0]['image']
    except: 
        pass
    return None

# === ПАРСИНГ НОВОСТЕЙ ===
async def fetch_news_hub():
    context = ""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        for url in RSS_SOURCES:
            try:
                async with session.get(url) as r:
                    if r.status == 200:
                        feed = feedparser.parse(await r.text())
                        for entry in feed.entries[:2]:
                            async with session.get(entry.link) as page_resp:
                                html = await page_resp.text()
                                full_text = trafilatura.extract(html) or ""
                                if full_text: 
                                    context += f"📰 {entry.title}\n{full_text[:500]}\n\n"
            except Exception as e:
                print(f"RSS error {url}: {e}")
                continue
    return context if context else "Нет свежих новостей."

# === КАЛЕНДАРЬ F1 (FASTF1) ===
async def get_f1_calendar(days_ahead=14):
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
            return "📅 На ближайшие две недели гонок нет."
    except Exception as e:
        return f"Ошибка календаря: {e}"

# === ЧАТ С ИИ ===
async def chat_with_nico(user_message: str) -> str:
    """Нико отвечает на вопросы как эксперт"""
    try:
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]
        
        resp = await client.chat.completions.create(
            model="openrouter/free",
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"❌ Ошибка связи с ИИ: {e}\nПопробуй ещё раз позже."

# === ГЕНЕРАЦИЯ ПОСТОВ ===
async def generate_posts_pack(task_context=""):
    raw_news = await fetch_news_hub()
    calendar = await get_f1_calendar(7)
    
    # Формируем контекст в зависимости от задачи
    if task_context and ("пост" in task_context.lower() or "сделай" in task_context.lower()):
        # Пользователь попросил пост на конкретную тему
        full_context = f"ПОЛЬЗОВАТЕЛЬ ПОПРОСИЛ СДЕЛАТЬ ПОСТ НА ТЕМУ: {task_context}\n\n{calendar}\n\nИспользуй свои знания о F1, чтобы создать интересный пост."
    else:
        # Обычный сбор новостей
        full_context = f"Свежие новости:\n{raw_news}\n\n{calendar}"
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Используя данные ниже, создай 1-3 поста. Если новостей нет — создай аналитический пост на основе своих знаний.\n\n{full_context}"}
    ]
    
    resp = await client.chat.completions.create(
        model="openrouter/free",
        messages=messages,
        temperature=0.4,
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
