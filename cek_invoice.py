import sqlite3

conn = sqlite3.connect("receiving.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

def show_table_info(name):
    print(f"\n=== {name} ===")
    cur.execute(f"PRAGMA table_info({name});")
    for r in cur.fetchall():
        print(dict(r))

show_table_info("invoice_header")
show_table_info("invoice_detail")

conn.close()


