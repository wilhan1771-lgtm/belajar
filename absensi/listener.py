from zk import ZK
import time
from datetime import datetime
from helpers.db import get_conn, DB_PATH

ip = "192.168.1.201"
port = 4370

zk = ZK(ip, port=port, timeout=5)

def start_listener():
    while True:
        try:
            print("🔌 Mencoba koneksi ke mesin...")

            conn = zk.connect()
            print("✅ Connected ke mesin absensi")
            print("Menunggu fingerprint...")

            last_count = 0

            while True:
                attendances = conn.get_attendance()

                if len(attendances) != last_count:
                    new_data = attendances[last_count:]

                    for att in new_data:
                        fingerprint_id = str(att.user_id)
                        waktu = att.timestamp
                        tanggal = waktu.date()
                        status_scan = str(att.status)

                        db = get_conn()
                        cur = db.cursor()

                        cur.execute("""
                        INSERT OR IGNORE INTO attendance_raw
                        (tanggal, waktu, fingerprint_id, no_id, tipe_scan, status_absen, sumber, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            tanggal,
                            waktu.strftime("%H:%M:%S"),
                            fingerprint_id,
                            fingerprint_id,
                            "fingerprint",
                            status_scan,
                            "mb460",
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        ))

                        db.commit()
                        db.close()

                        print("✅ MASUK RAW:", fingerprint_id, waktu)

                    last_count = len(attendances)

                time.sleep(2)

        except Exception as e:
            print("❌ Koneksi putus:", e)
            print("🔄 Coba reconnect 5 detik lagi...")
            time.sleep(5)