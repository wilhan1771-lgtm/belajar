import sqlite3

DB = "receiving.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_receiving_id
ON invoice_header(receiving_id);
""")

conn.commit()
conn.close()
print("OK: UNIQUE index invoice_header(receiving_id) created.")
