import sqlite3
from datetime import datetime
from typing import List, Dict, Optional

DB_PATH = "nico_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # История диалогов
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT, message TEXT, response TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Посты в канал
    c.execute('''CREATE TABLE IF NOT EXISTS posts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  text TEXT, photo_url TEXT, published_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Статистика пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS user_stats
                 (user_id TEXT PRIMARY KEY,
                  username TEXT, first_name TEXT,
                  first_seen DATETIME, last_seen DATETIME,
                  messages_count INTEGER DEFAULT 0)''')
    
    # Баг-репорты
    c.execute('''CREATE TABLE IF NOT EXISTS bug_reports
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT, message TEXT, status TEXT DEFAULT 'new',
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()
    conn.close()
    print("✅ База данных готова")

def save_conversation(user_id: int, message: str, response: str, username: str = None, first_name: str = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO chat_history (user_id, message, response) VALUES (?, ?, ?)",
              (str(user_id), message, response))
    
    now = datetime.now()
    c.execute('''INSERT INTO user_stats (user_id, username, first_name, first_seen, last_seen, messages_count)
                 VALUES (?, ?, ?, ?, ?, 1)
                 ON CONFLICT(user_id) DO UPDATE SET
                 username = COALESCE(?, username),
                 first_name = COALESCE(?, first_name),
                 last_seen = ?,
                 messages_count = messages_count + 1''',
              (str(user_id), username, first_name, now, now, username, first_name, now))
    conn.commit()
    conn.close()

def get_stats() -> Dict[str, int]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    posts = c.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    dialogs = c.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0]
    users = c.execute("SELECT COUNT(*) FROM user_stats").fetchone()[0]
    bugs = c.execute("SELECT COUNT(*) FROM bug_reports WHERE status='new'").fetchone()[0]
    conn.close()
    return {"posts": posts, "dialogs": dialogs, "users": users, "bugs": bugs}

def get_all_users(limit: int = 100) -> List[tuple]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, messages_count, last_seen FROM user_stats ORDER BY messages_count DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def clear_all_history():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM chat_history")
    c.execute("DELETE FROM user_stats")
    conn.commit()
    conn.close()

def save_bug_report(user_id: int, message: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO bug_reports (user_id, message) VALUES (?, ?)", (str(user_id), message))
    conn.commit()
    conn.close()
