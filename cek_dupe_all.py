import sqlite3

DB = "receiving.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("== DUPES (ALL rows) ==")
rows = cur.execute("""
    SELECT receiving_id, COUNT(*) AS cnt
    FROM invoice_header
    GROUP BY receiving_id
    HAVING cnt > 1
    ORDER BY cnt DESC
""").fetchall()

for r in rows:
    print(dict(r))

print("\n== DETAIL for dupes ==")
for r in rows:
    rid = r["receiving_id"]
    det = cur.execute("""
        SELECT id, receiving_id, COALESCE(status,'(NULL)') AS status, total, created_at
        FROM invoice_header
        WHERE receiving_id=?
        ORDER BY id
    """, (rid,)).fetchall()
    for d in det:
        print(dict(d))

conn.close()
