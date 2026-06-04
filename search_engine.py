import asyncio
import aiohttp
import random
import re
from datetime import datetime, timedelta
from duckduckgo_search import DDGS
from fake_useragent import UserAgent

ua = UserAgent()
search_cache = {}

SEARXNG_INSTANCES = [
    "https://opnxng.com",
    "https://priv.au",
    "https://searx.perennialte.ch",
    "https://search.canine.tools",
    "https://search.catboy.house",
    "https://searx.work",
    "https://searx.be",
]

def _parse_searxng_html(html: str, max_results: int) -> str:
    results = []
    article_pattern = r'<article class="result[^>]*>(.*?)</article>'
    articles = re.findall(article_pattern, html, re.DOTALL)
    
    for article in articles[:max_results]:
        title_match = re.search(r'<h[3|4][^>]*><a href="([^"]+)"[^>]*>(.*?)</a></h[3|4]>', article, re.DOTALL)
        if not title_match:
            continue
        link = title_match.group(1)
        title = re.sub(r'<[^>]+>', '', title_match.group(2)).strip()
        
        if any(x in title.lower() for x in ['wikipedia', 'covid', 'википедия', 'пандемия', 'multiple sclerosis']):
            continue
        
        desc_match = re.search(r'<p class="content"[^>]*>(.*?)</p>', article, re.DOTALL)
        description = re.sub(r'<[^>]+>', '', desc_match.group(1)).strip() if desc_match else ''
        
        results.append(f"📌 **{title}**\n📄 {description[:500]}\n🔗 {link}\n\n")
    
    if results:
        return "🌐 **Результаты поиска:**\n\n" + "".join(results[:max_results])
    return None

async def _search_searxng_html(query: str, max_results: int = 5) -> str:
    cache_key = query.lower().strip()
    if cache_key in search_cache:
        result, timestamp = search_cache[cache_key]
        if datetime.now() - timestamp < timedelta(minutes=15):
            return result

    instances = SEARXNG_INSTANCES.copy()
    random.shuffle(instances)

    for instance in instances:
        try:
            url = f"{instance}/search?q={query}"
            headers = {'User-Agent': ua.random}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=15) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        results = _parse_searxng_html(html, max_results)
                        if results:
                            search_cache[cache_key] = (results, datetime.now())
                            return results
        except Exception as e:
            print(f"Ошибка {instance}: {e}")
            continue
    return None

async def _search_ddg(query: str, max_results: int = 5) -> str:
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
            if not results:
                return None
            formatted = "🌐 **Результаты поиска (DDG):**\n\n"
            count = 0
            for r in results:
                if count >= max_results:
                    break
                title = r.get('title', '')
                body = r.get('body', '')[:500]
                href = r.get('href', '')
                if any(x in title.lower() for x in ['wikipedia', 'covid', 'википедия']):
                    continue
                formatted += f"📌 **{title}**\n📄 {body}\n🔗 {href}\n\n"
                count += 1
            return formatted if count > 0 else None
    except Exception as e:
        print(f"DDG error: {e}")
        return None

async def search_web(query: str, max_results: int = 5) -> str:
    result = await _search_searxng_html(query, max_results)
    if result:
        return result
    result = await _search_ddg(query, max_results)
    if result:
        return result
    return "❌ Не удалось найти информацию. Попробуй переформулировать запрос."
