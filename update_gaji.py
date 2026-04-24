from helpers.db import get_conn

GAJI_BORONGAN = 50000

def main():
    conn = get_conn()
    cur = conn.cursor()

    try:
        # cek jumlah data sebelum update
        cur.execute("""
            SELECT COUNT(*) AS total
            FROM employees
            WHERE LOWER(TRIM(bagian)) = 'borongan'
        """)
        total = cur.fetchone()["total"]

        # update gaji_harian borongan
        cur.execute("""
            UPDATE employees
            SET gaji_harian = ?
            WHERE LOWER(TRIM(bagian)) = 'borongan'
        """, (GAJI_BORONGAN,))
        updated = cur.rowcount

        conn.commit()

        print("=== UPDATE GAJI BORONGAN SELESAI ===")
        print(f"Total karyawan borongan : {total}")
        print(f"Berhasil diupdate       : {updated}")
        print(f"Gaji harian baru        : Rp {GAJI_BORONGAN:,}")

    except Exception as e:
        conn.rollback()
        print("Gagal:", e)

    finally:
        conn.close()

if __name__ == "__main__":
    main()