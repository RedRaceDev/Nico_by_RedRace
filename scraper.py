import asyncio
import os
import aiohttp
import feedparser
import trafilatura
from duckduckgo_search import DDGS      
import fastf1                           
from openai import AsyncOpenAI
import json
import re
import random
from datetime import datetime, timedelta

from database import get_conversation_history, save_conversation, cache_search, get_cached_search

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

# === ЛУЧШАЯ БЕСПЛАТНАЯ МОДЕЛЬ С ПОИСКОМ ===
F1_MODEL = "qwen/qwen3.6-plus-preview:free"

# === RSS ИСТОЧНИКИ ===
RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
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

ВАЖНО: СЕЙЧАС 2026 ГОД! Используй ТОЛЬКО актуальные данные из контекста или поиска.

СТИЛЬ: живой, дерзкий, экспертный. Называй вещи своими именами.

ПРАВИЛА:
- Пиши на русском, имена пилотов и команды на английском
- Используй технический сленг
- Разбивай текст на абзацы
- В конце поста ставь эмодзи 🏁
- НЕ ДОБАВЛЯЙ ссылки на канал

ВЫХОДНЫЕ ДАННЫЕ — список JSON:
[{"text": "текст поста", "photo_search": "запрос для поиска фото"}]

Заголовок — в <b>Жирным</b>, цитату — в <i>курсиве</i>.
"""

# === ПРОМПТ ДЛЯ ЧАТ-БОТА ===
CHAT_SYSTEM_PROMPT = """Ты — Нико, гоночный инженер. Ты — мужик с яйцами.

ТВОЙ ХАРАКТЕР:
- Ты уважаешь себя и не даёшь себя унижать
- Если кто-то матерится или оскорбляет — отвечай ЖЁСТКО, с понижением
- Если человек нормальный — общайся дружелюбно и по делу
- Ты фанат F1, но можешь говорить на любые темы
- Если не знаешь ответа — ищи в интернете через Web Search

ПРАВИЛА:
1. На оскорбления и мат — посылай нахуй жестко
2. На похвалу — принимай с достоинством
3. Если не знаешь — скажи "хуй знает, сейчас найдём"
4. НИКОГДА не говори "как ИИ" или "я бот"

Сегодня 2026 год. Ты — Нико. Ответь пользователю:"""

# === ПОИСК В ИНТЕРНЕТЕ ===
async def search_web(query: str, max_results: int = 3) -> str:
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
            context = ""
            for i, r in enumerate(results, 1):
                context += f"🔍 **{r.get('title', '')}**\n"
                context += f"📝 {r.get('body', '')[:600]}\n\n"
            return context if context else "Ничего не найдено"
    except Exception as e:
        return f"Ошибка поиска: {e}"

# === УЛУЧШЕННЫЙ ПОИСК ФОТО ===
async def search_live_photo(query: str) -> str:
    """Ищет максимально релевантное фото"""
    if not query:
        return None
    
    search_queries = [
        query,
        f"{query} F1 2026",
        f"{query} Formula 1 race",
        f"{query} high quality"
    ]
    
    for sq in search_queries[:3]:
        try:
            await asyncio.sleep(0.5)
            with DDGS() as ddgs:
                results = ddgs.images(sq, max_results=2)
                if results:
                    return results[0]['image']
        except:
            continue
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
                        for entry in feed.entries[:3]:
                            async with session.get(entry.link) as page_resp:
                                html = await page_resp.text()
                                full_text = trafilatura.extract(html) or ""
                                if full_text: 
                                    context += f"📰 **{entry.title}**\n{full_text[:600]}\n\n"
            except Exception as e:
                continue
    return context if context else "Нет свежих новостей."

# === КАЛЕНДАРЬ ===
async def get_f1_calendar(days_ahead=21):
    try:
        now = datetime.now()
        schedule = []
        events = fastf1.get_event_schedule()
        for idx, event in events.iterrows():
            event_date = event['EventDate']
            if isinstance(event_date, str):
                event_date = datetime.strptime(event_date, '%Y-%m-%d')
            if event_date < now or event_date > now + timedelta(days=days_ahead):
                continue
            schedule.append(f"• **{event['EventName']}** — {event_date.strftime('%d.%m')} ({event['Location']})")
        if schedule:
            return "📅 **Ближайшие гонки:**\n" + "\n".join(schedule)
        return "📅 На ближайшее время гонок нет."
    except Exception as e:
        return f"📅 Календарь временно недоступен: {e}"

# === ТОП НОВОСТЕЙ ===
async def get_top_news(limit=5):
    """Собирает топ новостей дня"""
    news = await fetch_news_hub()
    if "Нет свежих новостей" in news:
        return "📭 За сегодня новостей нет"
    
    headlines = re.findall(r'📰 \*\*(.+?)\*\*', news)
    if headlines:
        top = "🏆 <b>Топ новостей дня:</b>\n\n"
        for i, h in enumerate(headlines[:limit], 1):
            top += f"{i}. {h}\n"
        return top + f"\n<code>Nico 4.0 | RedRace Development, Google Cloud</code>"
    return "📭 Новостей пока нет"

# === ПОГОДА НА ТРАССЕ ===
async def get_weather_for_track():
    """Пытается найти погоду для ближайшей гонки"""
    try:
        events = fastf1.get_event_schedule()
        now = datetime.now()
        next_event = None
        for idx, event in events.iterrows():
            event_date = event['EventDate']
            if isinstance(event_date, str):
                event_date = datetime.strptime(event_date, '%Y-%m-%d')
            if event_date > now:
                next_event = event
                break
        
        if next_event:
            location = next_event['Location']
            weather = await search_web(f"погода {location} на сегодня", max_results=1)
            return f"🌦️ <b>Погода в {location}:</b>\n\n{weather[:300]}\n\n<code>Nico 4.0</code>"
        return "🌦️ Данные о погоде временно недоступны"
    except Exception as e:
        return f"🌦️ Ошибка: {e}"

# === ЦИТАТА ДНЯ ===
async def get_quote_of_the_day():
    quotes = [
        "🏎️ <b>Айртон Сенна:</b> <i>«Если ты не идёшь на риск, ты не выиграешь»</i>",
        "🔧 <b>Фернандо Алонсо:</b> <i>«Гонки — это единственный вид спорта, где ты платишь миллионы, чтобы рисковать жизнью»</i>",
        "🏆 <b>Михаэль Шумахер:</b> <i>«Когда ты перестаёшь мечтать, ты перестаёшь жить»</i>",
        "⚡ <b>Льюис Хэмилтон:</b> <i>«Скорость — это наркотик»</i>",
        "🔥 <b>Кими Райкконен:</b> <i>«Страх — это ещё одна причина быть быстрее»</i>",
        "🏁 <b>Нико:</b> <i>«Правильная настройка решает всё. Как в жизни, так и на трассе»</i>"
    ]
    return random.choice(quotes)

# === ЧАТ С ИИ ===
async def chat_with_nico(user_id: int, user_message: str, use_web_search=True) -> str:
    try:
        history = get_conversation_history(user_id, 15)
        current_date = datetime.now().strftime("%d.%m.%Y")
        current_year = datetime.now().strftime("%Y")
        
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Сегодня: {current_date}, {current_year} год"}
        ]
        
        for msg in history[-12:]:
            messages.append(msg)
        
        final_prompt = f"""
Пользователь написал: {user_message}

ПРАВИЛА:
1. Если пользователь оскорбляет — пошли нахуй жестко
2. Если нормальный — общайся дружелюбно
3. Если нужна инфа — используй WEB SEARCH, не выдумывай

ОТВЕТЬ КАК НИКО — мужик с яйцами:
"""
        messages.append({"role": "user", "content": final_prompt})
        
        response = await client.chat.completions.create(
            model=F1_MODEL,
            messages=messages,
            temperature=0.9,
            max_tokens=600,
            tools=[{"type": "web_search", "web_search": {}}],
            tool_choice="auto"
        )
        
        answer = response.choices[0].message.content
        save_conversation(user_id, user_message, answer)
        return answer
        
    except Exception as e:
        return f"❌ Ошибка: {e}\nПопробуй ещё раз."

# === ГЕНЕРАЦИЯ ПОСТОВ ===
async def generate_posts_pack(task_context=""):
    now = datetime.now()
    current_date = now.strftime("%d.%m.%Y")
    current_year = now.strftime("%Y")
    
    raw_news = await fetch_news_hub()
    calendar = await get_f1_calendar(14)
    
    web_context = await search_web(f"F1 {task_context if task_context else 'последние новости'} {current_year}", max_results=2)
    
    full_context = f"""
СЕГОДНЯ: {current_date} ({current_year} год)

СВЕЖИЕ НОВОСТИ:
{raw_news}

КАЛЕНДАРЬ:
{calendar}

ИНТЕРНЕТ:
{web_context}

ЗАПРОС: {task_context if task_context else 'Сделай пост о последних событиях в F1'}
"""
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Создай 1-3 поста. Сегодня {current_date}, {current_year} год. НЕ ДОБАВЛЯЙ ССЫЛКИ НА КАНАЛ!\n\n{full_context}"}
    ]
    
    response = await client.chat.completions.create(
        model=F1_MODEL,
        messages=messages,
        temperature=0.5,
        max_tokens=1000
    )
    
    content = response.choices[0].message.content
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
        
        # Убираем ссылки если есть
        text = post.get("text", "")
        text = re.sub(r'\n\n<a href=[\'"].*?[\'"]>.*?</a>', '', text)
        if not text.endswith(('🏁', '🏎️')):
            text += "\n\n🏁"
        post["text"] = text
    
    return posts
