import sqlite3

DB = "receiving.db"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

rid = 6

# cek semua invoice untuk receiving_id=6
rows = cur.execute(
    "SELECT id, status, total, created_at FROM invoice_header WHERE receiving_id=? ORDER BY id",
    (rid,)
).fetchall()

print("Before:")
for r in rows:
    print(dict(r))

if len(rows) <= 1:
    print("No duplicate found for receiving_id=6")
    conn.close()
    raise SystemExit

# pilih yang dipertahankan: id terkecil
keep_id = rows[0]["id"]

# pastikan kolom status ada
cols = [r["name"] for r in cur.execute("PRAGMA table_info(invoice_header)").fetchall()]
if "status" not in cols:
    raise RuntimeError("Kolom 'status' tidak ada di invoice_header. Kasih saya CREATE TABLE invoice_header kamu.")

# void sisanya
cur.execute(
    "UPDATE invoice_header SET status='VOID' WHERE receiving_id=? AND id<>?",
    (rid, keep_id)
)

conn.commit()

rows2 = cur.execute(
    "SELECT id, status, total, created_at FROM invoice_header WHERE receiving_id=? ORDER BY id",
    (rid,)
).fetchall()

print("\nAfter:")
for r in rows2:
    print(dict(r))

print(f"\nKept invoice id={keep_id}, others set to VOID.")
conn.close()
