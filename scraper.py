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

from database import get_conversation_history, save_conversation

# === OPENROUTER ===
API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not API_KEY:
    raise ValueError("OPENROUTER_API_KEY not set")
BASE_URL = "https://openrouter.ai/api/v1"
client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

# === НОВЫЕ БЕСПЛАТНЫЕ МОДЕЛИ (Май 2026) ===
FREE_MODELS = [
    "openrouter/free",
    "qwen/qwen3.6-plus-preview:free",
    "qwen/qwen3.7-max:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "deepseek/deepseek-v4-flash:free",
    "openrouter/owl-alpha",
    "inclusionai/ring-2.6-1t"
]

# === КЭШ РАБОЧИХ МОДЕЛЕЙ ===
working_models = []
current_model_index = 0
last_model_check = 0

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

Твой стиль: живой, дерзкий, экспертный.

ЖЁСТКИЕ ПРАВИЛА ФОРМАТИРОВАНИЯ:
1. ЗАПРЕЩЕНЫ символы в тексте поста: *, **, __, _
2. Используй ТОЛЬКО HTML теги: <b>жирный</b> и <i>курсив</i>
3. Заголовок новости — в <b>Жирным</b> в первой строке
4. Цитаты — в <i>курсиве</i>
5. Хештеги пиши через # — разрешено

ПРАВИЛА:
- Пиши на русском, имена пилотов и команды на английском
- Используй технический сленг
- Разбивай текст на абзацы по 2-3 предложения

ВЫХОДНЫЕ ДАННЫЕ — список JSON:
[
  {
    "text": "текст поста с HTML (<b>, <i>) и хештегами (#F1)",
    "photo_search": "английский запрос для поиска фото"
  }
]"""

CHAT_SYSTEM_PROMPT = """Ты — Нико. Если оскорбляют — пошли нахуй. Если нормально — отвечай по делу. Никогда не говори "я бот". Сегодня 2026 год."""

# === АВТО-ПЕРЕКЛЮЧЕНИЕ МОДЕЛЕЙ ===
async def get_working_model():
    global working_models, current_model_index, last_model_check
    now = datetime.now().timestamp()
    
    if not working_models or (now - last_model_check) > 300:
        working_models = []
        print("🔍 Проверка моделей...")
        for model in FREE_MODELS:
            try:
                test_response = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=3,
                    temperature=0.1
                )
                if test_response and test_response.choices:
                    working_models.append(model)
                    print(f"✅ {model}")
            except:
                print(f"❌ {model}")
        last_model_check = now
        current_model_index = 0
        if not working_models:
            working_models = ["openrouter/free"]
    
    model = working_models[current_model_index % len(working_models)]
    current_model_index += 1
    return model

# === ПОИСК ЧЕРЕЗ DUCKDUCKGO ===
async def search_web(query: str, max_results: int = 3) -> str:
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
            context = ""
            for i, r in enumerate(results, 1):
                context += f"🔍 **{r.get('title', '')}**\n"
                context += f"📝 {r.get('body', '')[:600]}\n"
                context += f"🔗 {r.get('href', '')}\n\n"
            return context if context else "Ничего не найдено"
    except Exception as e:
        return f"Ошибка поиска: {e}"

async def search_news(query: str) -> str:
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
    except:
        return "Ошибка поиска новостей"

async def smart_search(query: str) -> str:
    news_keywords = ["новости", "что случилось", "последние", "события", "обнови"]
    if any(word in query.lower() for word in news_keywords):
        return await search_news(query)
    return await search_web(query)

# === ПОИСК ФОТО ===
async def search_live_photo(query: str) -> str:
    if not query:
        return None
    for sq in [query, f"{query} F1 2026"]:
        try:
            with DDGS() as ddgs:
                results = ddgs.images(sq, max_results=2)
                if results:
                    return results[0]['image']
        except:
            continue
    return None

# === ЛОКАЛЬНЫЙ КАЛЕНДАРЬ ===
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
            schedule.append(f"• **{race['name']}** — {race_date.strftime('%d.%m')} ({race['location']})")
    if schedule:
        return "📅 **Ближайшие гонки F1 2026:**\n" + "\n".join(schedule[:10])
    return "📅 На ближайшее время гонок нет."

async def get_last_race_result():
    completed_races = [
        {"name": "Гран-при Австралии", "date": "2026-03-08", "winner": "Lando Norris", "team": "McLaren"},
        {"name": "Гран-при Китая", "date": "2026-03-15", "winner": "Max Verstappen", "team": "Red Bull Racing"},
        {"name": "Гран-при Японии", "date": "2026-03-29", "winner": "Oscar Piastri", "team": "McLaren"},
    ]
    now = datetime.now()
    last_race = None
    for race in completed_races:
        race_date = datetime.strptime(race["date"], '%Y-%m-%d')
        if race_date < now:
            last_race = race
    if last_race:
        return f"🏁 **{last_race['name']}**\n\n🏆 Победитель: **{last_race['winner']}** ({last_race['team']})\n\n📅 Состоялась: {last_race['date']}\n\n#F1 #{last_race['winner'].replace(' ', '')} #{last_race['team'].replace(' ', '')}"
    return await smart_search("последняя гонка F1 результаты 2026")

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

async def get_weather_for_track():
    try:
        next_race = {"name": "Гран-при Майами", "date": "2026-05-03", "location": "Miami"}
        now = datetime.now()
        race_date = datetime.strptime(next_race["date"], '%Y-%m-%d')
        if race_date > now:
            weather = await search_web(f"погода {next_race['location']}", max_results=1)
            return f"🌦️ **Погода в {next_race['location']}:**\n\n{weather[:300]}"
        return "🌦️ Ближайших гонок нет"
    except:
        return "🌦️ Ошибка получения погоды"

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

СВЕЖИЕ НОВОСТИ:
{raw_news}

КАЛЕНДАРЬ:
{calendar}

ИНТЕРНЕТ:
{web_context}

ЗАДАНИЕ: {task_context if task_context else 'Сделай пост о последних событиях в F1'}
"""
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Создай 1-2 поста. Сегодня {current_date}, {current_year} год. НЕ ИСПОЛЬЗУЙ * В ТЕКСТЕ.\n\n{full_context}"}
    ]
    
    model_to_use = await get_working_model()
    response = await client.chat.completions.create(
        model=model_to_use,
        messages=messages,
        temperature=0.7,
        max_tokens=800
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
            text = post["text"]
            text = re.sub(r'\*\*', '', text)
            text = re.sub(r'\*', '', text)
            text = re.sub(r'__', '', text)
            text = re.sub(r'_', '', text)
            post["text"] = text
        if post.get("photo_search"):
            img_url = await search_live_photo(post["photo_search"])
            post["photo_url"] = img_url
    return posts
