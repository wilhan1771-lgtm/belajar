import sqlite3
import sqlite3

DB_PATH = r"C:\Users\Win 10\PycharmProjects\belajar\receiving.db"
receiving_id = 47

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
DELETE FROM invoice_detail
WHERE invoice_id IN (
    SELECT id FROM invoice_header WHERE receiving_id = ?
)
""", (receiving_id,))

cur.execute("DELETE FROM invoice_header WHERE receiving_id = ?", (receiving_id,))

conn.commit()
conn.close()

print("Invoice terkait receiving", receiving_id, "berhasil dihapus")
