from flask import render_template, request, redirect, url_for, jsonify
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json

from . import invoice_bp
from .service import create_invoice_from_receiving, rebuild_invoice_lines
from .pricing import interpolate_price
from . import repository as repo
from datetime import time, timedelta, datetime

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
    jenis = (header.get("jenis") or "").strip().lower()
    is_kupasan = (jenis == "kupasan")

    # price_keys hanya untuk non-kupasan
    price_keys = [] if is_kupasan else needed_price_keys(partai)

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

    payment_type = (form.get("payment_type") or "transfer").strip().lower()
    if payment_type not in ("cash", "transfer"):
        payment_type = "transfer"

    tempo_hari = to_int(form, "tempo_hari", 0)

    cash_deduct_per_kg_rp = to_int(form, "cash_deduct_per_kg_rp", 0)
    if payment_type != "cash":
        cash_deduct_per_kg_rp = 0

    # =========================
    # KUPASAN: ambil kebutuhan grade dari partai
    # =========================
    kupasan_prices = None
    price_points = {}

    if is_kupasan:
        needs_kecil = False
        needs_besar = False
        for p in partai:
            g = (p.get("kategori_kupasan") or p.get("grade") or "").strip().lower()
            if g == "kecil":
                needs_kecil = True
            elif g == "besar":
                needs_besar = True

        hk = to_int(form, "kupasan_kecil_rp", 0)
        hb = to_int(form, "kupasan_besar_rp", 0)

        missing = []
        if needs_kecil and hk <= 0:
            missing.append("kecil")
        if needs_besar and hb <= 0:
            missing.append("besar")

        # kalau data partai tidak punya grade sama sekali, fallback: minta dua2
        if not needs_kecil and not needs_besar:
            if hk <= 0:
                missing.append("kecil")
            if hb <= 0:
                missing.append("besar")

        if missing:
            return render_template(
                "invoice/create.html",
                header=header,
                partai=partai,
                price_keys=price_keys,
                form=form,
                error=f"Harga kupasan {', '.join(missing)} wajib diisi.",
            )

        kupasan_prices = {
            "kecil": hk if hk > 0 else None,
            "besar": hb if hb > 0 else None,
        }

    # =========================
    # NON-KUPASAN: price_points wajib isi sesuai keys
    # =========================
    else:
        missing_keys = []
        for k in price_keys:
            v = (form.get(f"p{k}") or "").strip()
            if v == "":
                missing_keys.append(k)
            else:
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

        # validasi: semua round_size harus bisa dihitung
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

    # overrides (paid + note)
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

    try:
        invoice_id = create_invoice_from_receiving(
            receiving_id=receiving_id,
            price_points=price_points,          # non-kupasan: terisi; kupasan: {}
            payment_type=payment_type,
            tempo_hari=tempo_hari,
            cash_deduct_per_kg_rp=cash_deduct_per_kg_rp,
            partai_overrides=overrides,
            kupasan_prices=kupasan_prices,      # kupasan: dict; non-kupasan: None
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

    rh = repo.fetch_receiving_header(h["receiving_id"])
    jenis = (rh.get("jenis") or "").strip().lower() if rh else ""

    lines = repo.fetch_invoice_lines(invoice_id)
    return render_template("invoice/detail.html", header=h, lines=lines, jenis=jenis)

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

    # ambil receiving_id dari invoice header (WAJIB di atas)
    receiving_id = int(inv["receiving_id"])

    header = repo.fetch_receiving_header(receiving_id)
    if not header:
        return "Receiving tidak ditemukan", 404

    partai = repo.fetch_receiving_items(receiving_id)

    jenis = (header.get("jenis") or "").strip().lower()
    is_kupasan = (jenis == "kupasan")

    # parse price_points_json (untuk non-kupasan)
    try:
        price_points = json.loads(inv.get("price_points_json") or "{}")
        price_points = {int(k): int(v) for k, v in price_points.items()}
    except Exception:
        price_points = {}

    # lines lama (untuk kebutuhan tampil edit + parsing paid/note)
    lines = repo.fetch_invoice_lines(invoice_id)  # pastikan repo punya fungsi ini

    # key input harga hanya buat non-kupasan
    price_keys = [] if is_kupasan else needed_price_keys(partai)

    # ===== GET =====
    if request.method == "GET":
        form = {
            "payment_type": (inv.get("payment_type") or "transfer"),
            "tempo_hari": str(inv.get("tempo_hari") or 0),
            "cash_deduct_per_kg_rp": str(inv.get("cash_deduct_per_kg_rp") or 0),
            "invoice_note": inv.get("invoice_note") or "",
        }

        # Prefill paid_kg / note dari invoice_line yang ada (biar edit nyaman)
        # paid_g -> tampil kg (3 desimal)
        for r in lines:
            no = int(r["partai_no"])
            paid_g = int(r.get("paid_g") or 0)
            form[f"paid_kg_{no}"] = f"{paid_g/1000:.3f}"
            if r.get("note"):
                form[f"note_{no}"] = r.get("note")

        # Prefill harga kupasan dari invoice_line
        if is_kupasan:
            kp = repo.get_kupasan_prices_from_invoice(invoice_id)  # sudah kamu fix di repo
            if kp.get("kecil") is not None:
                form["kupasan_kecil_rp"] = str(kp["kecil"])
            if kp.get("besar") is not None:
                form["kupasan_besar_rp"] = str(kp["besar"])

        # Prefill sampling points untuk non-kupasan
        if not is_kupasan:
            for k in price_keys:
                if int(k) in price_points:
                    form[f"p{k}"] = str(price_points[int(k)])

        return render_template(
            "invoice/create.html",
            header=header,
            partai=partai,
            price_keys=price_keys,
            price_points=price_points,
            form=form,
            error=None,
            inv=inv,
            lines=lines,
            mode="edit",
        )

    # ===== POST =====
    form = request.form.to_dict()

    payment_type = (form.get("payment_type") or "transfer").strip().lower()
    if payment_type not in ("cash", "transfer"):
        payment_type = "transfer"

    tempo_hari = to_int(form, "tempo_hari", 0)

    cash_deduct_per_kg_rp = to_int(form, "cash_deduct_per_kg_rp", 0)
    if payment_type != "cash":
        cash_deduct_per_kg_rp = 0

    # overrides per partai: paid_g + note
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
                    mode="edit",
                    inv=inv,
                    lines=lines,
                    header=header,
                    partai=partai,
                    price_keys=price_keys,
                    price_points=price_points,
                    form=form,
                    error=str(e),
                )
            if paid_g is not None:
                d["paid_g"] = paid_g

        if note:
            d["note"] = note

        if d:
            overrides[no] = d

    new_price_points = {}
    kupasan_prices = None

    if is_kupasan:
        # cek kebutuhan input berdasarkan kategori di receiving_item
        needs_kecil = any((p.get("kategori_kupasan") or "").strip().lower() == "kecil" for p in partai)
        needs_besar = any((p.get("kategori_kupasan") or "").strip().lower() == "besar" for p in partai)

        hk = to_int(form, "kupasan_kecil_rp", 0)
        hb = to_int(form, "kupasan_besar_rp", 0)

        missing = []
        if needs_kecil and hk <= 0:
            missing.append("kecil")
        if needs_besar and hb <= 0:
            missing.append("besar")

        # fallback kalau data kategori kosong semua (biar aman)
        if not needs_kecil and not needs_besar:
            if hk <= 0:
                missing.append("kecil")
            if hb <= 0:
                missing.append("besar")

        if missing:
            return render_template(
                "invoice/create.html",
                mode="edit",
                inv=inv,
                lines=lines,
                header=header,
                partai=partai,
                price_keys=price_keys,
                price_points=price_points,
                form=form,
                error=f"Harga kupasan {', '.join(missing)} wajib diisi.",
            )

        kupasan_prices = {
            "kecil": hk if hk > 0 else None,
            "besar": hb if hb > 0 else None,
        }

    else:
        # update sampling points
        missing_keys = []
        for k in price_keys:
            v = (form.get(f"p{k}") or "").strip()
            if v == "":
                missing_keys.append(k)
            else:
                vv = v.replace(".", "")
                new_price_points[int(k)] = int(vv)

        if missing_keys:
            return render_template(
                "invoice/create.html",
                mode="edit",
                inv=inv,
                lines=lines,
                header=header,
                partai=partai,
                price_keys=price_keys,
                price_points=new_price_points,
                form=form,
                error=f"Harga patokan wajib diisi untuk size: {missing_keys}",
            )

        # validasi interpolate round_size
        missing_sizes = []
        for p in partai:
            rs = p.get("round_size")
            if rs is None:
                continue
            if interpolate_price(rs, new_price_points) is None:
                missing_sizes.append(rs)

        if missing_sizes:
            missing_sizes = sorted(set(missing_sizes))
            return render_template(
                "invoice/create.html",
                mode="edit",
                inv=inv,
                lines=lines,
                header=header,
                partai=partai,
                price_keys=price_keys,
                price_points=new_price_points,
                form=form,
                error=f"Tidak bisa hitung harga untuk round_size: {missing_sizes}",
            )

    # hitung due_date
    due_date = None
    try:
        d = datetime.strptime(header["tanggal"], "%Y-%m-%d").date()
        due_date = (d + timedelta(days=int(tempo_hari or 0))).isoformat()
    except Exception:
        due_date = None

    # simpan header invoice + rebuild lines + totals
    price_points_json = json.dumps({str(k): v for k, v in (new_price_points or {}).items()})

    conn = repo.get_conn()
    try:
        conn.execute("""
            UPDATE invoice_header
            SET payment_type=?,
                tempo_hari=?,
                due_date=?,
                cash_deduct_per_kg_rp=?,
                price_points_json=?,
                note=?
            WHERE id=?
        """, (
            payment_type,
            int(tempo_hari or 0),
            due_date,
            int(cash_deduct_per_kg_rp or 0),
            price_points_json,
            (form.get("invoice_note") or "").strip() or None,
            invoice_id
        ))

        # hapus lines lama
        conn.execute("DELETE FROM invoice_line WHERE invoice_id=?", (invoice_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # rebuild lines + totals
    rebuild_invoice_lines(
        invoice_id=invoice_id,
        receiving_id=receiving_id,
        price_points=new_price_points,
        payment_type=payment_type,
        tempo_hari=tempo_hari,
        cash_deduct_per_kg_rp=cash_deduct_per_kg_rp,
        partai_overrides=overrides,
        kupasan_prices=kupasan_prices,
    )

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
    rows = [dict(r) for r in rows]
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