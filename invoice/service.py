from datetime import datetime, timedelta
from .pricing import interpolate_price, div_round
from . import repository as repo

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
    return div_round(a * b, d)

def create_invoice_from_receiving(receiving_id, price_points, payment_type,
                                 cash_deduct_per_kg_rp=0, komisi_per_kg_rp=0,
                                 tempo_hari=0, partai_overrides=None):
    existing = repo.invoice_exists_for_receiving(receiving_id)
    if existing:
        raise ValueError(f"Invoice sudah ada untuk receiving ini. (invoice_id={existing['id']})")

    rh = repo.fetch_receiving_header(receiving_id)
    if not rh:
        raise ValueError("Receiving header tidak ditemukan.")

    supplier = rh["supplier"]

    due_date = None
    if tempo_hari and int(tempo_hari) > 0:
        try:
            d = datetime.strptime(rh["tanggal"], "%Y-%m-%d").date()
            due_date = (d + timedelta(days=int(tempo_hari))).isoformat()
        except Exception:
            due_date = None

    # cash deduct hanya berlaku jika cash
    if payment_type != "cash":
        cash_deduct_per_kg_rp = 0

    invoice_id = repo.insert_invoice_header(
        receiving_id=receiving_id,
        supplier=supplier,
        price_points=price_points,
        payment_type=payment_type,
        cash_deduct_per_kg_rp=int(cash_deduct_per_kg_rp),
        komisi_per_kg_rp=int(komisi_per_kg_rp),
        tempo_hari=int(tempo_hari),
        due_date=due_date,
    )

    items = repo.fetch_receiving_items(receiving_id)
    if not items:
        repo.update_invoice_totals(invoice_id, 0, 0, 0, 0, 0, 0)
        return invoice_id

    partai_overrides = partai_overrides or {}

    subtotal_rp = 0
    total_paid_g = 0

    for it in items:
        partai_no = int(it["partai_no"])
        rs = it.get("round_size")

        base_price = interpolate_price(rs, price_points)
        if base_price is None:
            raise ValueError(f"Harga tidak bisa dihitung untuk round_size={rs} (partai {partai_no}).")

        net_g = kg_to_g(it.get("netto"))
        paid_g = net_g
        price_override = None

        ov = partai_overrides.get(partai_no) or {}
        if "paid_kg" in ov and ov["paid_kg"] is not None:
            paid_g = kg_to_g(ov["paid_kg"])
        if "price_override" in ov and ov["price_override"] is not None and str(ov["price_override"]).strip() != "":
            price_override = int(ov["price_override"])

        used_price = price_override if price_override is not None else int(base_price)
        line_total = mul_div_round(int(paid_g), int(used_price), 1000)

        note = ov.get("note") or it.get("note")

        repo.insert_invoice_line(
            invoice_id=invoice_id,
            receiving_item_id=int(it["id"]),
            partai_no=partai_no,
            net_g=int(net_g),
            paid_g=int(paid_g),
            round_size=rs,
            price_per_kg_rp=int(base_price),
            price_override_per_kg_rp=price_override,
            line_total_rp=int(line_total),
            note=note,
        )

        subtotal_rp += int(line_total)
        total_paid_g += int(paid_g)

    cash_deduct_total = 0
    if payment_type == "cash" and int(cash_deduct_per_kg_rp) > 0:
        cash_deduct_total = mul_div_round(total_paid_g, int(cash_deduct_per_kg_rp), 1000)

    komisi_total = 0
    if int(komisi_per_kg_rp) > 0:
        komisi_total = mul_div_round(total_paid_g, int(komisi_per_kg_rp), 1000)

    pph_amount = 0  # belum dipakai

    total_payable = subtotal_rp - cash_deduct_total - pph_amount

    repo.update_invoice_totals(
        invoice_id=invoice_id,
        subtotal_rp=subtotal_rp,
        total_paid_g=total_paid_g,
        cash_deduct_total_rp=cash_deduct_total,
        komisi_total_rp=komisi_total,
        pph_amount_rp=pph_amount,
        total_payable_rp=total_payable,
    )

    return invoice_id