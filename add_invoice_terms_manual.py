import sqlite3

conn = sqlite3.connect("receiving.db")
cur = conn.cursor()

def add_col(sql):
    try:
        cur.execute(sql)
    except Exception:
        pass  # ignore jika kolom sudah ada

add_col("ALTER TABLE invoice_header ADD COLUMN due_date TEXT;")
add_col("ALTER TABLE invoice_header ADD COLUMN payment_type TEXT DEFAULT 'TRANSFER';")
add_col("ALTER TABLE invoice_header ADD COLUMN cash_deduct_per_kg REAL DEFAULT 0;")
add_col("ALTER TABLE invoice_header ADD COLUMN reject_kg REAL DEFAULT 0;")
add_col("ALTER TABLE invoice_header ADD COLUMN reject_price REAL DEFAULT 0;")
add_col("ALTER TABLE invoice_header ADD COLUMN cash_deduct_total REAL DEFAULT 0;")
add_col("ALTER TABLE invoice_header ADD COLUMN reject_total REAL DEFAULT 0;")

conn.commit()
conn.close()
print("OK: invoice terms columns added/exists")
