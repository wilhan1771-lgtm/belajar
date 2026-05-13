import sqlite3
from tabulate import tabulate

# =========================
# SETTING DATABASE
# =========================
DB_PATH = "receiving.db"   # ganti sesuai nama database

# =========================
# KONEK DATABASE
# =========================
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# =========================
# CEK RAW LOG
# =========================
def cek_raw(tanggal=None):

    print("\n================ RAW LOG ================\n")

    if tanggal:
        query = """
        SELECT
            tanggal,
            waktu,
            fingerprint_id,
            no_id,
            tipe_scan,
            status_absen,
            sumber,
            processed
        FROM raw_attendance
        WHERE tanggal = ?
        ORDER BY waktu ASC
        """
        cursor.execute(query, (tanggal,))
    else:
        query = """
        SELECT
            tanggal,
            waktu,
            fingerprint_id,
            no_id,
            tipe_scan,
            status_absen,
            sumber,
            processed
        FROM raw_attendance
        ORDER BY waktu DESC
        LIMIT 50
        """
        cursor.execute(query)

    data = cursor.fetchall()

    header = [
        "Tanggal",
        "Waktu",
        "Fingerprint",
        "No ID",
        "Scan",
        "Status",
        "Sumber",
        "Processed"
    ]

    print(tabulate(data, headers=header, tablefmt="grid"))


# =========================
# CEK ATTENDANCE
# =========================
def cek_attendance(tanggal=None):

    print("\n================ ATTENDANCE ================\n")

    if tanggal:
        query = """
        SELECT
            employee_id,
            fingerprint_id,
            work_date,
            shift_code,
            period1_in,
            period1_out,
            period2_in,
            period2_out,
            actual_hours,
            overtime_hours,
            late_minutes,
            early_leave_minutes,
            status_hadir,
            total_insentif
        FROM attendance
        WHERE work_date = ?
        ORDER BY employee_id ASC
        """
        cursor.execute(query, (tanggal,))
    else:
        query = """
        SELECT
            employee_id,
            fingerprint_id,
            work_date,
            shift_code,
            period1_in,
            period1_out,
            period2_in,
            period2_out,
            actual_hours,
            overtime_hours,
            late_minutes,
            early_leave_minutes,
            status_hadir,
            total_insentif
        FROM attendance
        ORDER BY work_date DESC
        LIMIT 50
        """
        cursor.execute(query)

    data = cursor.fetchall()

    header = [
        "Emp ID",
        "Fingerprint",
        "Tanggal",
        "Shift",
        "P1 IN",
        "P1 OUT",
        "P2 IN",
        "P2 OUT",
        "Jam Kerja",
        "Lembur",
        "Terlambat",
        "Pulang Cepat",
        "Status",
        "Insentif"
    ]

    print(tabulate(data, headers=header, tablefmt="grid"))


# =========================
# MENU
# =========================
while True:

    print("\n========== MENU ==========")
    print("1. Cek RAW")
    print("2. Cek Attendance")
    print("3. Cek RAW by tanggal")
    print("4. Cek Attendance by tanggal")
    print("0. Keluar")

    pilih = input("Pilih menu: ")

    if pilih == "1":
        cek_raw()

    elif pilih == "2":
        cek_attendance()

    elif pilih == "3":
        tgl = input("Masukkan tanggal (YYYY-MM-DD): ")
        cek_raw(tgl)

    elif pilih == "4":
        tgl = input("Masukkan tanggal (YYYY-MM-DD): ")
        cek_attendance(tgl)

    elif pilih == "0":
        break

    else:
        print("Menu tidak ada")

conn.close()