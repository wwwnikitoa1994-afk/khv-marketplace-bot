import sqlite3

conn = sqlite3.connect("database.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS ads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    user_id INTEGER,
    username TEXT,

    action TEXT,
    category TEXT,

    title TEXT,
    description TEXT,

    condition TEXT,
    price TEXT,
    exchange TEXT,

    photos TEXT,

    message_id INTEGER,

    created_at TEXT,
    last_bump TEXT,

    status TEXT
)
""")

conn.commit()
conn.close()
