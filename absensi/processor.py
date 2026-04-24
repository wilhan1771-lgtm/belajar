from helpers.db import get_conn
from datetime import datetime, time as dt_time, timedelta
import time
from .rules import apply_pagi_rules


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
        shift_code = (emp["shift_default"] or "PAGI").upper()

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
        # =========================
        if shift_code == "PAGI":

            masuk_pagi = []
            keluar_siang = []
            masuk_siang = []
            pulang_normal = []
            scan_lembur = []

            for dt in scan_times:
                t = dt.time()

                if dt_time(6, 30) <= t <= dt_time(9, 0):
                    masuk_pagi.append(dt)
                elif dt_time(10, 0) <= t <= dt_time(12, 34):
                    keluar_siang.append(dt)
                elif dt_time(12, 35) <= t <= dt_time(15, 0):
                    masuk_siang.append(dt)
                elif dt_time(15, 1) <= t <= dt_time(18, 0):
                    pulang_normal.append(dt)
                elif dt_time(18, 1) <= t <= dt_time(23, 59):
                    scan_lembur.append(dt)

            if masuk_pagi:
                period1_in = masuk_pagi[0].strftime("%H:%M:%S")

            if keluar_siang:
                period1_out = keluar_siang[-1].strftime("%H:%M:%S")

            if masuk_siang:
                period2_in = masuk_siang[0].strftime("%H:%M:%S")

            if pulang_normal:
                period2_out = pulang_normal[-1].strftime("%H:%M:%S")

            if not period2_in and period2_out:
                period2_in = "13:00:00"

            if len(scan_lembur) >= 2:
                period3_in = scan_lembur[0].strftime("%H:%M:%S")
                period3_out = scan_lembur[-1].strftime("%H:%M:%S")
            elif len(scan_lembur) == 1:
                period3_in = scan_lembur[0].strftime("%H:%M:%S")
                period3_out = scan_lembur[0].strftime("%H:%M:%S")

            if period1_in:
                jadwal = parse_dt(tanggal, "08:00:00")
                actual = parse_dt(tanggal, period1_in)
                telat_menit = diff_minutes(actual, jadwal)

                if telat_menit >= 2:
                    potongan_telat = 10000
                else:
                    potongan_telat = 0

            if period2_out:
                jadwal_pulang = parse_dt(tanggal, "17:30:00")
                actual_pulang = parse_dt(tanggal, period2_out)
                if actual_pulang < jadwal_pulang:
                    early_leave_minutes = diff_minutes(jadwal_pulang, actual_pulang)

            hasil = apply_pagi_rules(period1_in)
            lembur_p1 = hasil["lembur_p1"]

            if lembur_p1 > 0:
                overtime_hours = lembur_p1

        # =========================
        # SHIFT BORONGAN
        # =========================
        elif shift_code == "BORONGAN":

            masuk_pagi = []
            keluar_siang = []
            masuk_siang = []
            pulang_normal = []
            scan_malam = []

            for dt in scan_times:
                t = dt.time()

                if dt_time(6, 0) <= t <= dt_time(9, 0):
                    masuk_pagi.append(dt)
                elif dt_time(10, 30) <= t <= dt_time(12, 30):
                    keluar_siang.append(dt)
                elif dt_time(12, 30) <= t <= dt_time(14, 30):
                    masuk_siang.append(dt)
                elif dt_time(14, 30) <= t <= dt_time(18, 0):
                    pulang_normal.append(dt)
                elif dt_time(18, 0) <= t <= dt_time(23, 59):
                    scan_malam.append(dt)

            if masuk_pagi:
                period1_in = masuk_pagi[0].strftime("%H:%M:%S")

            if keluar_siang:
                period1_out = keluar_siang[-1].strftime("%H:%M:%S")

            if masuk_siang:
                period2_in = masuk_siang[0].strftime("%H:%M:%S")

            if pulang_normal:
                period2_out = pulang_normal[-1].strftime("%H:%M:%S")

            if not period2_in and period2_out:
                period2_in = "12:30:00"

            if len(scan_malam) >= 2:
                period3_in = scan_malam[0].strftime("%H:%M:%S")
                period3_out = scan_malam[-1].strftime("%H:%M:%S")
            elif len(scan_malam) == 1:
                period3_in = scan_malam[0].strftime("%H:%M:%S")
                period3_out = scan_malam[0].strftime("%H:%M:%S")

            if period1_in:
                jadwal_masuk = parse_dt(tanggal, "08:00:00")
                actual_masuk = parse_dt(tanggal, period1_in)
                if actual_masuk > jadwal_masuk:
                    late_minutes = diff_minutes(actual_masuk, jadwal_masuk)

            if period2_out:
                jadwal_pulang = parse_dt(tanggal, "17:00:00")
                actual_pulang = parse_dt(tanggal, period2_out)
                if actual_pulang < jadwal_pulang:
                    early_leave_minutes = diff_minutes(jadwal_pulang, actual_pulang)

        # =========================
        # SHIFT SORE
        # P1 = sesi sore
        # P2 = 18:30 sampai selesai
        # lembur dihitung jika P2 OUT > 22:00
        # P2 bisa lanjut sampai besok 02:00
        # =========================
        elif shift_code == "SORE":

            sore_masuk = []
            sore_pulang = []
            malam_hari_ini = []
            malam_besok = []

            besok = (
                datetime.strptime(tanggal, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")

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

                if scan_date == tanggal and dt_time(8, 30) <= t <= dt_time(15, 0):
                    sore_masuk.append(dt)
                elif scan_date == tanggal and dt_time(16, 30) <= t <= dt_time(18, 0):
                    sore_pulang.append(dt)
                elif scan_date == tanggal and dt_time(18, 21) <= t <= dt_time(23, 59):
                    malam_hari_ini.append(dt)
                elif scan_date == besok and dt_time(0, 0) <= t <= dt_time(2, 0):
                    malam_besok.append(dt)

            if sore_masuk:
                period1_in = sore_masuk[0].strftime("%H:%M:%S")

            if sore_pulang:
                period1_out = sore_pulang[-1].strftime("%H:%M:%S")

            if malam_hari_ini or malam_besok:
                if malam_hari_ini:
                    period2_in = malam_hari_ini[0].strftime("%H:%M:%S")

                if malam_besok:
                    period2_out = malam_besok[-1].strftime("%H:%M:%S")
                elif malam_hari_ini:
                    period2_out = malam_hari_ini[-1].strftime("%H:%M:%S")

            period3_in = None
            period3_out = None

        # =========================
        # SHIFT MALAM
        # =========================
        elif shift_code == "MALAM":

            malam_masuk = []
            pagi_pulang = []

            besok = (
                datetime.strptime(tanggal, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")

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
                if dt_time(0, 0) <= dt_besok.time() <= dt_time(10, 0):
                    next_day_scans.append(dt_besok)

            all_scans = scan_times + next_day_scans
            all_scans.sort()

            for dt in all_scans:
                t = dt.time()
                scan_date = dt.strftime("%Y-%m-%d")

                if scan_date == tanggal and dt_time(21, 0) <= t <= dt_time(23, 0):
                    malam_masuk.append(dt)
                elif scan_date == besok and dt_time(0, 0) <= t <= dt_time(10, 0):
                    pagi_pulang.append(dt)

            if malam_masuk:
                period1_in = malam_masuk[0].strftime("%H:%M:%S")

            if pagi_pulang:
                period1_out = pagi_pulang[-1].strftime("%H:%M:%S")

            period2_in = None
            period2_out = None
            period3_in = None
            period3_out = None

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

        if shift_code == "SORE":
            if period1_in and period1_out:
                dt1 = parse_dt(tanggal, period1_in)
                dt2 = parse_dt(tanggal, period1_out)
                actual_hours += max(0, (dt2 - dt1).total_seconds() / 3600)

            if period2_in and period2_out:
                dt1 = parse_dt(tanggal, period2_in)

                if period2_out < period2_in:
                    dt2 = parse_dt(
                        (datetime.strptime(tanggal, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"),
                        period2_out
                    )
                else:
                    dt2 = parse_dt(tanggal, period2_out)

                actual_hours += max(0, (dt2 - dt1).total_seconds() / 3600)

                batas_lembur = parse_dt(tanggal, "22:00:00")
                if dt2 > batas_lembur:
                    overtime_hours = round((dt2 - batas_lembur).total_seconds() / 3600, 2)
                else:
                    overtime_hours = 0.0

            actual_hours = round(actual_hours, 2)

        elif shift_code == "MALAM" and period1_in and period1_out:
            dt_in = parse_dt(tanggal, period1_in)
            dt_out = parse_dt(
                (datetime.strptime(tanggal, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"),
                period1_out
            )

            actual_hours = round(max(0, (dt_out - dt_in).total_seconds() / 3600), 2)

            batas_normal = parse_dt(
                (datetime.strptime(tanggal, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"),
                "08:00:00"
            )

            if dt_out > batas_normal:
                overtime_hours = round((dt_out - batas_normal).total_seconds() / 3600, 2)
            else:
                overtime_hours = 0.0

        else:
            if period1_in and period1_out:
                dt1 = parse_dt(tanggal, period1_in)
                dt2 = parse_dt(tanggal, period1_out)
                actual_hours += max(0, (dt2 - dt1).total_seconds() / 3600)

            if period2_in and period2_out:
                dt1 = parse_dt(tanggal, period2_in)

                if period2_out < period2_in:
                    dt2 = parse_dt(
                        (datetime.strptime(tanggal, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"),
                        period2_out
                    )
                else:
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

        if shift_code != "MALAM":
            overtime_calc = max(0, round(actual_hours - normal_hours, 2))
        else:
            overtime_calc = overtime_hours

        # =========================
        # FINAL OVERRIDE RULE PAGI
        # =========================
        if shift_code == "PAGI" and period1_in:
            hasil = apply_pagi_rules(period1_in)

            if hasil["lembur_p1"] > 0:
                overtime_hours = 1.0
            else:
                overtime_hours = overtime_calc
        else:
            overtime_hours = overtime_calc

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
        if shift_code in ["MALAM", "SORE"]:
            besok = (
                    datetime.strptime(tanggal, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")

            cur.execute("""
                UPDATE attendance_raw
                SET processed = 1
                WHERE fingerprint_id = ?
                  AND tanggal IN (?, ?)
                  AND IFNULL(processed, 0) = 0
            """, (fingerprint_id, tanggal, besok))

        else:
            cur.execute("""
                UPDATE attendance_raw
                SET processed = 1
                WHERE fingerprint_id = ?
                  AND tanggal = ?
                  AND IFNULL(processed, 0) = 0
            """, (fingerprint_id, tanggal))


if __name__ == "__main__":
    while True:
        process_attendance()
        time.sleep(10)