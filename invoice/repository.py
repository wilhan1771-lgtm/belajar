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
        rows = conn.execute(
            "SELECT * FROM invoice_line WHERE invoice_id=? ORDER BY partai_no ASC, id ASC",
            (invoice_id,),
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