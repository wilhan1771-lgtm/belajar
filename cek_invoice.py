import sqlite3
DB_PATH = r"C:\Users\Win 10\PycharmProjects\udang\belajar\receiving.db"
conn = sqlite3.connect(DB_PATH)
rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print([r[0] for r in rows])
conn.close()
