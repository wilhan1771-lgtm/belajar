from datetime import datetime, timedelta
from .pricing import interpolate_price, div_round
from . import repository as repo
import json
from .pricing import resolve_price
def kg_to_g(kg):
    """
    Konversi kg (REAL sqlite) -> gram int stabil.
    Contoh: 157.8 -> 157800
    """
    if kg is None:
        return 0
    s = str(kg)
    try:
        if "." in s:
            whole, frac = s.split(".", 1)
            frac = (frac + "000")[:3]
            return int(whole) * 1000 + int(frac)
        return int(s) * 1000
    except Exception:
        return int(round(float(kg) * 1000))


def mul_div_round(a, b, d):
    # pembulatan sesuai div_round kamu
    return div_round(a * b, d)

def create_invoice_from_receiving(
    receiving_id,
    price_points,
    payment_type,
    cash_deduct_per_kg_rp=0,
    tempo_hari=0,
    partai_overrides=None,
    grade_prices=None,  # dipakai untuk manual_grade
):
    existing = repo.invoice_exists_for_receiving(receiving_id)
    if existing:
        raise ValueError(f"Invoice sudah ada untuk receiving ini. (invoice_id={existing['id']})")

    rh = repo.fetch_receiving_header(receiving_id)
    if not rh:
        raise ValueError("Receiving header tidak ditemukan.")

    jenis = (rh.get("jenis") or "").strip().lower()
    mode = repo.get_jenis_mode(jenis)  # "udang_size" | "manual_grade"
    is_manual = (mode == "manual_grade")

    items = repo.fetch_receiving_items(receiving_id) or []
    supplier = rh["supplier"]

    payment_type = (payment_type or "transfer").strip().lower()
    if payment_type not in ("cash", "transfer"):
        payment_type = "transfer"

    tempo_hari = int(tempo_hari or 0)
    cash_deduct_per_kg_rp = int(cash_deduct_per_kg_rp or 0)
    if payment_type != "cash":
        cash_deduct_per_kg_rp = 0

    # =========================
    # due_date
    # =========================
    due_date = None
    try:
        d = datetime.strptime(rh["tanggal"], "%Y-%m-%d").date()
        if payment_type == "cash":
            tempo_hari = 0
            due_date = d.isoformat()
        else:
            due_date = (d + timedelta(days=max(0, tempo_hari))).isoformat()
    except Exception:
        due_date = None

    # =========================
    # VALIDASI MANUAL GRADE
    # =========================
    if is_manual:
        if not isinstance(grade_prices, dict):
            raise ValueError("Manual grade butuh grade_prices (dict).")

        required_grades = sorted({
            (it.get("grade_manual") or "").strip()
            for it in items
            if (it.get("grade_manual") or "").strip()
        })

        if not required_grades:
            raise ValueError("Tidak ada grade_manual pada receiving_item. Isi grade per partai dulu.")

        missing = [g for g in required_grades if int(grade_prices.get(g) or 0) <= 0]
        if missing:
            raise ValueError(f"Harga untuk grade {', '.join(missing)} wajib diisi dan > 0.")

    # =========================
    # INSERT HEADER
    # (NOTE: grade_prices akan disimpan kalau repo kamu support)
    # =========================
    invoice_id = repo.insert_invoice_header(
        receiving_id=receiving_id,
        supplier=supplier,
        price_points=price_points or {},
        payment_type=payment_type,
        cash_deduct_per_kg_rp=cash_deduct_per_kg_rp,
        tempo_hari=tempo_hari,
        due_date=due_date,
        grade_prices=(grade_prices if is_manual else None),
    )

    if not items:
        repo.update_invoice_totals(
            invoice_id=invoice_id,
            subtotal_rp=0,
            total_paid_g=0,
            cash_deduct_total_rp=0,
            pph_amount_rp=0,
            total_payable_rp=0,
        )
        return invoice_id

    partai_overrides = partai_overrides or {}

    subtotal_rp = 0
    total_paid_g = 0

    # =========================
    # BUILD LINES
    # =========================
    for it in items:
        partai_no = int(it["partai_no"])

        # berat
        net_g = kg_to_g(it.get("netto"))
        paid_g = net_g

        ov = partai_overrides.get(partai_no) or {}
        if ov.get("paid_g") is not None:
            paid_g = int(ov["paid_g"])

        # harga/kg
        if is_manual:
            g = (it.get("grade_manual") or "").strip()
            used_price = int(grade_prices.get(g) or 0)
            if used_price <= 0:
                raise ValueError(f"Partai {partai_no}: harga grade_manual '{g}' tidak valid.")
        else:
            rs = it.get("round_size")
            try:
                rs_int = int(rs) if rs is not None and str(rs).strip() != "" else None
            except:
                rs_int = None

            base_price = interpolate_price(rs_int, price_points) if rs_int is not None else None

            # fallback nearest jika interpolate gagal tapi ada price_points
            if base_price is None and price_points and rs_int is not None:
                nearest = min(price_points.keys(), key=lambda k: abs(int(k) - rs_int))
                base_price = price_points[nearest]

            if base_price is None:
                raise ValueError(f"Harga tidak bisa dihitung untuk round_size={rs} (partai {partai_no}).")

            used_price = int(base_price)

        line_total = mul_div_round(int(paid_g), int(used_price), 1000)
        note = ov.get("note") or it.get("note")

        repo.insert_invoice_line(
            invoice_id=invoice_id,
            receiving_item_id=int(it["id"]),
            partai_no=partai_no,
            net_g=int(net_g),
            paid_g=int(paid_g),
            round_size=it.get("round_size"),
            price_per_kg_rp=int(used_price),
            line_total_rp=int(line_total),
            note=note,
        )

        subtotal_rp += int(line_total)
        total_paid_g += int(paid_g)

    # =========================
    # totals
    # =========================
    cash_deduct_total = 0
    if payment_type == "cash" and cash_deduct_per_kg_rp > 0:
        cash_deduct_total = mul_div_round(total_paid_g, cash_deduct_per_kg_rp, 1000)

    pph_amount = 0
    total_payable = subtotal_rp - cash_deduct_total - pph_amount

    repo.update_invoice_totals(
        invoice_id=invoice_id,
        subtotal_rp=subtotal_rp,
        total_paid_g=total_paid_g,
        cash_deduct_total_rp=cash_deduct_total,
        pph_amount_rp=pph_amount,
        total_payable_rp=total_payable,
    )

    return invoice_id

def mul_div_round(a, b, d):
    return div_round(a * b, d)

from . import repository as repo
from .pricing import interpolate_price, div_round

def rebuild_invoice_lines(
    invoice_id: int,
    receiving_id: int,
    price_points: dict | None,
    payment_type: str,
    tempo_hari: int = 0,
    cash_deduct_per_kg_rp: int = 0,
    partai_overrides: dict | None = None,
    grade_prices: dict | None = None,   # ✅ manual_grade
):
    """
    Rebuild invoice_line + totals berdasarkan receiving_item terbaru.
    - Mode 'udang_size': pakai interpolate_price dari price_points
    - Mode 'manual_grade': pakai grade_manual + grade_prices
      Jika grade_prices None → ambil dari invoice_header.grade_prices_json
    """

    rh = repo.fetch_receiving_header(receiving_id)
    if not rh:
        raise ValueError("Receiving header tidak ditemukan.")

    jenis = (rh.get("jenis") or "").strip().lower()
    mode = repo.get_jenis_mode(jenis)  # "udang_size" | "manual_grade"
    is_manual = (mode == "manual_grade")

    items = repo.fetch_receiving_items(receiving_id) or []
    partai_overrides = partai_overrides or {}
    price_points = price_points or {}

    # ambil grade_prices dari header jika manual dan param belum dikirim
    if is_manual and not isinstance(grade_prices, dict):
        inv = repo.get_invoice_header(invoice_id)
        try:
            gp = json.loads(inv.get("grade_prices_json") or "{}")
            if isinstance(gp, dict):
                grade_prices = {str(k): int(v) for k, v in gp.items()}
            else:
                grade_prices = {}
        except Exception:
            grade_prices = {}

    # validasi manual
    if is_manual:
        if not isinstance(grade_prices, dict):
            raise ValueError("Manual grade butuh grade_prices (dict).")

        required_grades = sorted({
            (it.get("grade_manual") or "").strip()
            for it in items
            if (it.get("grade_manual") or "").strip()
        })

        if not required_grades:
            raise ValueError("Tidak ada grade pada partai. Isi grade per partai dulu.")

        missing = [g for g in required_grades if int(grade_prices.get(g) or 0) <= 0]
        if missing:
            raise ValueError(f"Harga untuk grade {', '.join(missing)} wajib diisi dan > 0.")

    subtotal_rp = 0
    total_paid_g = 0

    conn = repo.get_conn()
    try:
        # hapus lines lama dulu (aman karena receiving_item_id UNIQUE)
        conn.execute("DELETE FROM invoice_line WHERE invoice_id=?", (int(invoice_id),))

        for it in items:
            partai_no = int(it["partai_no"])
            rs = it.get("round_size")

            # tentukan harga/kg
            if is_manual:
                g = (it.get("grade_manual") or "").strip()
                used_price = int(grade_prices.get(g) or 0)
                if used_price <= 0:
                    raise ValueError(f"Partai {partai_no}: harga grade '{g}' belum diisi.")
            else:
                base_price = interpolate_price(rs, price_points)
                if base_price is None:
                    raise ValueError(f"Harga tidak bisa dihitung untuk round_size={rs} (partai {partai_no}).")
                used_price = int(base_price)

            net_g = kg_to_g(it.get("netto"))
            paid_g = net_g

            ov = partai_overrides.get(partai_no) or {}
            if ov.get("paid_g") is not None:
                paid_g = int(ov["paid_g"])

            line_total = mul_div_round(int(paid_g), int(used_price), 1000)
            note = ov.get("note") or it.get("note")

            conn.execute("""
                INSERT INTO invoice_line (
                    invoice_id, receiving_item_id, partai_no,
                    net_g, paid_g, round_size, price_per_kg_rp, line_total_rp, note
                ) VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                int(invoice_id),
                int(it["id"]),
                int(partai_no),
                int(net_g),
                int(paid_g),
                rs,
                int(used_price),
                int(line_total),
                note
            ))

            subtotal_rp += int(line_total)
            total_paid_g += int(paid_g)

        # cash deduct
        cash_deduct_total = 0
        if (payment_type or "").strip().lower() == "cash" and int(cash_deduct_per_kg_rp or 0) > 0:
            cash_deduct_total = mul_div_round(total_paid_g, int(cash_deduct_per_kg_rp), 1000)

        # pph belum dipakai
        pph_amount = 0
        total_payable = subtotal_rp - cash_deduct_total - pph_amount

        conn.execute("""
            UPDATE invoice_header
            SET subtotal_rp=?,
                total_paid_g=?,
                cash_deduct_total_rp=?,
                pph_amount_rp=?,
                total_payable_rp=?
            WHERE id=?
        """, (
            int(subtotal_rp),
            int(total_paid_g),
            int(cash_deduct_total),
            int(pph_amount),
            int(total_payable),
            int(invoice_id)
        ))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def rebuild_invoice_from_receiving_if_exists(conn, receiving_id: int):
    """
    Jika invoice untuk receiving ini sudah ada:
    - rebuild ulang invoice_line dari receiving_item terbaru
    - harga lama dipakai sebagai fallback
    """

    inv = conn.execute("""
        SELECT id, price_points_json, payment_type, cash_deduct_per_kg_rp
        FROM invoice_header
        WHERE receiving_id=?
        LIMIT 1
    """, (receiving_id,)).fetchone()

    if not inv:
        return

    invoice_id = int(inv["id"])

    # =========================
    # ambil mode jenis
    # =========================
    rh = conn.execute(
        "SELECT jenis FROM receiving_header WHERE id=?",
        (receiving_id,)
    ).fetchone()

    jenis = (rh["jenis"] or "").strip().lower() if rh else ""

    rowm = conn.execute("""
        SELECT COALESCE(mode,'udang_size') AS mode
        FROM master_jenis
        WHERE LOWER(nama)=LOWER(?)
        LIMIT 1
    """, (jenis,)).fetchone()

    mode = (rowm["mode"] if rowm else "udang_size") or "udang_size"
    mode = mode.strip().lower()

    is_manual = (mode == "manual_grade")

    # =========================
    # load price_points
    # =========================
    price_points = {}

    try:
        pts = json.loads(inv["price_points_json"] or "{}")
        price_points = {int(k): int(v) for k, v in pts.items()}
    except:
        price_points = {}

    # =========================
    # harga lama invoice_line
    # =========================
    old_prices = {}

    for r in conn.execute("""
        SELECT receiving_item_id, price_per_kg_rp
        FROM invoice_line
        WHERE invoice_id=?
    """, (invoice_id,)).fetchall():

        old_prices[int(r["receiving_item_id"])] = int(r["price_per_kg_rp"] or 0)

    # =========================
    # ambil receiving_item terbaru
    # =========================
    items = conn.execute("""
        SELECT *
        FROM receiving_item
        WHERE header_id=?
        ORDER BY partai_no ASC
    """, (receiving_id,)).fetchall()

    # hapus lines lama
    conn.execute("DELETE FROM invoice_line WHERE invoice_id=?", (invoice_id,))

    subtotal_rp = 0
    total_paid_g = 0

    # =========================
    # rebuild lines
    # =========================
    for it in items:

        rid = int(it["id"])
        partai_no = int(it["partai_no"])
        rs = it["round_size"]

        used_price = 0

        if is_manual:

            used_price = int(old_prices.get(rid) or 0)

            if used_price <= 0:
                raise ValueError(
                    f"Invoice manual_grade tidak punya harga untuk partai {partai_no}. "
                    f"Edit invoice lalu isi harga grade."
                )

        else:

            base_price = interpolate_price(rs, price_points) if rs else None

            if base_price is None:

                used_price = int(old_prices.get(rid) or 0)

                if used_price <= 0:
                    raise ValueError(
                        f"Harga tidak bisa dihitung untuk round_size={rs} "
                        f"(partai {partai_no})."
                    )
            else:
                used_price = int(base_price)

        net_g = kg_to_g(it["netto"])
        paid_g = net_g

        line_total = mul_div_round(paid_g, used_price, 1000)

        conn.execute("""
            INSERT INTO invoice_line (
                invoice_id,
                receiving_item_id,
                partai_no,
                net_g,
                paid_g,
                round_size,
                price_per_kg_rp,
                line_total_rp,
                note
            ) VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            invoice_id,
            rid,
            partai_no,
            net_g,
            paid_g,
            rs,
            used_price,
            line_total,
            it["note"],
        ))

        subtotal_rp += line_total
        total_paid_g += paid_g

    # =========================
    # cash deduction
    # =========================
    payment_type = (inv["payment_type"] or "transfer").strip().lower()

    cash_deduct_per_kg_rp = int(inv["cash_deduct_per_kg_rp"] or 0)

    if payment_type != "cash":
        cash_deduct_per_kg_rp = 0

    cash_deduct_total = 0

    if payment_type == "cash" and cash_deduct_per_kg_rp > 0:

        cash_deduct_total = mul_div_round(
            total_paid_g,
            cash_deduct_per_kg_rp,
            1000
        )

    total_payable = subtotal_rp - cash_deduct_total

    conn.execute("""
        UPDATE invoice_header
        SET subtotal_rp=?,
            total_paid_g=?,
            cash_deduct_total_rp=?,
            total_payable_rp=?
        WHERE id=?
    """, (
        subtotal_rp,
        total_paid_g,
        cash_deduct_total,
        total_payable,
        invoice_id
    ))