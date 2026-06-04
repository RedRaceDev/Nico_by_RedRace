import asyncio
from typing import Optional, List, Dict

# Пытаемся импортировать wizsearch, если нет — fallback на старый метод
try:
    from wizsearch import WizSearch
    WIZSEARCH_AVAILABLE = True
    print("✅ WizSearch загружен")
except ImportError:
    WIZSEARCH_AVAILABLE = False
    print("⚠️ WizSearch не найден, использую fallback")
    from duckduckgo_search import AsyncDDGS

# Кеш для результатов
search_cache = {}
CACHE_TTL = 300  # 5 минут

async def search_web(query: str, max_results: int = 5) -> str:
    """Основная функция поиска с автоматическим выбором движка"""
    
    # Проверяем кеш
    cache_key = query.lower().strip()
    if cache_key in search_cache:
        result, timestamp = search_cache[cache_key]
        if asyncio.get_event_loop().time() - timestamp < CACHE_TTL:
            return result
    
    # Выбираем движок
    if WIZSEARCH_AVAILABLE:
        result = await search_with_wizsearch(query, max_results)
    else:
        result = await search_with_ddg(query, max_results)
    
    # Сохраняем в кеш
    if result and "❌" not in result:
        search_cache[cache_key] = (result, asyncio.get_event_loop().time())
    
    return result or "❌ Не удалось найти информацию. Попробуй переформулировать запрос."

async def search_with_wizsearch(query: str, max_results: int = 5) -> Optional[str]:
    """Поиск через WizSearch (multi-engine)"""
    try:
        searcher = WizSearch(
            engines=["duckduckgo", "brave"],  # DDG + Brave как резерв
            max_results=max_results,
            timeout=15
        )
        
        results = await searcher.search(query)
        
        if not results:
            return None
        
        # Фильтруем мусор
        filtered = []
        for r in results[:max_results]:
            title = r.get('title', '')
            url = r.get('url', '')
            content = r.get('content', '')[:500]
            
            # Пропускаем википедию и мусор
            if any(x in title.lower() for x in ['wikipedia', 'covid', 'википедия']):
                continue
            
            filtered.append({
                'title': title,
                'content': content,
                'url': url
            })
        
        if not filtered:
            return None
        
        # Форматируем вывод
        formatted = "🌐 **Результаты поиска (WizSearch):**\n\n"
        for r in filtered[:max_results]:
            formatted += f"📌 **{r['title']}**\n"
            formatted += f"📄 {r['content']}\n"
            formatted += f"🔗 {r['url']}\n\n"
        
        return formatted
        
    except Exception as e:
        print(f"WizSearch error: {e}")
        return None

async def search_with_ddg(query: str, max_results: int = 5) -> Optional[str]:
    """Fallback поиск через DuckDuckGo"""
    try:
        async with AsyncDDGS() as ddgs:
            results = []
            async for r in ddgs.atext(query, max_results=max_results):
                results.append(r)
            
            if not results:
                return None
            
            formatted = "🌐 **Результаты поиска (DDG):**\n\n"
            for r in results[:max_results]:
                title = r.get('title', '')
                body = r.get('body', '')[:500]
                href = r.get('href', '')
                
                if any(x in title.lower() for x in ['wikipedia', 'covid', 'википедия']):
                    continue
                
                formatted += f"📌 **{title}**\n"
                formatted += f"📄 {body}\n"
                formatted += f"🔗 {href}\n\n"
            
            return formatted if "📌" in formatted else None
            
    except Exception as e:
        print(f"DDG error: {e}")
        return None

async def search_news(query: str, max_results: int = 3) -> str:
    """Поиск только новостей (для мониторинга)"""
    if WIZSEARCH_AVAILABLE:
        try:
            searcher = WizSearch(
                engines=["duckduckgo"],
                max_results=max_results,
                timeout=10
            )
            results = await searcher.search(f"{query} F1 news 2026")
            
            if results:
                formatted = "📰 **Свежие новости:**\n\n"
                for r in results[:max_results]:
                    formatted += f"📌 **{r.get('title', '')}**\n"
                    formatted += f"🔗 {r.get('url', '')}\n\n"
                return formatted
        except:
            pass
    
    return await search_with_ddg(f"{query} F1 news", max_results)
