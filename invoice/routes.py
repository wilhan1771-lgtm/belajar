from flask import render_template, request, redirect, url_for, jsonify
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from .repository import get_jenis_mode
from . import invoice_bp
from .service import create_invoice_from_receiving, rebuild_invoice_lines, kg_to_g
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

    partai = repo.fetch_receiving_items(receiving_id) or []

    jenis = (header.get("jenis") or "").strip().lower()
    mode = get_jenis_mode(jenis)  # "udang_size" | "manual_grade"
    is_manual = (mode == "manual_grade")

    # hanya untuk udang_size
    price_keys = [] if is_manual else needed_price_keys(partai)

    existing = repo.get_invoice_by_receiving(receiving_id)
    if request.method == "GET" and existing:
        return redirect(url_for("invoice.invoice_view", invoice_id=existing["id"]))

    if request.method == "GET":
        return render_template(
            "invoice/create.html",
            header=header,
            partai=partai,
            price_keys=price_keys,
            mode=mode,             # mode jenis
            page_mode="new",       # UI new/edit
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

    price_points = {}
    grade_prices = None

    # =========================
    # MANUAL (grade_manual + grade_prices)
    # =========================
    if is_manual:
        grades = sorted({
            (p.get("grade_manual") or "").strip()
            for p in partai
            if (p.get("grade_manual") or "").strip()
        })

        if not grades:
            return render_template(
                "invoice/create.html",
                header=header,
                partai=partai,
                price_keys=price_keys,
                mode=mode,
                page_mode="new",
                form=form,
                error="Tidak ada grade_manual pada receiving_item. Isi grade dulu di receiving.",
            )

        grade_prices = {}
        missing = []

        for g in grades:
            safe = g.strip().lower().replace(" ", "_").replace("/", "_")
            key = f"grade_price_{safe}"
            raw = (form.get(key) or "").strip()
            vv = int(raw.replace(".", "")) if raw else 0

            if vv <= 0:
                missing.append(g)
            else:
                grade_prices[g] = vv

        if missing:
            return render_template(
                "invoice/create.html",
                header=header,
                partai=partai,
                price_keys=price_keys,
                mode=mode,
                page_mode="new",
                form=form,
                error=f"Harga untuk grade {', '.join(missing)} wajib diisi.",
            )

    # =========================
    # UDANG SIZE
    # =========================
    else:
        missing_keys = []
        for k in price_keys:
            v = (form.get(f"p{k}") or "").strip()
            if v == "":
                missing_keys.append(k)
            else:
                price_points[int(k)] = int(v.replace(".", ""))

        if missing_keys:
            return render_template(
                "invoice/create.html",
                header=header,
                partai=partai,
                price_keys=price_keys,
                mode=mode,
                page_mode="new",
                form=form,
                error=f"Harga patokan wajib diisi untuk size: {missing_keys}",
            )

    try:
        invoice_id = create_invoice_from_receiving(
            receiving_id=receiving_id,
            price_points=price_points,
            payment_type=payment_type,
            tempo_hari=tempo_hari,
            cash_deduct_per_kg_rp=cash_deduct_per_kg_rp,
            partai_overrides={},          # masih kosong
            grade_prices=grade_prices,    # ✅ dipakai kalau manual
        )
        return redirect(url_for("invoice.invoice_view", invoice_id=invoice_id))

    except Exception as e:
        return render_template(
            "invoice/create.html",
            header=header,
            partai=partai,
            price_keys=price_keys,
            mode=mode,
            page_mode="new",
            form=form,
            error=str(e),
        )
@invoice_bp.route("/edit/<int:invoice_id>", methods=["GET", "POST"])invoice_edit(invoice_id):
    inv = repo.get_invoice_header(invoice_id)
    if not inv:
        return "Invoice tidak ditemukan", 404

    receiving_id = int(inv["receiving_id"])
    header = repo.fetch_receiving_header(receiving_id)
    if not header:
        return "Receiving tidak ditemukan", 404

    partai = repo.fetch_receiving_items(receiving_id) or []
    lines = repo.fetch_invoice_lines(invoice_id) or []

    # mode jenis: udang_size | manual_grade
    jenis = (header.get("jenis") or "").strip().lower()
    mode_receiving = repo.get_jenis_mode(jenis)
    is_manual = (mode_receiving == "manual_grade")

    # price_points hanya untuk udang_size
    try:
        pts = json.loads(inv.get("price_points_json") or "{}")
        price_points = {int(k): int(v) for k, v in pts.items()}
    except Exception:
        price_points = {}

    # hanya untuk udang_size
    price_keys = [] if is_manual else needed_price_keys(partai)

    def _render_err(msg, price_points_override=None):
        return render_template(
            "invoice/create.html",
            header=header,
            partai=partai,
            price_keys=price_keys,
            price_points=price_points_override if price_points_override is not None else price_points,
            form=form,
            error=msg,
            inv=inv,
            lines=lines,
            page_mode="edit",
            mode=mode_receiving,
        )

    # ================= GET =================
    if request.method == "GET":
        form = {
            "payment_type": (inv.get("payment_type") or "transfer"),
            "tempo_hari": str(inv.get("tempo_hari") or 0),
            "cash_deduct_per_kg_rp": str(inv.get("cash_deduct_per_kg_rp") or 0),
            "invoice_note": inv.get("note") or "",
        }

        # paid_kg default ikut receiving terbaru + grade per partai (manual)
        for p in partai:
            no = int(p["partai_no"])
            net_g = kg_to_g(p.get("netto"))
            form[f"paid_kg_{no}"] = f"{net_g/1000:.3f}"
            form[f"grade_{no}"] = (p.get("grade_manual") or "")

        # note prefill dari invoice_line
        for r in lines:
            no = int(r["partai_no"])
            if r.get("note"):
                form[f"note_{no}"] = r.get("note")

        # udang_size prefill sampling points
        if not is_manual:
            for k in price_keys:
                v = price_points.get(int(k))
                if v is not None:
                    form[f"p{k}"] = str(v)

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
            page_mode="edit",
            mode=mode_receiving,
        )

    # ================= POST =================
    form = request.form.to_dict()

    payment_type = (form.get("payment_type") or "transfer").strip().lower()
    if payment_type not in ("cash", "transfer"):
        payment_type = "transfer"

    tempo_hari = to_int(form, "tempo_hari", 0)

    cash_deduct_per_kg_rp = to_int(form, "cash_deduct_per_kg_rp", 0)
    if payment_type != "cash":
        cash_deduct_per_kg_rp = 0

    # default paid ikut receiving terbaru
    default_paid_g = {int(p["partai_no"]): kg_to_g(p.get("netto")) for p in partai}

    overrides = {}
    grade_updates = []  # (grade_manual, receiving_item_id)

    for p in partai:
        no = int(p["partai_no"])
        rid = int(p["id"])

        raw_paid = form.get(f"paid_kg_{no}")
        note = (form.get(f"note_{no}") or "").strip()

        # manual grade: simpan grade per partai ke receiving_item.grade_manual
        if is_manual:
            gm_new = (form.get(f"grade_{no}") or "").strip() or None
            gm_old = (p.get("grade_manual") or "").strip() or None
            if gm_new != gm_old:
                grade_updates.append((gm_new, rid))

        d = {}

        # override paid hanya jika beda dari receiving netto terbaru
        if raw_paid is not None and raw_paid.strip() != "":
            try:
                paid_g = parse_kg_to_g(raw_paid)
            except ValueError as e:
                return _render_err(str(e))
            if paid_g is not None and int(paid_g) != int(default_paid_g.get(no, 0)):
                d["paid_g"] = int(paid_g)

        if note:
            d["note"] = note

        if d:
            overrides[no] = d

    new_price_points = {}
    grade_prices = None

    # ===== MANUAL GRADE (cumi + kupasan) =====
    if is_manual:
        # ambil grade dari FORM jika ada, fallback DB
        grades_form = []
        for p in partai:
            no = int(p["partai_no"])
            g = (form.get(f"grade_{no}") or "").strip()
            if g and g not in grades_form:
                grades_form.append(g)

        grades_db = []
        for p in partai:
            g = (p.get("grade_manual") or "").strip()
            if g and g not in grades_db:
                grades_db.append(g)

        grades = sorted(grades_form or grades_db)

        if not grades:
            return _render_err(
                "Tidak ada grade pada partai. Isi grade per partai (mis: kecil/besar atau S/M/L/XL) lalu isi harga grade."
            )

        grade_prices = {}
        missing = []
        for g in grades:
            safe = g.strip().lower().replace(" ", "_").replace("/", "_")
            key = f"grade_price_{safe}"
            raw = (form.get(key) or "").strip()
            vv = int(raw.replace(".", "")) if raw else 0

            if vv <= 0:
                missing.append(g)
            else:
                grade_prices[g] = vv

        if missing:
            return _render_err(f"Harga untuk grade {', '.join(missing)} wajib diisi.")

    # ===== UDANG SIZE =====
    else:
        missing_keys = []
        for k in price_keys:
            v = (form.get(f"p{k}") or "").strip()
            if v == "":
                missing_keys.append(k)
            else:
                new_price_points[int(k)] = int(v.replace(".", ""))

        if missing_keys:
            return _render_err(
                f"Harga patokan wajib diisi untuk size: {missing_keys}",
                price_points_override=new_price_points
            )

    # due_date
    due_date = None
    try:
        d = datetime.strptime(header["tanggal"], "%Y-%m-%d").date()
        due_date = (d + timedelta(days=int(tempo_hari or 0))).isoformat()
    except Exception:
        due_date = None

    price_points_json = json.dumps({str(k): v for k, v in (new_price_points or {}).items()})
    grade_prices_json = json.dumps(grade_prices or {})

    conn = repo.get_conn()
    try:
        # simpan grade_manual ke receiving_item (manual mode)
        if is_manual:
            for gm, rid in grade_updates:
                conn.execute("UPDATE receiving_item SET grade_manual=? WHERE id=?", (gm, rid))

        # update invoice_header
        conn.execute("""
            UPDATE invoice_header
            SET payment_type=?,
                tempo_hari=?,
                due_date=?,
                cash_deduct_per_kg_rp=?,
                price_points_json=?,
                grade_prices_json=?,
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

        # rebuild lines: hapus dulu (agar receiving_item_id UNIQUE aman)
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
        grade_prices=grade_prices,   # ✅ dipakai kalau manual
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