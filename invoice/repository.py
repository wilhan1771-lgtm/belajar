def get_receiving_header(conn, receiving_id):
    return conn.execute(
        "SELECT * FROM receiving_header WHERE id=?",
        (receiving_id,)
    ).fetchone()

def get_receiving_partai(conn, receiving_id):
    return conn.execute("""
        SELECT partai_no, round_size, COALESCE(netto, 0) AS netto
        FROM receiving_partai
        WHERE header_id=?
        ORDER BY partai_no ASC
    """, (receiving_id,)).fetchall()

def get_existing_invoice(conn, receiving_id):
    return conn.execute("""
        SELECT id
        FROM invoice_header
        WHERE receiving_id=? AND status!='VOID'
        ORDER BY id DESC
        LIMIT 1
    """, (receiving_id,)).fetchone()
