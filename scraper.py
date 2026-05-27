import asyncio
import os
import aiohttp
import feedparser
import trafilatura
from duckduckgo_search import DDGS
from openai import AsyncOpenAI
import json
import re
import random
import hashlib
from datetime import datetime, timedelta

from database import get_conversation_history, save_conversation

# === OPENROUTER ===
API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not API_KEY:
    raise ValueError("OPENROUTER_API_KEY not set")
BASE_URL = "https://openrouter.ai/api/v1"
client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

# === ГЛОБАЛЬНАЯ ПЕРЕМЕННАЯ ДЛЯ ВЫБРАННОЙ МОДЕЛИ ===
_selected_model = None

def set_selected_model(model_name):
    global _selected_model
    _selected_model = model_name
    print(f"✅ Модель установлена: {model_name}")

def get_selected_model():
    return _selected_model

# === СПИСОК МОДЕЛЕЙ ===
FREE_MODELS = [
    "openrouter/free",
    "qwen/qwen3.6-plus-preview:free",
    "qwen/qwen3.7-max:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "deepseek/deepseek-v4-flash:free"
]

# === КЭШ ДЛЯ ПРЕДОТВРАЩЕНИЯ ДУБЛЕЙ ===
posted_hashes = set()
POSTED_HISTORY_FILE = "posted_history.txt"

def load_posted_history():
    global posted_hashes
    if os.path.exists(POSTED_HISTORY_FILE):
        with open(POSTED_HISTORY_FILE, 'r') as f:
            posted_hashes = set(line.strip() for line in f)

def save_post_hash(post_hash):
    global posted_hashes
    posted_hashes.add(post_hash)
    with open(POSTED_HISTORY_FILE, 'a') as f:
        f.write(post_hash + '\n')

def is_already_posted(text):
    post_hash = hashlib.md5(text[:200].encode()).hexdigest()
    return post_hash in posted_hashes

# === RSS ИСТОЧНИКИ ===
RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
    "https://www.the-race.com/feed/",
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.motorsport-total.com/rss.xml",
    "https://www.formel1.de/rss/news/feed.xml",
    "https://www.planetf1.com/feed",
    "https://www.gpblog.com/en/rss/news",
    "https://www.racefans.net/feed/",
    "https://www.crash.net/f1/rss",
    "https://www.grandprix247.com/feed/"
]

# === ПРОМПТЫ ===
SYSTEM_PROMPT = """Ты — Нико, гоночный инженер.

Твой стиль: живой, дерзкий, экспертный.

ЖЁСТКИЕ ПРАВИЛА ФОРМАТИРОВАНИЯ:
1. ЗАПРЕЩЕНЫ символы в тексте поста: *, **, __, _
2. Используй ТОЛЬКО HTML теги: <b>жирный</b> и <i>курсив</i>
3. Заголовок новости — в <b>Жирным</b> в первой строке
4. Цитаты — в <i>курсиве</i>
5. Хештеги пиши через # — разрешено
6. Обязательно разбивай текст на абзацы по 2-3 предложения

ВЫХОДНЫЕ ДАННЫЕ — список JSON:
[
  {
    "text": "текст поста с HTML и хештегами",
    "photo_search": "запрос для фото"
  }
]"""

CHAT_SYSTEM_PROMPT = """Ты — Нико. Если оскорбляют — пошли нахуй. Если нормально — отвечай по делу. Сегодня 2026 год."""

# === АВТО-ПЕРЕКЛЮЧЕНИЕ МОДЕЛЕЙ ===
working_models = []
current_model_index = 0
last_model_check = 0

async def get_working_model():
    global working_models, current_model_index, last_model_check, _selected_model
    
    if _selected_model:
        return _selected_model
    
    now = datetime.now().timestamp()
    
    if not working_models or (now - last_model_check) > 300:
        working_models = []
        for model in FREE_MODELS:
            try:
                test_response = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=3
                )
                if test_response and test_response.choices:
                    working_models.append(model)
                    print(f"✅ {model}")
            except:
                print(f"❌ {model}")
        last_model_check = now
        if not working_models:
            working_models = ["openrouter/free"]
    
    model = working_models[current_model_index % len(working_models)]
    current_model_index += 1
    return model

# === ФОРМАТИРОВАНИЕ ТЕКСТА ===
def format_post_text(text: str) -> str:
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'\*', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    if '#F1' not in text:
        text += '\n\n#F1 #Nico'
    
    return text

# === ПОИСК (без ИИ) ===
async def search_web(query: str, max_results: int = 3) -> str:
    """Чистый поиск без ИИ — возвращает только результаты"""
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
            context = ""
            for i, r in enumerate(results, 1):
                context += f"🔍 **{r.get('title', '')}**\n"
                context += f"📝 {r.get('body', '')[:500]}\n"
                context += f"🔗 {r.get('href', '')}\n\n"
            return context if context else "Ничего не найдено"
    except Exception as e:
        return f"Ошибка поиска: {e}"

async def search_news(query: str) -> str:
    """Поиск новостей без ИИ"""
    try:
        with DDGS() as ddgs:
            results = ddgs.news(query, max_results=4)
            context = ""
            for r in results:
                context += f"📰 **{r.get('title', '')}**\n"
                if r.get('date'):
                    context += f"📅 {r.get('date')}\n"
                context += f"📝 {r.get('body', '')[:400]}\n"
                context += f"🔗 {r.get('url', '')}\n\n"
            return context if context else "Новостей не найдено"
    except Exception as e:
        return f"Ошибка поиска: {e}"

async def smart_search(query: str) -> str:
    """Умный поиск — выбирает новости или обычный поиск"""
    if any(word in query.lower() for word in ["новости", "что случилось", "последние"]):
        return await search_news(query)
    return await search_web(query)

async def search_live_photo(query: str) -> str:
    if not query:
        return None
    try:
        with DDGS() as ddgs:
            results = ddgs.images(query, max_results=2)
            if results:
                return results[0]['image']
    except:
        pass
    return None

# === КАЛЕНДАРЬ ===
async def get_f1_calendar(days_ahead=21):
    races_2026 = [
        {"name": "Гран-при Австралии", "date": "2026-03-08", "location": "Melbourne"},
        {"name": "Гран-при Китая", "date": "2026-03-15", "location": "Shanghai"},
        {"name": "Гран-при Японии", "date": "2026-03-29", "location": "Suzuka"},
        {"name": "Гран-при Майами", "date": "2026-05-03", "location": "Miami"},
        {"name": "Гран-при Канады", "date": "2026-05-24", "location": "Montreal"},
        {"name": "Гран-при Монако", "date": "2026-06-07", "location": "Monte Carlo"},
        {"name": "Гран-при Барселоны", "date": "2026-06-14", "location": "Barcelona"},
        {"name": "Гран-при Австрии", "date": "2026-06-28", "location": "Spielberg"},
        {"name": "Гран-при Великобритании", "date": "2026-07-05", "location": "Silverstone"},
        {"name": "Гран-при Бельгии", "date": "2026-07-19", "location": "Spa-Francorchamps"},
        {"name": "Гран-при Венгрии", "date": "2026-07-26", "location": "Budapest"},
        {"name": "Гран-при Нидерландов", "date": "2026-08-23", "location": "Zandvoort"},
        {"name": "Гран-при Италии", "date": "2026-09-06", "location": "Monza"},
        {"name": "Гран-при Испании (Мадрид)", "date": "2026-09-13", "location": "Madrid"},
        {"name": "Гран-при Азербайджана", "date": "2026-09-26", "location": "Baku"},
        {"name": "Гран-при Сингапура", "date": "2026-10-11", "location": "Singapore"},
        {"name": "Гран-при США (Остин)", "date": "2026-10-25", "location": "Austin"},
        {"name": "Гран-при Мексики", "date": "2026-11-01", "location": "Mexico City"},
        {"name": "Гран-при Бразилии", "date": "2026-11-08", "location": "Sao Paulo"},
        {"name": "Гран-при Лас-Вегаса", "date": "2026-11-21", "location": "Las Vegas"},
        {"name": "Гран-при Катара", "date": "2026-11-29", "location": "Lusail"},
        {"name": "Гран-при Абу-Даби", "date": "2026-12-06", "location": "Yas Marina"}
    ]
    now = datetime.now()
    schedule = []
    for race in races_2026:
        race_date = datetime.strptime(race["date"], '%Y-%m-%d')
        if race_date >= now and race_date <= now + timedelta(days=days_ahead):
            schedule.append(f"• **{race['name']}** — {race_date.strftime('%d.%m')}")
    return "📅 **Ближайшие гонки:**\n" + "\n".join(schedule[:5]) if schedule else "📅 На ближайшее время гонок нет."

# === УТРЕННИЙ ДАЙДЖЕСТ ===
async def generate_morning_digest():
    top_news = await get_top_news(5)
    calendar = await get_f1_calendar(14)
    quotes = [
        "🏎️ **Сенна:** *«Если не идёшь на риск — не выиграешь»*",
        "🔧 **Алонсо:** *«Гонки — это риск жизнью за миллионы»*",
        "🏆 **Шумахер:** *«Перестал мечтать — перестал жить»*"
    ]
    quote = random.choice(quotes)
    
    digest = f"☀️ <b>Доброе утро, Red Race!</b>\n\n"
    digest += f"📅 <b>{datetime.now().strftime('%d.%m.%Y')}</b>\n\n"
    digest += f"{top_news}\n\n"
    digest += f"{calendar}\n\n"
    digest += f"{quote}\n\n"
    digest += f"<i>Хорошего дня! 🏁</i>\n\n"
    digest += f"<code>Nico 7.0 | Code by: RedRace Development</code>"
    return digest

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
                                if full_text and not is_already_posted(full_text[:200]):
                                    context += f"📰 **{entry.title}**\n{full_text[:500]}\n\n"
            except:
                continue
    return context if context else "Нет свежих новостей."

async def get_top_news(limit=5):
    news = await fetch_news_hub()
    if "Нет свежих новостей" in news:
        return "📭 За сегодня новостей нет"
    headlines = re.findall(r'📰 \*\*(.+?)\*\*', news)
    if headlines:
        top = "🏆 **Топ новостей дня:**\n\n"
        for i, h in enumerate(headlines[:limit], 1):
            top += f"{i}. {h}\n"
        return top
    return "📭 Новостей пока нет"

async def get_last_race_result():
    return await smart_search("последняя гонка F1 результаты 2026")

async def get_weather_for_track():
    return await search_web("погода Miami май 2026", max_results=1)

async def get_quote_of_the_day():
    quotes = [
        "🏎️ **Сенна:** *«Если не идёшь на риск — не выиграешь»*",
        "🔧 **Алонсо:** *«Гонки — это риск жизнью за миллионы»*"
    ]
    return random.choice(quotes)

async def get_interesting_fact():
    facts = [
        "🏎️ Самый быстрый пит-стоп — 1.82 секунды (Red Bull, 2019)",
        "🔧 Шина F1 весит около 10 кг, давление до 25 PSI"
    ]
    return random.choice(facts)

# === ЧАТ С ИИ ===
async def chat_with_nico(user_id: int, user_message: str, use_web_search=True) -> str:
    try:
        history = get_conversation_history(user_id, 15)
        web_context = ""
        if use_web_search and len(user_message) > 5:
            web_context = await smart_search(f"F1 {user_message}")
        
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Сегодня: {datetime.now().strftime('%d.%m.%Y')}"}
        ]
        for msg in history[-10:]:
            messages.append(msg)
        messages.append({"role": "user", "content": f"Вопрос: {user_message}\n\nИнтернет:\n{web_context}\n\nОтветь как Нико:"})
        
        model = await get_working_model()
        response = await client.chat.completions.create(
            model=model, messages=messages, temperature=0.9, max_tokens=600
        )
        answer = response.choices[0].message.content
        save_conversation(user_id, user_message, answer)
        return answer
    except Exception as e:
        return f"❌ Ошибка: {e}"

# === ГЕНЕРАЦИЯ ПОСТОВ ===
async def generate_posts_pack(task_context=""):
    raw_news = await fetch_news_hub()
    calendar = await get_f1_calendar(14)
    web_context = await smart_search(f"F1 {task_context}") if task_context else ""
    
    full_context = f"""
СЕГОДНЯ: {datetime.now().strftime('%d.%m.%Y')}

НОВОСТИ:
{raw_news}

КАЛЕНДАРЬ:
{calendar}

ИНТЕРНЕТ:
{web_context}

ЗАДАНИЕ: {task_context if task_context else 'Сделай пост о последних событиях в F1'}
"""
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Создай 1-2 поста. Обязательно разбей на абзацы. НЕ ИСПОЛЬЗУЙ *\n\n{full_context}"}
    ]
    
    model = await get_working_model()
    response = await client.chat.completions.create(
        model=model, messages=messages, temperature=0.7, max_tokens=1000
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
        if "text" in post:
            post["text"] = format_post_text(post["text"])
            if is_already_posted(post["text"]):
                continue
            save_post_hash(post["text"])
        if post.get("photo_search"):
            post["photo_url"] = await search_live_photo(post["photo_search"])
    
    return posts

# Загружаем историю при старте
load_posted_history()
