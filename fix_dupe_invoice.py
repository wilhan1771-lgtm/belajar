import sqlite3

DB = "receiving.db"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

rows = cur.execute("""
    SELECT receiving_id, COUNT(*) AS cnt
    FROM invoice_header
    GROUP BY receiving_id
    HAVING cnt > 1
    ORDER BY cnt DESC
""").fetchall()

print("DUPLICATE receiving_id:")
for r in rows:
    print(dict(r))

conn.close()
