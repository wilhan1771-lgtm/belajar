from receiving.calculator import hitung_partai
from receiving.calculator import recalc_receiving
from invoice.service import create_invoice_from_receiving
from helpers.number_utils import to_float, to_int
from invoice.repository import fetch_receiving_header
from invoice.repository import invoice_exists_for_receiving
from invoice.pricing import interpolate_price
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import date, datetime, timedelta
import json
from invoice import invoice_bp

from receiving.service import update_receiving
from receiving.routes import receiving_bp
from helpers.db import init_db, get_conn


# init database
init_db()

app = Flask(__name__)
app.secret_key = "belajar-secret"

app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,     # karena masih http
    SESSION_COOKIE_HTTPONLY=True
)

app.permanent_session_lifetime = timedelta(hours=8)
app.register_blueprint(invoice_bp)
app.config["ADMIN_USERNAME"] = "admin"
app.config["ADMIN_PASSWORD"] = "1234"   # atau ADMIN_PIN
DATE_FMT = "%Y-%m-%d"
print("INI FILE YANG AKTIF")


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if (
                username == app.config["ADMIN_USERNAME"] and
                password == app.config["ADMIN_PASSWORD"]
        ):
            session.clear()
            session["user"] = username
            session.permanent = True
            return redirect("/dashboard")

        return render_template("login.html", error="Login gagal")

    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    print("SESSION:", dict(session))  # 🔎 DEBUG
    if not require_login():
        return redirect("/")
    return render_template("dashboard.html")

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
def admin_db_table_view(table_name):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()
    try:
        tables = [r["name"] for r in conn.execute("""
            SELECT name FROM sqlite_master WHERE type='table'
        """).fetchall()]
        if table_name not in tables:
            return "Table tidak valid", 400

        limit = request.args.get("limit", "200")
        try:
            limit = int(limit)
        except:
            limit = 200
        limit = max(1, min(limit, 2000))

        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]

        rows = conn.execute(f"""
            SELECT * FROM {table_name}
            ORDER BY rowid DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return render_template(
            "admin_db_table.html",
            table_name=table_name,
            cols=cols,
            rows=[dict(r) for r in rows],
            limit=limit
        )
    finally:
        conn.close()

# =========================
# Auth
# =========================

@app.get("/production/<int:prod_id>")
def production_view(prod_id):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()
    try:
        prod = conn.execute(
            "SELECT * FROM production_header WHERE id=?",
            (prod_id,)
        ).fetchone()

        if not prod:
            return "Production tidak ditemukan", 404

        rec = conn.execute("""
            SELECT h.id, h.tanggal, h.supplier, h.jenis,
                   COALESCE(SUM(COALESCE(p.netto,0)),0) AS total_netto
            FROM receiving_header h
            LEFT JOIN receiving_item p ON p.header_id = h.id
            WHERE h.id = ?
            GROUP BY h.id
        """, (prod["receiving_id"],)).fetchone()

        packing = conn.execute("""
            SELECT * FROM production_packing
            WHERE production_id=?
            ORDER BY id
        """, (prod_id,)).fetchall()

        # ===== steps diambil dari kolom-kolom di production_header =====
        prod_dict = dict(prod)

        skip_cols = {
            "id", "receiving_id", "tanggal", "supplier", "jenis",
            "bahan_masuk", "created_at"
        }

        steps = []
        for col, val in prod_dict.items():
            if col in skip_cols:
                continue
            if val is None:
                continue

            # kalau step kamu berupa angka 0/1 (checkbox), bisa filter di sini:
            # if isinstance(val, (int, float)) and val == 0:
            #     continue

            steps.append({"name": col, "value": val})

        return render_template(
            "production.html",
            receiving=dict(rec) if rec else None,
            production=prod_dict,
            packing=[dict(r) for r in packing],
            steps=steps,
        )
    finally:
        conn.close()


# =========================
# Menus (optional, kamu masih pakai)
# =========================
# =========================
# Helpers
# =======================
def require_login() -> bool:
    return bool(session.get("user"))

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


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================
# DEBUG RECEIVING
# =========================

if app.debug:

    @app.get("/receiving/debug")
    def receiving_debug():
        if not require_login():
            return redirect(url_for("login"))

        conn = get_conn()
        try:
            headers = conn.execute(
                "SELECT * FROM receiving_header ORDER BY id DESC LIMIT 50"
            ).fetchall()
            partai = conn.execute(
                "SELECT * FROM receiving_item ORDER BY id DESC LIMIT 200"
            ).fetchall()

            return {
                "headers": [dict(r) for r in headers],
                "partai": [dict(r) for r in partai],
            }
        finally:
            conn.close()

@app.get("/debug/cols/<table>")
def debug_cols(table):
    conn = get_conn()
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {"table": table, "cols": [r["name"] for r in rows]}
    finally:
        conn.close()

@app.get("/debug/tables")
def debug_tables():
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table'
            ORDER BY name
        """).fetchall()

        return {
            "tables": [r["name"] for r in rows]
        }
    finally:
        conn.close()


@app.get("/master/jenis")
def master_jenis():
    if not require_login():
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401

    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, nama FROM udang_jenis WHERE aktif=1 ORDER BY id"
        ).fetchall()
        return jsonify({"ok": True, "data": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500
    finally:
        conn.close()


@app.post("/master/suppliers")
def master_supplier_add():
    if not require_login():
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    nama = (data.get("nama") or "").strip()
    if not nama:
        return jsonify({"ok": False, "msg": "Nama supplier wajib"}), 400

    conn = get_conn()
    try:
        conn.execute("INSERT INTO supplier (nama) VALUES (?)", (nama,))
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "msg": f"Gagal tambah supplier: {e}"}), 400
    finally:
        conn.close()
@app.get("/master/suppliers")
def master_suppliers():
    if not require_login():
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401

    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, nama FROM supplier ORDER BY id"
        ).fetchall()
        return jsonify({"ok": True, "data": [dict(r) for r in rows]})
    finally:
        conn.close()



@app.get("/debug-production")
def debug_production():
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, receiving_id, hl, kupas, soaking
        FROM production_header
        ORDER BY id DESC
    """).fetchall()
    conn.close()
    return {"data": [dict(r) for r in rows]}

### -------------------
### --- Production List
### -------------------
@app.get("/production/list")
def production_list():
    if not require_login():
        return redirect(url_for("login"))

    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    supplier_q = (request.args.get("supplier") or "").strip()
    jenis_q = (request.args.get("jenis") or "").strip()

    where = []
    params = []

    if start:
        where.append("h.tanggal >= ?")
        params.append(start)
    if end:
        where.append("h.tanggal <= ?")
        params.append(end)
    if supplier_q:
        where.append("h.supplier = ?")
        params.append(supplier_q)
    if jenis_q:
        where.append("h.jenis = ?")
        params.append(jenis_q)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    conn = get_conn()
    try:
        # Suppliers dan jenis
        suppliers = [s["nama"] for s in conn.execute("SELECT nama FROM supplier ORDER BY nama").fetchall()]
        jenis_list = [j["nama"] for j in conn.execute("SELECT nama FROM udang_jenis ORDER BY nama").fetchall()]

        # Ambil data production_header, join ke receiving_header untuk info tanggal/supplier/jenis
        rows = conn.execute(f"""
            SELECT
                r.id AS receiving_id,
                r.tanggal,
                r.supplier,
                r.jenis,

                -- RM dari receiving_item
                COALESCE(SUM(rp.netto), 0) AS rm_kg,

                -- Data produksi (jika ada)
                COALESCE(ph.hl, 0) AS hl_kg,
                COALESCE(ph.kupas, 0) AS kupas_kg,
                COALESCE(ph.soaking, 0) AS fg_kg,

                CASE 
                    WHEN COALESCE(SUM(rp.netto),0) > 0 
                    THEN (COALESCE(ph.hl,0) / SUM(rp.netto)) * 100 
                    ELSE 0 
                END AS hl_yield,

                CASE 
                    WHEN COALESCE(SUM(rp.netto),0) > 0 
                    THEN (COALESCE(ph.kupas,0) / SUM(rp.netto)) * 100 
                    ELSE 0 
                END AS kupas_yield,

                CASE 
                    WHEN COALESCE(SUM(rp.netto),0) > 0 
                    THEN (COALESCE(ph.soaking,0) / SUM(rp.netto)) * 100 
                    ELSE 0 
                END AS fg_yield

            FROM receiving_header r
            LEFT JOIN receiving_item rp ON rp.header_id = r.id
            LEFT JOIN production_header ph ON ph.receiving_id = r.id

            {where_sql}

            GROUP BY r.id
            ORDER BY r.id DESC
        """, params).fetchall()

        rows = [dict(r) for r in rows]

        summary = {
            "total_rm": sum(x.get("rm_kg",0) for x in rows),
            "total_fg": sum(x.get("fg_kg",0) for x in rows),
            "avg_yield": (sum(x.get("fg_yield",0) for x in rows)/len(rows)) if rows else 0,
            "count_rows": len(rows),
        }

        return render_template("production_list.html",
                               rows=rows,
                               summary=summary,
                               start=start,
                               end=end,
                               supplier=supplier_q,
                               jenis=jenis_q,
                               suppliers=suppliers,
                               jenis_list=jenis_list)
    finally:
        conn.close()

@app.get("/production/open/<int:receiving_id>")
def production_open(receiving_id):
    if not require_login():
        return redirect(url_for("login"))

    conn = get_conn()
    try:
        # --- 1. Ambil receiving ---
        receiving = conn.execute("""
            SELECT h.id, h.tanggal, h.supplier, h.jenis,
                   COALESCE(SUM(p.netto),0) AS total_netto
            FROM receiving_header h
            LEFT JOIN receiving_item p ON p.header_id=h.id
            WHERE h.id=?
            GROUP BY h.id
        """, (receiving_id,)).fetchone()
        if not receiving:
            return "Receiving tidak ditemukan", 404

        # --- 2. Ambil production_header ---
        prod = conn.execute("""
            SELECT *
            FROM production_header
            WHERE receiving_id=?
            ORDER BY id DESC
            LIMIT 1
        """, (receiving_id,)).fetchone()

        if not prod:
            # buat header baru jika belum ada
            conn.execute("""
                INSERT INTO production_header
                    (receiving_id, tanggal, supplier, jenis, bahan_masuk, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                receiving["id"],
                receiving["tanggal"],
                receiving["supplier"],
                receiving["jenis"],
                receiving["total_netto"]
            ))
            conn.commit()
            prod = conn.execute("""
                SELECT * FROM production_header
                WHERE receiving_id=?
                ORDER BY id DESC
                LIMIT 1
            """, (receiving_id,)).fetchone()

        # --- 3. Ambil packing terkait ---
        packing = conn.execute("""
            SELECT *
            FROM production_packing
            WHERE production_id=?
            ORDER BY id ASC
        """, (prod["id"],)).fetchall()
        packing = [dict(p) for p in packing]

        # --- 4. Kirim ke template ---
        steps = [
            {"step_name":"HL", "berat_kg": prod["hl"] or 0},
            {"step_name":"SOAKING", "berat_kg": prod["soaking"] or 0}
        ]

        return render_template("production.html",
                               receiving=dict(receiving),
                               production=dict(prod),
                               steps=steps,
                               packing=packing)
    finally:
        conn.close()

@app.post("/production/save/<int:receiving_id>")
def production_save(receiving_id):
    if not require_login():
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401

    data = request.get_json(force=True) or {}
    packing_rows = data.get("packing_rows") or []
    hl_input = float(data.get("hl") or 0)

    conn = get_conn()
    try:
        # --- 1. Ambil header produksi ---
        prod = conn.execute("""
            SELECT *
            FROM production_header
            WHERE receiving_id=?
            ORDER BY id DESC
            LIMIT 1
        """, (receiving_id,)).fetchone()

        if not prod:
            return jsonify({"ok": False, "msg": "Production tidak ditemukan"}), 404

        # --- 2. Ambil bahan_masuk dari receiving_header ---
        receiving = conn.execute("""
            SELECT COALESCE(SUM(netto),0) AS total_netto
            FROM receiving_item
            WHERE header_id=?
        """, (receiving_id,)).fetchone()
        bahan_masuk = receiving["total_netto"] if receiving else 0

        # --- 3. Hitung total kupas & soaking ---
        total_kupas = 0
        total_soaking = 0

        for row in packing_rows:
            kupas = float(row.get("kupas_kg") or 0)
            mc = float(row.get("mc") or 0)
            berat = float(row.get("berat_per_dus") or 0)
            total = mc * berat

            total_kupas += kupas
            total_soaking += total

            # --- update/insert packing ---
            existing = conn.execute("""
                SELECT id FROM production_packing
                WHERE production_id=? AND size=?
            """, (prod["id"], row.get("size"))).fetchone()
            if existing:
                conn.execute("""
                    UPDATE production_packing
                    SET kupas_kg=?, mc=?, berat_per_dus=?, total_kg=?, yield_ratio=?
                    WHERE id=?
                """, (kupas, mc, berat, total, (total-kupas)/kupas*100 if kupas>0 else 0, existing["id"]))
            else:
                conn.execute("""
                    INSERT INTO production_packing
                        (production_id, size, kupas_kg, mc, berat_per_dus, total_kg, yield_ratio, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (prod["id"], row.get("size"), kupas, mc, berat, total, (total-kupas)/kupas*100 if kupas>0 else 0))

        # --- 4. Update header ---
        conn.execute("""
            UPDATE production_header
            SET hl=?, kupas=?, soaking=?, bahan_masuk=?
            WHERE id=?
        """, (hl_input, total_kupas, total_soaking, bahan_masuk, prod["id"]))

        conn.commit()
        return jsonify({"ok": True, "prod_id": prod["id"]})
    finally:
        conn.close()

# =========================
# Menus (optional, kamu masih pakai)
# =========================
@app.route("/menu1")
def menu1():
    if not require_login():
        return redirect(url_for("login"))
    return render_template("menu1.html", today=date.today().strftime("%Y-%m-%d"))
if app.debug:

    @app.get("/debug/routes")
    def debug_routes():
        return "<br>".join(sorted([str(r) for r in app.url_map.iter_rules()]))

    @app.get("/debug/pragma")
    def debug_pragma():
        conn = get_conn()
        try:
            a = conn.execute("PRAGMA table_info(invoice_header)").fetchall()
            b = conn.execute("PRAGMA table_info(receiving_header)").fetchall()
            c = conn.execute("SELECT * FROM invoice_header WHERE id=51").fetchone()
            return {
                "invoice_header": [dict(x) for x in a],
                "receiving_header": [dict(x) for x in b],
                "invoice_51": dict(c) if c else None
            }
        finally:
            conn.close()
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
        ORDER BY tanggal DESC
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

print("=== ROUTE LIST ===")
print(app.url_map)

app.register_blueprint(receiving_bp, url_prefix="/receiving")
# Run
# =========================
if __name__ == "__main__":

    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

