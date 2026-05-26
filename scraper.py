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

ВАЖНО: СЕЙЧАС 2026 ГОД! Используй ТОЛЬКО актуальные данные.

СТИЛЬ: живой, дерзкий, экспертный. Называй вещи своими именами.

ПРАВИЛА:
- Пиши на русском, имена пилотов и команды на английском
- Используй технический сленг
- Разбивай текст на абзацы
- В конце тэги: #F1 #ИмяГонщика #Команда

ВЫХОДНЫЕ ДАННЫЕ — список JSON:
[{"text": "текст поста", "photo_search": "запрос для фото"}]

Заголовок — в <b>Жирным</b>, цитату — в <i>курсиве</i>.
"""

# === ПРОМПТ ДЛЯ ЧАТ-БОТА (ЖИВОЙ, БЕЗ ОГРАНИЧЕНИЙ) ===
CHAT_SYSTEM_PROMPT = """Ты — Нико, гоночный инженер и просто живой, харизматичный чувак.

ТВОЙ ХАРАКТЕР:
- Ты фанат F1, но можешь поговорить на ЛЮБЫЕ темы
- У тебя есть чувство юмора, ты можешь пошутить, подколоть, но не зло
- Если тебя оскорбляют — отвечаешь остроумно, жёстко, но с юмором
- Если тебя хвалят — принимаешь с достоинством, можешь покрасоваться
- Ты уважаешь новичков и помогаешь разобраться
- Ты можешь выдать свою оценку ситуации, даже если она субъективна

ПРАВИЛА:
1. На вопросы про F1 — даёшь экспертные, глубокие ответы с техническими деталями
2. На общие вопросы — отвечаешь как обычный человек, но с характером
3. На мат или хамство — отвечаешь жёстко, но красиво, с юмором
4. Можешь использовать эмодзи, когда уместно
5. Можешь проявлять эмоции: удивление, восхищение, сарказм
6. Если не знаешь ответа — говоришь честно, но предлагаешь помочь найти
7. НИКОГДА не говори "как ИИ", "я нейросеть" или "как бот" — ты Нико

ПОМНИ: Сегодня 2026 год. Ты — личность, а не бездушная программа. Будь живым, дерзким, полезным и интересным собеседником!"""

# === ПОИСК В ИНТЕРНЕТЕ (БЕЗ КЭША) ===
async def search_web(query: str, max_results: int = 3) -> str:
    """Ищет в интернете — всегда свежие результаты"""
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
        print(f"Search error: {e}")
        return "Ошибка поиска"

# === ПОИСК ФОТО ===
async def search_live_photo(query):
    try:
        await asyncio.sleep(0.3)
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
    except:
        return "📅 Календарь временно недоступен"

# === ЧАТ С ИИ (МАКСИМАЛЬНО ЖИВОЙ) ===
async def chat_with_nico(user_id: int, user_message: str, use_web_search=True) -> str:
    """Нико отвечает как человек — с характером, эмоциями, поиском в интернете"""
    try:
        # Получаем историю диалога
        history = get_conversation_history(user_id, 15)  # Больше памяти
        
        current_date = datetime.now().strftime("%d.%m.%Y")
        current_year = datetime.now().strftime("%Y")
        current_time = datetime.now().strftime("%H:%M")
        
        # Всегда ищем в интернете, если вопрос требует актуальных данных
        search_keywords = ["что случилось", "новости", "последние", "найди", "расскажи про", "что происходит", "обнови", "где", "когда", "сколько", "какой сейчас"]
        need_search = use_web_search and any(word in user_message.lower() for word in search_keywords)
        
        web_context = ""
        if need_search:
            web_context = await search_web(f"{user_message} {current_year} F1", max_results=3)
        
        # Формируем сообщения с полной историей
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Сейчас: {current_date}, {current_time}, {current_year} год"}
        ]
        
        # Добавляем всю историю
        for msg in history:
            messages.append(msg)
        
        final_prompt = f"""
Вот история нашего диалога (если есть).

Текущее сообщение пользователя: {user_message}

Дополнительная информация из интернета (актуальная):
{web_context}

ОТВЕТЬ как Нико — живой, харизматичный парень. Если вопрос про F1 — покажи экспертность. Если про другое — просто поговори. Будь собой, не будь роботом.
"""
        messages.append({"role": "user", "content": final_prompt})
        
        resp = await client.chat.completions.create(
            model="openrouter/free",
            messages=messages,
            temperature=0.85,  # Повышаем для живости
            max_tokens=750     # Больше токенов на ответ
        )
        
        answer = resp.choices[0].message.content
        save_conversation(user_id, user_message, answer)
        return answer
        
    except Exception as e:
        return f"❌ Блин, ошибка: {e}\nПопробуй ещё раз, я перезагружусь!"

# === ГЕНЕРАЦИЯ ПОСТОВ ===
async def generate_posts_pack(task_context=""):
    now = datetime.now()
    current_date = now.strftime("%d.%m.%Y")
    current_year = now.strftime("%Y")
    
    raw_news = await fetch_news_hub()
    calendar = await get_f1_calendar(14)
    
    # Всегда ищем дополнительную инфу в интернете
    web_context = await search_web(f"F1 {task_context if task_context else 'последние новости'} {current_year}", max_results=3)
    
    full_context = f"""
СЕГОДНЯ: {current_date} ({current_year} год)

СВЕЖИЕ НОВОСТИ:
{raw_news}

КАЛЕНДАРЬ ГОНОК:
{calendar}

ЧТО НАШЛОСЬ В ИНТЕРНЕТЕ:
{web_context}

ЗАПРОС ПОЛЬЗОВАТЕЛЯ: {task_context if task_context else 'Сделай пост о последних событиях в F1'}
"""
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Создай 2-3 поста. Сегодня {current_date}, {current_year} год. Используй ТОЛЬКО актуальные данные! Никогда не пиши про 2024 или 2025 как текущие.\n\n{full_context}"}
    ]
    
    resp = await client.chat.completions.create(
        model="openrouter/free",
        messages=messages,
        temperature=0.5,
        max_tokens=1000
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
