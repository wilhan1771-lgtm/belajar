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
    # pembulatan sesuai div_round kamu
    return div_round(a * b, d)


def create_invoice_from_receiving(
    receiving_id,
    price_points,
    payment_type,
    cash_deduct_per_kg_rp=0,
    tempo_hari=0,
    partai_overrides=None,
):
    existing = repo.invoice_exists_for_receiving(receiving_id)
    if existing:
        raise ValueError(f"Invoice sudah ada untuk receiving ini. (invoice_id={existing['id']})")

    rh = repo.fetch_receiving_header(receiving_id)
    if not rh:
        raise ValueError("Receiving header tidak ditemukan.")

    supplier = rh["supplier"]

    payment_type = (payment_type or "transfer").strip()
    if payment_type not in ("cash", "transfer"):
        payment_type = "transfer"

    tempo_hari = int(tempo_hari or 0)
    cash_deduct_per_kg_rp = int(cash_deduct_per_kg_rp or 0)

    # due_date hanya relevan untuk transfer
    due_date = None
    if payment_type == "transfer" and tempo_hari > 0:
        try:
            d = datetime.strptime(rh["tanggal"], "%Y-%m-%d").date()
            due_date = (d + timedelta(days=tempo_hari)).isoformat()
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
        cash_deduct_per_kg_rp=cash_deduct_per_kg_rp,
        tempo_hari=tempo_hari,
        due_date=due_date,
    )

    items = repo.fetch_receiving_items(receiving_id)
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

    for it in items:
        partai_no = int(it["partai_no"])
        rs = it.get("round_size")

        base_price = interpolate_price(rs, price_points)
        if base_price is None:
            raise ValueError(f"Harga tidak bisa dihitung untuk round_size={rs} (partai {partai_no}).")

        # receiving_item netto masih kg (float) -> gram int
        net_g = kg_to_g(it.get("netto"))
        paid_g = net_g

        ov = partai_overrides.get(partai_no) or {}

        # override hanya paid_g (gram) + note
        if "paid_g" in ov and ov["paid_g"] is not None:
            paid_g = int(ov["paid_g"])

        used_price = int(base_price)
        line_total = mul_div_round(int(paid_g), used_price, 1000)  # gram->kg

        note = ov.get("note") or it.get("note")

        repo.insert_invoice_line(
            invoice_id=invoice_id,
            receiving_item_id=int(it["id"]),
            partai_no=partai_no,
            net_g=int(net_g),
            paid_g=int(paid_g),
            round_size=rs,
            price_per_kg_rp=int(base_price),
            line_total_rp=int(line_total),
            note=note,
        )

        subtotal_rp += int(line_total)
        total_paid_g += int(paid_g)

    cash_deduct_total = 0
    if payment_type == "cash" and cash_deduct_per_kg_rp > 0:
        cash_deduct_total = mul_div_round(total_paid_g, cash_deduct_per_kg_rp, 1000)

    pph_amount = 0  # belum dipakai
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