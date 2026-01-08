import sqlite3

DB = "receiving.db"

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1) Cek header invoice 44 dan 45
    print("== INVOICE HEADER 44 & 45 ==")
    rows = cur.execute("""
        SELECT *
        FROM invoice_header
        WHERE id IN (44,46)
    """).fetchall()
    for r in rows:
        print(dict(r))

    # 2) Pastikan receiving mapping (15 -> 44, 16 -> 45)
    print("\n== CHECK receiving_id -> invoice_id ==")
    for rid in (15, 17):
        row = cur.execute(
            "SELECT id FROM invoice_header WHERE receiving_id=?",
            (rid,)
        ).fetchone()
        print("receiving_id", rid, "=>", dict(row) if row else None)

    # 3) Cari tabel yang mengandung kata 'invoice' (buat nemuin detail table)
    print("\n== TABLES containing 'invoice' ==")
    tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    invoice_tables = [t["name"] for t in tables if "invoice" in t["name"].lower()]
    for t in invoice_tables:
        print("-", t)

    # 4) Dari tabel invoice selain invoice_header, cek mana yang punya kolom invoice_id
    print("\n== DETAIL TABLE candidates with invoice_id column ==")
    detail_tables = []
    for t in invoice_tables:
        if t.lower() == "invoice_header":
            continue
        cols = cur.execute(f"PRAGMA table_info({t})").fetchall()
        colnames = [c["name"] for c in cols]
        if "invoice_id" in colnames:
            detail_tables.append(t)
            print("-", t, "| columns:", colnames)

    # 5) Kalau ketemu detail table, cek apakah invoice 44/45 punya rows
    print("\n== DETAIL ROW COUNT for invoice_id 44/46 ==")
    for t in detail_tables:
        cnt = cur.execute(
            f"SELECT COUNT(*) AS c FROM {t} WHERE invoice_id IN (44,46)"
        ).fetchone()["c"]
        print(t, "=>", cnt, "rows")
        if cnt > 0:
            sample = cur.execute(
                f"SELECT * FROM {t} WHERE invoice_id IN (44,46) LIMIT 10"
            ).fetchall()
            for s in sample:
                print(" ", dict(s))

    # 6) Bonus: cek tabel receiving detail (buat lihat receiving 15/16 punya item atau nggak)
    print("\n== TABLES containing 'receiving' ==")
    receiving_tables = [t["name"] for t in tables if "receiving" in t["name"].lower()]
    for t in receiving_tables:
        print("-", t)

    print("\n== RECEIVING detail candidates with receiving_id column ==")
    rec_detail_tables = []
    for t in receiving_tables:
        if t.lower() == "receiving_header":
            continue
        cols = cur.execute(f"PRAGMA table_info({t})").fetchall()
        colnames = [c["name"] for c in cols]
        if "receiving_id" in colnames:
            rec_detail_tables.append(t)
            print("-", t, "| columns:", colnames)

    print("\n== RECEIVING ROW COUNT for receiving_id 15/17 ==")
    for t in rec_detail_tables:
        cnt = cur.execute(
            f"SELECT COUNT(*) AS c FROM {t} WHERE receiving_id IN (15,17)"
        ).fetchone()["c"]
        print(t, "=>", cnt, "rows")
        if cnt > 0:
            sample = cur.execute(
                f"SELECT * FROM {t} WHERE receiving_id IN (15,17) LIMIT 10"
            ).fetchall()
            for s in sample:
                print(" ", dict(s))

    conn.close()

if __name__ == "__main__":
    main()
