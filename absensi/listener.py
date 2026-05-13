from zk import ZK
import time
from datetime import datetime
from helpers.db import get_conn

IP = "192.168.1.201"
PORT = 4370


def get_last_scan():
    db = get_conn()
    cur = db.cursor()

    cur.execute("""
        SELECT tanggal, waktu
        FROM attendance_raw
        ORDER BY tanggal DESC, waktu DESC
        LIMIT 1
    """)

    row = cur.fetchone()
    db.close()

    if row and row["tanggal"] and row["waktu"]:
        return datetime.strptime(
            f"{row['tanggal']} {row['waktu']}",
            "%Y-%m-%d %H:%M:%S"
        )

    return None


def start_listener():

    last_scan = get_last_scan()

    while True:

        conn = None
        db = None

        try:
            print("🔌 Mencoba koneksi ke mesin...")

            # buat object baru setiap reconnect
            zk = ZK(
                IP,
                port=PORT,
                timeout=10,
                force_udp=False
            )

            conn = zk.connect()

            print("✅ Connected ke mesin absensi")

            while True:

                try:
                    attendances = conn.get_attendance()

                except Exception as e:
                    print("❌ Gagal baca attendance:", e)
                    break

                if not attendances:
                    time.sleep(2)
                    continue

                db = get_conn()
                cur = db.cursor()

                inserted = 0
                newest_scan = last_scan

                for att in attendances:

                    fingerprint_id = str(att.user_id).strip()
                    waktu = att.timestamp

                    if not fingerprint_id or not waktu:
                        continue

                    if last_scan and waktu <= last_scan:
                        continue

                    tanggal = waktu.strftime("%Y-%m-%d")
                    jam = waktu.strftime("%H:%M:%S")

                    cur.execute("""
                        INSERT OR IGNORE INTO attendance_raw
                        (
                            tanggal,
                            waktu,
                            fingerprint_id,
                            no_id,
                            tipe_scan,
                            status_absen,
                            sumber,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        tanggal,
                        jam,
                        fingerprint_id,
                        fingerprint_id,
                        "fingerprint",
                        str(att.status),
                        "mb460",
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ))

                    if cur.rowcount > 0:
                        inserted += 1
                        print("✅ MASUK RAW:", fingerprint_id, waktu)

                    if newest_scan is None or waktu > newest_scan:
                        newest_scan = waktu

                db.commit()
                db.close()
                db = None

                if newest_scan:
                    last_scan = newest_scan

                if inserted == 0:
                    print("Tidak ada data baru")

                time.sleep(2)

        except Exception as e:
            print("❌ Koneksi putus:", e)

        finally:

            try:
                if db:
                    db.close()
            except:
                pass

            try:
                if conn:
                    conn.disconnect()
            except:
                pass

            print("🔄 Reconnect 5 detik lagi...")
            time.sleep(5)


if __name__ == "__main__":
    start_listener()
