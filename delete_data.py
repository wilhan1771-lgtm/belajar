import sqlite3
import os

DB_PATH = r"C:\Users\Asus\belajar\receiving.db"
receiving_ids = (97,)  # bisa ganti tuple dengan banyak ID, misal (97, 98, 99)

# 1️⃣ Cek apakah file database ada
if not os.path.exists(DB_PATH):
    raise FileNotFoundError(f"Database tidak ditemukan: {DB_PATH}")

try:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    placeholders = ",".join("?" * len(receiving_ids))

    # 2️⃣ Hapus invoice_detail dulu
    cur.execute(f"""
        DELETE FROM invoice_detail
        WHERE invoice_id IN (
            SELECT id FROM invoice_header
            WHERE receiving_id IN ({placeholders})
        )
    """, receiving_ids)

    # 3️⃣ Hapus invoice_header
    cur.execute(f"""
        DELETE FROM invoice_header
        WHERE receiving_id IN ({placeholders})
    """, receiving_ids)

    # 4️⃣ Hapus receiving_partai
    cur.execute(f"""
        DELETE FROM receiving_partai
        WHERE header_id IN ({placeholders})
    """, receiving_ids)

    # 5️⃣ Hapus receiving_header
    cur.execute(f"""
        DELETE FROM receiving_header
        WHERE id IN ({placeholders})
    """, receiving_ids)

    conn.commit()
    print(f"✅ Receiving + Invoice untuk ID {receiving_ids} berhasil dihapus total")

except sqlite3.OperationalError as e:
    print("❌ Terjadi error SQLite:", e)

except Exception as e:
    print("❌ Terjadi error:", e)

finally:
    conn.close()