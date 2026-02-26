from flask import render_template, request, redirect, url_for, jsonify
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json

from . import invoice_bp
from .service import create_invoice_from_receiving
from .pricing import interpolate_price
from . import repository as repo


# -----------------------------
# Helpers
# -----------------------------

def parse_kg_to_g(raw: str | None) -> int | None:
    """
    Input UI: kg (boleh pakai koma), output: gram integer.
    Contoh:
      "12,345" -> 12345 g
      "12.345" -> 12345 g
      "" / None -> None
      "1.250,5" -> 1250500 g
    """
    if raw is None:
        return None
    s = raw.strip()
    if s == "":
        return None

    # format indo: "1.250,5" => "1250.5"
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")

    try:
        kg = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"Format Paid kg tidak valid: {raw!r}")

    if kg < 0:
        raise ValueError("Paid kg tidak boleh negatif")

    g = int((kg * Decimal("1000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return g


def to_int(form: dict, name: str, default: int = 0) -> int:
    v = (form.get(name) or "").strip()
    if v == "":
        return default
    # support "10.000"
    v = v.replace(".", "")
    return int(v)


def needed_price_keys(partai_rows):
    """
    Tentukan key harga yang dibutuhkan dari round_size.
    - size 65 -> butuh 60 & 70
    - size 93 -> butuh 90 & 100
    - size 70 -> butuh 70 saja
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


def _price_keys_from_lines(lines):
    keys = set()
    for r in lines:
        rs = r.get("round_size")
        if rs is None:
            continue
        try:
            s = int(rs)
        except:
            continue
        lo = (s // 10) * 10
        hi = lo + 10
        if s % 10 == 0:
            keys.add(lo)
        else:
            keys.add(lo)
            keys.add(hi)
    return sorted(keys)


# -----------------------------
# Routes
# -----------------------------

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

    payment_type = (form.get("payment_type") or "transfer").strip()
    if payment_type not in ("cash", "transfer"):
        payment_type = "transfer"

    tempo_hari = to_int(form, "tempo_hari", 0)

    cash_deduct_per_kg_rp = to_int(form, "cash_deduct_per_kg_rp", 0)
    if payment_type != "cash":
        cash_deduct_per_kg_rp = 0

    # --- price_points: WAJIB isi sesuai keys yang dibutuhkan ---
    price_points = {}
    missing_keys = []
    for k in price_keys:
        v = (form.get(f"p{k}") or "").strip()
        if v == "":
            missing_keys.append(k)
        else:
            # support "55.000"
            vv = v.replace(".", "")
            price_points[int(k)] = int(vv)

    if missing_keys:
        return render_template(
            "invoice/create.html",
            header=header,
            partai=partai,
            price_keys=price_keys,
            form=form,
            error=f"Harga patokan wajib diisi untuk size: {missing_keys}",
        )

    # --- overrides per partai: hanya paid_g + note (tanpa price override) ---
    overrides = {}
    for p in partai:
        no = int(p["partai_no"])

        raw_paid = form.get(f"paid_kg_{no}")
        note = (form.get(f"note_{no}") or "").strip()

        d = {}

        if raw_paid is not None and raw_paid.strip() != "":
            try:
                paid_g = parse_kg_to_g(raw_paid)
            except ValueError as e:
                return render_template(
                    "invoice/create.html",
                    header=header,
                    partai=partai,
                    price_keys=price_keys,
                    form=form,
                    error=str(e),
                )
            if paid_g is not None:
                d["paid_g"] = paid_g

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
            tempo_hari=tempo_hari,
            cash_deduct_per_kg_rp=cash_deduct_per_kg_rp,
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


@invoice_bp.route("/api/<int:invoice_id>", methods=["GET"])
def invoice_api(invoice_id):
    h = repo.get_invoice_header(invoice_id)
    if not h:
        return jsonify({"ok": False, "error": "Invoice not found"}), 404
    lines = repo.fetch_invoice_lines(invoice_id)
    return jsonify({"ok": True, "header": h, "lines": lines})


@invoice_bp.route("/edit/<int:invoice_id>", methods=["GET", "POST"])
def invoice_edit(invoice_id):
    inv = repo.get_invoice_header(invoice_id)
    if not inv:
        return "Invoice tidak ditemukan", 404

    lines = repo.fetch_invoice_lines(invoice_id)

    # parse price_points_json
    try:
        price_points = json.loads(inv.get("price_points_json") or "{}")
        price_points = {int(k): int(v) for k, v in price_points.items()}
    except:
        price_points = {}

    price_keys = _price_keys_from_lines(lines)

    if request.method == "GET":
        return render_template(
            "invoice/edit.html",
            inv=inv,
            lines=lines,
            price_keys=price_keys,
            price_points=price_points,
            msg=None,
        )

    form = request.form.to_dict()

    payment_type = (form.get("payment_type") or "transfer").strip()
    if payment_type not in ("cash", "transfer"):
        payment_type = "transfer"

    tempo_hari = to_int(form, "tempo_hari", 0)

    cash_deduct_per_kg_rp = to_int(form, "cash_deduct_per_kg_rp", 0)
    if payment_type != "cash":
        cash_deduct_per_kg_rp = 0

    # update price points sesuai keys
    new_points = {}
    missing_keys = []
    for k in price_keys:
        v = (form.get(f"p{k}") or "").strip()
        if v == "":
            missing_keys.append(k)
        else:
            vv = v.replace(".", "")
            new_points[int(k)] = int(vv)

    if missing_keys:
        return render_template(
            "invoice/edit.html",
            inv=inv, lines=lines,
            price_keys=price_keys,
            price_points=new_points,
            msg=f"Harga patokan wajib diisi untuk size: {missing_keys}",
        )

    # kumpulkan update per line + validasi interpolate
    updates = []
    missing_sizes = []
    total_paid_g = 0
    subtotal_rp = 0

    for r in lines:
        partai_no = int(r["partai_no"])
        rs = r.get("round_size")

        raw_paid = form.get(f"paid_kg_{partai_no}")
        try:
            paid_g_input = parse_kg_to_g(raw_paid)
        except ValueError as e:
            return render_template(
                "invoice/edit.html",
                inv=inv, lines=lines,
                price_keys=price_keys,
                price_points=new_points,
                msg=str(e),
            )

        paid_g = paid_g_input if paid_g_input is not None else int(r["net_g"] or 0)

        note = (form.get(f"note_{partai_no}") or "").strip() or None

        base_price = interpolate_price(rs, new_points) if rs is not None else None
        if rs is not None and base_price is None:
            missing_sizes.append(rs)
            base_price = 0

        price_used = int(base_price or 0)
        line_total = (paid_g * price_used) // 1000

        updates.append((paid_g, price_used, line_total, note, r["id"]))

        total_paid_g += paid_g
        subtotal_rp += line_total

    if missing_sizes:
        missing_sizes = sorted(set(missing_sizes))
        return render_template(
            "invoice/edit.html",
            inv=inv, lines=lines,
            price_keys=price_keys,
            price_points=new_points,
            msg=f"Tidak bisa hitung harga untuk round_size: {missing_sizes}",
        )

    cash_deduct_total_rp = 0
    if payment_type == "cash" and cash_deduct_per_kg_rp > 0:
        cash_deduct_total_rp = (total_paid_g * cash_deduct_per_kg_rp) // 1000

    pph_amount_rp = inv.get("pph_amount_rp") or 0
    pph_rate_bp = inv.get("pph_rate_bp") or 0

    total_payable_rp = subtotal_rp - cash_deduct_total_rp - pph_amount_rp

    conn = repo.get_conn()
    try:
        conn.executemany(
            "UPDATE invoice_line SET paid_g=?, price_per_kg_rp=?, line_total_rp=?, note=? WHERE id=?",
            updates
        )

        if payment_type == "transfer" and tempo_hari > 0:
            conn.execute("""
                UPDATE invoice_header
                SET price_points_json=?,
                    payment_type=?,
                    tempo_hari=?,
                    due_date=date(tanggal, printf('+%d days', ?)),
                    cash_deduct_per_kg_rp=?,
                    cash_deduct_total_rp=?,
                    pph_rate_bp=?,
                    pph_amount_rp=?,
                    subtotal_rp=?,
                    total_payable_rp=?,
                    total_paid_g=?
                WHERE id=?
            """, (
                json.dumps({str(k): v for k, v in new_points.items()}),
                payment_type,
                tempo_hari,
                tempo_hari,
                cash_deduct_per_kg_rp,
                cash_deduct_total_rp,
                pph_rate_bp,
                pph_amount_rp,
                subtotal_rp,
                total_payable_rp,
                total_paid_g,
                invoice_id,
            ))
        else:
            conn.execute("""
                UPDATE invoice_header
                SET price_points_json=?,
                    payment_type=?,
                    tempo_hari=?,
                    due_date=NULL,
                    cash_deduct_per_kg_rp=?,
                    cash_deduct_total_rp=?,
                    pph_rate_bp=?,
                    pph_amount_rp=?,
                    subtotal_rp=?,
                    total_payable_rp=?,
                    total_paid_g=?
                WHERE id=?
            """, (
                json.dumps({str(k): v for k, v in new_points.items()}),
                payment_type,
                tempo_hari,
                cash_deduct_per_kg_rp,
                cash_deduct_total_rp,
                pph_rate_bp,
                pph_amount_rp,
                subtotal_rp,
                total_payable_rp,
                total_paid_g,
                invoice_id,
            ))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return redirect(url_for("invoice.invoice_view", invoice_id=invoice_id))
@invoice_bp.route("/list", methods=["GET"])
def invoice_list():
    start = (request.args.get("start") or "").strip() or None
    end = (request.args.get("end") or "").strip() or None
    supplier = (request.args.get("supplier") or "").strip() or None
    payment_type = (request.args.get("payment_type") or "").strip() or None

    rows = repo.fetch_invoice_list(
        start=start,
        end=end,
        supplier=supplier,
        payment_type=payment_type,
        limit=request.args.get("limit") or 500
    )

    total_payable = sum(int(r.get("total_payable_rp") or 0) for r in rows)

    return render_template(
        "invoice/list.html",
        rows=rows,
        start=start,
        end=end,
        supplier=supplier,
        payment_type=payment_type,
        total_payable=total_payable,
    )