import asyncio
import random
import aiohttp
import re
from datetime import datetime, timedelta
from google import genai
import os

# === GEMINI ДЛЯ УТОЧНЕНИЯ ЗАПРОСОВ ===
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    gemini_model = genai.GenerativeModel('gemini-2.0-flash-lite')
else:
    gemini_model = None

# === КЭШ ===
search_cache = {}

# === РАБОЧИЕ ИНСТАНСЫ SEARXNG ===
SEARXNG_INSTANCES = [
    "https://searx.tiekoetter.com",
    "https://searx.ninja",
    "https://search.sapti.me",
    "https://searx.work",
    "https://searx.be",
]

async def _enhance_query_with_ai(original_query: str) -> str:
    """Уточняет запрос через Gemini для новостей F1"""
    if not gemini_model:
        return f"{original_query} Формула-1 новости 2026"
    
    prompt = f"""
    Ты помощник для новостного бота про Формулу-1.
    Преврати запрос пользователя в точный поисковый запрос для новостей.
    Добавь "Формула-1", "F1", "новости", "2026".
    Верни ТОЛЬКО строку запроса.

    Запрос: {original_query}
    Ответ:"""
    
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: gemini_model.generate_content(prompt)
        )
        enhanced = response.text.strip()
        print(f"🔍 AI: '{original_query}' → '{enhanced}'")
        return enhanced
    except:
        return f"{original_query} Формула-1 F1 новости 2026"

async def search_searxng(query: str, max_results: int = 5) -> str:
    """Поиск через SearXNG — без ключей, без банов"""
    cache_key = query.lower().strip()
    if cache_key in search_cache:
        result, timestamp = search_cache[cache_key]
        if datetime.now() - timestamp < timedelta(minutes=30):
            return result

    instances = SEARXNG_INSTANCES.copy()
    random.shuffle(instances)

    for instance in instances:
        try:
            url = f"{instance}/search?q={query}&format=json&categories=news"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])
                        if results:
                            formatted = "🌐 **Результаты поиска:**\n\n"
                            count = 0
                            for res in results:
                                title = res.get('title', '')
                                url_res = res.get('url', '#')
                                content = res.get('content', '')[:500]
                                # Пропускаем явный мусор
                                if any(x in title.lower() for x in ['wikipedia', 'covid', 'википедия']):
                                    continue
                                formatted += f"📌 **{title}**\n📄 {content}\n🔗 {url_res}\n\n"
                                count += 1
                                if count >= max_results:
                                    break
                            if count > 0:
                                search_cache[cache_key] = (formatted, datetime.now())
                                return formatted
        except Exception as e:
            print(f"SearXNG error {instance}: {e}")
            continue

    return "❌ Не удалось найти новости. Попробуй позже."

async def search_web(query: str, max_results: int = 5) -> str:
    """Главная функция поиска"""
    enhanced = await _enhance_query_with_ai(query)
    return await search_searxng(enhanced, max_results)
