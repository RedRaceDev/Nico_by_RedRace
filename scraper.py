import asyncio
import aiohttp
import feedparser
import hashlib
import json
import os
import re
import time
from datetime import datetime
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from openai import AsyncOpenAI
from fake_useragent import UserAgent
from cachetools import TTLCache
from dotenv import load_dotenv
from newspaper import Article
import concurrent.futures

load_dotenv()

# === КОНФИГ ===
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
openrouter_client = AsyncOpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1") if OPENROUTER_KEY else None

# === КЭШ ===
cache = TTLCache(maxsize=100, ttl=300)
ua = UserAgent()

# === ПУЛ ПОТОКОВ ===
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# === RSS ИСТОЧНИКИ ===
RSS_SOURCES = [
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.the-race.com/feed/",
    "https://www.planetf1.com/feed",
    "https://www.crash.net/f1/rss",
    "https://www.f1news.ru/export/news.xml"
]

# === СПОРТИВНЫЕ САЙТЫ ===
SPORTS_SITES = [
    "autosport.com", "motorsport.com", "the-race.com",
    "planetf1.com", "crash.net", "f1news.ru", "formula1.com"
]

# === ПАМЯТЬ О ПОСТАХ ===
HASH_FILE = "posted_hashes.json"

def load_hashes():
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_hash(h):
    hashes = load_hashes()
    hashes.add(h)
    with open(HASH_FILE, 'w') as f:
        json.dump(list(hashes), f)

def is_posted(title, link):
    h = hashlib.md5(f"{title}{link}".encode()).hexdigest()
    return h in load_hashes()

def mark_posted(title, link):
    h = hashlib.md5(f"{title}{link}".encode()).hexdigest()
    save_hash(h)

# === NEWSPAPER3K ===
def extract_article_sync(url: str) -> dict:
    try:
        article = Article(url)
        article.download()
        article.parse()
        article.nlp()
        return {
            "title": article.title,
            "text": article.text[:3000] if article.text else "",
            "summary": article.summary[:800] if article.summary else "",
            "top_image": article.top_image if article.top_image else None
        }
    except Exception as e:
        return {"title": "", "text": "", "summary": "", "top_image": None}

async def fetch_full_article(url: str) -> dict:
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(executor, extract_article_sync, url)
    except:
        return {"title": "", "text": "", "summary": "", "top_image": None}

# === ПОИСК ===
async def search_f1(query: str) -> str:
    try:
        with DDGS(headers={'User-Agent': ua.random}) as ddgs:
            site_query = " OR ".join([f"site:{s}" for s in SPORTS_SITES])
            results = ddgs.text(f"{query} ({site_query})", max_results=3)
            context = ""
            for r in results:
                context += f"🔍 **{r.get('title', '')}**\n"
                context += f"📝 {r.get('body', '')[:500]}\n"
                context += f"🔗 {r.get('href', '')}\n\n"
            return context if context else "Ничего не найдено"
    except Exception as e:
        return f"Ошибка поиска: {e}"

# === ПРОВЕРКИ ===
def is_valid_entry(entry) -> bool:
    title = entry.get('title', '').lower()
    banned = ['403', 'error', 'blocked', 'access denied', '404', '503']
    return not any(w in title for w in banned) and len(title) > 10

def is_real_news(text: str) -> bool:
    trash = ["смотрите также", "читайте также", "список десяти лучших"]
    return not any(m in text.lower() for m in trash)

def clean_post(text: str) -> str:
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'\*', '', text)
    text = re.sub(r'_{2,}', '', text)
    text = re.sub(r'_', '', text)
    if len(text) > 2000:
        text = text[:text.rfind('.', 0, 2000)+1]
    return text.strip()

# === LLM ===
async def ask_llm(prompt: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://text.pollinations.ai/",
                json={"messages": [{"role": "user", "content": prompt}], "model": "openai"},
                timeout=20
            ) as resp:
                if resp.status == 200:
                    return await resp.text()
    except:
        pass
    
    if openrouter_client:
        try:
            resp = await openrouter_client.chat.completions.create(
                model="openrouter/free",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.7
            )
            return resp.choices[0].message.content
        except:
            pass
    
    return "❌ ИИ недоступен"

# === ПЕРЕВОД ===
async def translate_text(text: str) -> str:
    if any(ru in text for ru in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"):
        return text
    prompt = f"Переведи на русский (только перевод): {text}"
    return await ask_llm(prompt)

# === ГЕНЕРАЦИЯ ПОСТА С ПРИМЕРАМИ ===
async def gen_post(title: str, content: str, source_url: str) -> str:
    title_ru = await translate_text(title)
    
    prompt = f"""Ты Нико. Напиши пост для Telegram-канала RedRace.

НОВОСТЬ: {title_ru}
ПОДРОБНОСТИ: {content[:1500]}

=== ПРИМЕРЫ ИДЕАЛЬНЫХ ПОСТОВ ===

ПРИМЕР 1 (новость Williams):
<b>В Барселоне откроется фан-зона Williams</b>

С 8 по 14 июня в Барселоне будет работать фан-зона Williams, где болельщики смогут быть ближе к команде, участвовать в розыгрыше призов, встретиться с Карлосом Сайнсом и руководителем команды Джеймсом Ваулзом.

На территории фан-зоны выставят шоу-кар FW48. Организатор — спонсор команды Kraken. Вход бесплатный.

ПРИМЕР 2 (благотворительный аукцион):
<b>Гонщики поддержали благотворительный аукцион в Монако</b>

Шарль Леклер, Фернандо Алонсо, Ландо Норрис, Ален Прост и Оскар Пиастри передали лоты для акции Formula One for Life, организованной при поддержке князя Альбера II.

Аукцион будет проходить в дни Гран‑при Монако, а вырученные средства пойдут в фонд «Антуан Аллено», помогающий семьям, потерявшим детей в ДТП, и финансирующий проекты по повышению дорожной безопасности.

=== ПРАВИЛА ===
1. Заголовок — жирным <b>в первой строке</b>, без точки в конце
2. Пиши на русском
3. 3-5 предложений
4. Называй конкретные даты, места, имена, цифры, спонсоров
5. Не добавляй хештеги в текст
6. Не пиши "Red Race | Подписаться" — это добавится автоматически

ПОСТ:"""
    
    post = await ask_llm(prompt)
    post = clean_post(post)
    return post + "\n\nRed Race | Подписаться"

# === ОЦЕНКА КАЧЕСТВА ===
async def rate_post(post: str, title: str) -> bool:
    prompt = f"Оцени пост от 0 до 100. Только число.\n\nНАЗВАНИЕ: {title}\nПОСТ: {post[:600]}\n\nОЦЕНКА:"
    resp = await ask_llm(prompt)
    try:
        score = int(re.search(r'\d+', resp).group())
        return score >= 65
    except:
        return True

# === УТРЕННИЙ ДАЙДЖЕСТ ===
async def get_morning_digest() -> str:
    news = []
    for src in RSS_SOURCES:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(src, timeout=15, headers={'User-Agent': ua.random}) as resp:
                    if resp.status == 200:
                        feed = feedparser.parse(await resp.text())
                        for entry in feed.entries[:1]:
                            news.append({"title": entry.get('title', '')})
        except:
            continue
    
    news_text = ""
    for i, item in enumerate(news[:5], 1):
        title_ru = await translate_text(item['title'])
        news_text += f"{i}. {title_ru}\n"
    
    digest = (
        f"☀️ Доброе утро, RedRace!\n\n"
        f"📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
        f"🏆 Топ новостей дня:\n{news_text}\n"
        f"📅 Ближайшие гонки:\n• Гран-при Монако — 07.06\n\n"
        f"<code>Nico | RedRace Development</code>"
    )
    
    return digest

# === КАЛЕНДАРЬ ===
async def get_f1_calendar() -> str:
    return """📅 **Календарь F1 2026**

Май: 03 Майами, 24 Канада
Июнь: 07 Монако, 14 Барселона, 28 Австрия
Июль: 05 Великобритания, 19 Бельгия, 26 Венгрия
Август: 23 Нидерланды
Сентябрь: 06 Италия, 13 Испания, 26 Азербайджан
Октябрь: 11 Сингапур, 25 США
Ноябрь: 01 Мексика, 08 Бразилия, 21 Лас-Вегас, 29 Катар
Декабрь: 06 Абу-Даби

#F1 #Calendar2026"""

# === РАНДОМНЫЙ ПОСТ ===
async def random_post() -> str:
    prompt = """Ты Нико. Напиши пост о Формуле-1. Заголовок жирным. 5-7 предложений. На русском.

ПРИМЕР:
<b>Технические новинки F1: граунд-эффект возвращается</b>

С 2026 года команды получили новые правила по аэродинамике. Главное изменение — упрощение днища и ограничение сложных дефлекторов.

Инженеры говорят, что это снизит прижимную силу на 15-20%, но сделает гонки более непредсказуемыми. Ferrari и Red Bull уже тестируют новые решения в симуляторе."""
    
    post = await ask_llm(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

# === ПОСТ НА ТЕМУ ===
async def post_on_topic(topic: str) -> str:
    prompt = f"""Ты Нико. Напиши пост о Формуле-1 на тему: {topic}. Заголовок жирным. 4-6 предложений. На русском.

ПРИМЕРЫ:
- Если тема про Ferrari: <b>Ferrari готовит новый мотор для 2026</b>
- Если тема про пилотов: <b>Хэмилтон продлил контракт с Mercedes</b>
- Если тема про технологии: <b>Гибридные системы станут мощнее</b>"""
    
    post = await ask_llm(prompt)
    return clean_post(post) + "\n\nRed Race | Подписаться"

# === ЧАТ ===
async def chat_reply(msg: str) -> str:
    prompt = f"""Ты Нико, гоночный инженер. Ответь кратко, по делу.

Вопрос: {msg}"""
    return await ask_llm(prompt)

# === МОНИТОРИНГ ===
async def monitor(callback):
    last = {}
    while True:
        for src in RSS_SOURCES:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(src, timeout=15, headers={'User-Agent': ua.random}) as resp:
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
                                
                                article = await fetch_full_article(link)
                                content = article.get("text", "") or article.get("summary", "") or entry.get('summary', '')
                                
                                if not content or not is_real_news(content):
                                    mark_posted(entry.get('title', ''), link)
                                    continue
                                
                                post = await gen_post(entry.get('title', ''), content, link)
                                
                                if await rate_post(post, entry.get('title', '')):
                                    await callback(post, entry.get('title', ''), link)
                                else:
                                    mark_posted(entry.get('title', ''), link)
            except:
                continue
        
        await asyncio.sleep(60)
