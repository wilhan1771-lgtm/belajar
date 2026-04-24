from datetime import datetime, time, timedelta


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


    return hasil
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
    shift_code = (r.get("shift_code") or "").strip().upper()
    gaji_harian = int(r.get("gaji_harian") or 100000)
    overtime_hours_db = float(r.get("overtime_hours") or 0)

    p1_in = parse_time_only(r.get("period1_in"))
    p1_out = parse_time_only(r.get("period1_out"))
    p2_in = parse_time_only(r.get("period2_in"))
    p2_out = parse_time_only(r.get("period2_out"))
    p3_in = parse_time_only(r.get("period3_in"))
    p3_out = parse_time_only(r.get("period3_out"))

    work_date = r.get("work_date")
    is_weekend = False
    is_hari_besar = False

    if work_date:
        try:
            dt = datetime.strptime(str(work_date), "%Y-%m-%d")
            is_weekend = dt.weekday() == 6   # Minggu
        except:
            pass

    # kalau nanti ada tabel hari libur, isi dari sini
    # is_hari_besar = cek_libur(work_date)

    insentif_libur_umum = 20000 if (is_weekend or is_hari_besar) else 0

    # =========================
    # VALIDASI DASAR
    # =========================
    if not p1_in:
        hasil["is_valid"] = False
        hasil["note"] = "Tidak scan masuk"
        return hasil

    # =========================
    # POTONGAN TELAT SEMUA SHIFT
    # > 1 menit dari jam masuk shift
    # =========================
    jadwal_masuk = get_shift_start(shift_code)
    telat_menit = int((p1_in - jadwal_masuk).total_seconds() // 60)
    if telat_menit >= 1:
        hasil["potongan_telat"] = 10000

    # =========================
    # LEMBUR MASUK LEBIH AWAL (P1)
    # berlaku semua shift
    # =========================
    lembur_awal_p1 = 0.0
    if p1_in < jadwal_masuk:
        lembur_awal_p1 = diff_hours(p1_in, jadwal_masuk)

    # =========================
    # BORONGAN
    # P1 IN + P1 OUT = 50rb
    # P3 IN + P3 OUT = insentif 10rb
    # =========================
    if shift_code == "BORONGAN" or bagian == "borongan":

        if p1_in and p1_out:
            hasil["work_type"] = "full"
            hasil["gaji_pokok"] = 50000
        else:
            hasil["work_type"] = "none"
            hasil["gaji_pokok"] = 0
            hasil["gaji_lembur"] = 0
            hasil["insentif"] = 0
            hasil["gaji_final"] = 0
            return hasil

        # P3 = insentif flat 10rb
        if p3_in and p3_out:
            hasil["insentif"] += 10000

        # Minggu / libur
        hasil["insentif"] += insentif_libur_umum

        hasil = apply_potongan_mes(r, hasil)

        hasil["gaji_final"] = (
                hasil["gaji_pokok"]
                + hasil["gaji_lembur"]
                + hasil["insentif"]
                - hasil["potongan_telat"]
                - hasil["potongan_mes"]
        )

        return hasil

    if shift_code == "MALAM":

        if not p1_out:
            hasil["is_valid"] = False
            hasil["note"] = "Shift malam belum checkout"
            return hasil

        hasil["work_type"] = "full"
        hasil["gaji_pokok"] = gaji_harian

        # lembur malam hanya dihitung setelah jam 08:00 pagi
        batas_normal = parse_time_only("08:00:00")
        if p1_out > batas_normal:
            jam = diff_hours(batas_normal, p1_out)
            hasil["gaji_lembur"] += lembur_to_uang(jam)

        hasil["insentif"] += insentif_libur_umum

        hasil = apply_potongan_mes(r, hasil)

        hasil["gaji_final"] = (
                hasil["gaji_pokok"]
                + hasil["gaji_lembur"]
                + hasil["insentif"]
                - hasil["potongan_telat"]
                - hasil["potongan_mes"]
        )

        return hasil

    if shift_code == "SORE":

        if p1_in:
            hasil["work_type"] = "full"
            hasil["gaji_pokok"] = gaji_harian
        else:
            hasil["work_type"] = "none"
            hasil["gaji_pokok"] = 0

        # shift sore / coldroom:
        # P1 normal 13:00 - 17:30
        # P2 normal 19:00 - 22:00
        # lembur hanya dihitung jika lewat 22:00
        if p2_out:
            batas_lembur = parse_time_only("22:00:00")
            if p2_out > batas_lembur:
                jam = diff_hours(batas_lembur, p2_out)
                hasil["gaji_lembur"] += lembur_to_uang(jam)

        hasil["insentif"] += insentif_libur_umum

        hasil = apply_potongan_mes(r, hasil)

        hasil["gaji_final"] = (
                hasil["gaji_pokok"]
                + hasil["gaji_lembur"]
                + hasil["insentif"]
                - hasil["potongan_telat"]
                - hasil["potongan_mes"]
        )

        return hasil
    # =========================
    # UMUM (shift pagi manual)
    # =========================
    if bagian == "umum":

        if p1_in or r.get("status_hadir") == "hadir":
            hasil["work_type"] = "full"
            hasil["gaji_pokok"] = gaji_harian
        else:
            hasil["work_type"] = "none"
            hasil["gaji_pokok"] = 0

        # lembur pagi UMUM dari P1 In
        if p1_in:
            batas_masuk = parse_time_only("08:00:00")
            if p1_in < batas_masuk:
                jam_awal = diff_hours(p1_in, batas_masuk)
                hasil["gaji_lembur"] += lembur_to_uang(jam_awal)
        # lembur P3 UMUM
        if p3_in and p3_out:
            jam_p3 = diff_hours(p3_in, p3_out)
            hasil["gaji_lembur"] += lembur_to_uang(jam_p3)

        hasil["insentif"] += insentif_libur_umum
        hasil = apply_potongan_mes(r, hasil)

        hasil["gaji_final"] = (
                hasil["gaji_pokok"]
                + hasil["gaji_lembur"]
                + hasil["insentif"]
                - hasil["potongan_telat"]
                - hasil["potongan_mes"]
        )

        return hasil
    # =========================
    # PAGI / PRODUKSI / BEKU / TRAINING / DEFAULT
    # out tidak terlalu ketat
    # ada P1 IN = full harian
    # =========================
    if p1_in:
        hasil["work_type"] = "full"
        hasil["gaji_pokok"] = gaji_harian
    else:
        hasil["work_type"] = "none"
        hasil["gaji_pokok"] = 0

    # lembur pagi khusus produksi / beku
    if bagian in ["produksi", "beku"] and p1_in:
        if p1_in <= parse_time_only("07:10:00"):
            hasil["gaji_lembur"] += 10000
        elif parse_time_only("07:11:00") <= p1_in <= parse_time_only("07:35:00"):
            hasil["gaji_lembur"] += 5000

    # P3 lembur per jam
    # hitung dari jam standar lembur, bukan dari scan awal rollingan
    if bagian in ["produksi", "beku", "training"] and p3_out:
        batas_p3 = parse_time_only("19:00:00")
        if p3_out > batas_p3:
            jam_p3 = diff_hours(batas_p3, p3_out)
            hasil["gaji_lembur"] += lembur_to_uang(jam_p3)

    hasil["insentif"] += insentif_libur_umum
    hasil = apply_potongan_mes(r, hasil)

    hasil["gaji_final"] = (
            hasil["gaji_pokok"]
            + hasil["gaji_lembur"]
            + hasil["insentif"]
            - hasil["potongan_telat"]
            - hasil["potongan_mes"]
    )

    return hasil