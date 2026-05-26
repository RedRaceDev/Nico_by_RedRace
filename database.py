import sqlite3
import json
from datetime import datetime

DB_PATH = "nico_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Таблица для истории диалогов
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history
                 (user_id INTEGER, message TEXT, response TEXT, timestamp DATETIME)''')
    
    # Таблица для постов
    c.execute('''CREATE TABLE IF NOT EXISTS posts
                 (id INTEGER PRIMARY KEY, text TEXT, photo_url TEXT, published_at DATETIME)''')
    
    # Таблица для настроек пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS user_settings
                 (user_id INTEGER PRIMARY KEY, chat_mode BOOLEAN, language TEXT)''')
    
    # Таблица для кэша поиска (чтобы не искать одно и то же дважды)
    c.execute('''CREATE TABLE IF NOT EXISTS search_cache
                 (query TEXT PRIMARY KEY, result TEXT, timestamp DATETIME)''')
    
    conn.commit()
    conn.close()

def save_conversation(user_id, message, response):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO chat_history (user_id, message, response, timestamp) VALUES (?, ?, ?, ?)",
              (user_id, message, response, datetime.now()))
    conn.commit()
    conn.close()

def get_conversation_history(user_id, limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT message, response FROM chat_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
              (user_id, limit))
    rows = c.fetchall()
    conn.close()
    
    history = []
    for msg, resp in reversed(rows):
        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": resp})
    return history

def save_post(text, photo_url):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO posts (text, photo_url, published_at) VALUES (?, ?, ?)",
              (text, photo_url, datetime.now()))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    posts_count = c.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    chats_count = c.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0]
    conn.close()
    return {"posts": posts_count, "chats": chats_count}

def cache_search(query, result):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO search_cache (query, result, timestamp) VALUES (?, ?, ?)",
              (query, result, datetime.now()))
    conn.commit()
    conn.close()

def get_cached_search(query, max_age_hours=24):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT result, timestamp FROM search_cache WHERE query = ?", (query,))
    row = c.fetchone()
    conn.close()
    if row:
        result, timestamp = row
        age = (datetime.now() - datetime.fromisoformat(timestamp)).total_seconds() / 3600
        if age < max_age_hours:
            return result
    return None
