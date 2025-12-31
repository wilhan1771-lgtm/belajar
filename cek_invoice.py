import sqlite3

conn = sqlite3.connect("receiving.db")
conn.row_factory = sqlite3.Row

print("=== invoice_detail ===")
rows = conn.execute("PRAGMA table_info(invoice_detail);").fetchall()
for r in rows:
    print(dict(r))

conn.close()

