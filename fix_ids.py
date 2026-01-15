import sqlite3

conn = sqlite3.connect("receiving.db")
conn.row_factory = sqlite3.Row

for r in conn.execute("PRAGMA table_info(invoice_detail)"):
    print(r["name"])
