import sqlite3
from datetime import datetime

DB_PATH = "nico_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT,
                  message TEXT,
                  response TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS posts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  text TEXT,
                  photo_url TEXT,
                  published_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_stats
                 (user_id TEXT PRIMARY KEY,
                  username TEXT,
                  first_name TEXT,
                  last_name TEXT,
                  first_seen DATETIME,
                  last_seen DATETIME,
                  messages_count INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS bug_reports
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT,
                  message TEXT,
                  status TEXT DEFAULT 'new',
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
    c.execute('''INSERT INTO user_stats 
                 (user_id, username, first_name, first_seen, last_seen, messages_count)
                 VALUES (?, ?, ?, ?, ?, 1)
                 ON CONFLICT(user_id) DO UPDATE SET
                 username = COALESCE(?, username),
                 first_name = COALESCE(?, first_name),
                 last_seen = ?,
                 messages_count = messages_count + 1''',
              (str(user_id), username, first_name, now, now,
               username, first_name, now))
    conn.commit()
    conn.close()

def save_post(text, photo_url=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO posts (text, photo_url) VALUES (?, ?)", (text, photo_url))
    conn.commit()
    conn.close()

def save_bug_report(user_id, message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO bug_reports (user_id, message) VALUES (?, ?)", (str(user_id), message))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    posts = c.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    dialogs = c.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0]
    users = c.execute("SELECT COUNT(*) FROM user_stats").fetchone()[0]
    bugs = c.execute("SELECT COUNT(*) FROM bug_reports WHERE status = 'new'").fetchone()[0]
    conn.close()
    return {"posts": posts, "dialogs": dialogs, "users": users, "bugs": bugs}

def get_all_users(limit=100):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, messages_count, last_seen FROM user_stats ORDER BY messages_count DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_user_message_count(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT messages_count FROM user_stats WHERE user_id = ?", (str(user_id),))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def get_last_dialogs(limit=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT user_id, message, response, timestamp FROM chat_history
                 ORDER BY timestamp DESC LIMIT ?''', (limit,))
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

def get_bug_reports(status="new"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, user_id, message, created_at FROM bug_reports WHERE status = ? ORDER BY created_at DESC", (status,))
    rows = c.fetchall()
    conn.close()
    return rows

def update_bug_status(bug_id, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE bug_reports SET status = ? WHERE id = ?", (status, bug_id))
    conn.commit()
    conn.close()
