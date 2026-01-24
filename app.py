from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import date, datetime, timedelta
import json
from db import init_db, get_conn

# init database
init_db()

app = Flask(__name__)
app.secret_key = "belajar-secret"

DEMO_USER = {"username": "admin", "password": "1234"}

DATE_FMT = "%Y-%m-%d"

def today_str() -> str:
    return date.today().strftime(DATE_FMT)

def calc_invoice_totals(det_rows, pph_rate=0.0, cash_deduct_per_kg=0.0, reject_kg=0.0, reject_price=0.0):
    total_kg = sum(float(r.get("berat_netto") or 0) for r in det_rows)

    subtotal = 0.0
    for r in det_rows:
        kg = float(r.get("berat_netto") or 0)
        harga = float(r.get("harga") or 0)
        subtotal += kg * harga

    cash_total = float(cash_deduct_per_kg or 0) * total_kg
    reject_total = float(reject_kg or 0) * float(reject_price or 0)

    pph_amount = subtotal * (float(pph_rate or 0) / 100.0)

    total = subtotal - cash_total - reject_total - pph_amount

    return {
        "total_kg": total_kg,
        "subtotal": subtotal,
        "cash_deduct_total": cash_total,
        "reject_total": reject_total,
        "pph_amount": pph_amount,
        "total": total,
    }


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
    except (TypeError, ValueError):
        return None

    # only keep valid numeric points
    pts: dict[int, int] = {}
    for k, v in points.items():
        if v is None:
            continue
        if str(v).strip() == "":
            continue
        try:
            pts[int(k)] = int(v)
        except (TypeError, ValueError):
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


def require_login() -> bool:
    return bool(session.get("user"))

from flask import render_template, request, redirect, url_for
import sqlite3

@app.route("/admin/db", methods=["GET"])
def admin_db_home():
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()
    tables = [r["name"] for r in conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table'
        ORDER BY name
    """).fetchall()]

    # quick check: invoice header tapi detail kosong / subtotal mismatch
    bad = conn.execute("""
        SELECT
          h.id AS invoice_id,
          h.receiving_id,
          h.tanggal,
          h.supplier,
          h.subtotal AS header_subtotal,
          COALESCE(SUM(d.total_harga), 0) AS detail_subtotal,
          COUNT(d.id) AS detail_count
        FROM invoice_header h
        LEFT JOIN invoice_detail d ON d.invoice_id = h.id
        WHERE h.status != 'VOID'
        GROUP BY h.id
        HAVING detail_count = 0 OR ABS(header_subtotal - detail_subtotal) > 0.01
        ORDER BY h.id DESC
        LIMIT 50
    """).fetchall()

    conn.close()
    return render_template(
        "admin_db_home.html",
        tables=tables,
        bad=[dict(r) for r in bad]
    )

@app.route("/admin/db/table/<table_name>", methods=["GET"])
def admin_db_table(table_name):
    if not require_login():
        return redirect(url_for("login"))

    # whitelist table name (anti SQL injection)
    conn = get_conn()
    tables = [r["name"] for r in conn.execute("""
        SELECT name FROM sqlite_master WHERE type='table'
    """).fetchall()]
    if table_name not in tables:
        conn.close()
        return "Table tidak valid", 400

    limit = request.args.get("limit", "200")
    try:
        limit = int(limit)
    except:
        limit = 200
    limit = max(1, min(limit, 2000))

    # ambil column list
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]

    rows = conn.execute(f"""
        SELECT * FROM {table_name}
        ORDER BY rowid DESC
        LIMIT ?
    """, (limit,)).fetchall()

    conn.close()
    return render_template(
        "admin_db_table.html",
        table_name=table_name,
        cols=cols,
        rows=[dict(r) for r in rows],
        limit=limit
    )

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

        error = "Username / password salah"

    return render_template("login.html", error=error)

@app.get("/debug/pragma")
def debug_pragma():
    conn = get_conn()
    a = conn.execute("PRAGMA table_info(invoice_header)").fetchall()
    b = conn.execute("PRAGMA table_info(receiving_header)").fetchall()
    c = conn.execute("SELECT * FROM invoice_header WHERE id=51").fetchone()
    conn.close()
    return {
        "invoice_header": [dict(x) for x in a],
        "receiving_header": [dict(x) for x in b],
        "invoice_51": dict(c) if c else None
    }
def recalc_receiving(header_id: int):
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT id, pcs, kg_sample, tara_per_keranjang, timbangan_json, fiber
        FROM receiving_partai
        WHERE header_id=?
    """, (header_id,)).fetchall()

    total_fiber = 0.0

    for r in rows:
        # ---- TIMBANGAN ----
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
            size = r["pcs"] / r["kg_sample"]
            round_size = int(round(size))

        # ---- UPDATE PARTAI ----
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

        # ---- AKUMULASI FIBER (DARI NOL) ----
        try:
            total_fiber += float(r["fiber"] or 0)
        except:
            pass

    # ✅ TIMPA HEADER (BUKAN TAMBAH)
    cur.execute("""
        UPDATE receiving_header
        SET fiber=?
        WHERE id=?
    """, (total_fiber, header_id))

    conn.commit()
    conn.close()

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
def to_float(v):
    if v is None:
        return 0.0
    if isinstance(v, str):
        v = v.replace(",", ".").strip()
    try:
        return float(v)
    except:
        return 0.0
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
        size = round(raw, 1)        # ✅ 1 desimal
        round_size = round(raw)     # ✅ normal round

    return {
        "bruto": bruto,
        "keranjang": keranjang,
        "total_tara": total_tara,
        "netto": netto,
        "size": size,
        "round_size": round_size,
        "timbangan_json": json.dumps(timbangan)
    }

# =========================
# Receiving UI
# =========================
@app.route("/receiving")
def receiving():
    if not require_login():
        return redirect(url_for("login"))
    today = date.today().strftime("%Y-%m-%d")
    return render_template("receiving.html", today=today)

@app.post("/receiving/save")
def receiving_save():
    if not require_login():
        return jsonify({"ok": False}), 401

    data = request.get_json(force=True)
    partai_list = data.get("partai") or []

    conn = get_conn()
    cur = conn.cursor()

    total_fiber = sum(
    float(p.get("fiber") or 0)
    for p in partai_list
    )

    try:
        cur.execute("""
            INSERT INTO receiving_header (tanggal, supplier, jenis, fiber, is_test)
            VALUES (?, ?, ?, ?, ?)
        """, (
            data.get("tanggal"),
            data.get("supplier"),
            data.get("jenis"),
            total_fiber,
            1 if request.args.get("test") == "1" else 0
        ))

        header_id = cur.lastrowid

        for p in partai_list:
            for b in p.get("timbangan") or []:
                if float(b) > 60:
                    raise ValueError("Berat timbangan maksimal 60 kg")
            h = hitung_partai(p)

            cur.execute("""
                        INSERT INTO receiving_partai
                        (header_id,
                         partai_no,
                         pcs,
                         kg_sample,
                         size,
                         round_size,
                         keranjang,
                         tara_per_keranjang,
                         bruto,
                         total_tara,
                         netto,
                         note,
                         timbangan_json,
                         kategori_kupasan,fiber)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,?)
                        """, (
                            header_id,
                            p.get("partai_no"),
                            p.get("pcs"),
                            p.get("kg_sample"),
                            h["size"],
                            h["round_size"],
                            h["keranjang"],
                            p.get("tara_per_keranjang"),
                            h["bruto"],
                            h["total_tara"],
                            h["netto"],
                            p.get("note"),
                            h["timbangan_json"],
                            p.get("kategori_kupasan"),
                            p.get("fiber") # ✅ TERAKHIR
                        ))

        conn.commit()
        return jsonify({"ok": True, "header_id": header_id})

    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "msg": str(e)}), 500
    finally:
        conn.close()

@app.post("/receiving/update/<int:header_id>")
def receiving_update(header_id):
    if not require_login():
        return jsonify({"ok": False}), 401

    data = request.get_json(force=True)
    partai_rows = data.get("partai") or []

    conn = get_conn()
    cur = conn.cursor()

    try:
        for p in partai_rows:
            pid = p.get("id")
            if not pid:
                continue

            h = hitung_partai(p)

            cur.execute("""
                UPDATE receiving_partai
                SET pcs=?,
                    kg_sample=?,
                    size=?,
                    round_size=?,
                    keranjang=?,
                    tara_per_keranjang=?,
                    bruto=?,
                    total_tara=?,
                    netto=?,
                    note=?,
                    timbangan_json=?,
                    fiber=?                 -- 🔥 WAJIB
                WHERE id=? AND header_id=?
                """, (
                        p.get("pcs"),
                        p.get("kg_sample"),
                        h["size"],
                        h["round_size"],
                        h["keranjang"],
                        p.get("tara_per_keranjang"),
                        h["bruto"],
                        h["total_tara"],
                        h["netto"],
                        p.get("note"),
                        h["timbangan_json"],
                        p.get("fiber"),  # 🔥 INI
                        pid,
                        header_id
                        ))


                     # ✅ HARUS DI SINI (SETELAH LOOP SELESAI)
            recalc_receiving(header_id)
            sync_invoice_from_receiving(conn, header_id)

        conn.commit()
        return jsonify({"ok": True})

    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "msg": str(e)}), 500
    finally:
        conn.close()

def sync_invoice_from_receiving(conn, receiving_id: int):
    """
    Sinkronkan invoice dari receiving jika invoice masih DRAFT:
    - update size_round + berat_netto di invoice_detail sesuai receiving_partai
    - total_harga = berat_netto * harga (harga dipertahankan)
    - update invoice_header subtotal/pph/total berdasarkan pph_rate
    """
    inv = conn.execute("""
        SELECT id, COALESCE(pph_rate,0) AS pph_rate
        FROM invoice_header
        WHERE receiving_id=? AND status='DRAFT'
        ORDER BY id DESC
        LIMIT 1
    """, (receiving_id,)).fetchone()

    if not inv:
        return

    invoice_id = inv["id"]
    pph_rate = float(inv["pph_rate"] or 0)

    det_rows = conn.execute("""
        SELECT id, partai_no, COALESCE(harga,0) AS harga
        FROM invoice_detail
        WHERE invoice_id=?
        ORDER BY partai_no
    """, (invoice_id,)).fetchall()

    parts = conn.execute("""
        SELECT partai_no, round_size, COALESCE(netto,0) AS netto
        FROM receiving_partai
        WHERE header_id=?
    """, (receiving_id,)).fetchall()
    part_map = {p["partai_no"]: p for p in parts}

    cur = conn.cursor()
    subtotal = 0.0

    for d in det_rows:
        pn = d["partai_no"]
        harga = float(d["harga"] or 0)

        p = part_map.get(pn)
        if not p:
            round_size = None
            berat_netto = 0.0
        else:
            round_size = p["round_size"]
            berat_netto = float(p["netto"] or 0)

        total_harga = berat_netto * harga
        subtotal += total_harga

        cur.execute("""
            UPDATE invoice_detail
            SET round_size=?, berat_netto=?, total_harga=?
            WHERE id=? AND invoice_id=?
        """, (round_size, berat_netto, total_harga, d["id"], invoice_id))

    pph = subtotal * pph_rate
    total = subtotal - pph   # sesuai logic kamu: total = subtotal - pph

    cur.execute("""
        UPDATE invoice_header
        SET subtotal=?, pph=?, total=?
        WHERE id=?
    """, (subtotal, pph, total, invoice_id))

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
        "SELECT * FROM receiving_header WHERE id=?",
        (header_id,)
    ).fetchone()
    if not header:
        conn.close()
        return "Receiving tidak ditemukan", 404

    partai_rows = conn.execute("""
        SELECT * FROM receiving_partai
        WHERE header_id=?
        ORDER BY partai_no
    """, (header_id,)).fetchall()

    inv = conn.execute("""
        SELECT id FROM invoice_header
        WHERE receiving_id=? AND status!='VOID'
        ORDER BY id DESC LIMIT 1
    """, (header_id,)).fetchone()

    conn.close()

    partai = []
    total_netto = 0
    for r in partai_rows:
        d = dict(r)
        d["timbangan"] = json.loads(d.get("timbangan_json") or "[]")
        total_netto += d.get("netto") or 0
        partai.append(d)

    return render_template(
        "receiving_detail.html",
        header=dict(header),
        partai=partai,
        total_netto=total_netto,
        invoice=inv   # ⬅️ penting
    )


@app.route("/receiving/edit/<int:header_id>", methods=["GET", "POST"])
def receiving_edit(header_id):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()

    # ✅ LOCK: kalau sudah ada invoice, jangan boleh edit
    inv = conn.execute("""
                       SELECT id, status
                       FROM invoice_header
                       WHERE receiving_id = ?
                         AND status!='VOID'
                       ORDER BY id DESC LIMIT 1
                       """, (header_id,)).fetchone()

    if inv and inv["status"] != "DRAFT":
        conn.close()
        return "Receiving terkunci karena invoice sudah FINAL.", 400

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

    # 1) Ambil receiving header
    header = conn.execute(
        "SELECT * FROM receiving_header WHERE id=?",
        (receiving_id,)
    ).fetchone()
    if not header:
        conn.close()
        return "Receiving tidak ditemukan", 404

    # 2) Jika invoice sudah ada (dan bukan VOID) → jangan generate lagi
    existing = conn.execute("""
        SELECT id
        FROM invoice_header
        WHERE receiving_id=? AND status!='VOID'
        ORDER BY id DESC
        LIMIT 1
    """, (receiving_id,)).fetchone()

    if existing and request.method == "GET":
        conn.close()
        return redirect(url_for("invoice_view", invoice_id=existing["id"]))

    # 3) Ambil partai dari receiving
    partai_rows = conn.execute("""
        SELECT partai_no, round_size, COALESCE(netto, 0) AS netto
        FROM receiving_partai
        WHERE header_id=?
        ORDER BY partai_no ASC
    """, (receiving_id,)).fetchall()

    # ===== GET =====
    if request.method == "GET":
        # Deteksi apakah receiving ini pakai size atau tidak
        has_size = any(r["round_size"] is not None for r in partai_rows)

        # Kumpulkan titik harga wajib (p20, p30, dst) untuk mode size
        required_sizes = set()
        if has_size:
            for r in partai_rows:
                rs = r["round_size"]
                if rs is None:
                    continue
                s = int(rs)
                lo = (s // 10) * 10
                hi = lo + 10
                required_sizes.add(lo)
                required_sizes.add(hi)

        required_sizes = sorted(required_sizes)

        # Default tempo & due date
        default_tempo = 7
        tgl_inv = datetime.strptime(header["tanggal"], "%Y-%m-%d")
        default_due = (tgl_inv + timedelta(days=default_tempo)).strftime("%Y-%m-%d")

        conn.close()
        return render_template(
            "invoice_new.html",
            header=dict(header),
            partai=[dict(r) for r in partai_rows],
            has_size=has_size,                 # <-- tambahan: dipakai untuk switch UI
            required_sizes=required_sizes,      # <-- sudah sorted list
            default_tempo=default_tempo,
            default_due=default_due
        )


    # ===== POST (GENERATE) =====
    # 4) kalau POST tapi invoice sudah ada → redirect saja
    if existing:
        conn.close()
        return redirect(url_for("invoice_view", invoice_id=existing["id"]))

    # 5) ambil payment term
    payment_type = (request.form.get("payment_type") or "TRANSFER").strip().upper()

    # tempo hari input manual
    tempo_raw = (request.form.get("tempo_hari") or "").strip()
    try:
        tempo_hari = int(tempo_raw) if tempo_raw != "" else (1 if payment_type == "CASH" else 7)
    except:
        tempo_hari = (1 if payment_type == "CASH" else 7)

    cash_raw = (request.form.get("cash_deduct_per_kg") or "").replace(",", ".").strip()
    try:
        cash_deduct_per_kg = float(cash_raw) if cash_raw != "" else 0.0
    except:
        cash_deduct_per_kg = 0.0

    reject_kg_raw = (request.form.get("reject_kg") or "").replace(",", ".").strip()
    try:
        reject_kg = float(reject_kg_raw) if reject_kg_raw != "" else 0.0
    except:
        reject_kg = 0.0

    reject_price_raw = (request.form.get("reject_price") or "").replace(",", ".").strip()
    try:
        reject_price = float(reject_price_raw) if reject_price_raw != "" else 0.0
    except:
        reject_price = 0.0

    # 6) input harga patokan points
    points = {}
    for k, v in request.form.items():
        if k.startswith("p"):
            try:
                sz = int(k[1:])
                points[sz] = int(v) if str(v).strip() != "" else None
            except:
                pass

    # 7) PPH persen (boleh desimal: 0.4 → 0.004%)
    pph_raw = (request.form.get("pph") or "").replace(",", ".").strip()
    try:
        pph_rate = float(pph_raw) / 100.0 if pph_raw != "" else 0.0
    except:
        pph_rate = 0.0

    # 8) hitung detail & subtotal (berdasarkan receiving)
    details = []
    subtotal = 0.0
    total_berat = 0.0

    for r in partai_rows:
        pno = r["partai_no"]
        round_size = r["round_size"]
        netto = float(r["netto"] or 0.0)

        total_berat += netto

        harga = interpolate_price(round_size, points)
        total_harga = (netto * float(harga)) if harga is not None else 0.0

        subtotal += total_harga

        details.append({
            "partai_no": pno,
            "round_size": round_size,
            "berat_netto": netto,
            "harga": int(harga) if harga is not None else None,
            "total_harga": float(total_harga)
        })

    # 9) hitung due date dari tanggal invoice
    tgl_inv = datetime.strptime(header["tanggal"], "%Y-%m-%d")
    due_date = (tgl_inv + timedelta(days=int(tempo_hari))).strftime("%Y-%m-%d")

    # 10) cash deduct total (dipakai kalau CASH, tapi tetap simpan)
    cash_deduct_total = float(cash_deduct_per_kg) * float(total_berat) if payment_type == "CASH" else 0.0

    # 11) reject total (opsional)
    reject_total = float(reject_kg) * float(reject_price) if reject_kg > 0 and reject_price > 0 else 0.0

    # 12) PPH dan total akhir
    pph = subtotal * pph_rate
    total = subtotal - pph - cash_deduct_total - reject_total

    cur = conn.cursor()
    cur.execute("""
                    
            INSERT INTO invoice_header
            (receiving_id, tanggal, supplier, price_points_json,
             pph_rate, subtotal, pph, total, status,
             due_date, payment_type, cash_deduct_per_kg, cash_deduct_total,
             reject_kg, reject_price, reject_total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        receiving_id,
        header["tanggal"],
        header["supplier"],
        json.dumps(points),
        float(pph_rate),
        float(subtotal),
        float(pph),
        float(total),
        "DRAFT",  # default invoice baru
        due_date,
        payment_type,
        float(cash_deduct_per_kg),
        float(cash_deduct_total),
        float(reject_kg),
        float(reject_price),
        float(reject_total),
    ))
    invoice_id = cur.lastrowid

    for d in details:
        cur.execute("""
                    INSERT INTO invoice_detail
                        (invoice_id, partai_no, round_size, berat_netto, harga, total_harga)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        invoice_id,
                        d["partai_no"],
                        d["round_size"],
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
@app.route("/production/list/print")
def production_list_print():
    if not require_login():
        return redirect(url_for("login"))

    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    supplier_q = (request.args.get("supplier") or "").strip()
    jenis_q = (request.args.get("jenis") or "").strip()

    conn = get_conn()

    # --- filter sama seperti production_list ---
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

    if supplier_q:
        where.append("LOWER(TRIM(r.supplier)) = ?")
        params.append(supplier_q.strip().lower())

    if jenis_q:
        where.append("LOWER(TRIM(r.jenis)) = ?")
        params.append(jenis_q.strip().lower())

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

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

    rows = [dict(r) for r in rows]

    summary = {
        "total_rm": sum([(x.get("rm_kg") or 0) for x in rows]),
        "total_fg": sum([(x.get("fg_kg") or 0) for x in rows]),
        "avg_yield": (sum([(x.get("final_pct") or 0) for x in rows]) / len(rows)) if rows else 0,
        "count_rows": len(rows),
    }

    conn.close()

    return render_template(
        "production_list_print.html",
        rows=rows,
        summary=summary,
        start=start,
        end=end,
        supplier=supplier_q,
        jenis=jenis_q
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

    inv = dict(inv)
    det = [dict(r) for r in det]

    # fallback: total_kg dari detail kalau belum tersimpan
    if inv.get("total_kg") in (None, 0, 0.0):
        inv["total_kg"] = sum(float(r.get("berat_netto") or 0) for r in det)

    return render_template("invoice_view.html", inv=inv, det=det)


@app.route("/invoice/list")
def invoice_list():
    if not require_login():
        return redirect(url_for("login"))

    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    supplier_q = (request.args.get("supplier") or "").strip()

    conn = get_conn()

    where = ["status!='VOID'"]
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

    # DEBUG PRINT (sementara)
    print("INVOICE LIST SQL:", where_sql, "PARAMS:", params)

    rows = conn.execute(f"""
        SELECT id, receiving_id, tanggal, supplier, subtotal, pph, total, status, created_at
        FROM invoice_header
        {where_sql}
        ORDER BY id DESC
        LIMIT 200
    """, params).fetchall()

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
        supplier=supplier_q,
        total_beli=total_beli
    )

@app.route("/invoice/save_price", methods=["POST"])
def invoice_save_price():
    data = request.json
    invoice_id = data["invoice_id"]
    partai_no = data["partai_no"]
    harga = float(data["harga"])

    conn = get_conn()   # ✅ GANTI INI
    cur = conn.cursor()

    row = cur.execute("""
        SELECT berat_netto FROM invoice_detail
        WHERE invoice_id=? AND partai_no=?
    """, (invoice_id, partai_no)).fetchone()

    if not row:
        return {"status": "error"}

    total = row["berat_netto"] * harga

    cur.execute("""
        UPDATE invoice_detail
        SET harga=?, total_harga=?
        WHERE invoice_id=? AND partai_no=?
    """, (harga, total, invoice_id, partai_no))
    conn.commit()
    print("SAVE PRICE", invoice_id, partai_no, harga)
    return {"status": "ok"}

@app.get("/invoice/edit/<int:invoice_id>")
def invoice_edit(invoice_id):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()

    inv = conn.execute("""
        SELECT * FROM invoice_header WHERE id=?
    """, (invoice_id,)).fetchone()

    if not inv:
        conn.close()
        return "Invoice tidak ditemukan", 404

    parts = conn.execute("""
        SELECT partai_no, round_size, COALESCE(netto,0) AS netto
        FROM receiving_partai
        WHERE header_id=?
        ORDER BY partai_no
    """, (inv["receiving_id"],)).fetchall()

    det = conn.execute("""
        SELECT partai_no, harga
        FROM invoice_detail
        WHERE invoice_id=?
    """, (invoice_id,)).fetchall()

    conn.close()

    det_map = {d["partai_no"]: (d["harga"] or 0) for d in det}

    # ✅ RETURN HARUS ADA DI SINI (PALING BAWAH)
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
    items = data.get("items") or []

    conn = get_conn()
    cur = conn.cursor()

    inv = conn.execute("SELECT * FROM invoice_header WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        conn.close()
        return jsonify({"ok": False, "msg": "Invoice tidak ditemukan"}), 404

    receiving_id = inv["receiving_id"]

    parts = conn.execute("""
        SELECT partai_no,
               COALESCE(round_size,0) AS round_size,
               COALESCE(netto,0) AS netto
        FROM receiving_partai
        WHERE header_id=?
        ORDER BY partai_no
    """, (receiving_id,)).fetchall()

    harga_map = {int(it.get("partai_no")): float(it.get("harga") or 0) for it in items}

    payment_type = (data.get("payment_type") or "TRANSFER").strip().upper()
    tempo_hari = int(float(data.get("tempo_hari") or 0))
    due_date = (data.get("due_date") or "").strip() or None

    # UI input contoh 0.4 = 0.4%
    pph_rate_pct = float(data.get("pph_rate") or 0)
    pph_rate = pph_rate_pct / 100.0  # simpan DESIMAL ke DB

    cash_deduct_per_kg = float(data.get("cash_deduct_per_kg") or 0)
    reject_kg = float(data.get("reject_kg") or 0)
    reject_price = float(data.get("reject_price") or 0)

    try:
        cur.execute("BEGIN")

        cur.execute("DELETE FROM invoice_detail WHERE invoice_id=?", (invoice_id,))

        subtotal = 0.0
        total_kg = 0.0

        for p in parts:
            partai_no = int(p["partai_no"])
            berat_netto = float(p["netto"] or 0)
            round_size = int(p["round_size"] or 0)

            harga = float(harga_map.get(partai_no, 0))
            total_harga = berat_netto * harga

            total_kg += berat_netto
            subtotal += total_harga

            cur.execute("""
                INSERT INTO invoice_detail (invoice_id, partai_no, round_size, berat_netto, harga, total_harga)
                VALUES (?,?,?,?,?,?)
            """, (invoice_id, partai_no, round_size, berat_netto, harga, total_harga))

        # due date otomatis bila kosong
        if not due_date:
            tgl_inv = datetime.strptime(inv["tanggal"], "%Y-%m-%d")
            due_date = (tgl_inv + timedelta(days=int(tempo_hari))).strftime("%Y-%m-%d")

        # PPH aman
        pph_amount = 0.0 if subtotal <= 0 else subtotal * pph_rate

        # cash hanya untuk CASH (sesuaikan aturanmu)
        cash_total = (total_kg * cash_deduct_per_kg) if payment_type == "CASH" else 0.0

        # reject aman
        reject_total = (reject_kg * reject_price) if (reject_kg > 0 and reject_price > 0) else 0.0

        total = subtotal - pph_amount - cash_total - reject_total

        cur.execute("""
            UPDATE invoice_header
            SET payment_type=?,
                tempo_hari=?,
                due_date=?,
                subtotal=?,
                pph_rate=?,
                pph=?,
                pph_amount=?,
                cash_deduct_per_kg=?,
                cash_deduct_total=?,
                reject_kg=?,
                reject_price=?,
                reject_total=?,
                total_kg=?,
                total=?
            WHERE id=?
        """, (
            payment_type,
            tempo_hari,
            due_date,
            subtotal,
            pph_rate,
            pph_amount,
            pph_amount,
            cash_deduct_per_kg,
            cash_total,
            reject_kg,
            reject_price,
            reject_total,
            total_kg,
            total,
            invoice_id
        ))

        conn.commit()
        return jsonify({"ok": True})

    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "msg": f"Gagal update: {e}"}), 500
    finally:
        conn.close()

@app.route("/invoice/list/print")
def invoice_list_print():
    if not require_login():
        return redirect(url_for("login"))

    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    supplier_q = (request.args.get("supplier") or "").strip()

    conn = get_conn()

    where = ["status! ='VOID'"]
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

