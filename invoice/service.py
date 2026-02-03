

def sync_invoice_from_receiving(conn, receiving_id: int):
    """
    Sinkronkan invoice dari receiving jika invoice masih DRAFT:
    - update size_round + berat_netto di invoice_detail sesuai receiving_partai
    - total_harga = berat_netto * harga (harga dipertahankan)
    - update invoice_header subtotal/pph/total berdasarkan pph_rate
    """
    inv = conn.execute("""
        SELECT id, COALESCE(pph_rate,0) AS pph_rate
        FROM invoice_header
        WHERE receiving_id=? AND status='DRAFT'
        ORDER BY id DESC
        LIMIT 1
    """, (receiving_id,)).fetchone()

    if not inv:
        return

    invoice_id = inv["id"]
    pph_rate = float(inv["pph_rate"] or 0)

    det_rows = conn.execute("""
        SELECT id, partai_no, COALESCE(harga,0) AS harga
        FROM invoice_detail
        WHERE invoice_id=?
        ORDER BY partai_no
    """, (invoice_id,)).fetchall()

    parts = conn.execute("""
        SELECT partai_no, round_size, COALESCE(netto,0) AS netto
        FROM receiving_partai
        WHERE header_id=?
    """, (receiving_id,)).fetchall()
    part_map = {p["partai_no"]: p for p in parts}

    cur = conn.cursor()
    subtotal = 0.0

    for d in det_rows:
        pn = d["partai_no"]
        harga = float(d["harga"] or 0)

        p = part_map.get(pn)
        if not p:
            round_size = None
            berat_netto = 0.0
        else:
            round_size = p["round_size"]
            berat_netto = float(p["netto"] or 0)

        total_harga = berat_netto * harga
        subtotal += total_harga

        cur.execute("""
            UPDATE invoice_detail
            SET round_size=?, berat_netto=?, total_harga=?
            WHERE id=? AND invoice_id=?
        """, (round_size, berat_netto, total_harga, d["id"], invoice_id))

    pph = subtotal * pph_rate
    total = subtotal - pph   # sesuai logic kamu: total = subtotal - pph

    cur.execute("""
        UPDATE invoice_header
        SET subtotal=?, pph=?, total=?
        WHERE id=?
    """, (subtotal, pph, total, invoice_id))
