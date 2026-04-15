from helpers.db import get_conn

TANGGAL = "2026-04-14"   # ganti tanggal di sini


def main():
    conn = get_conn()
    cur = conn.cursor()

    try:
        # cek dulu berapa data daily shift sore
        cur.execute("""
            SELECT COUNT(*) AS total
            FROM attendance_daily
            WHERE work_date = ?
              AND shift_code = 'SORE'
        """, (TANGGAL,))
        total_daily = cur.fetchone()["total"]

        # hapus attendance_daily shift sore
        cur.execute("""
            DELETE FROM attendance_daily
            WHERE work_date = ?
              AND shift_code = 'SORE'
        """, (TANGGAL,))
        deleted_daily = cur.rowcount

        # reset raw untuk semua fingerprint yang shift_default = SORE
        cur.execute("""
            UPDATE attendance_raw
            SET processed = 0
            WHERE tanggal = ?
              AND fingerprint_id IN (
                  SELECT fingerprint_id
                  FROM employees
                  WHERE shift_default = 'SORE'
                    AND fingerprint_id IS NOT NULL
                    AND TRIM(fingerprint_id) != ''
              )
        """, (TANGGAL,))
        reset_raw = cur.rowcount

        conn.commit()

        print("=== UPDATE SELESAI ===")
        print(f"Tanggal                : {TANGGAL}")
        print(f"Daily shift SORE ada   : {total_daily}")
        print(f"Daily terhapus         : {deleted_daily}")
        print(f"Raw di-reset           : {reset_raw}")
        print("")
        print("Silakan jalankan processor.py lagi.")

    except Exception as e:
        conn.rollback()
        print("Gagal:", e)

    finally:
        conn.close()


if __name__ == "__main__":
    main()