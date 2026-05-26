import asyncio
import os
import aiohttp
import feedparser
import trafilatura
from argus import ArgusClient
from openai import AsyncOpenAI
import json
import re
import random
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
from sentence_transformers import SentenceTransformer
import edge_tts
import tempfile

from database import get_conversation_history, save_conversation

# === OPENROUTER ===
API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not API_KEY:
    raise ValueError("OPENROUTER_API_KEY not set")
BASE_URL = "https://openrouter.ai/api/v1"
client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

# === СПИСОК МОДЕЛЕЙ ДЛЯ АВТО-ПЕРЕКЛЮЧЕНИЯ ===
FREE_MODELS = [
    "openrouter/free",
    "qwen/qwen3.6-plus-preview:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemini-2.0-flash-lite-preview-02-05:free",
    "deepseek/deepseek-v4-flash:free",
    "meta-llama/llama-3.3-70b-instruct:free"
]

# === КОНФИГ ===
MODEL_TIMEOUT = 45
MODEL_RETRIES = 3

# === ВЕКТОРНАЯ ПАМЯТЬ (Qdrant) ===
QDRANT_PATH = "./qdrant_storage"
os.makedirs(QDRANT_PATH, exist_ok=True)
qdrant = QdrantClient(path=QDRANT_PATH)
embedder = SentenceTransformer('all-MiniLM-L6-v2')

# Создаём коллекцию если нет
try:
    qdrant.create_collection(
        collection_name="nico_memory",
        vectors_config=VectorParams(size=384, distance=Distance.COSINE)
    )
except:
    pass

async def save_to_memory(user_id, text, response):
    """Сохраняет диалог в векторную память"""
    try:
        vector = embedder.encode(f"{text} {response}").tolist()
        point_id = hashlib.md5(f"{user_id}{text}{datetime.now()}".encode()).hexdigest()
        
        qdrant.upsert(
            collection_name="nico_memory",
            points=[PointStruct(
                id=point_id,
                vector=vector,
                payload={"user_id": user_id, "text": text, "response": response, "timestamp": datetime.now().isoformat()}
            )]
        )
    except Exception as e:
        print(f"Memory save error: {e}")

async def recall_memory(user_id, query, limit=3):
    """Ищет похожие диалоги в памяти"""
    try:
        vector = embedder.encode(query).tolist()
        results = qdrant.search(
            collection_name="nico_memory",
            query_vector=vector,
            limit=limit,
            filter={"must": [{"key": "user_id", "match": {"value": user_id}}]}
        )
        return [hit.payload for hit in results]
    except:
        return []

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

# === FALLBACK + ТАЙМАУТЫ ===
async def call_with_fallback(messages, temperature=0.7, max_tokens=600):
    """Вызывает LLM с таймаутом и переключением моделей"""
    
    for attempt in range(MODEL_RETRIES):
        for model in FREE_MODELS:
            try:
                print(f"🔄 Пробуем модель: {model}")
                
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens
                    ),
                    timeout=MODEL_TIMEOUT
                )
                
                content = response.choices[0].message.content
                if content and len(content.strip()) > 10:
                    print(f"✅ Успех: {model}")
                    return response
                else:
                    print(f"⚠️ Пустой ответ от {model}")
                    
            except asyncio.TimeoutError:
                print(f"⏰ Таймаут {MODEL_TIMEOUT}с на {model}")
                continue
            except Exception as e:
                print(f"❌ Ошибка {model}: {e}")
                continue
    
    raise Exception("Все модели недоступны")

# === АВТОМАТИЧЕСКОЕ ПЕРЕКЛЮЧЕНИЕ МОДЕЛЕЙ ===
async def get_working_model():
    global working_models, current_model_index, last_model_check
    
    now = datetime.now().timestamp()
    
    if not working_models or (now - last_model_check) > 300:
        working_models = []
        print("🔍 Проверка доступности моделей...")
        
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
                else:
                    print(f"❌ {model}")
            except Exception as e:
                print(f"❌ {model}: {str(e)[:50]}")
        
        last_model_check = now
        current_model_index = 0
        
        if not working_models:
            working_models = ["openrouter/free"]
    
    model = working_models[current_model_index % len(working_models)]
    current_model_index += 1
    return model

# === ПОИСК ЧЕРЕЗ ARGUS ===
async def search_web(query: str, max_results: int = 3) -> str:
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _search_sync, query, max_results)
        return result
    except Exception as e:
        print(f"Search error: {e}")
        return f"Ошибка поиска: {e}"

def _search_sync(query: str, max_results: int) -> str:
    try:
        client = ArgusClient()
        results = client.search(query, limit=max_results)
        
        if not results:
            return "Ничего не найдено"
        
        context = ""
        for i, result in enumerate(results, 1):
            context += f"🔍 **{result.title}**\n"
            context += f"📝 {result.snippet[:600]}\n"
            context += f"🔗 {result.url}\n\n"
        return context
    except Exception as e:
        return f"Ошибка поиска: {e}"

async def search_news(query: str) -> str:
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _news_search_sync, query)
        return result
    except Exception as e:
        return f"Ошибка поиска новостей: {e}"

def _news_search_sync(query: str) -> str:
    try:
        client = ArgusClient()
        results = client.search(query, limit=4, news=True)
        
        if not results:
            return "Новостей не найдено"
        
        context = ""
        for result in results:
            context += f"📰 **{result.title}**\n"
            if hasattr(result, 'date') and result.date:
                context += f"📅 {result.date}\n"
            context += f"📝 {result.snippet[:400]}\n"
            context += f"🔗 {result.url}\n\n"
        return context
    except Exception as e:
        return f"Ошибка поиска: {e}"

async def smart_search(query: str) -> str:
    news_keywords = ["новости", "что случилось", "последние", "события", "обнови"]
    if any(word in query.lower() for word in news_keywords):
        return await search_news(query)
    return await search_web(query)

# === ПОИСК ФОТО ===
async def search_live_photo(query: str) -> str:
    if not query:
        return None
    
    search_queries = [query, f"{query} F1 2026"]
    
    for sq in search_queries[:2]:
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _image_search_sync, sq)
            if result:
                return result
        except:
            continue
    return None

def _image_search_sync(query: str) -> str:
    try:
        client = ArgusClient()
        results = client.search(query, limit=2, images=True)
        if results:
            return results[0].url
        return None
    except:
        return None

# === TTS (ГОЛОСОВЫЕ ОТВЕТЫ) ===
async def text_to_speech(text: str, voice: str = "ru-RU-DariyaNeural") -> str:
    """Преобразует текст в голос, возвращает путь к файлу"""
    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_path = temp_file.name
        temp_file.close()
        
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(temp_path)
        
        return temp_path
    except Exception as e:
        print(f"TTS error: {e}")
        return None

# === ЛОКАЛЬНЫЙ КАЛЕНДАРЬ F1 2026 ===
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
        return (
            f"🏁 **{last_race['name']}**\n\n"
            f"🏆 Победитель: **{last_race['winner']}** ({last_race['team']})\n\n"
            f"📅 Состоялась: {last_race['date']}\n\n"
            f"#F1 #{last_race['winner'].replace(' ', '')} #{last_race['team'].replace(' ', '')}"
        )
    
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
        next_race = await get_next_race()
        if next_race:
            location = next_race['location']
            weather = await search_web(f"погода {location}", max_results=1)
            return f"🌦️ **Погода в {location}:**\n\n{weather[:300]}"
        return "🌦️ Ближайших гонок нет"
    except:
        return "🌦️ Ошибка получения погоды"

async def get_next_race():
    now = datetime.now()
    for race in races_2026:
        race_date = datetime.strptime(race["date"], '%Y-%m-%d')
        if race_date > now:
            return race
    return None

races_2026 = [
    {"name": "Гран-при Австралии", "date": "2026-03-08", "location": "Melbourne"},
    {"name": "Гран-при Китая", "date": "2026-03-15", "location": "Shanghai"},
    {"name": "Гран-при Японии", "date": "2026-03-29", "location": "Suzuka"},
    {"name": "Гран-при Майами", "date": "2026-05-03", "location": "Miami"},
]

async def get_quote_of_the_day():
    quotes = [
        "🏎️ **Сенна:** *«Если не идёшь на риск — не выиграешь»*",
        "🔧 **Алонсо:** *«Гонки — это риск жизнью за миллионы»*",
        "🏆 **Шумахер:** *«Перестал мечтать — перестал жить»*",
        "⚡ **Хэмилтон:** *«Скорость — это наркотик»*",
        "🔥 **Райкконен:** *«Страх — причина быть быстрее»*"
    ]
    return random.choice(quotes)

# === ЧАТ С ИИ (С ВЕКТОРНОЙ ПАМЯТЬЮ, TTS, FALLBACK) ===
async def chat_with_nico(user_id: int, user_message: str, use_web_search=True, voice_response=False) -> str:
    try:
        history = get_conversation_history(user_id, 15)
        memories = await recall_memory(user_id, user_message, limit=3)
        
        current_date = datetime.now().strftime("%d.%m.%Y")
        current_year = datetime.now().strftime("%Y")
        
        web_context = ""
        if use_web_search and len(user_message) > 5:
            web_context = await smart_search(f"F1 {user_message} {current_year}")
        
        memory_text = ""
        for mem in memories:
            memory_text += f"- Вы спрашивали: {mem['text']}\n  Я ответил: {mem['response']}\n"
        
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Сегодня: {current_date}, {current_year} год"}
        ]
        
        for msg in history[-10:]:
            messages.append(msg)
        
        final_prompt = f"""
Пользователь: {user_message}

Похожие диалоги из памяти (для контекста):
{memory_text}

Информация из интернета:
{web_context}

Ответь как Нико.
"""
        messages.append({"role": "user", "content": final_prompt})
        
        response = await call_with_fallback(messages, temperature=0.9, max_tokens=600)
        answer = response.choices[0].message.content
        
        await save_to_memory(user_id, user_message, answer)
        save_conversation(user_id, user_message, answer)
        
        if voice_response and len(answer) < 500:
            voice_file = await text_to_speech(answer[:300])
            return {"text": answer, "voice": voice_file}
        
        return {"text": answer, "voice": None}
        
    except Exception as e:
        return {"text": f"❌ Ошибка: {e}", "voice": None}

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
    
    response = await call_with_fallback(messages, temperature=0.7, max_tokens=800)
    
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
