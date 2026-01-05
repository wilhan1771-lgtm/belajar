import sqlite3

conn = sqlite3.connect("receiving.db")
cur = conn.cursor()

# lihat isi invoice_header
rows = cur.execute("""
SELECT id, receiving_id, status, total, created_at
FROM invoice_header
ORDER BY id DESC
""").fetchall()

print("INVOICE HEADER:")
for r in rows:
    print(r)

conn.close()
