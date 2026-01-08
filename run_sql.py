import sqlite3

conn = sqlite3.connect("receiving.db")  # ganti sesuai nama DB kamu
cur = conn.cursor()

cur.execute("""
ALTER TABLE receiving_header
ADD COLUMN is_test INTEGER DEFAULT 0
""")

conn.commit()
conn.close()

print("Kolom is_test berhasil ditambahkan")

