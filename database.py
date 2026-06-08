import sqlite3
from datetime import datetime

DB_PATH = "nico_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT, message TEXT, response TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS posts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  text TEXT, media_type TEXT, media_id TEXT,
                  published_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_stats
                 (user_id TEXT PRIMARY KEY,
                  username TEXT, first_name TEXT,
                  first_seen DATETIME, last_seen DATETIME,
                  messages_count INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS donations
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT, amount INTEGER,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()
    print("✅ База данных готова")

def save_conversation(user_id, message, response, username=None, first_name=None):
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

def save_post(text, media_type=None, media_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO posts (text, media_type, media_id) VALUES (?, ?, ?)", (text, media_type, media_id))
    conn.commit()
    conn.close()

def save_donation(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO donations (user_id, amount) VALUES (?, ?)", (str(user_id), amount))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    posts = c.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    dialogs = c.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0]
    users = c.execute("SELECT COUNT(*) FROM user_stats").fetchone()[0]
    donations = c.execute("SELECT SUM(amount) FROM donations").fetchone()[0] or 0
    conn.close()
    return {"posts": posts, "dialogs": dialogs, "users": users, "donations": donations}

def get_all_users(limit=50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, messages_count FROM user_stats ORDER BY messages_count DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def clear_all_history():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM chat_history")
    c.execute("DELETE FROM user_stats")
    c.execute("DELETE FROM posts")
    conn.commit()
    conn.close()
