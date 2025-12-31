from db import get_conn

conn = get_conn()
cur = conn.cursor()

# WAJIB: pastikan FK defer? SQLite tidak punya DEFERRABLE default, jadi kita matikan FK sementara selama migrasi aman.
cur.execute("PRAGMA foreign_keys = OFF;")

# helper update id di header + child
def move_prod_id(old_id: int, new_id: int):
    # production_step
    cur.execute("UPDATE production_step SET production_id=? WHERE production_id=?", (new_id, old_id))
    # production_packing
    cur.execute("UPDATE production_packing SET production_id=? WHERE production_id=?", (new_id, old_id))
    # production_header (PK)
    cur.execute("UPDATE production_header SET id=? WHERE id=?", (new_id, old_id))

# 1) swap 4 <-> 5 pakai temp 1004
move_prod_id(4, 1004)
move_prod_id(5, 4)
move_prod_id(1004, 5)

# 2) move 2 -> 6 (pakai temp 1002 kalau takut tabrakan, tapi 6 belum ada prod_id jadi aman)
move_prod_id(2, 6)

conn.commit()

cur.execute("PRAGMA foreign_keys = ON;")
conn.close()

print("DONE: production_id sudah disamakan dengan receiving_id (4,5,6).")
