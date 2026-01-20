import sqlite3, os

DB_NAME = os.path.join(os.path.dirname(__file__), "receiving.db")
conn = sqlite3.connect(DB_NAME)

tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table';"
).fetchall()

for t in tables:
    print(t[0])

conn.close()
