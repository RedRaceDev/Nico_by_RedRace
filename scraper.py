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
import fastf1
import pandas as pd
from cachetools import TTLCache

# === НАСТРОЙКА FASTF1 ===
fastf1.Cache.enable_cache('f1_cache')
fastf1.set_log_level('WARNING')

# === КОНФИГ ===
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"
MEMORY_FILE = "memory.json"
HASH_FILE = "posted_hashes.json"

RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
]

# === API КЛЮЧ ===
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")

# === КЕШ ===
standings_cache = TTLCache(maxsize=1, ttl=3600)  # 1 час
race_cache = TTLCache(maxsize=1, ttl=3600)

# === ТЕСТОВЫЕ ДАННЫЕ (FALLBACK) ===
FALLBACK_STANDINGS = [
    {"pos": 1, "driver": "Kimi Antonelli", "points": 131, "team": "Mercedes"},
    {"pos": 2, "driver": "George Russell", "points": 88, "team": "Mercedes"},
    {"pos": 3, "driver": "Charles Leclerc", "points": 75, "team": "Ferrari"},
    {"pos": 4, "driver": "Lewis Hamilton", "points": 72, "team": "Ferrari"},
    {"pos": 5, "driver": "Lando Norris", "points": 58, "team": "McLaren"}
]

FALLBACK_RACE = {
    "name": "Гран-при Канады 2026",
    "results": [
        {"pos": 1, "driver": "Kimi Antonelli", "points": 25},
        {"pos": 2, "driver": "George Russell", "points": 18},
        {"pos": 3, "driver": "Charles Leclerc", "points": 15},
        {"pos": 4, "driver": "Lewis Hamilton", "points": 12},
        {"pos": 5, "driver": "Lando Norris", "points": 10}
    ]
}

# === AI ФУНКЦИЯ ===
async def ask_ai(prompt: str, image_url: str = None) -> str:
    if not OPENROUTER_KEY:
        return "❌ Ключ OpenRouter не найден"
    
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
    
    try:
        response = await client.chat.completions.create(
            model="mistralai/mistral-small-2603:free",
            messages=messages,
            max_tokens=800,
            temperature=0.3,
            timeout=25
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI error: {e}")
        return "❌ AI временно недоступен"

# === F1 DATA FUNCTIONS ===
async def get_driver_standings(year=2026):
    """Получить таблицу чемпионата (FastF1 → Fallback)"""
    if "standings_2026" in standings_cache:
        return standings_cache["standings_2026"]
    
    try:
        # FastF1
        schedule = fastf1.get_event_schedule(year)
        if schedule.empty:
            return FALLBACK_STANDINGS.copy()
        
        last_round = schedule['RoundNumber'].iloc[-1]
        session = fastf1.get_session(year, last_round, 'R')
        session.load()
        
        results = session.results[['Position', 'Abbreviation', 'Points', 'TeamName']]
        
        standings = []
        for idx, row in results.head(10).iterrows():
            standings.append({
                "pos": int(row['Position']),
                "driver": row['Abbreviation'],
                "points": int(row['Points']),
                "team": row['TeamName']
            })
        
        standings_cache["standings_2026"] = standings
        return standings
    except Exception as e:
        print(f"FastF1 standings error: {e}")
        return FALLBACK_STANDINGS.copy()

async def get_last_race_results(year=2026):
    """Получить результаты последней гонки (FastF1 → Fallback)"""
    if "race_2026" in race_cache:
        return race_cache["race_2026"]
    
    try:
        schedule = fastf1.get_event_schedule(year)
        if schedule.empty:
            return FALLBACK_RACE.copy()
        
        last_round = schedule['RoundNumber'].iloc[-1]
        session = fastf1.get_session(year, last_round, 'R')
        session.load()
        
        results = session.results[['Position', 'Abbreviation', 'Points']]
        
        race_results = []
        for idx, row in results.head(5).iterrows():
            race_results.append({
                "pos": int(row['Position']),
                "driver": row['Abbreviation'],
                "points": int(row['Points'])
            })
        
        race_name = schedule[schedule['RoundNumber'] == last_round]['EventName'].values[0]
        result = {"name": race_name, "results": race_results}
        race_cache["race_2026"] = result
        return result
    except Exception as e:
        print(f"FastF1 race error: {e}")
        return FALLBACK_RACE.copy()

async def get_next_race(year=2026):
    """Получить следующую гонку"""
    try:
        schedule = fastf1.get_event_schedule(year)
        if schedule.empty:
            return {"name": "TBD", "date": "TBD", "circuit": "TBD"}
        
        now = datetime.now()
        for _, row in schedule.iterrows():
            race_date = row['EventDate']
            if race_date > now:
                return {
                    "name": row['EventName'],
                    "date": race_date.strftime('%d.%m.%Y'),
                    "circuit": row['Location']
                }
        return {"name": "Сезон завершён", "date": "-", "circuit": "-"}
    except Exception as e:
        print(f"Next race error: {e}")
        return {"name": "TBD", "date": "TBD", "circuit": "TBD"}

async def get_race_schedule(year=2026):
    """Получить всё расписание сезона"""
    try:
        schedule = fastf1.get_event_schedule(year)
        races = []
        for _, row in schedule.iterrows():
            races.append({
                "round": int(row['RoundNumber']),
                "name": row['EventName'],
                "date": row['EventDate'].strftime('%d.%m.%Y'),
                "circuit": row['Location']
            })
        return races
    except Exception as e:
        print(f"Schedule error: {e}")
        return None

async def compare_drivers(driver1: str, driver2: str, year=2026, gp=None):
    """Сравнить телеметрию двух пилотов"""
    try:
        if gp is None:
            schedule = fastf1.get_event_schedule(year)
            if schedule.empty:
                return None
            last_round = schedule['RoundNumber'].iloc[-1]
            gp = schedule[schedule['RoundNumber'] == last_round]['EventName'].values[0]
        
        session = fastf1.get_session(year, gp, 'R')
        session.load()
        
        laps1 = session.laps.pick_driver(driver1.upper()).pick_fastest()
        laps2 = session.laps.pick_driver(driver2.upper()).pick_fastest()
        
        if laps1 is None or laps2 is None:
            return None
        
        tele1 = laps1.get_telemetry()
        tele2 = laps2.get_telemetry()
        
        return {
            "driver1": driver1.upper(),
            "time1": laps1['LapTime'].total_seconds(),
            "max_speed1": tele1['Speed'].max(),
            "driver2": driver2.upper(),
            "time2": laps2['LapTime'].total_seconds(),
            "max_speed2": tele2['Speed'].max()
        }
    except Exception as e:
        print(f"Compare error: {e}")
        return None

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
    except:
        pass

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
    # 1. Сравнение пилотов
    if 'сравни' in message.lower() and len(message.split()) >= 3:
        parts = message.split()
        driver1 = parts[1].upper()[:3]
        driver2 = parts[2].upper()[:3]
        comparison = await compare_drivers(driver1, driver2)
        if comparison:
            return (f"📊 **Сравнение {driver1} vs {driver2}:**\n\n"
                    f"🏁 {driver1}: {comparison['time1']:.2f} сек, max {comparison['max_speed1']:.0f} км/ч\n"
                    f"🏁 {driver2}: {comparison['time2']:.2f} сек, max {comparison['max_speed2']:.0f} км/ч")
    
    # 2. Чемпионат
    if any(word in message.lower() for word in ['чемпионат', 'лидирует', 'очки', 'таблица', 'standings']):
        standings = await get_driver_standings(2026)
        text = "🏆 **Чемпионат F1 2026:**\n\n"
        for s in standings[:5]:
            text += f"{s['pos']}. **{s['driver']}** — {s['points']} очков ({s['team']})\n"
        return text
    
    # 3. Календарь
    if 'календарь' in message.lower() or 'расписание' in message.lower():
        races = await get_race_schedule(2026)
        if races:
            text = "📅 **Календарь F1 2026:**\n\n"
            for r in races[:8]:
                text += f"**{r['round']}.** {r['name']} — {r['date']} ({r['circuit']})\n"
            return text
        return await get_calendar_fallback()
    
    # 4. Последняя гонка
    if any(word in message.lower() for word in ['последняя гонка', 'результаты', 'last race']):
        race = await get_last_race_results(2026)
        text = f"🏁 **{race['name']}**\n\n"
        for r in race['results'][:5]:
            text += f"{r['pos']}. {r['driver']} — {r['points']} очков\n"
        return text
    
    # 5. Следующая гонка
    if any(word in message.lower() for word in ['следующая гонка', 'next race']):
        next_race = await get_next_race(2026)
        return f"⏩ **Следующая гонка:**\n\n🏎️ {next_race['name']}\n📅 {next_race['date']}\n🏁 {next_race['circuit']}"
    
    # 6. Технические вопросы
    if any(word in message.lower() for word in ['мотор', 'двигатель', 'подвеска', 'аэродинамика', 'шины', 'клиппинг']):
        return "❌ Нет технических данных по сезону 2026. FastF1 предоставляет только результаты и телеметрию."
    
    # 7. AI ответ
    memory = get_memory(user_id, 5)
    context = ""
    for m in memory[-3:]:
        context += f"Пользователь: {m['message']}\nНико: {m['response']}\n"
    
    prompt = f"""Ты Нико, гоночный инженер. Отвечай кратко, 1-2 предложения.
У тебя нет знаний о 2026 годе. Не выдумывай факты.
Если не знаешь — скажи 'Нет данных' или используй команды.
История: {context}
Вопрос: {message}
Ответ:"""
    
    answer = await ask_ai(prompt, photo_url)
    if len(answer) > 400:
        answer = answer[:400] + "..."
    
    save_to_memory(user_id, message, answer)
    return answer

def get_calendar_fallback():
    return """📅 **Календарь F1 2026**

7 июня — Монако
14 июня — Барселона
28 июня — Австрия
5 июля — Великобритания
19 июля — Бельгия
26 июля — Венгрия
23 августа — Нидерланды
6 сентября — Италия
#F1 #Calendar2026"""

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
    prompt = f"""Напиши пост о Формуле-1. Новость: {title}
Детали: {content[:500]}
Заголовок жирным, 3-5 предложений, только факты. В конце #F1"""
    post = await ask_ai(prompt)
    post = re.sub(r'\*\*', '', post)
    return post + "\n\nRed Race | Подписаться"

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
                print(f"Monitor error: {src} - {e}")
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
    "Псиникс": "Ебланище конченное. Роман с Райконненом. Проебал 10кк на Пиастри.",
    "Вхуй": "Уебище жирное, дизайнер который нихуя не делает.",
    "Кими": "Создатель канала. Муж Псиникса.",
    "Пиастри": "Уебище из-за которого Псиникс проебал 10кк.",
    "СанРайз": "жирное уебище, конченный психопат.",
    "Акира": "главное хуйло чата. Живет в штрафостане.",
    "Артур": "позорно проебал во Франции.",
    "МохмедАлл": "Съебись с чата, всем ПОХУЙ на ливреи."
}

def get_random_character():
    name, desc = random.choice(list(REDRACE_CHARACTERS.items()))
    return f"🎭 **Ты — {name}**\n\n{desc}\n\n#RedRace"

# === ИНФОРМАЦИЯ О СИСТЕМЕ ===
def get_system_info() -> str:
    uptime = datetime.now() - datetime.fromtimestamp(os.path.getctime(MEMORY_FILE) if os.path.exists(MEMORY_FILE) else 0)
    return f"""ℹ️ **Информация о системе**

**Бот:** Нико 3.1
**Платформа:** aiogram 3.28
**Данные:** FastF1 + Jolpica
**AI:** OpenRouter (Mistral Small)

**Команды:**
/start — Главное меню
/info — Эта справка
/health — Диагностика
/reload — Очистить кеш (админ)

**Доступные кнопки:**
🏆 Чемпионат — Таблица лидеров
📅 Календарь — Расписание гонок
🏁 Последняя гонка — Результаты
⏩ Следующая гонка
🎭 Персонаж

**Пример сравнения:**
`сравни VER LEC` — сравнить Ферстаппена и Леклера

#RedRace #F1"""
