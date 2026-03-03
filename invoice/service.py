from datetime import datetime, timedelta
from .pricing import interpolate_price, div_round
from . import repository as repo
import json

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
    kupasan_prices=None,
    grade_prices=None,
):
    existing = repo.invoice_exists_for_receiving(receiving_id)
    if existing:
        raise ValueError(f"Invoice sudah ada untuk receiving ini. (invoice_id={existing['id']})")
    row = repo.get_conn().execute(
        "SELECT COALESCE(mode,'udang_size') AS mode FROM master_jenis WHERE LOWER(nama)=LOWER(?)",
        (jenis,)
    ).fetchone()

    mode = (row["mode"] if row else "udang_size").lower()

    rh = repo.fetch_receiving_header(receiving_id)
    if not rh:
        raise ValueError("Receiving header tidak ditemukan.")

    jenis = (rh.get("jenis") or "").strip().lower()

    mode = repo.get_jenis_mode(jenis)  # buat helper ini
    is_kupasan = (mode == "kupasan")
    is_manual = (mode == "manual_grade")
    required_manual_grades = set()

    if is_manual:
        if not isinstance(grade_prices, dict):
            raise ValueError("Manual grade butuh grade_prices (dict).")

        for it in items:
            g = (it.get("grade_manual") or "").strip()
            if g:
                required_manual_grades.add(g)

        if not required_manual_grades:
            raise ValueError("Tidak ada grade_manual pada receiving.")

        missing = []
        for g in required_manual_grades:
            if int(grade_prices.get(g) or 0) <= 0:
                missing.append(g)

        if missing:
            raise ValueError(f"Harga untuk grade {', '.join(missing)} wajib diisi dan > 0.")

    supplier = rh["supplier"]

    payment_type = (payment_type or "transfer").strip().lower()
    if payment_type not in ("cash", "transfer"):
        payment_type = "transfer"

    tempo_hari = int(tempo_hari or 0)
    cash_deduct_per_kg_rp = int(cash_deduct_per_kg_rp or 0)

    # due_date (cash & transfer)
    due_date = None
    try:
        d = datetime.strptime(rh["tanggal"], "%Y-%m-%d").date()

        if payment_type == "cash":
            tempo_hari = 0  # biar konsisten: cash selalu 0 hari
            due_date = d.isoformat()  # cash jatuh tempo hari itu
        else:
            # transfer
            due_date = (d + timedelta(days=max(0, tempo_hari))).isoformat()
    except Exception:
        due_date = None

    if payment_type != "cash":
        cash_deduct_per_kg_rp = 0

    items = repo.fetch_receiving_items(receiving_id)
    if not items:
        invoice_id = repo.insert_invoice_header(
            receiving_id=receiving_id,
            supplier=supplier,
            price_points=price_points or {},
            payment_type=payment_type,
            cash_deduct_per_kg_rp=cash_deduct_per_kg_rp,
            tempo_hari=tempo_hari,
            due_date=due_date,
        )
        repo.update_invoice_totals(
            invoice_id=invoice_id,
            subtotal_rp=0,
            total_paid_g=0,
            cash_deduct_total_rp=0,
            pph_amount_rp=0,
            total_payable_rp=0,
        )
        return invoice_id

    # --- KUPASAN: tentukan grade yang diperlukan dari items ---
    hk = hb = None
    required_grades = set()
    if is_kupasan:
        if not isinstance(kupasan_prices, dict):
            raise ValueError("Kupasan butuh kupasan_prices (dict).")

        # ambil required dari data receiving_item
        for it in items:
            g = (it.get("kategori_kupasan") or it.get("grade") or "").strip().lower()
            if g in ("kecil", "besar"):
                required_grades.add(g)

        # fallback kalau data grade kosong semua: anggap perlu dua (biar aman)
        if not required_grades:
            required_grades = {"kecil", "besar"}

        hk = int(kupasan_prices.get("kecil") or 0) if "kecil" in required_grades else 0
        hb = int(kupasan_prices.get("besar") or 0) if "besar" in required_grades else 0

        missing = []
        if "kecil" in required_grades and hk <= 0:
            missing.append("kecil")
        if "besar" in required_grades and hb <= 0:
            missing.append("besar")
        if missing:
            raise ValueError(f"Harga kupasan {', '.join(missing)} wajib diisi dan > 0.")

    # simpan header invoice
    invoice_id = repo.insert_invoice_header(
        receiving_id=receiving_id,
        supplier=supplier,
        price_points=price_points or {},  # kupasan boleh {}
        payment_type=payment_type,
        cash_deduct_per_kg_rp=cash_deduct_per_kg_rp,
        tempo_hari=tempo_hari,
        due_date=due_date,
    )

    partai_overrides = partai_overrides or {}

    subtotal_rp = 0
    total_paid_g = 0

    for it in items:
        partai_no = int(it["partai_no"])
        rs = it.get("round_size")

        # tentukan harga
        if is_kupasan:
            grade = (it.get("kategori_kupasan") or it.get("grade") or "").strip().lower()
            if grade == "kecil":
                used_price = hk
            elif grade == "besar":
                used_price = hb
            else:
                raise ValueError(
                    f"Partai {partai_no}: kategori_kupasan tidak valid ('{grade}'). Harus kecil/besar."
                )
        else:
            base_price = interpolate_price(rs, price_points)
            if base_price is None:
                raise ValueError(f"Harga tidak bisa dihitung untuk round_size={rs} (partai {partai_no}).")
            used_price = int(base_price)

        net_g = kg_to_g(it.get("netto"))
        paid_g = net_g

        ov = partai_overrides.get(partai_no) or {}
        if "paid_g" in ov and ov["paid_g"] is not None:
            paid_g = int(ov["paid_g"])

        line_total = mul_div_round(int(paid_g), int(used_price), 1000)

        note = ov.get("note") or it.get("note")

        repo.insert_invoice_line(
            invoice_id=invoice_id,
            receiving_item_id=int(it["id"]),
            partai_no=partai_no,
            net_g=int(net_g),
            paid_g=int(paid_g),
            round_size=rs,  # kupasan boleh None
            price_per_kg_rp=int(used_price),
            line_total_rp=int(line_total),
            note=note,
        )

        subtotal_rp += int(line_total)
        total_paid_g += int(paid_g)

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

def rebuild_invoice_from_receiving_if_exists(conn, receiving_id: int):
    """
    Jika sudah ada invoice untuk receiving_id, rebuild invoice_line + totals
    berdasarkan receiving_item terbaru.
    - Menggunakan setting dari invoice_header: price_points_json, payment_type,
      tempo_hari, cash_deduct_per_kg_rp, pph_amount_rp
    - Lines dihapus lalu insert ulang (aman untuk receiving_item_id UNIQUE)
    """

    inv = repo.get_invoice_by_receiving_conn(conn, receiving_id)
    if not inv:
        return

    # Kalau kamu mau invoice selalu ikut berubah, hapus blok ini.
    invoice_id = int(inv["id"])

    # ambil setting invoice
    try:
        pts = json.loads(inv.get("price_points_json") or "{}")
        price_points = {int(k): int(v) for k, v in pts.items()}
    except Exception:
        price_points = {}

    payment_type = (inv.get("payment_type") or "transfer").strip()
    if payment_type not in ("cash", "transfer"):
        payment_type = "transfer"

    tempo_hari = int(inv.get("tempo_hari") or 0)
    cash_deduct_per_kg_rp = int(inv.get("cash_deduct_per_kg_rp") or 0)
    if payment_type != "cash":
        cash_deduct_per_kg_rp = 0

    pph_amount = int(inv.get("pph_amount_rp") or 0)

    # ambil receiving terbaru (pakai conn yang sama)
    items = conn.execute(
        "SELECT * FROM receiving_item WHERE header_id=? ORDER BY partai_no ASC, id ASC",
        (int(receiving_id),)
    ).fetchall()

    # rebuild lines
    repo.delete_invoice_lines_conn(conn, invoice_id)

    subtotal_rp = 0
    total_paid_g = 0

    for it in items:
        it = dict(it)
        partai_no = int(it["partai_no"])
        rs = it.get("round_size")

        base_price = interpolate_price(rs, price_points)
        if base_price is None:
            raise ValueError(f"Harga tidak bisa dihitung untuk round_size={rs} (partai {partai_no}).")

        net_g = kg_to_g(it.get("netto"))
        paid_g = net_g  # karena kamu mau invoice mengikuti receiving (tanpa bayar sebagian)

        line_total = mul_div_round(int(paid_g), int(base_price), 1000)

        repo.insert_invoice_line_conn(
            conn=conn,
            invoice_id=invoice_id,
            receiving_item_id=int(it["id"]),
            partai_no=partai_no,
            net_g=int(net_g),
            paid_g=int(paid_g),
            round_size=rs,
            price_per_kg_rp=int(base_price),
            line_total_rp=int(line_total),
            note=it.get("note"),
        )

        subtotal_rp += int(line_total)
        total_paid_g += int(paid_g)

    cash_deduct_total = 0
    if payment_type == "cash" and cash_deduct_per_kg_rp > 0:
        cash_deduct_total = mul_div_round(total_paid_g, cash_deduct_per_kg_rp, 1000)

    total_payable = subtotal_rp - cash_deduct_total - pph_amount

    repo.update_invoice_totals_conn(
        conn=conn,
        invoice_id=invoice_id,
        subtotal_rp=subtotal_rp,
        total_paid_g=total_paid_g,
        cash_deduct_total_rp=cash_deduct_total,
        pph_amount_rp=pph_amount,
        total_payable_rp=total_payable,
    )

    # due_date update mengikuti payment_type/tempo_hari (berdasarkan tanggal invoice_header)
    repo.update_invoice_due_date_conn(conn, invoice_id)

def rebuild_invoice_lines(
    invoice_id,
    receiving_id,
    price_points,
    payment_type,
    tempo_hari=0,
    cash_deduct_per_kg_rp=0,
    partai_overrides=None,
    kupasan_prices=None,
):
    rh = repo.fetch_receiving_header(receiving_id)
    if not rh:
        raise ValueError("Receiving header tidak ditemukan.")

    jenis = (rh.get("jenis") or "").strip().lower()
    is_kupasan = (jenis == "kupasan")

    items = repo.fetch_receiving_items(receiving_id) or []
    partai_overrides = partai_overrides or {}

    # kupasan: tentukan required grades
    hk = hb = 0
    if is_kupasan:
        if not isinstance(kupasan_prices, dict):
            raise ValueError("Kupasan butuh kupasan_prices (dict).")

        required = set()
        for it in items:
            g = (it.get("kategori_kupasan") or it.get("grade") or "").strip().lower()
            if g in ("kecil", "besar"):
                required.add(g)
        if not required:
            required = {"kecil", "besar"}

        if "kecil" in required:
            hk = int(kupasan_prices.get("kecil") or 0)
            if hk <= 0:
                raise ValueError("Harga kupasan kecil wajib diisi dan > 0.")
        if "besar" in required:
            hb = int(kupasan_prices.get("besar") or 0)
            if hb <= 0:
                raise ValueError("Harga kupasan besar wajib diisi dan > 0.")

    subtotal_rp = 0
    total_paid_g = 0

    conn = repo.get_conn()
    try:
        for it in items:
            partai_no = int(it["partai_no"])
            rs = it.get("round_size")

            if is_kupasan:
                grade = (it.get("kategori_kupasan") or it.get("grade") or "").strip().lower()
                if grade == "kecil":
                    used_price = hk
                elif grade == "besar":
                    used_price = hb
                else:
                    raise ValueError(f"Partai {partai_no}: kategori_kupasan tidak valid ('{grade}').")
            else:
                base_price = interpolate_price(rs, price_points)
                if base_price is None:
                    raise ValueError(f"Harga tidak bisa dihitung untuk round_size={rs} (partai {partai_no}).")
                used_price = int(base_price)

            net_g = kg_to_g(it.get("netto"))
            paid_g = net_g

            ov = partai_overrides.get(partai_no) or {}
            if "paid_g" in ov and ov["paid_g"] is not None:
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
                partai_no,
                int(net_g),
                int(paid_g),
                rs,
                int(used_price),
                int(line_total),
                note
            ))

            subtotal_rp += int(line_total)
            total_paid_g += int(paid_g)

        cash_deduct_total = 0
        if payment_type == "cash" and int(cash_deduct_per_kg_rp or 0) > 0:
            cash_deduct_total = mul_div_round(total_paid_g, int(cash_deduct_per_kg_rp), 1000)

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
        """, (subtotal_rp, total_paid_g, cash_deduct_total, pph_amount, total_payable, int(invoice_id)))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()