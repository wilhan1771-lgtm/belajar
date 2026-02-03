from receiving.calculator import hitung_partai, recalc_receiving
import json

def update_receiving(conn, header_id: int, partai_list: list):
    """
    partai_list = list of dict dari request.form / request.json
    """
    cur = conn.cursor()

    for p in partai_list:
        pid = p.get("id")
        if not pid:
            continue

        hasil = hitung_partai(p)

        cur.execute("""
            UPDATE receiving_partai
            SET pcs=?,
                kg_sample=?,
                tara_per_keranjang=?,
                keranjang=?,
                bruto=?,
                total_tara=?,
                netto=?,
                size=?,
                round_size=?,
                timbangan_json=?
            WHERE id=?
        """, (
            p.get("pcs"),
            p.get("kg_sample"),
            p.get("tara_per_keranjang"),
            hasil["keranjang"],
            hasil["bruto"],
            hasil["total_tara"],
            hasil["netto"],
            hasil["size"],
            hasil["round_size"],
            hasil["timbangan_json"],
            pid
        ))

    # 🔁 hitung ulang header (fiber, dll)
    recalc_receiving(conn, header_id)
