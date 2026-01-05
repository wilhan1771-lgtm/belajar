import sqlite3

DB = "receiving.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cols = [r["name"] for r in cur.execute("PRAGMA table_info(invoice_header)").fetchall()]
if "status" not in cols:
    raise RuntimeError("Kolom status tidak ada di invoice_header")

dupes = cur.execute("""
    SELECT receiving_id
    FROM invoice_header
    GROUP BY receiving_id
    HAVING COUNT(*) > 1
""").fetchall()

if not dupes:
    print("No duplicates found.")
    conn.close()
    raise SystemExit

for d in dupes:
    rid = d["receiving_id"]

    # keep invoice dengan total terbesar (biasanya yang valid)
    keep = cur.execute("""
        SELECT id
        FROM invoice_header
        WHERE receiving_id=?
        ORDER BY COALESCE(total,0) DESC, id ASC
        LIMIT 1
    """, (rid,)).fetchone()
    keep_id = keep["id"]

    cur.execute("""
        UPDATE invoice_header
        SET status='VOID'
        WHERE receiving_id=? AND id<>?
    """, (rid, keep_id))

    print(f"receiving_id={rid}: keep id={keep_id}, void others")

conn.commit()
conn.close()
print("Done voiding duplicates.")
