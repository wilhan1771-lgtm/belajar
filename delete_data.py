import sqlite3

DB_PATH = r"C:\Users\Win 10\PycharmProjects\belajar\receiving.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

header_id = 39

cur.execute("DELETE FROM receiving_partai WHERE header_id = ?", (header_id,))
cur.execute("DELETE FROM receiving_header WHERE id = ?", (header_id,))

conn.commit()
conn.close()

print("Data receiving id", header_id, "berhasil dihapus")
