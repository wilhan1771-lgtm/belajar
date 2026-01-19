import sqlite3

conn = sqlite3.connect("receiving.db")   # ganti sesuai nama db kamu
conn.row_factory = sqlite3.Row

cur = conn.cursor()
rows = cur.execute("SELECT id, nama FROM supplier").fetchall()

for r in rows:
    print(dict(r))
