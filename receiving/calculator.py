from helpers.number_utils import to_float
import json

def hitung_partai(p):
    timbangan = p.get("timbangan") or []
    timbangan = [to_float(x) for x in timbangan if to_float(x) > 0]

    tara = to_float(p.get("tara_per_keranjang"))

    bruto = round(sum(timbangan), 2)
    keranjang = len(timbangan)
    total_tara = round(keranjang * tara, 2)
    netto = round(bruto - total_tara, 2)

    size = None
    round_size = None

    pcs = to_float(p.get("pcs"))
    kg  = to_float(p.get("kg_sample") or p.get("kg"))

    if pcs > 0 and kg > 0:
        raw = pcs / kg
        size = round(raw, 1)
        round_size = round(raw)

    return {
        "bruto": bruto,
        "keranjang": keranjang,
        "total_tara": total_tara,
        "netto": netto,
        "size": size,
        "round_size": round_size,
        "timbangan_json": json.dumps(timbangan)
    }


def recalc_receiving(conn, header_id: int):
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT id, pcs, kg_sample, tara_per_keranjang, timbangan_json, fiber
        FROM receiving_partai
        WHERE header_id=?
    """, (header_id,)).fetchall()

    total_fiber = 0.0

    for r in rows:
        timbangan = json.loads(r["timbangan_json"] or "[]")
        timbangan = [float(x) for x in timbangan if x]

        keranjang = len(timbangan)
        bruto = sum(timbangan)

        tara = float(r["tara_per_keranjang"] or 0)
        total_tara = keranjang * tara
        netto = max(bruto - total_tara, 0)

        size = None
        round_size = None
        if r["pcs"] and r["kg_sample"] and r["kg_sample"] > 0:
            raw = r["pcs"] / r["kg_sample"]
            size = round(raw, 1)
            round_size = round(raw)

        cur.execute("""
            UPDATE receiving_partai
            SET keranjang=?, bruto=?, total_tara=?, netto=?,
                size=?, round_size=?
            WHERE id=?
        """, (
            keranjang, bruto, total_tara, netto,
            size, round_size,
            r["id"]
        ))

        try:
            total_fiber += float(r["fiber"] or 0)
        except:
            pass

    cur.execute("""
        UPDATE receiving_header
        SET fiber=?
        WHERE id=?
    """, (total_fiber, header_id))
