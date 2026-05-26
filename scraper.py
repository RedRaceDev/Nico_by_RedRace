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
from datetime import datetime, timedelta

from database import get_conversation_history, save_conversation, cache_search, get_cached_search

# === OPENROUTER ===
API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not API_KEY:
    raise ValueError("OPENROUTER_API_KEY not set")
BASE_URL = "https://openrouter.ai/api/v1"
client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

# === МОДЕЛЬ ===
F1_MODEL = "google/gemini-2.0-flash-lite-preview-02-05:free"

# === СПИСОК МОДЕЛЕЙ ДЛЯ ПЕРЕКЛЮЧЕНИЯ ===
AVAILABLE_MODELS = [
    "openrouter/free",
    "google/gemini-2.0-flash-lite-preview-02-05:free",
    "qwen/qwen3.6-plus-preview:free",
    "google/gemma-4-31b-it:free"
]

working_models = []
model_check_time = None

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

# === ПРОМПТЫ ===
SYSTEM_PROMPT = """Ты — Нико, гоночный инженер.

СТИЛЬ: живой, дерзкий, экспертный.

ПРАВИЛА:
- Пиши на русском, имена пилотов на английском
- В конце поста эмодзи 🏁
- НЕ ДОБАВЛЯЙ ссылки

ВЫХОДНЫЕ ДАННЫЕ — список JSON:
[{"text": "текст поста", "photo_search": "запрос для фото"}]
"""

CHAT_SYSTEM_PROMPT = """Ты — Нико. Если оскорбляют — пошли нахуй. Если нормально — отвечай по делу. Никогда не говори "я бот". Сегодня 2026 год."""

# === JOLPICA API — КАЛЕНДАРЬ И РЕЗУЛЬТАТЫ ===
async def get_f1_calendar(days_ahead=21):
    """Получает календарь гонок через Jolpica API"""
    try:
        current_year = datetime.now().year
        url = f"https://api.jolpica.com/api/f1/{current_year}.json"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                races = data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
                
                now = datetime.now()
                schedule = []
                
                for race in races:
                    race_date_str = race.get('date', '')
                    if race_date_str:
                        race_date = datetime.strptime(race_date_str, '%Y-%m-%d')
                        if race_date >= now and race_date <= now + timedelta(days=days_ahead):
                            race_name = race.get('raceName', 'Гонка')
                            circuit = race.get('Circuit', {}).get('circuitName', '')
                            schedule.append(f"• **{race_name}** — {race_date.strftime('%d.%m')} ({circuit})")
                
                if schedule:
                    return "📅 **Ближайшие гонки (Jolpica):**\n" + "\n".join(schedule[:10])
                return "📅 На ближайшее время гонок нет."
    except Exception as e:
        return f"📅 Ошибка календаря: {e}"

async def get_last_race_result():
    """Получает результаты последней гонки"""
    try:
        url = "https://api.jolpica.com/api/f1/current/last/results.json"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                race = data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
                if race:
                    race_name = race[0].get('raceName', '')
                    results = race[0].get('Results', [])[:5]
                    text = f"🏁 **Результаты гонки: {race_name}**\n\n"
                    for i, r in enumerate(results, 1):
                        driver = r.get('Driver', {}).get('familyName', '')
                        constructor = r.get('Constructor', {}).get('name', '')
                        text += f"{i}. {driver} ({constructor})\n"
                    return text
                return "🏁 Данные о последней гонке временно недоступны"
    except:
        return "🏁 Ошибка получения результатов"

# === ПРОВЕРКА МОДЕЛЕЙ ===
async def check_models_health():
    global working_models, model_check_time
    working = []
    print("🔍 Проверка моделей...")
    for model in AVAILABLE_MODELS:
        try:
            test_response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=3
            )
            if test_response and test_response.choices:
                working.append(model)
                print(f"✅ {model}")
            else:
                print(f"❌ {model}")
        except:
            print(f"❌ {model}")
    working_models = working
    model_check_time = datetime.now()
    return working

async def get_working_model():
    global working_models, model_check_time
    if not working_models or not model_check_time or (datetime.now() - model_check_time).seconds > 300:
        await check_models_health()
    return working_models[0] if working_models else "openrouter/free"

# === ПОИСК В ИНТЕРНЕТЕ ===
async def search_web_duckduckgo(query: str, max_results: int = 3) -> str:
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
            context = ""
            for i, r in enumerate(results, 1):
                context += f"🔍 **{r.get('title', '')}**\n📝 {r.get('body', '')[:600]}\n\n"
            return context if context else "Ничего не найдено"
    except Exception as e:
        return f"Ошибка поиска: {e}"

async def search_news(query: str) -> str:
    try:
        with DDGS() as ddgs:
            results = ddgs.news(query, max_results=3)
            context = ""
            for i, r in enumerate(results, 1):
                context += f"📰 **{r.get('title', '')}**\n📅 {r.get('date', '')}\n📝 {r.get('body', '')[:400]}\n\n"
            return context if context else "Новостей не найдено"
    except:
        return "Ошибка поиска"

async def smart_search(query: str) -> str:
    news_keywords = ["новости", "что случилось", "последние"]
    if any(word in query.lower() for word in news_keywords):
        return await search_news(query)
    return await search_web_duckduckgo(query)

async def search_live_photo(query: str) -> str:
    if not query:
        return None
    search_queries = [query, f"{query} F1 2026"]
    for sq in search_queries[:2]:
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
            except:
                continue
    return context if context else "Нет свежих новостей."

# === ТОП НОВОСТЕЙ ===
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

# === ПОГОДА ===
async def get_weather_for_track():
    try:
        current_year = datetime.now().year
        url = f"https://api.jolpica.com/api/f1/{current_year}.json"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                races = data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
                now = datetime.now()
                next_race = None
                for race in races:
                    race_date_str = race.get('date', '')
                    if race_date_str:
                        race_date = datetime.strptime(race_date_str, '%Y-%m-%d')
                        if race_date > now:
                            next_race = race
                            break
                if next_race:
                    location = next_race.get('Circuit', {}).get('location', '')
                    country = next_race.get('Circuit', {}).get('country', '')
                    weather = await search_web_duckduckgo(f"погода {location} {country}", max_results=1)
                    return f"🌦️ **Погода в {location} ({country}):**\n\n{weather[:300]}"
                return "🌦️ Ближайших гонок нет"
    except:
        return "🌦️ Ошибка получения погоды"

# === ЦИТАТА ДНЯ ===
async def get_quote_of_the_day():
    quotes = [
        "🏎️ **Сенна:** *«Если не идёшь на риск — не выиграешь»*",
        "🔧 **Алонсо:** *«Гонки — это риск жизнью за миллионы»*",
        "🏆 **Шумахер:** *«Перестал мечтать — перестал жить»*",
        "⚡ **Хэмилтон:** *«Скорость — это наркотик»*",
        "🔥 **Райкконен:** *«Страх — причина быть быстрее»*"
    ]
    return random.choice(quotes)

# === ЧАТ С ИИ ===
async def chat_with_nico(user_id: int, user_message: str, use_web_search=True) -> str:
    try:
        history = get_conversation_history(user_id, 15)
        current_date = datetime.now().strftime("%d.%m.%Y")
        current_year = datetime.now().strftime("%Y")
        
        web_context = ""
        if use_web_search and len(user_message) > 5:
            web_context = await smart_search(f"F1 {user_message} {current_year}")
        
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Сегодня: {current_date}, {current_year} год"}
        ]
        
        for msg in history[-10:]:
            messages.append(msg)
        
        final_prompt = f"""
Пользователь: {user_message}

Информация из интернета:
{web_context}

Ответь как Нико.
"""
        messages.append({"role": "user", "content": final_prompt})
        
        model_to_use = await get_working_model()
        
        response = await client.chat.completions.create(
            model=model_to_use,
            messages=messages,
            temperature=0.9,
            max_tokens=600
        )
        
        answer = response.choices[0].message.content
        save_conversation(user_id, user_message, answer)
        return answer
        
    except Exception as e:
        global working_models
        if len(working_models) > 1:
            working_models.pop(0)
            return await chat_with_nico(user_id, user_message, use_web_search)
        return f"❌ Ошибка: {e}"

# === ГЕНЕРАЦИЯ ПОСТОВ ===
async def generate_posts_pack(task_context=""):
    now = datetime.now()
    current_date = now.strftime("%d.%m.%Y")
    current_year = now.strftime("%Y")
    
    raw_news = await fetch_news_hub()
    calendar = await get_f1_calendar(14)
    
    web_context = ""
    if task_context and len(task_context) > 10:
        web_context = await smart_search(f"F1 {task_context} {current_year}")
    
    full_context = f"""
СЕГОДНЯ: {current_date} ({current_year} год)

НОВОСТИ:
{raw_news}

КАЛЕНДАРЬ:
{calendar}

ИНТЕРНЕТ:
{web_context}

ЗАДАНИЕ: {task_context if task_context else 'Сделай пост о F1'}
"""
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Создай 1-2 поста. {full_context}"}
    ]
    
    model_to_use = await get_working_model()
    
    response = await client.chat.completions.create(
        model=model_to_use,
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
        text = post.get("text", "")
        text = re.sub(r'\n\n<a href=[\'"].*?[\'"]>.*?</a>', '', text)
        if not text.endswith(('🏁', '🏎️')):
            text += "\n\n🏁"
        post["text"] = text
    
    return posts

# Алиас для обратной совместимости
search_web = search_web_duckduckgo
