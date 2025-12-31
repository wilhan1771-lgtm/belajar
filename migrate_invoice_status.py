from db import get_conn

conn = get_conn()
cur = conn.cursor()

try:
    cur.execute("ALTER TABLE invoice_header ADD COLUMN status TEXT DEFAULT 'ACTIVE';")
    conn.commit()
    print("OK: kolom status berhasil ditambahkan ke invoice_header")
except Exception as e:
    print("INFO:", e)

conn.close()
