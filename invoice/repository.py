import json
from helpers.db import get_conn


def fetch_receiving_header(receiving_id):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM receiving_header WHERE id=?", (receiving_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def fetch_receiving_items(receiving_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM receiving_item WHERE header_id=? ORDER BY partai_no ASC, id ASC",
            (receiving_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def invoice_exists_for_receiving(receiving_id):
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM invoice_header WHERE receiving_id=?", (receiving_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def insert_invoice_header(
    receiving_id,
    supplier,
    price_points,
    payment_type,
    cash_deduct_per_kg_rp=0,
    tempo_hari=0,
    due_date=None,
):
    conn = get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO invoice_header
            (receiving_id, supplier, price_points_json, payment_type,
             tempo_hari, due_date,
             cash_deduct_per_kg_rp, cash_deduct_total_rp,
             pph_rate_bp, pph_amount_rp,
             subtotal_rp, total_payable_rp, total_paid_g,
             status)
            VALUES (?, ?, ?, ?,
                    ?, ?,
                    ?, 0,
                    0, 0,
                    0, 0, 0,
                    'draft')
            """,
            (
                int(receiving_id),
                supplier,
                json.dumps({str(k): int(v) for k, v in (price_points or {}).items()}, ensure_ascii=False),
                payment_type,
                int(tempo_hari or 0),
                due_date,
                int(cash_deduct_per_kg_rp or 0),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def insert_invoice_line(
    invoice_id,
    receiving_item_id,
    partai_no,
    net_g,
    paid_g,
    round_size,
    price_per_kg_rp,
    line_total_rp,
    note,
):
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO invoice_line
            (invoice_id, receiving_item_id, partai_no,
             net_g, paid_g, round_size,
             price_per_kg_rp, line_total_rp, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(invoice_id),
                int(receiving_item_id),
                int(partai_no),
                int(net_g),
                int(paid_g),
                int(round_size) if round_size is not None else None,
                int(price_per_kg_rp),
                int(line_total_rp),
                note,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_invoice_header(invoice_id):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM invoice_header WHERE id=?", (invoice_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_invoice_by_receiving(receiving_id):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM invoice_header WHERE receiving_id=?", (receiving_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def fetch_invoice_lines(invoice_id):
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT il.*,
                   ri.kategori_kupasan AS kategori_kupasan
            FROM invoice_line il
            LEFT JOIN receiving_item ri
                   ON ri.id = il.receiving_item_id
            WHERE il.invoice_id = ?
            ORDER BY il.partai_no ASC, il.id ASC
        """, (invoice_id,)).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_invoice_by_receiving_conn(conn, receiving_id):
    row = conn.execute(
        "SELECT * FROM invoice_header WHERE receiving_id=?",
        (int(receiving_id),)
    ).fetchone()
    return dict(row) if row else None


def delete_invoice_lines_conn(conn, invoice_id):
    conn.execute("DELETE FROM invoice_line WHERE invoice_id=?", (int(invoice_id),))


def insert_invoice_line_conn(
    conn,
    invoice_id,
    receiving_item_id,
    partai_no,
    net_g,
    paid_g,
    round_size,
    price_per_kg_rp,
    line_total_rp,
    note,
):
    conn.execute(
        """
        INSERT INTO invoice_line
        (invoice_id, receiving_item_id, partai_no,
         net_g, paid_g, round_size,
         price_per_kg_rp, line_total_rp, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(invoice_id),
            int(receiving_item_id),
            int(partai_no),
            int(net_g),
            int(paid_g),
            int(round_size) if round_size is not None else None,
            int(price_per_kg_rp),
            int(line_total_rp),
            note,
        ),
    )


def update_invoice_totals_conn(
    conn,
    invoice_id,
    subtotal_rp,
    total_paid_g,
    cash_deduct_total_rp,
    pph_amount_rp,
    total_payable_rp,
):
    conn.execute(
        """
        UPDATE invoice_header
        SET subtotal_rp=?,
            total_paid_g=?,
            cash_deduct_total_rp=?,
            pph_amount_rp=?,
            total_payable_rp=?
        WHERE id=?
        """,
        (
            int(subtotal_rp),
            int(total_paid_g),
            int(cash_deduct_total_rp),
            int(pph_amount_rp),
            int(total_payable_rp),
            int(invoice_id),
        ),
    )


def update_invoice_due_date_conn(conn, invoice_id):
    # due_date = tanggal + tempo_hari untuk transfer, selain itu NULL
    inv = conn.execute("SELECT payment_type, tempo_hari FROM invoice_header WHERE id=?", (int(invoice_id),)).fetchone()
    if not inv:
        return
    payment_type = (inv["payment_type"] or "transfer").strip()
    tempo_hari = int(inv["tempo_hari"] or 0)

    if payment_type == "transfer" and tempo_hari > 0:
        conn.execute(
            """
            UPDATE invoice_header
            SET due_date = date(tanggal, printf('+%d days', tempo_hari))
            WHERE id=?
            """,
            (int(invoice_id),)
        )
    else:
        conn.execute("UPDATE invoice_header SET due_date=NULL WHERE id=?", (int(invoice_id),))
def fetch_invoice_list(start=None, end=None, supplier=None, payment_type=None, limit=500):
    conn = get_conn()
    try:
        where = []
        params = []

        if start:
            where.append("tanggal >= ?")
            params.append(start)
        if end:
            where.append("tanggal <= ?")
            params.append(end)
        if supplier:
            where.append("LOWER(supplier) = LOWER(?)")
            params.append(supplier.strip())
        if payment_type in ("cash", "transfer"):
            where.append("payment_type = ?")
            params.append(payment_type)

        wsql = ("WHERE " + " AND ".join(where)) if where else ""

        limit = int(limit or 500)
        limit = max(1, min(limit, 2000))

        rows = conn.execute(
            f"""
            SELECT
              id,
              receiving_id,
              tanggal,
              supplier,
              payment_type,
              cash_deduct_per_kg_rp,
              cash_deduct_total_rp,
              tempo_hari,
              due_date,
              subtotal_rp,
              pph_amount_rp,
              total_payable_rp,
              status,
              created_at
            FROM invoice_header
            {wsql}
            ORDER BY tanggal DESC, id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()

def update_invoice_totals(
    invoice_id,
    subtotal_rp,
    total_paid_g,
    cash_deduct_total_rp,
    pph_amount_rp,
    total_payable_rp,
):
    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE invoice_header
            SET subtotal_rp=?,
                total_paid_g=?,
                cash_deduct_total_rp=?,
                pph_amount_rp=?,
                total_payable_rp=?
            WHERE id=?
            """,
            (
                int(subtotal_rp),
                int(total_paid_g),
                int(cash_deduct_total_rp),
                int(pph_amount_rp),
                int(total_payable_rp),
                int(invoice_id),
            ),
        )

        conn.commit()
    finally:
        conn.close()

def get_kupasan_prices_from_invoice(invoice_id: int):
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT
                il.price_per_kg_rp AS price,
                COALESCE(ri.kategori_kupasan, '') AS kategori
            FROM invoice_line il
            JOIN receiving_item ri
              ON ri.id = il.receiving_item_id
            WHERE il.invoice_id = ?
        """, (invoice_id,)).fetchall()

        hk = None
        hb = None
        for r in rows:
            kategori = (r["kategori"] or "").strip().lower()
            price = int(r["price"] or 0)
            if price <= 0:
                continue

            if kategori == "kecil" and hk is None:
                hk = price
            elif kategori == "besar" and hb is None:
                hb = price

        return {"kecil": hk, "besar": hb}
    finally:
        conn.close()