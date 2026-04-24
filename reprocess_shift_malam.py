from helpers.db import get_conn
from absensi.processor import process_attendance
from datetime import datetime, timedelta


START_DATE = "2026-04-20"
END_DATE = "2026-04-20"


def plus_one_day(date_str):
    return (
        datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")


def reset_raw_processed(start_date, end_date):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE attendance_raw
            SET processed = 0
            WHERE tanggal BETWEEN ? AND ?
        """, (start_date, end_date))

        updated = cur.rowcount
        conn.commit()
        print(f"Reset processed raw : {updated} baris")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_attendance_daily(start_date, end_date):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            DELETE FROM attendance_daily
            WHERE work_date BETWEEN ? AND ?
        """, (start_date, end_date))

        deleted = cur.rowcount
        conn.commit()
        print(f"Delete attendance_daily : {deleted} baris")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    raw_end_date = plus_one_day(END_DATE)

    print("=== REPROCESS ATTENDANCE DAILY SHIFT MALAM ===")
    print(f"Work date : {START_DATE} s/d {END_DATE}")
    print(f"Raw date  : {START_DATE} s/d {raw_end_date}")

    delete_attendance_daily(START_DATE, END_DATE)
    reset_raw_processed(START_DATE, raw_end_date)

    process_attendance()

    print("Selesai reprocess.")


if __name__ == "__main__":
    main()