from datetime import datetime, time

JAM_MASUK = time(8, 0)
JAM_PULANG = time(17, 30)


def hitung_absensi(scans):

    if not scans:
        return None

    jam_masuk = scans[0]
    jam_pulang = scans[-1]

    terlambat = 0
    lembur = 0

    # Hitung terlambat
    if jam_masuk.time() > JAM_MASUK:
        terlambat = (
            datetime.combine(jam_masuk.date(), jam_masuk.time()) -
            datetime.combine(jam_masuk.date(), JAM_MASUK)
        ).seconds // 60

    # Hitung lembur
    if jam_pulang.time() > JAM_PULANG:
        lembur = (
            datetime.combine(jam_pulang.date(), jam_pulang.time()) -
            datetime.combine(jam_pulang.date(), JAM_PULANG)
        ).seconds // 60

    total_jam = (jam_pulang - jam_masuk).seconds // 3600

    return {
        "jam_masuk": jam_masuk,
        "jam_pulang": jam_pulang,
        "terlambat": terlambat,
        "lembur": lembur,
        "total_jam": total_jam
    }