from helpers.db import get_conn

conn = get_conn()

try:
    conn.execute("""
    UPDATE invoice_header
    SET tanggal = (
        SELECT tanggal
        FROM receiving_header
        WHERE receiving_header.id = invoice_header.receiving_id
    )
    """)

    conn.commit()
    print("Tanggal invoice berhasil disamakan dengan receiving")

finally:
    conn.close()