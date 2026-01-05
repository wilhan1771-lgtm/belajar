import sqlite3

DB = "receiving.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# cari semua receiving_id yang dobel
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

print("Duplicate receiving_id:", [d["receiving_id"] for d in dupes])

for d in dupes:
    rid = d["receiving_id"]

    # pilih invoice yang dipertahankan = total terbesar (biasanya yang benar)
    keep = cur.execute("""
        SELECT id, COALESCE(total,0) AS total
        FROM invoice_header
        WHERE receiving_id=?
        ORDER BY COALESCE(total,0) DESC, id ASC
        LIMIT 1
    """, (rid,)).fetchone()
    keep_id = keep["id"]

    # list yang akan dihapus
    others = cur.execute("""
        SELECT id, COALESCE(total,0) AS total, COALESCE(status,'(NULL)') AS status, created_at
        FROM invoice_header
        WHERE receiving_id=? AND id<>?
        ORDER BY id
    """, (rid, keep_id)).fetchall()

    print(f"\nreceiving_id={rid} keep id={keep_id} total={keep['total']}")
    for o in others:
        print(" delete:", dict(o))

    # hapus detail dulu (aman walau sudah ada ON DELETE CASCADE)
    cur.execute("DELETE FROM invoice_detail WHERE invoice_id IN (SELECT id FROM invoice_header WHERE receiving_id=? AND id<>?)", (rid, keep_id))
    cur.execute("DELETE FROM invoice_header WHERE receiving_id=? AND id<>?", (rid, keep_id))

conn.commit()
conn.close()
print("\nDone. Duplicates removed.")
