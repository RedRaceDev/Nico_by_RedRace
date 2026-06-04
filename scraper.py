import asyncio
import os
import json
import re
import hashlib
import random
import aiohttp
import feedparser
from datetime import datetime, timedelta
import openai

# === F1 DATA ===
try:
    import fastf1
    FASTF1_AVAILABLE = True
    # Создаём папку для кеша
    os.makedirs('f1_cache', exist_ok=True)
    fastf1.Cache.enable_cache('f1_cache')
    print("✅ FastF1 загружен")
except ImportError:
    FASTF1_AVAILABLE = False
    print("⚠️ FastF1 не установлен")

# === КОНФИГ ===
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"
MEMORY_FILE = "memory.json"
HASH_FILE = "posted_hashes.json"

RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
]

# === API КЛЮЧИ ===
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
BRAVE_KEY = os.environ.get("BRAVE_API_KEY")

# === OpenRouter БЕСПЛАТНЫЕ МОДЕЛИ (июнь 2026) ===
OPENROUTER_MODELS = [
    "xiaomi/mimo-v2-flash:free",           # 309B MoE, 1M контекста
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",  # 30B, reasoning
    "zai-org/glm-4.7-flash:free",           # GLM-4.7 Flash
    "cerebras/llama3.1-70b:free",           # ультрабыстрый
    "tencent/hy3-preview:free",             # 295B MoE
    "mistralai/mistral-small-2603:free",    # 22B
    "openai/gpt-oss-120b:free",             # GPT-OSS
    "openrouter/free"                       # универсальный fallback
]

# === POLLINATIONS AI (без ключа) ===
POLLINATIONS_URL = "https://text.pollinations.ai/openai"

# === AI ФУНКЦИИ ===
async def ask_pollinations(prompt: str) -> str:
    """Бесплатный эндпойнт без API ключа (резерв)"""
    try:
        client = openai.AsyncOpenAI(
            base_url=POLLINATIONS_URL,
            api_key="anything"
        )
        response = await client.chat.completions.create(
            model="openai",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.4,
            timeout=20
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Pollinations error: {e}")
        return None

async def ask_openrouter(prompt: str, image_url: str = None) -> str:
    """Вызов OpenRouter с fallback по моделям"""
    if not OPENROUTER_KEY:
        return await ask_pollinations(prompt)
    
    client = openai.AsyncOpenAI(
        api_key=OPENROUTER_KEY,
        base_url="https://openrouter.ai/api/v1"
    )
    
    messages = []
    if image_url:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]
        })
    else:
        messages.append({"role": "user", "content": prompt})
    
    for model in OPENROUTER_MODELS:
        for attempt in range(2):
            try:
                print(f"🔍 Пробую: {model}")
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=800,
                    temperature=0.3,
                    timeout=25
                )
                if response and response.choices:
                    print(f"✅ {model} ответил")
                    return response.choices[0].message.content
            except Exception as e:
                print(f"❌ {model} error: {e}")
                if attempt == 0:
                    await asyncio.sleep(1)
                continue
    
    # Последний шанс — Pollinations
    return await ask_pollinations(prompt) or "❌ ИИ временно недоступен. Попробуй позже."

async def ask_ai(prompt: str, image_url: str = None) -> str:
    return await ask_openrouter(prompt, image_url)

# === F1 DATA FUNCTIONS ===
async def get_driver_standings(year=2026):
    url = f"https://api.jolpica.f1/api/v1/{year}/driverstandings.json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                standings_list = data.get('MRData', {}).get('StandingsTable', {}).get('StandingsLists', [])
                if not standings_list:
                    return None
                standings = standings_list[0].get('DriverStandings', [])
                if not standings:
                    return None
                result = []
                for i, s in enumerate(standings[:10], 1):
                    driver = f"{s['Driver']['givenName']} {s['Driver']['familyName']}"
                    result.append({
                        "pos": i,
                        "driver": driver,
                        "points": s['points'],
                        "team": s['Constructors'][0]['name']
                    })
                return result
    except Exception as e:
        print(f"Jolpica error: {e}")
        return None

async def get_last_race_results(year=2026):
    url = f"https://api.jolpica.f1/api/v1/{year}/last/results.json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                races = data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
                if not races:
                    return None
                race = races[0]
                results = []
                for r in race.get('Results', [])[:10]:
                    driver = f"{r['Driver']['givenName']} {r['Driver']['familyName']}"
                    results.append({
                        "pos": r.get('position', 'DNF'),
                        "driver": driver,
                        "points": r.get('points', '0')
                    })
                return {"name": race.get('raceName', 'Unknown'), "results": results}
    except Exception as e:
        print(f"Last race error: {e}")
        return None

async def get_next_race(year=2026):
    url = f"https://api.jolpica.f1/api/v1/{year}/next.json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                races = data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
                if not races:
                    return None
                race = races[0]
                return {
                    "name": race.get('raceName', 'Unknown'),
                    "date": race.get('date', 'TBD'),
                    "circuit": race.get('Circuit', {}).get('circuitName', 'Unknown')
                }
    except Exception as e:
        print(f"Next race error: {e}")
        return None

async def search_brave_images(query: str, max_results: int = 10) -> list:
    if not BRAVE_KEY:
        return []
    url = f"https://api.search.brave.com/res/v1/images/search?q={query}&count={max_results}"
    headers = {"X-Subscription-Token": BRAVE_KEY, "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = []
                    for i, img in enumerate(data.get('results', [])):
                        results.append({
                            'id': f"img_{i}",
                            'url': img.get('url'),
                            'thumbnail': img.get('thumbnail', {}).get('src'),
                            'title': img.get('title', ''),
                            'source': img.get('page', '')
                        })
                    return results
    except Exception as e:
        print(f"Brave error: {e}")
    return []

# === БЫСТРЫЕ ОТВЕТЫ БЕЗ AI ===
async def fast_standings_reply() -> str:
    standings = await get_driver_standings(2026)
    if not standings:
        return "❌ Данные чемпионата временно недоступны"
    
    text = "🏆 **Чемпионат F1 2026 (пилоты):**\n\n"
    for s in standings[:5]:
        text += f"{s['pos']}. **{s['driver']}** — {s['points']} очков ({s['team']})\n"
    return text

async def fast_last_race_reply() -> str:
    race = await get_last_race_results(2026)
    if not race:
        return "❌ Данные последней гонки недоступны"
    
    text = f"🏁 **{race['name']}**\n\n"
    for r in race['results'][:5]:
        text += f"{r['pos']}. {r['driver']} — {r['points']} очков\n"
    return text

# === ПАМЯТЬ ===
def load_memory():
    try:
        with open(MEMORY_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_memory(memory):
    try:
        with open(MEMORY_FILE, 'w') as f:
            json.dump(memory, f, indent=2)
    except Exception as e:
        print(f"Memory save error: {e}")

def get_memory(user_id, limit=10):
    memory = load_memory()
    return memory.get(str(user_id), [])[-limit:]

def save_to_memory(user_id, message, response):
    memory = load_memory()
    uid = str(user_id)
    if uid not in memory:
        memory[uid] = []
    memory[uid].append({
        "message": message,
        "response": response,
        "timestamp": datetime.now().isoformat()
    })
    if len(memory[uid]) > 50:
        memory[uid] = memory[uid][-50:]
    save_memory(memory)

# === ОСНОВНАЯ ФУНКЦИЯ ОТВЕТА ===
async def chat_reply(user_id: int, message: str, photo_url: str = None) -> str:
    # 1. ЖЁСТКИЙ ПЕРЕХВАТ ВОПРОСОВ ПРО ЧЕМПИОНАТ (БЕЗ AI)
    f1_keywords = ['чемпионат', 'лидирует', 'очки', 'таблица', 'лидер', 'standings', 'championship']
    
    if any(word in message.lower() for word in f1_keywords):
        standings = await get_driver_standings(2026)
        if standings:
            answer = "🏆 **Чемпионат F1 2026:**\n\n"
            for s in standings[:5]:
                answer += f"{s['pos']}. **{s['driver']}** — {s['points']} очков ({s['team']})\n"
            return answer
        return "❌ Данные чемпионата временно недоступны"
    
    # 2. ПЕРЕХВАТ ВОПРОСОВ ПРО ПОСЛЕДНЮЮ ГОНКУ
    if any(word in message.lower() for word in ['последняя гонка', 'прошлая гонка', 'результаты']):
        race = await get_last_race_results(2026)
        if race:
            answer = f"🏁 **{race['name']}**\n\n"
            for r in race['results'][:5]:
                answer += f"{r['pos']}. {r['driver']} — {r['points']} очков\n"
            return answer
        return "❌ Данные последней гонки недоступны"
    
    # 3. ТЕХНИЧЕСКИЕ ВОПРОСЫ — ЧЕСТНЫЙ ОТВЕТ
    if any(word in message.lower() for word in ['мотор', 'двигатель', 'подвеска', 'аэродинамика', 'шины', 'клиппинг']):
        return "❌ Нет технических данных по сезону 2026. Jolpica API предоставляет только результаты и очки."
    
    # 4. ОСТАЛЬНЫЕ ВОПРОСЫ — КРАТКИЙ AI
    memory = get_memory(user_id, 5)
    context = ""
    for m in memory[-3:]:
        context += f"Пользователь: {m['message']}\nНико: {m['response']}\n"
    
    prompt = f"""Ты Нико. Отвечай кратко, 1-2 предложения.
У тебя нет знаний о 2026 годе. Не выдумывай.
Если не знаешь — скажи 'Нет данных'.

История: {context}
Вопрос: {message}
Ответ:"""
    
    answer = await ask_ai(prompt, image_url=photo_url)
    
    if len(answer) > 400:
        answer = answer[:400] + "..."
    
    save_to_memory(user_id, message, answer)
    return answer

def clean_post(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    if len(text) > 1800:
        text = text[:text.rfind('.', 0, 1800)+1]
    return text.strip()

async def random_post() -> str:
    prompt = "Напиши случайный пост о Формуле-1 (заголовок жирным, 5-7 предложений)."
    post = await ask_ai(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

async def post_on_topic(topic: str) -> str:
    prompt = f"Напиши пост о Формуле-1 на тему: {topic}. Заголовок жирным, 4-6 предложений."
    post = await ask_ai(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

async def get_calendar() -> str:
    return """📅 Календарь F1 2026
7 июня — Монако
14 июня — Барселона
28 июня — Австрия
5 июля — Великобритания
19 июля — Бельгия
26 июля — Венгрия
23 августа — Нидерланды
#F1 #Calendar2026"""

async def analyze_photo(photo_url: str) -> str:
    prompt = "Ты гоночный инженер. Проанализируй это фото: что за машина, технические особенности?"
    return await ask_ai(prompt, image_url=photo_url)

# === RSS МОНИТОРИНГ ===
pending_posts = []
posted_hashes = set()

def load_hashes():
    global posted_hashes
    try:
        with open(HASH_FILE, 'r') as f:
            posted_hashes = set(json.load(f))
    except:
        posted_hashes = set()

def save_hash(h):
    posted_hashes.add(h)
    with open(HASH_FILE, 'w') as f:
        json.dump(list(posted_hashes), f)

def mark_posted(title, link):
    h = hashlib.md5(f"{title}{link}".encode()).hexdigest()
    save_hash(h)

def is_posted(title, link):
    h = hashlib.md5(f"{title}{link}".encode()).hexdigest()
    return h in posted_hashes

async def generate_post_from_news(title, content):
    prompt = f"Напиши пост о Формуле-1. Новость: {title}. Детали: {content[:500]}. Заголовок жирным, 3-5 абзацев, только факты. В конце #F1"
    post = await ask_ai(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

async def monitor():
    load_hashes()
    last = {}
    while True:
        for src in RSS_SOURCES:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(src, timeout=15) as resp:
                        if resp.status == 200:
                            feed = feedparser.parse(await resp.text())
                            if feed.entries:
                                entry = feed.entries[0]
                                link = entry.get('link', '')
                                key = f"{src}_{link}"
                                if key == last.get(src):
                                    continue
                                last[src] = key
                                if is_posted(entry.get('title', ''), link):
                                    continue
                                post = await generate_post_from_news(
                                    entry.get('title', ''),
                                    entry.get('summary', '')[:500]
                                )
                                pending_posts.append({
                                    "post": post,
                                    "title": entry.get('title', ''),
                                    "link": link
                                })
                                print(f"📰 Новость: {entry.get('title', '')[:50]}...")
            except Exception as e:
                print(f"Monitor error for {src}: {e}")
        await asyncio.sleep(60)

def get_pending_posts():
    return pending_posts

def clear_pending_posts():
    global pending_posts
    pending_posts = []

def set_pending_posts(posts):
    global pending_posts
    pending_posts = posts

async def morning_digest() -> str:
    news = []
    for src in RSS_SOURCES[:1]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(src, timeout=10) as resp:
                    if resp.status == 200:
                        feed = feedparser.parse(await resp.text())
                        for entry in feed.entries[:3]:
                            news.append(entry.get('title', ''))
        except:
            pass
    news_text = "\n".join([f"{i+1}. {title}" for i, title in enumerate(news[:3])]) if news else "Нет свежих новостей"
    return f"""☀️ Доброе утро, RedRace!
📅 {datetime.now().strftime('%d.%m.%Y')}
🏆 Топ новостей дня:
{news_text}
Red Race | Подписаться"""

# === ПЕРСОНАЖИ ===
REDRACE_CHARACTERS = {
    "Псиникс": "Ебланище конченное. Работает в РедРейзе. Роман с Райконненом. Проебал 10кк поставив на Пиастри.",
    "Вхуй": "Уебище жирное. Сирота, лучший дизайнер которого знает Кими, но который нихуя не делает. Вообщем ДОЛБАЕБ.",
    "Кими": "Создатель канала РедРейз. Муж Псиникса и уебанище. Топ 1 по заглатыванию)))!!!!",
    "Макс_Это_Скам": "я хз кто он. Он влиятельный хуй какой-то. Что ещё сказать.",
    "Пьер Гасли": "нормальный тип не придраться, но он хуесос т.к. не скинул мне свой писюн в ЛС и общается с ДЕВУШКОЙ!!! ФУУУУ",
    "Пиастри": "Уебище из за которого Псиникс проебал 10кк. Хуесос и спермобак. Из лучших моментов отмечу то что не оставил сурка в обиде и проторанил Албона на 12 круге гранд при Канады.",
    "Берман": "Нытик и конченное уебище которое ездит по гравию больше чем по дороге. Не умеет играть. Понял и съебался в ужасе бездарь",
    "Хирошима": "ООООО ФЕРНАНДО АЛООООНСО. Ничего сказать не могу. Долбаеб.",
    "СанРайз": "жирное уебище, конченный психопат.",
    "Акира": "главное хуйло чата. Это животное тупое, но умеет контрить. Живет в штрафостане не понимает животный язык. (Возможно играет в пабг)",
    "Артур": "тип на которого надеялся весь чат Монопосто, но в итоге так позорно проебал во Франции.",
    "МохмедАлл": "Съебись с чата и хватит просить у всех подряд Ливреи на то или иную хуйню. Всем ПОХУЙ. Чат Руссифицирован"
}

def get_random_character():
    name, desc = random.choice(list(REDRACE_CHARACTERS.items()))
    return f"🎭 <b>Ты — {name}</b>\n\n{desc}\n\n#RedRace"
