import sqlite3

DB_PATH = r"C:\Users\Win 10\PycharmProjects\belajar\receiving.db"
receiving_ids = (51, 52, 53, 54)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# helper untuk IN (?, ?, ?)
placeholders = ",".join("?" * len(receiving_ids))

# 1️⃣ Hapus invoice_detail
cur.execute(f"""
DELETE FROM invoice_detail
WHERE invoice_id IN (
    SELECT id FROM invoice_header
    WHERE receiving_id IN ({placeholders})
)
""", receiving_ids)

# 2️⃣ Hapus invoice_header
cur.execute(f"""
DELETE FROM invoice_header
WHERE receiving_id IN ({placeholders})
""", receiving_ids)

# 3️⃣ Hapus receiving_partai
cur.execute(f"""
DELETE FROM receiving_partai
WHERE header_id IN ({placeholders})
""", receiving_ids)

# 4️⃣ Hapus receiving_header
cur.execute(f"""
DELETE FROM receiving_header
WHERE id IN ({placeholders})
""", receiving_ids)

conn.commit()
conn.close()

print("Receiving + Invoice untuk", receiving_ids, "berhasil dihapus total")
