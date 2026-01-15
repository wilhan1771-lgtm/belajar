import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "receiving.db")

def rebuild_invoice_detail(invoice_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    inv = cur.execute(
        "SELECT id, receiving_id FROM invoice_header WHERE id=?",
        (invoice_id,)
    ).fetchone()

    if not inv:
        print("Invoice tidak ditemukan")
        return

    receiving_id = inv["receiving_id"]

    # hapus detail lama (jika ada)
    cur.execute(
        "DELETE FROM invoice_detail WHERE invoice_id=?",
        (invoice_id,)
    )

    parts = cur.execute("""
        SELECT partai_no, round_size, netto
        FROM receiving_partai
        WHERE header_id=?
        ORDER BY partai_no
    """, (receiving_id,)).fetchall()

    for p in parts:
        cur.execute("""
            INSERT INTO invoice_detail
            (invoice_id, partai_no, size_round, berat_netto, harga, total_harga)
            VALUES (?, ?, ?, ?, 0, 0)
        """, (
            invoice_id,
            p["partai_no"],
            p["round_size"],
            p["netto"]
        ))

    conn.commit()
    conn.close()
    print(f"invoice_detail rebuilt untuk invoice {invoice_id}")

if __name__ == "__main__":
    rebuild_invoice_detail(51)   # GANTI ID JIKA PERLU
