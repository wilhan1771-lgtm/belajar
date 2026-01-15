import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "receiving.db")

print("DB PATH:", DB_PATH)
print("EXISTS :", os.path.exists(DB_PATH))

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("\nTABLES:")
for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    print("-", r["name"])

print("\nINVOICE HEADER SAMPLE:")
for r in cur.execute("SELECT id, receiving_id, supplier FROM invoice_header LIMIT 5"):
    print(dict(r))

conn.close()
