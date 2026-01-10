import sqlite3

DB = "receiving.db"

def recalc_invoice(invoice_id: int):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    inv = cur.execute("SELECT * FROM invoice_header WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        print("Invoice tidak ditemukan")
        return

    rows = cur.execute("""
        SELECT COALESCE(berat_netto,0) AS netto,
               COALESCE(harga,0) AS harga,
               COALESCE(total_harga,0) AS total_harga
        FROM invoice_detail
        WHERE invoice_id=?
    """, (invoice_id,)).fetchall()

    subtotal = sum(float(r["total_harga"]) for r in rows)
    total_kg = sum(float(r["netto"]) for r in rows)

    pph_rate = float(inv["pph_rate"] or 0)  # sudah bentuk desimal (mis 0.0025)
    pph = subtotal * pph_rate

    cash_total = float(inv["cash_deduct_total"] or 0)
    reject_total = float(inv["reject_total"] or 0)

    total = subtotal - pph - cash_total - reject_total

    # Proteksi penting: kalau subtotal 0, paksa pph 0
    if subtotal == 0:
        pph = 0

    cur.execute("""
        UPDATE invoice_header
        SET subtotal=?,
            total_kg=?,
            pph=?,
            total=?
        WHERE id=?
    """, (subtotal, total_kg, pph, total, invoice_id))

    conn.commit()
    conn.close()
    print("OK updated invoice", invoice_id)

if __name__ == "__main__":
    recalc_invoice(45)   # ganti id yang mau diperbaiki
