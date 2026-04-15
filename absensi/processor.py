from helpers.db import get_conn
from datetime import datetime, time as dt_time, timedelta
import time


def parse_dt(tanggal, waktu):
    return datetime.strptime(
        f"{tanggal} {waktu}",
        "%Y-%m-%d %H:%M:%S"
    )


def diff_minutes(dt_a, dt_b):
    return max(0, int((dt_a - dt_b).total_seconds() // 60))


def process_attendance():

    db = get_conn()
    cur = db.cursor()

    # =========================
    # AMBIL RAW BELUM PROSES
    # =========================
    cur.execute("""
        SELECT DISTINCT fingerprint_id, tanggal
        FROM attendance_raw
        WHERE IFNULL(processed, 0) = 0
        ORDER BY fingerprint_id, tanggal
    """)

    pending_keys = cur.fetchall()

    if not pending_keys:
        print("Tidak ada data raw baru")
        db.close()
        return

    for key in pending_keys:

        fingerprint_id = key["fingerprint_id"]
        tanggal = key["tanggal"]

        # =========================
        # AMBIL SCAN
        # =========================
        cur.execute("""
            SELECT *
            FROM attendance_raw
            WHERE fingerprint_id = ?
              AND tanggal = ?
            ORDER BY waktu
        """, (fingerprint_id, tanggal))

        scans = cur.fetchall()

        # =========================
        # AMBIL EMPLOYEE
        # =========================
        cur.execute("""
            SELECT *
            FROM employees
            WHERE fingerprint_id = ?
              AND status_aktif = 1
            LIMIT 1
        """, (fingerprint_id,))

        emp = cur.fetchone()

        if not emp:
            print(f"Fingerprint {fingerprint_id} tidak ditemukan")
            continue

        employee_id = emp["id"]
        no_id = emp["no_id"]
        shift_code = emp["shift_default"] or "PAGI"

        scan_times = [
            parse_dt(s["tanggal"], s["waktu"])
            for s in scans
        ]
        scan_times.sort()

        # =========================
        # INIT
        # =========================
        period1_in = None
        period1_out = None
        period2_in = None
        period2_out = None
        period3_in = None
        period3_out = None

        late_minutes = 0
        early_leave_minutes = 0
        overtime_hours = 0.0

        # =========================
        # SHIFT PAGI
        # P1 = 08:00 - 12:00
        # P2 = 13:00 - 17:30
        # P3 = lembur
        # =========================
        if shift_code == "PAGI":

            masuk_pagi = []
            keluar_siang = []
            masuk_siang = []
            pulang_normal = []
            scan_lembur = []

            for dt in scan_times:
                t = dt.time()

                # scan masuk pagi
                if dt_time(6, 30) <= t <= dt_time(10, 0):
                    masuk_pagi.append(dt)

                # scan keluar istirahat
                elif dt_time(11, 30) <= t <= dt_time(12, 34):
                    keluar_siang.append(dt)

                # scan masuk sesi 2
                elif dt_time(12, 35 ) <= t <= dt_time(15, 0):
                    masuk_siang.append(dt)

                # scan pulang normal
                elif dt_time(15, 1) <= t <= dt_time(18, 30):
                    pulang_normal.append(dt)

                # scan lembur
                elif dt_time(18, 31) <= t <= dt_time(23, 59):
                    scan_lembur.append(dt)

            # assign P1
            if masuk_pagi:
                period1_in = masuk_pagi[0].strftime("%H:%M:%S")

            if keluar_siang:
                period1_out = keluar_siang[-1].strftime("%H:%M:%S")

            # assign P2
            if masuk_siang:
                period2_in = masuk_siang[0].strftime("%H:%M:%S")

            if pulang_normal:
                period2_out = pulang_normal[-1].strftime("%H:%M:%S")

            # kalau tidak scan masuk sesi 2 tapi ada pulang sesi 2,
            # anggap mulai sesi 2 jam 13:00
            if not period2_in and period2_out:
                period2_in = "13:00:00"

            # assign P3 lembur
            if len(scan_lembur) >= 2:
                period3_in = scan_lembur[0].strftime("%H:%M:%S")
                period3_out = scan_lembur[-1].strftime("%H:%M:%S")
            elif len(scan_lembur) == 1:
                # kalau hanya 1 scan lembur, anggap mulai lembur 17:30
                period3_in = "17:30:00"
                period3_out = scan_lembur[0].strftime("%H:%M:%S")

            # hitung telat
            if period1_in:
                jadwal_masuk = parse_dt(tanggal, "08:00:00")
                actual_masuk = parse_dt(tanggal, period1_in)
                if actual_masuk > jadwal_masuk:
                    late_minutes = diff_minutes(actual_masuk, jadwal_masuk)

            # hitung pulang cepat
            if period2_out:
                jadwal_pulang = parse_dt(tanggal, "17:30:00")
                actual_pulang = parse_dt(tanggal, period2_out)
                if actual_pulang < jadwal_pulang:
                    early_leave_minutes = diff_minutes(jadwal_pulang, actual_pulang)

        # =========================
        # SHIFT SORE
        # P1 = 13:00 - 17:30
        # P2 = 19:00 - 22:00
        # P3 = lembur sampai 02:00 besok
        # =========================
        elif shift_code == "SORE":

            sore_masuk = []
            sore_pulang = []
            malam_masuk = []
            malam_pulang = []
            scan_lembur = []

            besok = (
                    datetime.strptime(tanggal, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")

            # ambil scan besok dini hari untuk lembur
            cur.execute("""
                SELECT *
                FROM attendance_raw
                WHERE fingerprint_id = ?
                AND tanggal = ?
                ORDER BY waktu
            """, (fingerprint_id, besok))

            raw_besok = cur.fetchall()

            next_day_scans = []
            for s in raw_besok:
                dt_besok = parse_dt(s["tanggal"], s["waktu"])
                if dt_time(0, 0) <= dt_besok.time() <= dt_time(2, 0):
                    next_day_scans.append(dt_besok)

            all_scans = scan_times + next_day_scans
            all_scans.sort()

            for dt in all_scans:
                t = dt.time()
                scan_date = dt.strftime("%Y-%m-%d")

                # P1 IN
                if scan_date == tanggal and dt_time(12, 30) <= t <= dt_time(15, 0):
                    sore_masuk.append(dt)

                # P1 OUT
                elif scan_date == tanggal and dt_time(17, 0) <= t <= dt_time(18, 30):
                    sore_pulang.append(dt)

                # P2 IN
                elif scan_date == tanggal and dt_time(18, 30) <= t <= dt_time(20, 0):
                    malam_masuk.append(dt)

                # P2 OUT
                elif scan_date == tanggal and dt_time(21, 55) <= t <= dt_time(22, 30):
                    malam_pulang.append(dt)

                # P3 lembur
                elif (
                        (scan_date == tanggal and dt_time(22, 1) <= t <= dt_time(23, 59))
                        or
                        (scan_date == besok and dt_time(0, 0) <= t <= dt_time(2, 0))
                ):
                    scan_lembur.append(dt)

            # P1
            if sore_masuk:
                period1_in = sore_masuk[0].strftime("%H:%M:%S")

            if sore_pulang:
                period1_out = sore_pulang[-1].strftime("%H:%M:%S")

            # P2
            if malam_masuk:
                period2_in = malam_masuk[0].strftime("%H:%M:%S")

            if malam_pulang:
                period2_out = malam_pulang[-1].strftime("%H:%M:%S")

            if not period2_in and period2_out:
                period2_in = "19:00:00"

            # P3
            if len(scan_lembur) >= 2:
                period3_in = scan_lembur[0].strftime("%H:%M:%S")
                period3_out = scan_lembur[-1].strftime("%H:%M:%S")
            elif len(scan_lembur) == 1:
                period3_in = "22:00:00"
                period3_out = scan_lembur[0].strftime("%H:%M:%S")

        # =========================
        # FIX: kalau tidak checkout jam 22 tapi lanjut lembur
        # =========================

        # kalau ada lembur tapi tidak ada P2 OUT
        if period3_out and not period2_out:
            period2_out = "22:00:00"

        # kalau ada P2 OUT tapi tidak ada P2 IN
        if not period2_in and period2_out:
            period2_in = "19:00:00"

        # kalau ada lembur tapi tidak ada P3 IN
        if period3_out and not period3_in:
            period3_in = "22:00:00"
        # =========================
        # CHECK SCAN
        # =========================
        all_valid = [
            x for x in [
                period1_in, period1_out,
                period2_in, period2_out,
                period3_in, period3_out
            ] if x
        ]

        first_scan = all_valid[0] if all_valid else None

        # =========================
        # HITUNG JAM
        # =========================
        actual_hours = 0.0

        if period1_in and period1_out:
            dt1 = parse_dt(tanggal, period1_in)
            dt2 = parse_dt(tanggal, period1_out)
            actual_hours += max(0, (dt2 - dt1).total_seconds() / 3600)

        if period2_in and period2_out:
            dt1 = parse_dt(tanggal, period2_in)
            dt2 = parse_dt(tanggal, period2_out)
            actual_hours += max(0, (dt2 - dt1).total_seconds() / 3600)

        if period3_in and period3_out:
            dt1 = parse_dt(tanggal, period3_in)

            if period3_out < period3_in:
                dt2 = parse_dt(
                    (datetime.strptime(tanggal, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"),
                    period3_out
                )
            else:
                dt2 = parse_dt(tanggal, period3_out)

            actual_hours += max(0, (dt2 - dt1).total_seconds() / 3600)

        actual_hours = round(actual_hours, 2)

        # =========================
        # NORMAL HOURS
        # =========================
        cur.execute("""
            SELECT normal_hours
            FROM shift_definitions
            WHERE shift_code = ?
        """, (shift_code,))

        shift = cur.fetchone()
        normal_hours = shift["normal_hours"] if shift else 0

        overtime_hours = max(
            0,
            round(actual_hours - normal_hours, 2)
        )

        # =========================
        # STATUS
        # =========================
        status_hadir = "hadir" if first_scan else "tidak_hadir"

        # =========================
        # INSERT DAILY
        # =========================
        cur.execute("""
            INSERT OR REPLACE INTO attendance_daily
            (
                employee_id, fingerprint_id, work_date, shift_code,
                period1_in, period1_out,
                period2_in, period2_out,
                period3_in, period3_out,
                normal_hours, actual_hours, overtime_hours,
                late_minutes, early_leave_minutes,
                status_hadir, sumber, catatan, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            employee_id,
            fingerprint_id,
            tanggal,
            shift_code,
            period1_in, period1_out,
            period2_in, period2_out,
            period3_in, period3_out,
            normal_hours,
            actual_hours,
            overtime_hours,
            late_minutes,
            early_leave_minutes,
            status_hadir,
            "processor",
            f"Scan count: {len(scans)}"
        ))

        # =========================
        # UPDATE PROCESSED
        # =========================
        cur.execute("""
            UPDATE attendance_raw
            SET processed = 1
            WHERE fingerprint_id = ?
              AND tanggal = ?
              AND IFNULL(processed, 0) = 0
        """, (fingerprint_id, tanggal))

        print(f"Processed {no_id} - {tanggal}")

    db.commit()
    db.close()

    print("Selesai proses attendance_raw -> attendance_daily")


if __name__ == "__main__":
    while True:
        process_attendance()
        time.sleep(10)