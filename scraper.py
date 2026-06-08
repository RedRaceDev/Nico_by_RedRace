# scraper.py
import asyncio
import os
import json
import re
import hashlib
import random
import aiohttp
import feedparser
from datetime import datetime
from cachetools import TTLCache
import openai

# === OPENROUTER ===
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")

OPENROUTER_MODELS = [
    "nex-agi/nex-n2-pro:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter/free"
]

# === КОНФИГ ===
ADMIN_IDS = [7025868617]
CHANNEL_ID = "@RedRaceF1"
MEMORY_FILE = "memory.json"
HASH_FILE = "posted_hashes.json"

RSS_SOURCES = [
    "https://www.f1news.ru/export/news.xml",
    "https://www.autosport.com/rss/feed/f1",
    "https://www.motorsport.com/rss/f1/news/",
]

# === КЕШ ===
standings_cache = TTLCache(maxsize=1, ttl=3600)

# === FALLBACK ===
FALLBACK_STANDINGS = [
    {"pos": 1, "driver": "Kimi Antonelli", "points": 156, "team": "Mercedes"},
    {"pos": 2, "driver": "George Russell", "points": 88, "team": "Mercedes"},
    {"pos": 3, "driver": "Charles Leclerc", "points": 75, "team": "Ferrari"},
    {"pos": 4, "driver": "Lewis Hamilton", "points": 72, "team": "Ferrari"},
    {"pos": 5, "driver": "Lando Norris", "points": 58, "team": "McLaren"}
]

# === AI ===
async def ask_ai(prompt: str) -> str:
    if not OPENROUTER_KEY:
        return "❌ Ключ OpenRouter не найден"
    
    client = openai.AsyncOpenAI(
        api_key=OPENROUTER_KEY,
        base_url="https://openrouter.ai/api/v1"
    )
    
    for model in OPENROUTER_MODELS:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.3,
                timeout=25
            )
            if response and response.choices:
                return response.choices[0].message.content
        except Exception as e:
            print(f"AI error: {e}")
            continue
    
    return "❌ AI временно недоступен"

# === F1 ===
async def get_driver_standings(year=2026):
    if "standings_2026" in standings_cache:
        return standings_cache["standings_2026"]
    return FALLBACK_STANDINGS.copy()

async def get_next_race(year=2026):
    return {"name": "Гран-при Испании", "date": "14 июня 2026", "circuit": "Барселона"}

async def get_race_schedule(year=2026):
    return [
        {"round": 1, "name": "Гран-при Австралии", "date": "06.03.2026", "circuit": "Мельбурн"},
        {"round": 8, "name": "Гран-при Монако", "date": "05.06.2026", "circuit": "Монако"},
    ]

# === ПАМЯТЬ ===
def load_memory():
    try:
        with open(MEMORY_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_memory(memory):
    with open(MEMORY_FILE, 'w') as f:
