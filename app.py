from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import date
import json, sqlite3

from db import init_db, get_conn

# init database
init_db()

app = Flask(__name__)
app.secret_key = "belajar-secret"

DEMO_USER = {"username": "admin", "password": "1234"}


# =========================
# Helpers
# =========================
def interpolate_price(size: int | None, points: dict) -> int | None:
    """
    points contoh: {40:65000, 50:60000, 60:55000, 70:52000}
    size contoh: 54 -> hitung dari 50 & 60
    """
    if size is None:
        return None

    try:
        size = int(size)
    except:
        return None

    # only keep valid numeric points
    pts = {}
    for k, v in points.items():
        if v is None:
            continue
        if str(v).strip() == "":
            continue
        try:
            pts[int(k)] = int(v)
        except:
            pass

    if size in pts:
        return pts[size]

    lo = (size // 10) * 10
    hi = lo + 10

    if lo in pts and hi in pts:
        p_lo = pts[lo]
        p_hi = pts[hi]
        step = (p_lo - p_hi) / 10.0
        price = p_lo - step * (size - lo)
        return int(round(price))

    return None

def require_login():
    return "user" in session


# =========================
# Auth
# =========================
@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        if username == DEMO_USER["username"] and password == DEMO_USER["password"]:
            session["user"] = username
            return redirect(url_for("dashboard"))
        else:
            error = "Username / password salah"

    return render_template("login.html", error=error)

@app.route("/production/<int:prod_id>")
def production_view(prod_id):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()

    # ambil production by prod_id (INI KUNCI)
    prod = conn.execute(
        "SELECT * FROM production_header WHERE id=?",
        (prod_id,)
    ).fetchone()

    if not prod:
        conn.close()
        return "Production tidak ditemukan", 404

    # ambil receiving dari prod.receiving_id
    rec = conn.execute("""
        SELECT h.id, h.tanggal, h.supplier, h.jenis,
               COALESCE(SUM(COALESCE(p.netto,0)),0) AS total_netto
        FROM receiving_header h
        LEFT JOIN receiving_partai p ON p.header_id = h.id
        WHERE h.id = ?
        GROUP BY h.id
    """, (prod["receiving_id"],)).fetchone()

    # ambil steps + packing by prod_id
    steps = conn.execute("""
        SELECT step_name, berat_kg, yield_pct
        FROM production_step
        WHERE production_id=?
        ORDER BY id
    """, (prod_id,)).fetchall()

    packing = conn.execute("""
        SELECT * FROM production_packing
        WHERE production_id=?
        ORDER BY id
    """, (prod_id,)).fetchall()

    conn.close()

    return render_template(
        "production.html",
        receiving=dict(rec) if rec else None,
        production=dict(prod),
        steps=[dict(r) for r in steps],
        packing=[dict(r) for r in packing],
    )

@app.post("/production/save/<int:prod_id>")
def production_save(prod_id):
    if not require_login():
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401

    data = request.get_json(force=True) or {}

    try:
        hl = float(data.get("hl") or 0)
    except ValueError:
        return jsonify({"ok": False, "msg": "Input HL harus angka"}), 400

    packing_rows = data.get("packing") or []

    conn = get_conn()
    cur = conn.cursor()

    prod = conn.execute(
        "SELECT id, bahan_masuk_kg FROM production_header WHERE id=?",
        (prod_id,)
    ).fetchone()

    if not prod:
        conn.close()
        return jsonify({"ok": False, "msg": "Production tidak ditemukan"}), 404

    bahan_masuk = float(prod["bahan_masuk_kg"] or 0)

    def pct(x):
        return 0.0 if bahan_masuk <= 0 else (float(x) / bahan_masuk) * 100.0

    # hitung total
    try:
        total_pack = 0.0
        total_kupas = 0.0
        for r in packing_rows:
            k = float(r.get("kupas_kg") or 0)
            mc = float(r.get("mc") or 0)
            bpd = float(r.get("berat_per_dus") or 0)
            total_kupas += k
            total_pack += (mc * bpd) if (mc > 0 and bpd > 0) else 0.0
    except Exception:
        conn.close()
        return jsonify({"ok": False, "msg": "Data packing tidak valid"}), 400

    kupas = total_kupas
    soaking = total_pack

    if soaking > bahan_masuk + 1e-6:
        conn.close()
        return jsonify({"ok": False, "msg": "Total packing lebih besar dari Bahan Masuk"}), 400

    try:
        # update steps
        cur.execute("""
            UPDATE production_step SET berat_kg=?, yield_pct=?
            WHERE production_id=? AND step_name='HL'
        """, (hl, pct(hl), prod_id))

        cur.execute("""
            UPDATE production_step SET berat_kg=?, yield_pct=?
            WHERE production_id=? AND step_name='KUPAS'
        """, (kupas, pct(kupas), prod_id))

        cur.execute("""
            UPDATE production_step SET berat_kg=?, yield_pct=?
            WHERE production_id=? AND step_name='SOAKING'
        """, (soaking, pct(soaking), prod_id))

        # replace packing (ini tetap ok untuk sekarang)
        cur.execute("DELETE FROM production_packing WHERE production_id=?", (prod_id,))

        for r in packing_rows:
            size = (r.get("size") or "").strip() or None
            kupas_kg = float(r.get("kupas_kg") or 0)
            mc = float(r.get("mc") or 0)
            berat_per_dus = float(r.get("berat_per_dus") or 0)
            total_kg = (mc * berat_per_dus) if (mc > 0 and berat_per_dus > 0) else 0.0
            yield_ratio = (total_kg / kupas_kg) if kupas_kg > 0 else None

            if (not size) and kupas_kg == 0 and mc == 0 and berat_per_dus == 0:
                continue

            cur.execute("""
                INSERT INTO production_packing
                    (production_id, size, kupas_kg, mc, berat_per_dus, total_kg, yield_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (prod_id, size, kupas_kg, mc, berat_per_dus, total_kg, yield_ratio))

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"ok": False, "msg": f"Gagal simpan: {e}"}), 500

    conn.close()
    return jsonify({"ok": True})
@app.get("/production/open/<int:receiving_id>")
def production_open(receiving_id):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()

    # cek sudah ada production?
    prod = conn.execute(
        "SELECT * FROM production_header WHERE receiving_id=? ORDER BY id DESC LIMIT 1",
        (receiving_id,)
    ).fetchone()

    # kalau belum ada, buat
    if not prod:
        rec = conn.execute("""
            SELECT h.id, h.tanggal, h.supplier, h.jenis,
                   COALESCE(SUM(COALESCE(p.netto,0)),0) AS total_netto
            FROM receiving_header h
            LEFT JOIN receiving_partai p ON p.header_id = h.id
            WHERE h.id = ?
            GROUP BY h.id
        """, (receiving_id,)).fetchone()

        if not rec:
            conn.close()
            return "Receiving tidak ditemukan", 404

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO production_header (receiving_id, tanggal, supplier, jenis, bahan_masuk_kg)
            VALUES (?, ?, ?, ?, ?)
        """, (rec["id"], rec["tanggal"], rec["supplier"], rec["jenis"], float(rec["total_netto"] or 0)))
        prod_id = cur.lastrowid

        for step in ["HL", "KUPAS", "SOAKING"]:
            cur.execute("""
                INSERT INTO production_step (production_id, step_name, berat_kg, yield_pct)
                VALUES (?, ?, 0, 0)
            """, (prod_id, step))

        conn.commit()
        prod = conn.execute("SELECT * FROM production_header WHERE id=?", (prod_id,)).fetchone()

    conn.close()
    return redirect(url_for("production_view", prod_id=prod["id"]))


@app.route("/dashboard")
def dashboard():
    if not require_login():
        return redirect(url_for("login"))
    return render_template("dashboard.html", user=session["user"])


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================
# Debug
# =========================
@app.route("/receiving/debug")
def receiving_debug():
    conn = get_conn()
    headers = conn.execute("SELECT * FROM receiving_header ORDER BY id DESC").fetchall()
    partai = conn.execute("SELECT * FROM receiving_partai ORDER BY id DESC").fetchall()
    conn.close()
    return {
        "headers": [dict(r) for r in headers],
        "partai": [dict(r) for r in partai],
    }


# =========================
# Receiving UI
# =========================
@app.route("/receiving")
def receiving():
    if not require_login():
        return redirect(url_for("login"))
    # kamu pakai today untuk default tanggal di form
    today_str = date.today().strftime("%Y-%m-%d")
    return render_template("receiving.html", today=today_str)


@app.route("/receiving/save", methods=["POST"])
def receiving_save():
    data = request.get_json(force=True)

    tanggal = (data.get("tanggal") or "").strip()
    supplier = (data.get("supplier") or "").strip()
    jenis = (data.get("jenis") or "").strip()
    fiber = data.get("fiber")

    partai_list = data.get("partai", [])

    if not tanggal or not supplier:
        return jsonify({"ok": False, "msg": "Tanggal & Supplier wajib diisi"}), 400
    if not partai_list:
        return jsonify({"ok": False, "msg": "Minimal harus ada 1 partai"}), 400

    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO receiving_header (tanggal, supplier, jenis, fiber) VALUES (?, ?, ?, ?)",
            (tanggal, supplier, jenis or None, fiber)
        )
        header_id = cur.lastrowid

        for p in partai_list:
            timbangan = p.get("timbangan", [])
            cur.execute("""
                INSERT INTO receiving_partai
                (header_id, partai_no, pcs, kg_sample, size, round_size, keranjang,
                 tara_per_keranjang, bruto, total_tara, netto, note, timbangan_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                header_id,
                p.get("partai_no"),
                p.get("pcs"),
                p.get("kg_sample"),
                p.get("size"),
                p.get("round_size"),
                p.get("keranjang"),
                p.get("tara_per_keranjang"),
                p.get("bruto"),
                p.get("total_tara"),
                p.get("netto"),
                p.get("note"),
                json.dumps(timbangan)
            ))

        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "msg": f"Gagal simpan: {str(e)}"}), 500
    finally:
        conn.close()

    return jsonify({"ok": True, "header_id": header_id})

@app.post("/receiving/delete/<int:rid>")
def receiving_delete(rid):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()
    cur = conn.cursor()
    try:
        # --- hapus PRODUCTION turunan ---
        prod = cur.execute("SELECT id FROM production_header WHERE receiving_id=?", (rid,)).fetchone()
        if prod:
            prod_id = prod["id"]
            cur.execute("DELETE FROM production_packing WHERE production_id=?", (prod_id,))
            cur.execute("DELETE FROM production_step WHERE production_id=?", (prod_id,))
            cur.execute("DELETE FROM production_header WHERE id=?", (prod_id,))

        # --- hapus INVOICE turunan ---
        inv = cur.execute("SELECT id FROM invoice_header WHERE receiving_id=?", (rid,)).fetchone()
        if inv:
            inv_id = inv["id"]
            cur.execute("DELETE FROM invoice_detail WHERE invoice_id=?", (inv_id,))
            cur.execute("DELETE FROM invoice_header WHERE id=?", (inv_id,))

        # --- hapus RECEIVING detail lalu header ---
        cur.execute("DELETE FROM receiving_partai WHERE header_id=?", (rid,))
        cur.execute("DELETE FROM receiving_header WHERE id=?", (rid,))

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return f"Gagal hapus receiving: {e}", 500

    conn.close()
    return redirect(url_for("receiving_list"))

@app.get("/master/suppliers")
def master_suppliers():
    conn = get_conn()
    rows = conn.execute("SELECT id, nama FROM supplier WHERE aktif=1 ORDER BY nama").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.get("/master/jenis")
def master_jenis():
    conn = get_conn()
    rows = conn.execute("SELECT id, nama FROM udang_jenis WHERE aktif=1 ORDER BY id").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.post("/master/supplier/add")
def master_supplier_add():
    if not require_login():
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401

    data = request.get_json(force=True)
    nama = (data.get("nama") or "").strip()
    if not nama:
        return jsonify({"ok": False, "msg": "Nama supplier wajib"}), 400

    conn = get_conn()
    try:
        conn.execute("INSERT INTO supplier (nama) VALUES (?)", (nama,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"ok": False, "msg": f"Gagal tambah supplier: {e}"}), 400

    conn.close()
    return jsonify({"ok": True})


@app.route("/receiving/list")
def receiving_list():
    if not require_login():
        return redirect(url_for("login"))

    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    supplier_q = (request.args.get("supplier") or "").strip()

    where = []
    params = []

    if start and end:
        where.append("h.tanggal BETWEEN ? AND ?")
        params.extend([start, end])
    elif start:
        where.append("h.tanggal >= ?")
        params.append(start)
    elif end:
        where.append("h.tanggal <= ?")
        params.append(end)

    if supplier_q:
        where.append("LOWER(h.supplier) LIKE ?")
        params.append(f"%{supplier_q.lower()}%")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    conn = get_conn()

    rows = conn.execute(f"""
        SELECT
            h.id,
            h.tanggal,
            h.supplier,
            h.jenis,
            h.fiber,
            COALESCE(SUM(COALESCE(p.netto, 0)), 0) AS total_netto,
            COUNT(p.id) AS jml_partai
        FROM receiving_header h
        LEFT JOIN receiving_partai p ON p.header_id = h.id
        {where_sql}
        GROUP BY h.id
        ORDER BY h.id DESC
    """, params).fetchall()

    # total berat dari hasil filter (jumlah total_netto semua receiving yang tampil)
    total_berat = sum([(r["total_netto"] or 0) for r in rows])

    conn.close()

    return render_template(
        "receiving_list.html",
        rows=[dict(r) for r in rows],
        start=start,
        end=end,
        supplier=supplier_q,
        total_berat=total_berat
    )

@app.route("/receiving/<int:header_id>")
def receiving_detail(header_id):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()
    header = conn.execute(
        "SELECT * FROM receiving_header WHERE id = ?",
        (header_id,)
    ).fetchone()

    if not header:
        conn.close()
        return "Data receiving tidak ditemukan", 404

    partai_rows = conn.execute("""
        SELECT * FROM receiving_partai
        WHERE header_id = ?
        ORDER BY partai_no ASC, id ASC
    """, (header_id,)).fetchall()
    conn.close()

    partai = []
    for r in partai_rows:
        d = dict(r)
        try:
            d["timbangan"] = json.loads(d.get("timbangan_json") or "[]")
        except:
            d["timbangan"] = []
        partai.append(d)

    total_netto = sum([(p.get("netto") or 0) for p in partai])

    return render_template(
        "receiving_detail.html",
        header=dict(header),
        partai=partai,
        total_netto=total_netto
    )
@app.route("/receiving/edit/<int:header_id>", methods=["GET", "POST"])
def receiving_edit(header_id):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()

    # ✅ LOCK: kalau sudah ada invoice, jangan boleh edit
    inv = conn.execute(
        "SELECT id FROM invoice_header WHERE receiving_id = ? LIMIT 1",
        (header_id,)
    ).fetchone()
    if inv:
        conn.close()
        return "Receiving sudah dibuat invoice, tidak bisa diedit.", 400

    header = conn.execute(
        "SELECT * FROM receiving_header WHERE id = ?",
        (header_id,)
    ).fetchone()

    if not header:
        conn.close()
        return "Data receiving tidak ditemukan", 404

    partai_rows_raw = conn.execute("""
        SELECT * FROM receiving_partai
        WHERE header_id = ?
        ORDER BY partai_no ASC, id ASC
    """, (header_id,)).fetchall()

    # ✅ Decode timbangan_json supaya bisa muncul di template edit
    partai_rows = []
    for r in partai_rows_raw:
        d = dict(r)
        try:
            d["timbangan"] = json.loads(d.get("timbangan_json") or "[]")
            if not isinstance(d["timbangan"], list):
                d["timbangan"] = []
        except:
            d["timbangan"] = []
        partai_rows.append(d)

    if request.method == "POST":
        # --- header fields ---
        tanggal = (request.form.get("tanggal") or "").strip()
        supplier = (request.form.get("supplier") or "").strip()
        jenis = (request.form.get("jenis") or "").strip()
        fiber_raw = (request.form.get("fiber") or "").strip()

        if not tanggal or not supplier:
            conn.close()
            return "Tanggal & supplier wajib diisi", 400

        try:
            fiber = float(fiber_raw) if fiber_raw != "" else None
        except ValueError:
            conn.close()
            return "Fiber harus angka", 400

        conn.execute("""
            UPDATE receiving_header
            SET tanggal = ?, supplier = ?, jenis = ?, fiber = ?
            WHERE id = ?
        """, (tanggal, supplier, jenis or None, fiber, header_id))

        # --- update partai rows (+ timbangan_json) ---
        for r in partai_rows:
            pid = r["id"]

            pcs_raw = (request.form.get(f"pcs_{pid}") or "").strip()
            round_size_raw = (request.form.get(f"round_size_{pid}") or "").strip()
            netto_raw = (request.form.get(f"netto_{pid}") or "").strip()
            note = (request.form.get(f"note_{pid}") or "").strip()

            def to_int(v):
                if v == "":
                    return None
                return int(v)

            def to_float(v):
                if v == "":
                    return None
                return float(v)

            try:
                pcs = to_int(pcs_raw)
                round_size = to_int(round_size_raw)
                netto = to_float(netto_raw)
            except ValueError:
                conn.rollback()
                conn.close()
                return f"Input partai id={pid} tidak valid (angka).", 400

            # ✅ ambil semua input timbangan_{pid}_{idx}
            timbangan_list = []
            idx = 0
            while True:
                key = f"timbangan_{pid}_{idx}"
                if key not in request.form:
                    break

                val = (request.form.get(key) or "").strip().replace(",", ".")
                if val != "":
                    try:
                        timbangan_list.append(float(val))
                    except ValueError:
                        conn.rollback()
                        conn.close()
                        return f"Timbangan partai id={pid} baris #{idx+1} harus angka.", 400
                idx += 1

            timbangan_json = json.dumps(timbangan_list)

            conn.execute("""
                UPDATE receiving_partai
                SET pcs = ?, round_size = ?, netto = ?, note = ?, timbangan_json = ?
                WHERE id = ? AND header_id = ?
            """, (pcs, round_size, netto, note or None, timbangan_json, pid, header_id))

        conn.commit()
        conn.close()
        return redirect(url_for("receiving_detail", header_id=header_id))

    # GET: render form edit
    conn.close()
    return render_template(
        "receiving_edit.html",
        header=dict(header),
        partai=partai_rows
    )


# =========================
# Invoice
# =========================
@app.route("/invoice/new/<int:receiving_id>", methods=["GET", "POST"])
def invoice_new(receiving_id):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()
    header = conn.execute("SELECT * FROM receiving_header WHERE id=?", (receiving_id,)).fetchone()
    if not header:
        conn.close()
        return "Receiving tidak ditemukan", 404

    partai_rows = conn.execute("""
        SELECT partai_no, round_size, netto
        FROM receiving_partai
        WHERE header_id=?
        ORDER BY partai_no ASC
    """, (receiving_id,)).fetchall()

    if request.method == "GET":
        required_sizes = set()
        for r in partai_rows:
            if r["round_size"] is None:
                continue
            s = int(r["round_size"])
            lo = (s // 10) * 10
            hi = lo + 10
            required_sizes.add(lo)
            required_sizes.add(hi)

        required_sizes = sorted(required_sizes)
        conn.close()

        return render_template(
            "invoice_new.html",
            header=dict(header),
            partai=[dict(r) for r in partai_rows],
            required_sizes=required_sizes
        )

    # POST: generate invoice
    points = {}
    for k, v in request.form.items():
        if k.startswith("p"):
            try:
                sz = int(k[1:])
                points[sz] = int(v) if str(v).strip() != "" else None
            except:
                pass

    # PPH (%) opsional: 0.25 -> 0.0025
    pph_raw = (request.form.get("pph") or "").replace(",", ".").strip()
    pph_rate = float(pph_raw) / 100 if pph_raw else None

    details = []
    subtotal = 0.0

    for r in partai_rows:
        pno = r["partai_no"]
        size_round = r["round_size"]
        netto = r["netto"] or 0

        harga = interpolate_price(size_round, points)
        total_harga = (float(netto) * float(harga)) if harga is not None else None

        if total_harga is not None:
            subtotal += total_harga

        details.append({
            "partai_no": pno,
            "size_round": size_round,
            "berat_netto": float(netto),
            "harga": int(harga) if harga is not None else None,
            "total_harga": float(total_harga) if total_harga is not None else None
        })

    pph = (subtotal * pph_rate) if pph_rate is not None else None
    total = subtotal + (pph or 0)

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO invoice_header (receiving_id, tanggal, supplier, price_points_json, subtotal, pph, total)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        receiving_id,
        header["tanggal"],
        header["supplier"],
        json.dumps(points),
        float(subtotal),
        float(pph) if pph is not None else None,
        float(total)
    ))
    invoice_id = cur.lastrowid

    # insert details (FIX: loop dict, bukan unpack tuple)
    for d in details:
        cur.execute("""
            INSERT INTO invoice_detail (invoice_id, partai_no, size_round, berat_netto, harga, total_harga)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            invoice_id,
            d["partai_no"],
            d["size_round"],
            d["berat_netto"],
            d["harga"],
            d["total_harga"]
        ))

    conn.commit()
    conn.close()

    return redirect(url_for("invoice_view", invoice_id=invoice_id))

@app.route("/production/list")
def production_list():
    if not require_login():
        return redirect(url_for("login"))

    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    supplier_q = (request.args.get("supplier") or "").strip()   # akan berisi NAMA supplier
    jenis_q = (request.args.get("jenis") or "").strip()

    conn = get_conn()

    # ✅ isi dropdown
    suppliers = conn.execute("SELECT nama FROM supplier WHERE aktif=1 ORDER BY nama").fetchall()
    jenis_list = conn.execute("SELECT nama FROM udang_jenis WHERE aktif=1 ORDER BY id").fetchall()

    where = []
    params = []

    if start and end:
        where.append("r.tanggal BETWEEN ? AND ?")
        params.extend([start, end])
    elif start:
        where.append("r.tanggal >= ?")
        params.append(start)
    elif end:
        where.append("r.tanggal <= ?")
        params.append(end)

    # ✅ filter supplier dari dropdown (exact match, case-insensitive)
    if supplier_q:
        where.append("LOWER(TRIM(r.supplier)) = ?")
        params.append(supplier_q.strip().lower())

    # ✅ filter jenis dari dropdown (exact match, case-insensitive)
    if jenis_q:
        where.append("LOWER(TRIM(r.jenis)) = ?")
        params.append(jenis_q.strip().lower())

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    # ... LANJUTKAN query production list kamu yang sudah ada ...
    # Pastikan alias tabel receiving_header adalah r (atau sesuaikan)
    rows = conn.execute(f"""
        SELECT
          r.id AS receiving_id,
          r.tanggal, r.supplier, r.jenis,
          r.total_netto AS rm_kg,

          COALESCE(hl.berat_kg,0) AS hl_kg,
          COALESCE(hl.yield_pct,0) AS hl_yield,

          COALESCE(kp.berat_kg,0) AS kupas_kg,
          COALESCE(kp.yield_pct,0) AS kupas_yield,

          COALESCE(sk.berat_kg,0) AS fg_kg,
          COALESCE(sk.yield_pct,0) AS fg_yield,

          COALESCE(sk.yield_pct,0) AS final_pct
        FROM (
          SELECT h.id, h.tanggal, h.supplier, h.jenis,
                 COALESCE(SUM(COALESCE(p.netto,0)),0) AS total_netto
          FROM receiving_header h
          LEFT JOIN receiving_partai p ON p.header_id=h.id
          GROUP BY h.id
        ) r
        LEFT JOIN production_header ph ON ph.id = (
  SELECT id FROM production_header
  WHERE receiving_id = r.id
  ORDER BY id DESC
  LIMIT 1
)

        LEFT JOIN production_step hl ON hl.production_id=ph.id AND hl.step_name='HL'
        LEFT JOIN production_step kp ON kp.production_id=ph.id AND kp.step_name='KUPAS'
        LEFT JOIN production_step sk ON sk.production_id=ph.id AND sk.step_name='SOAKING'
        {where_sql}
        ORDER BY r.id DESC
    """, params).fetchall()

    # summary kamu tetap seperti sebelumnya (kalau kamu sudah punya)
    # contoh minimal:
    summary = {
        "total_rm": sum([(x["rm_kg"] or 0) for x in rows]),
        "total_fg": sum([(x["fg_kg"] or 0) for x in rows]),  # ✅ FIX DI SINI
        "avg_yield": (sum([(x["final_pct"] or 0) for x in rows]) / len(rows)) if rows else 0,
        "count_rows": len(rows),
    }

    conn.close()

    return render_template(
        "production_list.html",
        rows=[dict(r) for r in rows],
        summary=summary,
        start=start,
        end=end,
        supplier=supplier_q,
        jenis=jenis_q,
        suppliers=[s["nama"] for s in suppliers],   # ✅ dropdown data
        jenis_list=[j["nama"] for j in jenis_list], # ✅ dropdown data
    )

@app.get("/production/debug/<int:receiving_id>")
def production_debug(receiving_id):
    conn = get_conn()
    heads = conn.execute("SELECT * FROM production_header WHERE receiving_id=? ORDER BY id DESC", (receiving_id,)).fetchall()
    out = []
    for h in heads:
        pid = h["id"]
        steps = conn.execute("SELECT step_name, berat_kg FROM production_step WHERE production_id=? ORDER BY id", (pid,)).fetchall()
        pack_cnt = conn.execute("SELECT COUNT(*) c FROM production_packing WHERE production_id=?", (pid,)).fetchone()["c"]
        out.append({"prod_id": pid, "steps": [dict(s) for s in steps], "packing_count": pack_cnt})
    conn.close()
    return jsonify(out)



@app.route("/invoice/<int:invoice_id>")
def invoice_view(invoice_id):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()
    inv = conn.execute("SELECT * FROM invoice_header WHERE id=?", (invoice_id,)).fetchone()
    det = conn.execute(
        "SELECT * FROM invoice_detail WHERE invoice_id=? ORDER BY partai_no",
        (invoice_id,)
    ).fetchall()
    conn.close()

    if not inv:
        return "Invoice tidak ditemukan", 404

    return render_template("invoice_view.html", inv=dict(inv), det=[dict(r) for r in det])

@app.route("/invoice/list")
def invoice_list():
    if not require_login():
        return redirect(url_for("login"))

    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    supplier_q = (request.args.get("supplier") or "").strip()

    conn = get_conn()

    where = ["status='ACTIVE'"]
    params = []

    # filter tanggal
    if start and end:
        where.append("tanggal BETWEEN ? AND ?")
        params.extend([start, end])
    elif start:
        where.append("tanggal >= ?")
        params.append(start)
    elif end:
        where.append("tanggal <= ?")
        params.append(end)

    # filter supplier (case-insensitive)
    if supplier_q:
        where.append("LOWER(TRIM(supplier)) = ?")
        params.append(supplier_q.lower())

    where_sql = "WHERE " + " AND ".join(where)

    # data tabel
    rows = conn.execute(f"""
        SELECT id, receiving_id, tanggal, supplier, subtotal, pph, total, created_at
        FROM invoice_header
        {where_sql}
        ORDER BY id DESC
        LIMIT 200
    """, params).fetchall()

    # total pembelian sesuai filter
    total_beli_row = conn.execute(f"""
        SELECT COALESCE(SUM(COALESCE(total,0)),0) AS total_beli
        FROM invoice_header
        {where_sql}
    """, params).fetchone()

    total_beli = float(total_beli_row["total_beli"] or 0)

    conn.close()

    return render_template(
        "invoice_list.html",
        rows=[dict(r) for r in rows],
        start=start,
        end=end,
        supplier=supplier_q,  # <-- tambah
        total_beli=total_beli
    )


@app.get("/invoice/edit/<int:invoice_id>")
def invoice_edit(invoice_id):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()

    inv = conn.execute("SELECT * FROM invoice_header WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        conn.close()
        return "Invoice tidak ditemukan", 404

    # ambil partai dari receiving (sumber data utama)
    parts = conn.execute("""
        SELECT partai_no, round_size, COALESCE(netto,0) AS netto
        FROM receiving_partai
        WHERE header_id=?
        ORDER BY partai_no
    """, (inv["receiving_id"],)).fetchall()

    # ambil detail invoice lama (harga lama)
    det = conn.execute("""
        SELECT partai_no, harga
        FROM invoice_detail
        WHERE invoice_id=?
        ORDER BY partai_no
    """, (invoice_id,)).fetchall()

    conn.close()

    # map harga lama per partai
    det_map = {d["partai_no"]: (d["harga"] or 0) for d in det}

    return render_template(
        "invoice_edit.html",
        inv=dict(inv),
        parts=[dict(p) for p in parts],
        det_map=det_map
    )

@app.post("/invoice/update/<int:invoice_id>")
def invoice_update(invoice_id):
    if not require_login():
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401

    data = request.get_json(force=True) or {}
    items = data.get("items") or []   # [{partai_no:1, harga:32000}, ...]
    pph_input = data.get("pph_rate")  # input persen (contoh 1 = 1%)

    conn = get_conn()
    cur = conn.cursor()

    inv = conn.execute("SELECT * FROM invoice_header WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        conn.close()
        return jsonify({"ok": False, "msg": "Invoice tidak ditemukan"}), 404

    receiving_id = inv["receiving_id"]

    # sumber netto & size dari receiving
    parts = conn.execute("""
        SELECT partai_no, round_size, COALESCE(netto,0) AS netto
        FROM receiving_partai
        WHERE header_id=?
    """, (receiving_id,)).fetchall()
    part_map = {p["partai_no"]: p for p in parts}

    try:
        pph_rate = float(pph_input or 0) / 100.0
    except:
        pph_rate = 0.0

    subtotal = 0.0
    detail_rows = []

    for it in items:
        pn = int(it.get("partai_no") or 0)
        harga = int(float(it.get("harga") or 0))

        p = part_map.get(pn)
        if not p:
            continue

        size_round = p["round_size"]
        berat_netto = float(p["netto"] or 0)
        total_harga = berat_netto * harga

        subtotal += total_harga
        detail_rows.append((invoice_id, pn, size_round, berat_netto, harga, total_harga))

    pph = subtotal * pph_rate
    total = subtotal - pph   # kalau PPH menambah: subtotal + pph

    try:
        cur.execute("""
            UPDATE invoice_header
            SET pph_rate=?, subtotal=?, pph=?, total=?
            WHERE id=?
        """, (pph_rate, subtotal, pph, total, invoice_id))

        cur.execute("DELETE FROM invoice_detail WHERE invoice_id=?", (invoice_id,))
        for row in detail_rows:
            cur.execute("""
                INSERT INTO invoice_detail
                    (invoice_id, partai_no, size_round, berat_netto, harga, total_harga)
                VALUES (?, ?, ?, ?, ?, ?)
            """, row)

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"ok": False, "msg": f"Gagal update: {e}"}), 500

    conn.close()
    return jsonify({"ok": True})

@app.route("/invoice/list/print")
def invoice_list_print():
    if not require_login():
        return redirect(url_for("login"))

    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    supplier_q = (request.args.get("supplier") or "").strip()

    conn = get_conn()

    where = ["status='ACTIVE'"]
    params = []

    if start and end:
        where.append("tanggal BETWEEN ? AND ?")
        params.extend([start, end])
    elif start:
        where.append("tanggal >= ?")
        params.append(start)
    elif end:
        where.append("tanggal <= ?")
        params.append(end)

    if supplier_q:
        where.append("LOWER(TRIM(supplier)) = ?")
        params.append(supplier_q.lower())

    where_sql = "WHERE " + " AND ".join(where)

    rows = conn.execute(f"""
        SELECT id, receiving_id, tanggal, supplier, subtotal, pph, total, created_at
        FROM invoice_header
        {where_sql}
        ORDER BY id DESC
    """, params).fetchall()

    total_beli_row = conn.execute(f"""
        SELECT COALESCE(SUM(COALESCE(total,0)),0) AS total_beli
        FROM invoice_header
        {where_sql}
    """, params).fetchone()

    total_beli = float(total_beli_row["total_beli"] or 0)
    conn.close()

    return render_template(
        "invoice_list_print.html",
        rows=[dict(r) for r in rows],
        total_beli=total_beli,
        start=start,
        end=end,
        supplier=supplier_q
    )



@app.post("/invoice/save/<int:invoice_id>")
def invoice_save(invoice_id):
    if not require_login():
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401

    data = request.get_json(force=True) or {}
    rows = data.get("rows") or []
    deleted_ids = data.get("deleted_ids") or []

    conn = get_conn()
    cur = conn.cursor()

    inv = conn.execute("SELECT id FROM invoice_header WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        conn.close()
        return jsonify({"ok": False, "msg": "Invoice tidak ditemukan"}), 404

    try:
        # 1) delete baris yang memang dihapus user
        for did in deleted_ids:
            cur.execute("DELETE FROM invoice_detail WHERE id=? AND invoice_id=?", (did, invoice_id))

        # 2) upsert baris: kalau ada id -> UPDATE, kalau kosong -> INSERT
        for r in rows:
            detail_id = r.get("id")  # boleh None
            partai_no = int(r.get("partai_no") or 0)
            qty = float(r.get("qty") or 0)
            harga = float(r.get("harga") or 0)
            jumlah = qty * harga

            if detail_id:
                cur.execute("""
                    UPDATE invoice_detail
                    SET partai_no=?, qty=?, harga=?, jumlah=?
                    WHERE id=? AND invoice_id=?
                """, (partai_no, qty, harga, jumlah, detail_id, invoice_id))
            else:
                cur.execute("""
                    INSERT INTO invoice_detail (invoice_id, partai_no, qty, harga, jumlah)
                    VALUES (?, ?, ?, ?, ?)
                """, (invoice_id, partai_no, qty, harga, jumlah))

        # 3) hitung ulang header (subtotal/pph/total)
        subtotal = conn.execute("""
            SELECT COALESCE(SUM(COALESCE(jumlah,0)),0) AS s
            FROM invoice_detail WHERE invoice_id=?
        """, (invoice_id,)).fetchone()["s"]

        pph = float(data.get("pph") or 0)
        total = float(subtotal) - float(pph)

        cur.execute("""
            UPDATE invoice_header
            SET subtotal=?, pph=?, total=?
            WHERE id=?
        """, (subtotal, pph, total, invoice_id))

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"ok": False, "msg": f"Gagal simpan: {e}"}), 500

    conn.close()
    return jsonify({"ok": True})

@app.post("/invoice/void/<int:invoice_id>")
def invoice_void(invoice_id):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()
    conn.execute("UPDATE invoice_header SET status='VOID' WHERE id=?", (invoice_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("invoice_list"))

# =========================
# Menus (optional, kamu masih pakai)
# =========================
@app.route("/menu1")
def menu1():
    if not require_login():
        return redirect(url_for("login"))
    return render_template("menu1.html", today=date.today().strftime("%Y-%m-%d"))


@app.route("/menu2")
def menu2():
    if not require_login():
        return redirect(url_for("login"))
    return render_template("menu2.html")


@app.route("/menu3")
def menu3():
    if not require_login():
        return redirect(url_for("login"))
    return render_template("menu3.html")


@app.route("/menu4")
def menu4():
    if not require_login():
        return redirect(url_for("login"))
    return render_template("menu4.html")

print(app.url_map)

# Run
# =========================
if __name__ == "__main__":

    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

