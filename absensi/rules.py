from datetime import datetime, time, timedelta
from helpers.db import DB_PATH
import sqlite3
# =========================
# HELPER
# =========================
def parse_time_only(t):
    if not t:
        return None
    return datetime.strptime(t, "%H:%M:%S")

def apply_potongan_mes(r, hasil):
    potongan_mes = 0

    tinggal_di_mes = int(r.get("tinggal_di_mes") or 0)

    if tinggal_di_mes == 1:
        if hasil["work_type"] == "full":
            potongan_mes = 10000
        elif hasil["work_type"] == "half":
            potongan_mes = 5000

    hasil["potongan_mes"] = potongan_mes
    hasil["gaji_final"] = (
        hasil["gaji_pokok"]
        + hasil["gaji_lembur"]
        + hasil["insentif"]
        - hasil["potongan_telat"]
        - hasil["potongan_mes"]
    )

    return hasil
def lembur_to_uang_min_1(hours):
    """
    Lembur minimal 1 jam.
    Kalau ada lembur > 0 tapi kurang dari 1 jam,
    tetap dibayar 10.000.
    """
    if not hours or hours <= 0:
        return 0

    jam_bulat = round_half_hour(hours)

    if jam_bulat < 1:
        jam_bulat = 1

    return int(jam_bulat * 10000)

def apply_insentif_lembur_weekend(r, hasil, flags):
    bagian = (r.get("bagian") or "").strip().lower()

    p3_out = parse_time_only(r.get("period3_out"))
    p2_out = parse_time_only(r.get("period2_out"))
    p1_out = parse_time_only(r.get("period1_out"))

    if not (
        flags["is_sabtu"]
        or flags["is_minggu"]
        or flags["is_hari_khusus_lembur"]
    ):
        return hasil

    if bagian == "kebersihan":
        return hasil

    if bagian in ["produksi", "beku", "training", "umum"]:
        batas = parse_time_only("19:00:00")
        if p3_out:
            menit = int(diff_hours(batas, p3_out) * 60)
            if menit >= 30:
                hasil["insentif"] += 10000
        return hasil

    if bagian == "coldroom":
        batas = parse_time_only("22:00:00")
        if p2_out:
            menit = int(diff_hours(batas, p2_out) * 60)
            if menit >= 30:
                hasil["insentif"] += 10000
        return hasil

    if bagian == "malam":
        batas = parse_time_only("08:00:00")
        if p1_out:
            menit = int(diff_hours(batas, p1_out) * 60)
            if menit >= 30:
                hasil["insentif"] += 10000
        return hasil

    return hasil
def hitung_insentif_libur(r, p1_in, p2_out, work_type):
    """
    Minggu / hari libur / tanggal merah:
    - full day = 20.000
    - half day = 10.000
    - tidak hadir / none = 0
    """
    work_date = r.get("work_date")
    is_minggu = False
    is_hari_besar = False

    if work_date:
        try:
            dt = datetime.strptime(str(work_date), "%Y-%m-%d")
            is_minggu = dt.weekday() == 6
        except:
            pass

    # nanti kalau ada tabel hari libur:
    is_hari_besar = cek_libur(work_date)

    if not (is_minggu or is_hari_besar):
        return 0

    if work_type == "full":
        return 20000

    if work_type == "half":
        return 10000

    return 0


def cek_libur(work_date):
    if not work_date:
        return False

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT 1
        FROM hari_libur
        WHERE tanggal = ?
        LIMIT 1
    """, (work_date,))

    ada = cur.fetchone() is not None
    conn.close()

    return ada

def diff_hours(t1, t2):
    if not t1 or not t2:
        return 0.0

    dt1 = t1
    dt2 = t2

    # support lintas tengah malam
    if dt2 < dt1:
        dt2 = dt2 + timedelta(days=1)

    return max(0.0, (dt2 - dt1).total_seconds() / 3600)


def round_half_hour(hours):
    """Pembulatan ke 0.5 jam terdekat."""
    if not hours or hours <= 0:
        return 0.0
    return round(hours * 2) / 2


def lembur_to_uang(hours):
    """0.5 jam = 5.000 | 1 jam = 10.000"""
    jam_bulat = round_half_hour(hours)
    return int(jam_bulat * 10000)


def get_shift_start(shift_code):
    shift_code = (shift_code or "").strip().upper()

    if shift_code == "PAGI":
        return parse_time_only("08:00:00")
    elif shift_code == "BORONGAN":
        return parse_time_only("08:00:00")
    elif shift_code == "SORE":
        return parse_time_only("13:00:00")
    elif shift_code == "MALAM":
        return parse_time_only("22:00:00")

    return parse_time_only("08:00:00")


# =========================
# RULE SHIFT PAGI - dipakai processor
# =========================
def apply_pagi_rules(period1_in):
    if not period1_in:
        return {
            "lembur_p1": 0.0,
            "potongan_telat": 0
        }

    actual_in = parse_time_only(period1_in)
    jadwal = parse_time_only("08:00:00")

    lembur_p1 = 0.0
    potongan_telat = 0

    # masuk lebih awal = lembur
    if actual_in < jadwal:
        jam_awal = diff_hours(actual_in, jadwal)
        lembur_p1 = round_half_hour(jam_awal)

    # telat > 1 menit = potong 10rb
    telat_menit = int((actual_in - jadwal).total_seconds() // 60)
    if telat_menit >= 1:
        potongan_telat = 10000

    return {
        "lembur_p1": lembur_p1,
        "potongan_telat": potongan_telat
    }

def rule_produksi_beku_umum(r, hasil):
    bagian = (r.get("bagian") or "").strip().lower()
    gaji_harian = int(r.get("gaji_harian") or 100000)

    p1_in = parse_time_only(r.get("period1_in"))
    p1_out = parse_time_only(r.get("period1_out"))
    p2_in = parse_time_only(r.get("period2_in"))
    p2_out = parse_time_only(r.get("period2_out"))
    p3_in = parse_time_only(r.get("period3_in"))
    p3_out = parse_time_only(r.get("period3_out"))

    flags = get_day_flags(r.get("work_date"))

    batas_p1_masuk = parse_time_only("08:00:00")

    if not p1_in:
        hasil["work_type"] = "none"
        hasil["gaji_pokok"] = 0
        hasil["is_valid"] = False
        hasil["note"] = "Tidak scan masuk P1"
        return apply_potongan_mes(r, hasil)

    telat_menit = int((p1_in - batas_p1_masuk).total_seconds() // 60)
    if telat_menit >= 1:
        hasil["potongan_telat"] = 10000

    if not p1_out:
        hasil["work_type"] = "none"
        hasil["gaji_pokok"] = 0
        hasil["insentif"] = 0
        hasil["is_valid"] = False
        hasil["note"] = "Tidak checkout P1, gaji tidak dihitung"
        return apply_potongan_mes(r, hasil)

    if p1_in and p1_out and p2_in and p2_out:
        hasil["work_type"] = "full"
        hasil["gaji_pokok"] = gaji_harian
    else:
        hasil["work_type"] = "half"
        hasil["gaji_pokok"] = int(gaji_harian / 2)
        hasil["note"] = "Kerja setengah hari"

    # lembur masuk pagi
    if p1_in <= parse_time_only("07:10:00"):
        hasil["gaji_lembur"] += 10000
    elif parse_time_only("07:11:00") <= p1_in <= parse_time_only("07:35:00"):
        hasil["gaji_lembur"] += 5000

    # lembur P3
    if p3_in and p3_out:
        batas_p3 = parse_time_only("19:00:00")
        if p3_out > batas_p3:
            jam_p3 = diff_hours(batas_p3, p3_out)
            hasil["gaji_lembur"] += lembur_to_uang(jam_p3)

    hasil = apply_insentif_libur(r, hasil)
    hasil = apply_insentif_lembur_weekend(r, hasil, flags)
    return apply_potongan_mes(r, hasil)

def rule_borongan(r, hasil):
    p1_in = parse_time_only(r.get("period1_in"))
    p1_out = parse_time_only(r.get("period1_out"))
    p2_in = parse_time_only(r.get("period2_in"))
    p2_out = parse_time_only(r.get("period2_out"))
    p3_in = parse_time_only(r.get("period3_in"))
    p3_out = parse_time_only(r.get("period3_out"))

    flags = get_day_flags(r.get("work_date"))

    if not p1_in or not p1_out:
        hasil["work_type"] = "none"
        hasil["gaji_pokok"] = 0
        hasil["gaji_lembur"] = 0
        hasil["insentif"] = 0
        hasil["is_valid"] = False
        hasil["note"] = "Borongan wajib P1 in dan P1 out"
        return apply_potongan_mes(r, hasil)
    batas_p1_masuk = parse_time_only("08:00:00")
    hasil = apply_potongan_telat(p1_in, batas_p1_masuk, hasil)
    hasil["gaji_pokok"] = 50000

    if p2_in and p2_out:
        hasil["work_type"] = "full"
    else:
        hasil["work_type"] = "half"


    hasil = apply_insentif_libur(r, hasil)
    hasil = apply_insentif_lembur_weekend(r, hasil, flags)
    hasil = apply_potongan_telat(p1_in, batas_p1_masuk, hasil)
    if p3_in and p3_out:
        hasil["insentif"] += 10000

    return apply_potongan_mes(r, hasil)

def rule_coldroom_sore(r, hasil):
    gaji_harian = int(r.get("gaji_harian") or 100000)

    p1_in = parse_time_only(r.get("period1_in"))
    p1_out = parse_time_only(r.get("period1_out"))
    p2_in = parse_time_only(r.get("period2_in"))
    p2_out = parse_time_only(r.get("period2_out"))

    flags = get_day_flags(r.get("work_date"))

    batas_masuk = parse_time_only("13:00:00")
    batas_lembur = parse_time_only("22:00:00")

    if not p1_in:
        hasil["work_type"] = "none"
        hasil["gaji_pokok"] = 0
        hasil["is_valid"] = False
        hasil["note"] = "Tidak scan masuk P1"
        return apply_potongan_mes(r, hasil)

    if not p1_out:
        hasil["work_type"] = "none"
        hasil["gaji_pokok"] = 0
        hasil["is_valid"] = False
        hasil["note"] = "Tidak checkout P1"
        return apply_potongan_mes(r, hasil)

    if p1_in and p1_out and p2_in and p2_out:
        hasil["work_type"] = "full"
        hasil["gaji_pokok"] = gaji_harian
    else:
        hasil["work_type"] = "half"
        hasil["gaji_pokok"] = int(gaji_harian / 2)
        hasil["note"] = "Kerja setengah hari"

    if p2_out:
        jam_lembur = diff_hours(batas_lembur, p2_out)
        if jam_lembur > 0:
            hasil["gaji_lembur"] += lembur_to_uang(jam_lembur)

    hasil = apply_insentif_libur(r, hasil)
    hasil = apply_insentif_lembur_weekend(r, hasil, flags)
    hasil = apply_potongan_telat(p1_in, batas_masuk, hasil)
    return apply_potongan_mes(r, hasil)

def rule_malam(r, hasil):
    gaji_harian = int(r.get("gaji_harian") or 100000)

    p1_in = parse_time_only(r.get("period1_in"))
    p1_out = parse_time_only(r.get("period1_out"))

    flags = get_day_flags(r.get("work_date"))

    batas_masuk = parse_time_only("22:00:00")
    batas_normal_pulang = parse_time_only("08:00:00")

    if not p1_in:
        hasil["work_type"] = "none"
        hasil["gaji_pokok"] = 0
        hasil["is_valid"] = False
        hasil["note"] = "Tidak scan masuk malam"
        return apply_potongan_mes(r, hasil)


    if not p1_out:
        hasil["work_type"] = "none"
        hasil["gaji_pokok"] = 0
        hasil["is_valid"] = False
        hasil["note"] = "Shift malam belum checkout"
        return apply_potongan_mes(r, hasil)

    hasil["work_type"] = "full"
    hasil["gaji_pokok"] = gaji_harian
    hasil = apply_potongan_telat(p1_in, batas_masuk, hasil)
    jam_lembur = diff_hours(batas_normal_pulang, p1_out)
    menit_lembur = int(jam_lembur * 60)

    if menit_lembur >= 45:
        hasil["gaji_lembur"] += 10000
    elif menit_lembur > 15:
        hasil["gaji_lembur"] += 5000
    else:
        hasil["gaji_lembur"] += lembur_to_uang(jam_lembur)

    hasil = apply_insentif_libur(r, hasil)
    hasil = apply_insentif_lembur_weekend(r, hasil, flags)
    return apply_potongan_mes(r, hasil)

def rule_training(r, hasil):
    gaji_harian = int(r.get("gaji_harian") or 100000)

    p1_in = parse_time_only(r.get("period1_in"))
    p1_out = parse_time_only(r.get("period1_out"))
    p2_in = parse_time_only(r.get("period2_in"))
    p2_out = parse_time_only(r.get("period2_out"))
    p3_in = parse_time_only(r.get("period3_in"))
    p3_out = parse_time_only(r.get("period3_out"))

    flags = get_day_flags(r.get("work_date"))

    batas_p1_masuk = parse_time_only("08:00:00")

    if not p1_in:
        hasil["is_valid"] = False
        hasil["note"] = "Tidak scan masuk P1"
        return apply_potongan_mes(r, hasil)

    if not p1_out:
        hasil["is_valid"] = False
        hasil["note"] = "Tidak checkout P1, gaji tidak dihitung"
        return apply_potongan_mes(r, hasil)

    if p1_in and p1_out and p2_in and p2_out:
        hasil["work_type"] = "full"
        hasil["gaji_pokok"] = gaji_harian
    else:
        hasil["work_type"] = "half"
        hasil["gaji_pokok"] = int(gaji_harian / 2)
        hasil["note"] = "Kerja setengah hari"

    # tidak ada lembur pagi untuk training

    if p3_in and p3_out:
        batas_p3 = parse_time_only("19:00:00")
        if p3_out > batas_p3:
            jam_p3 = diff_hours(batas_p3, p3_out)
            hasil["gaji_lembur"] += lembur_to_uang(jam_p3)
    hasil = apply_potongan_telat(p1_in, batas_p1_masuk, hasil)
    hasil = apply_insentif_lembur_weekend(r, hasil, flags)
    hasil = apply_insentif_libur(r, hasil)

    return apply_potongan_mes(r, hasil)

def rule_kebersihan(r, hasil):
    gaji_harian = int(r.get("gaji_harian") or 100000)

    p1_in = parse_time_only(r.get("period1_in"))
    p1_out = parse_time_only(r.get("period1_out"))
    p2_in = parse_time_only(r.get("period2_in"))
    p2_out = parse_time_only(r.get("period2_out"))

    flags = get_day_flags(r.get("work_date"))

    batas_p1_masuk = parse_time_only("08:00:00")

    if not p1_in:
        hasil["is_valid"] = False
        hasil["note"] = "Tidak scan masuk P1"
        return apply_potongan_mes(r, hasil)

    if not p1_out:
        hasil["is_valid"] = False
        hasil["note"] = "Tidak checkout P1, gaji tidak dihitung"
        return apply_potongan_mes(r, hasil)

    if p1_in and p1_out and p2_in and p2_out:
        hasil["work_type"] = "full"
        hasil["gaji_pokok"] = gaji_harian
    else:
        hasil["work_type"] = "half"
        hasil["gaji_pokok"] = int(gaji_harian / 2)
        hasil["note"] = "Kerja setengah hari"

    # kebersihan tidak ada lembur sama sekali
    hasil = apply_potongan_telat(p1_in, batas_p1_masuk, hasil)
    hasil = apply_insentif_libur(r, hasil)
    return apply_potongan_mes(r, hasil)

def get_day_flags(work_date):
    is_sabtu = False
    is_minggu = False
    is_hari_besar = False

    if work_date:
        try:
            dt = datetime.strptime(str(work_date), "%Y-%m-%d")
            is_sabtu = dt.weekday() == 5
            is_minggu = dt.weekday() == 6
        except:
            pass

    # nanti bisa sambung ke DB hari libur
    is_hari_besar = cek_libur(work_date)

    return {
        "is_sabtu": is_sabtu,
        "is_minggu": is_minggu,
        "is_hari_besar": is_hari_besar,
        "is_tanggal_merah": is_minggu or is_hari_besar,
        "is_hari_khusus_lembur": is_sabtu or is_minggu or is_hari_besar,
        "insentif_libur_umum": 20000 if (is_minggu or is_hari_besar) else 0
    }
def apply_insentif_libur(r, hasil):
    work_date = r.get("work_date")

    is_minggu = False
    is_hari_besar = False

    if work_date:
        try:
            dt = datetime.strptime(str(work_date), "%Y-%m-%d")
            is_minggu = dt.weekday() == 6
        except:
            pass

    is_hari_besar = cek_libur(work_date)

    if not (is_minggu or is_hari_besar):
        return hasil

    if hasil["work_type"] == "full":
        hasil["insentif"] += 20000
    elif hasil["work_type"] == "half":
        hasil["insentif"] += 10000

    return hasil
# =========================
# HITUNG GAJI FINAL HARIAN
# =========================
def hitung_gaji_harian_row(r):

    hasil = {
        "work_type": "none",
        "gaji_pokok": 0,
        "gaji_lembur": 0,
        "insentif": 0,
        "potongan_telat": 0,
        "potongan_mes": 0,
        "gaji_final": 0,
        "note": "",
        "is_valid": True,
    }

    if r.get("status_hadir") != "hadir":
        hasil["note"] = "Tidak hadir"
        return hasil

    bagian = (r.get("bagian") or "").strip().lower()
    if bagian in ["produksi", "beku", "umum"]:
        return rule_produksi_beku_umum(r, hasil)
    if bagian == "borongan":
        return rule_borongan(r, hasil)
    if bagian == "coldroom":
        return rule_coldroom_sore(r, hasil)
    if bagian == "training":
        return rule_training(r, hasil)
    if bagian == "kebersihan":
        return rule_kebersihan(r, hasil)
    if bagian == "malam":
        return rule_malam(r, hasil)
    hasil["is_valid"] = False
    hasil["note"] = f"Rule bagian belum terdaftar: {bagian}"
    return apply_potongan_mes(r, hasil)

def apply_potongan_telat(p1_in, batas_masuk, hasil):
    if not p1_in:
        return hasil

    telat_menit = int((p1_in - batas_masuk).total_seconds() // 60)
    if telat_menit >= 1:
        hasil["potongan_telat"] = 10000

    return hasil
