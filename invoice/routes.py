from flask import render_template, request, redirect, url_for, jsonify
from . import invoice_bp
from .service import create_invoice_from_receiving
from .pricing import interpolate_price
from . import repository as repo

def needed_price_keys(partai_rows):
    """
    Tentukan key harga yang dibutuhkan dari round_size.
    - size 65 -> butuh 60 & 70
    - size 93 -> butuh 90 & 100
    - size 70 -> butuh 70 saja (karena tepat di titik)
    """
    keys = set()
    for p in partai_rows:
        rs = p.get("round_size")
        if rs is None:
            continue
        try:
            s = int(rs)
        except (TypeError, ValueError):
            continue

        lo = (s // 10) * 10
        hi = lo + 10

        if s % 10 == 0:
            keys.add(lo)
        else:
            keys.add(lo)
            keys.add(hi)

    return sorted(keys)


@invoice_bp.route("/new/<int:receiving_id>", methods=["GET", "POST"])
def invoice_new(receiving_id):
    header = repo.fetch_receiving_header(receiving_id)
    if not header:
        return "Receiving tidak ditemukan", 404

    partai = repo.fetch_receiving_items(receiving_id)
    price_keys = needed_price_keys(partai)

    # kalau sudah ada invoice → arahkan ke view
    existing = repo.get_invoice_by_receiving(receiving_id)
    if request.method == "GET" and existing:
        return redirect(url_for("invoice.invoice_view", invoice_id=existing["id"]))

    if request.method == "GET":
        return render_template(
            "invoice/create.html",
            header=header,
            partai=partai,
            price_keys=price_keys,
            form=None,
            error=None,
        )

    form = request.form.to_dict()

    def to_int(name, default=0):
        v = (form.get(name) or "").strip()
        if v == "":
            return default
        return int(v)

    def to_float(name):
        v = (form.get(name) or "").strip()
        if v == "":
            return None
        return float(v)

    payment_type = (form.get("payment_type") or "transfer").strip()
    cash_deduct_per_kg_rp = to_int("cash_deduct_per_kg_rp", 0)
    komisi_per_kg_rp = to_int("komisi_per_kg_rp", 0)
    tempo_hari = to_int("tempo_hari", 0)

    # --- price_points: WAJIB isi sesuai keys yang dibutuhkan ---
    price_points = {}
    missing_keys = []
    for k in price_keys:
        v = (form.get(f"p{k}") or "").strip()
        if v == "":
            missing_keys.append(k)
        else:
            price_points[int(k)] = int(v)

    if missing_keys:
        return render_template(
            "invoice/create.html",
            header=header,
            partai=partai,
            price_keys=price_keys,
            form=form,
            error=f"Harga patokan wajib diisi untuk size: {missing_keys}",
        )

    # --- overrides per partai ---
    overrides = {}
    for p in partai:
        no = int(p["partai_no"])
        paid_kg = to_float(f"paid_kg_{no}")
        price_override = (form.get(f"price_override_{no}") or "").strip()
        note = (form.get(f"note_{no}") or "").strip()

        d = {}
        if paid_kg is not None:
            d["paid_kg"] = paid_kg
        if price_override != "":
            d["price_override"] = int(price_override)
        if note != "":
            d["note"] = note
        if d:
            overrides[no] = d

    # --- validasi: semua round_size harus bisa dihitung ---
    missing_sizes = []
    for p in partai:
        rs = p.get("round_size")
        if rs is None:
            continue
        if interpolate_price(rs, price_points) is None:
            missing_sizes.append(rs)

    if missing_sizes:
        missing_sizes = sorted(set(missing_sizes))
        return render_template(
            "invoice/create.html",
            header=header,
            partai=partai,
            price_keys=price_keys,
            form=form,
            error=(
                f"Harga patokan kurang. Tidak bisa hitung untuk round_size: {missing_sizes}. "
                f"Isi titik harga yang mengapitnya (contoh 65 butuh 60 & 70)."
            ),
        )

    try:
        invoice_id = create_invoice_from_receiving(
            receiving_id=receiving_id,
            price_points=price_points,
            payment_type=payment_type,
            cash_deduct_per_kg_rp=cash_deduct_per_kg_rp,
            komisi_per_kg_rp=komisi_per_kg_rp,
            tempo_hari=tempo_hari,
            partai_overrides=overrides,
        )
    except Exception as e:
        return render_template(
            "invoice/create.html",
            header=header,
            partai=partai,
            price_keys=price_keys,
            form=form,
            error=str(e),
        )

    return redirect(url_for("invoice.invoice_view", invoice_id=invoice_id))


@invoice_bp.route("/view/<int:invoice_id>", methods=["GET"])
def invoice_view(invoice_id):
    h = repo.get_invoice_header(invoice_id)
    if not h:
        return "Invoice tidak ditemukan", 404
    lines = repo.fetch_invoice_lines(invoice_id)
    return render_template("invoice/detail.html", header=h, lines=lines)

# optional JSON
@invoice_bp.route("/api/<int:invoice_id>", methods=["GET"])
def invoice_api(invoice_id):
    h = repo.get_invoice_header(invoice_id)
    if not h:
        return jsonify({"ok": False, "error": "Invoice not found"}), 404
    lines = repo.fetch_invoice_lines(invoice_id)
    return jsonify({"ok": True, "header": h, "lines": lines})