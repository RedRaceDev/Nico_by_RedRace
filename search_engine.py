import asyncio
import random
import aiohttp
from datetime import datetime, timedelta
from ddg_rs import safe_search, SearchParams

# === КЭШ ===
search_cache = {}

# === ПУБЛИЧНЫЕ ИНСТАНСЫ SEARXNG ===
SEARXNG_INSTANCES = [
    "https://searx.tiekoetter.com",
    "https://searx.ninja",
    "https://search.sapti.me",
    "https://searx.work",
    "https://searx.be",
]

async def search_searxng(query: str, max_results: int = 5) -> str:
    """Поиск через SearXNG — бесплатно, без ключей, 70+ источников"""
    cache_key = query.lower().strip()
    if cache_key in search_cache:
        result, timestamp = search_cache[cache_key]
        if datetime.now() - timestamp < timedelta(minutes=30):
            return result

    instances = SEARXNG_INSTANCES.copy()
    random.shuffle(instances)

    for instance in instances:
        try:
            url = f"{instance}/search?q={query}&format=json&categories=general"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])
                        if results:
                            formatted = "🔍 **Результаты поиска:**\n\n"
                            for res in results[:max_results]:
                                title = res.get('title', 'Без названия')
                                url_res = res.get('url', '#')
                                content = res.get('content', 'Нет описания')[:500]
                                formatted += f"📌 **{title}**\n📄 {content}\n🔗 {url_res}\n\n"
                            search_cache[cache_key] = (formatted, datetime.now())
                            return formatted
        except Exception as e:
            print(f"SearXNG error {instance}: {e}")
            continue

    return await search_ddg(query, max_results)

async def search_ddg(query: str, max_results: int = 5) -> str:
    """Поиск через DuckDuckGo (fallback)"""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _search_ddg_sync, query, max_results)
        return result
    except Exception as e:
        return f"Ошибка поиска: {e}"

def _search_ddg_sync(query: str, max_results: int) -> str:
    try:
        with safe_search() as browser:
            params = SearchParams(query=query, max_results=max_results)
            results = browser.text(params)
            if not results:
                return "Ничего не найдено"
            context = "🔍 **Результаты поиска:**\n\n"
            for r in results:
                context += f"📌 **{r.title}**\n📄 {r.body[:500]}\n🔗 {r.url}\n\n"
            return context
    except Exception as e:
        return f"Ошибка: {e}"

async def search_web(query: str, max_results: int = 5) -> str:
    """Главная функция поиска — сначала SearXNG, потом DuckDuckGo"""
    return await search_searxng(query, max_results)
