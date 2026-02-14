from receiving.calculator import hitung_partai
from receiving.calculator import recalc_receiving
from invoice.service import sync_invoice_from_receiving
from helpers.number_utils import to_float, to_int
from invoice.repository import get_receiving_header
from invoice.repository import get_existing_invoice
from invoice.pricing import interpolate_price

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import date, datetime, timedelta
import json
from db import init_db, get_conn
from receiving.service import update_receiving

# init database
init_db()

app = Flask(__name__)
app.secret_key = "belajar-secret"

DEMO_USER = {"username": "admin", "password": "1234"}

DATE_FMT = "%Y-%m-%d"
print("INI FILE YANG AKTIF")

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

def require_login() -> bool:
    return bool(session.get("user"))

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
            LEFT JOIN receiving_partai p ON p.header_id = h.id
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

@app.route("/dashboard")
def dashboard():
    if not require_login():
        return redirect(url_for("login"))
    return render_template("dashboard.html", user=session["user"])


@app.post("/receiving/update/<int:header_id>")
def receiving_update(header_id):
    if not require_login():
        return jsonify({"ok": False}), 401

    data = request.get_json(force=True)
    partai_rows = data.get("partai") or []

    conn = get_conn()
    try:
        update_receiving(conn, header_id, partai_rows)
        sync_invoice_from_receiving(conn, header_id)

        conn.commit()
        return jsonify({"ok": True})

    except Exception as e:
        print("🔥 ERROR receiving_update:", e)   # ⬅️ TAMBAH DI SINI
        conn.rollback()
        return jsonify({"ok": False, "msg": str(e)}), 500

    finally:
        conn.close()

# =========================
# Menus (optional, kamu masih pakai)
# =========================
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
                "SELECT * FROM receiving_partai ORDER BY id DESC LIMIT 200"
            ).fetchall()

            return {
                "headers": [dict(r) for r in headers],
                "partai": [dict(r) for r in partai],
            }
        finally:
            conn.close()

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

@app.get("/master/suppliers")
def master_suppliers():
    if not require_login():
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401

    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, nama FROM supplier WHERE aktif=1 ORDER BY nama"
        ).fetchall()
        return jsonify({"ok": True, "data": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500
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


@app.post("/master/supplier/add")
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

@app.route("/receiving/list")
def receiving_list():
    if not require_login():
        return redirect(url_for("login"))

    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    supplier_q = (request.args.get("supplier") or "").strip()
    jenis_q = (request.args.get("jenis") or "").strip().lower()  # 🔥 INI

    where = []
    params = []

    # tanggal
    if start and end:
        where.append("h.tanggal BETWEEN ? AND ?")
        params.extend([start, end])
    elif start:
        where.append("h.tanggal >= ?")
        params.append(start)
    elif end:
        where.append("h.tanggal <= ?")
        params.append(end)

    # supplier
    if supplier_q:
        where.append("LOWER(h.supplier) LIKE ?")
        params.append(f"%{supplier_q.lower()}%")

    # 🔥 FILTER JENIS UDANG
    if jenis_q:
        where.append("LOWER(TRIM(h.jenis)) = ?")
        params.append(jenis_q)

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
            COUNT(p.id) AS jml_partai,
            CASE
            WHEN LOWER(h.jenis) = 'kupasan'
            THEN GROUP_CONCAT(DISTINCT p.kategori_kupasan)
            ELSE GROUP_CONCAT(DISTINCT COALESCE(p.round_size, p.size))
            END AS size_display
        FROM receiving_header h
        LEFT JOIN receiving_partai p ON p.header_id = h.id
        {where_sql}
        GROUP BY h.id
        ORDER BY h.tanggal DESC, h.id DESC

    """, params).fetchall()

    total_berat = sum([(r["total_netto"] or 0) for r in rows])

    conn.close()

    return render_template(
        "receiving_list.html",
        rows=[dict(r) for r in rows],
        start=start,
        end=end,
        supplier=supplier_q,
        jenis=jenis_q,     # 🔥 PENTING
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

                -- RM dari receiving_partai
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
            LEFT JOIN receiving_partai rp ON rp.header_id = r.id
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
            LEFT JOIN receiving_partai p ON p.header_id=h.id
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
            FROM receiving_partai
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

print("=== ROUTE LIST ===")
print(app.url_map)

# Run
# =========================
if __name__ == "__main__":

    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

