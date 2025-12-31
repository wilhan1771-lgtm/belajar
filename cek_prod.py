from db import get_conn

conn = get_conn()
cur = conn.cursor()

cur.execute("SELECT id, receiving_id FROM production_header ORDER BY id;")
rows = cur.fetchall()

print("ID PRODUCTION | RECEIVING_ID")
for r in rows:
    print(r["id"], "|", r["receiving_id"])

conn.close()
