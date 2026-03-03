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
from production import production_bp
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
app.register_blueprint(production_bp)
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

@app.get("/master/jenis")
def master_jenis():
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT id, nama, COALESCE(mode,'udang_size') AS mode, is_active, sort_order
            FROM master_jenis
            WHERE is_active = 1
            ORDER BY sort_order ASC, nama ASC
        """).fetchall()
        return jsonify(ok=True, rows=[dict(r) for r in rows])
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500
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

print("=== ROUTE LIST ===")
print(app.url_map)

app.register_blueprint(receiving_bp, url_prefix="/receiving")
# Run
# =========================
if __name__ == "__main__":

    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

