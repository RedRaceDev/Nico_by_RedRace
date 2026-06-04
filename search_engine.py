import asyncio
from duckduckgo_search import AsyncDDGS

search_cache = {}
CACHE_TTL = 300  # 5 минут

async def search_web(query: str, max_results: int = 5) -> str:
    """Основная функция поиска через DuckDuckGo"""
    
    # Проверяем кеш
    cache_key = query.lower().strip()
    if cache_key in search_cache:
        result, timestamp = search_cache[cache_key]
        if asyncio.get_event_loop().time() - timestamp < CACHE_TTL:
            return result
    
    try:
        async with AsyncDDGS() as ddgs:
            results = []
            async for r in ddgs.atext(query, max_results=max_results):
                results.append(r)
            
            if not results:
                return "❌ Ничего не найдено. Попробуй переформулировать запрос."
            
            formatted = "🌐 **Результаты поиска (DuckDuckGo):**\n\n"
            for r in results[:max_results]:
                title = r.get('title', '')
                body = r.get('body', '')[:500]
                href = r.get('href', '')
                
                # Фильтруем мусор
                if any(x in title.lower() for x in ['wikipedia', 'covid', 'википедия', 'multiple sclerosis']):
                    continue
                
                formatted += f"📌 **{title}**\n"
                formatted += f"📄 {body}\n"
                formatted += f"🔗 {href}\n\n"
            
            if formatted == "🌐 **Результаты поиска (DuckDuckGo):**\n\n":
                return "❌ Ничего не найдено (все результаты отфильтрованы)"
            
            # Сохраняем в кеш
            search_cache[cache_key] = (formatted, asyncio.get_event_loop().time())
            return formatted
            
    except Exception as e:
        print(f"Search error: {e}")
        return f"❌ Ошибка поиска: {str(e)}"

async def search_news(query: str, max_results: int = 3) -> str:
    """Поиск новостей (обёртка с фильтром)"""
    return await search_web(f"{query} formula 1 news 2026", max_results)
