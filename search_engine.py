import asyncio
from duckduckgo_search import DDGS
from cachetools import TTLCache

# Кеш на 5 минут
search_cache = TTLCache(maxsize=100, ttl=300)

async def search_web(query: str, max_results: int = 5) -> str:
    """Поиск с кешем, через синхронный DDGS в потоке"""
    
    cache_key = query.lower().strip()
    if cache_key in search_cache:
        return search_cache[cache_key]
    
    try:
        # Запускаем синхронный поиск в отдельном потоке
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, 
            lambda: list(DDGS().text(query, max_results=max_results))
        )
        
        if not results:
            return "❌ Ничего не найдено. Попробуй переформулировать запрос."
        
        formatted = "🌐 **Результаты поиска (DuckDuckGo):**\n\n"
        for r in results[:max_results]:
            title = r.get('title', '')
            body = r.get('body', '')[:500]
            href = r.get('href', '')
            
            # Фильтр мусора
            junk = ['wikipedia', 'covid', 'википедия', 'multiple sclerosis', 
                    'johns hopkins', 'who.int', 'cdc.gov']
            if any(x in title.lower() for x in junk):
                continue
            
            formatted += f"📌 **{title}**\n"
            formatted += f"📄 {body}\n"
            formatted += f"🔗 {href}\n\n"
        
        if formatted == "🌐 **Результаты поиска (DuckDuckGo):**\n\n":
            return "❌ Ничего не найдено (все результаты отфильтрованы)"
        
        search_cache[cache_key] = formatted
        return formatted
        
    except Exception as e:
        print(f"Search error: {e}")
        return f"❌ Ошибка поиска: {e}"

async def search_news(query: str, max_results: int = 3) -> str:
    """Поиск новостей F1"""
    return await search_web(f"{query} Formula 1 2026", max_results)
