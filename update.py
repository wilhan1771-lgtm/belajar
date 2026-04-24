from helpers.db import get_conn

TANGGAL = "2026-04-17"
SHIFT = "BORONGAN"

def main():
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("""
            DELETE FROM attendance_daily
            WHERE work_date = ?
              AND employee_id IN (
                  SELECT id
                  FROM employees
                  WHERE shift_default = ?
              )
        """, (TANGGAL, SHIFT))
        deleted_daily = cur.rowcount

        cur.execute("""
            UPDATE attendance_raw
            SET processed = 0
            WHERE tanggal = ?
              AND fingerprint_id IN (
                  SELECT fingerprint_id
                  FROM employees
                  WHERE shift_default = ?
                    AND fingerprint_id IS NOT NULL
                    AND TRIM(fingerprint_id) != ''
              )
        """, (TANGGAL, SHIFT))
        reset_raw = cur.rowcount

        conn.commit()

        print("=== RESET SELESAI ===")
        print(f"Tanggal      : {TANGGAL}")
        print(f"Shift        : {SHIFT}")
        print(f"Daily hapus  : {deleted_daily}")
        print(f"Raw di-reset : {reset_raw}")
        print("Silakan jalankan processor.py lagi.")

    except Exception as e:
        conn.rollback()
        print("Gagal:", e)

    finally:
        conn.close()

if __name__ == "__main__":
    main()