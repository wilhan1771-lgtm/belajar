from flask import Flask, render_template, request, redirect, url_for, session
from datetime import date
from db import init_db
init_db()
import json
from flask import jsonify

from db import get_conn
app = Flask(__name__)
app.secret_key = "belajar-secret"
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
def interpolate_price(size: int, points: dict) -> int | None:
    """
    points contoh: {40:65000, 50:60000, 60:55000, 70:52000}
    size contoh: 54 -> hitung dari 50 & 60
    """
    if size is None:
        return None

    size = int(size)
    pts = {int(k): int(v) for k, v in points.items() if v is not None and str(v) != ""}

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
@app.route("/invoice/new/<int:receiving_id>", methods=["GET", "POST"])
def invoice_new(receiving_id):
    if "user" not in session:
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
        # kumpulkan patokan size yang dibutuhkan dari round_size
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

    # ambil patokan harga dinamis dari form: p60, p70, p100, dst
    points = {}
    for k, v in request.form.items():
        if k.startswith("p"):
            try:
                sz = int(k[1:])  # "p60" -> 60
                points[sz] = int(v) if str(v).strip() != "" else None
            except:
                pass

    pph_rate = float(request.form.get("pph_rate") or 0.0025)

    details = []
    subtotal = 0.0

    for r in partai_rows:
        pno = r["partai_no"]
        size_round = r["round_size"]
        netto = r["netto"] or 0

        harga = interpolate_price(size_round, points)
        total_harga = (netto * harga) if harga is not None else None
        if total_harga is not None:
            subtotal += total_harga

        details.append((pno, size_round, netto, harga, total_harga))

    pph = subtotal * pph_rate
    total = subtotal - pph  # sesuai contoh sheet kamu

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO invoice_header(receiving_id, tanggal, supplier, price_points_json, pph_rate, subtotal, pph, total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        receiving_id,
        header["tanggal"],
        header["supplier"],
        json.dumps(points),
        pph_rate,
        subtotal,
        pph,
        total
    ))
    invoice_id = cur.lastrowid

    for (pno, size_round, netto, harga, total_harga) in details:
        cur.execute("""
            INSERT INTO invoice_detail(invoice_id, partai_no, size_round, berat_netto, harga, total_harga)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (invoice_id, pno, size_round, netto, harga, total_harga))

    conn.commit()
    conn.close()

    return redirect(url_for("invoice_view", invoice_id=invoice_id))
@app.route("/invoice/<int:invoice_id>")
def invoice_view(invoice_id):
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_conn()
    inv = conn.execute("SELECT * FROM invoice_header WHERE id=?", (invoice_id,)).fetchone()
    det = conn.execute("SELECT * FROM invoice_detail WHERE invoice_id=? ORDER BY partai_no", (invoice_id,)).fetchall()
    conn.close()

    if not inv:
        return "Invoice tidak ditemukan", 404

    return render_template("invoice_view.html", inv=dict(inv), det=[dict(r) for r in det])

@app.route("/invoice/list")
def invoice_list():
    if "user" not in session:
        return redirect(url_for("login"))

    start = (request.args.get("start") or "").strip()  # format: YYYY-MM-DD
    end = (request.args.get("end") or "").strip()

    conn = get_conn()

    if start and end:
        rows = conn.execute("""
            SELECT id, receiving_id, tanggal, supplier, subtotal, pph, total, created_at
            FROM invoice_header
            WHERE tanggal BETWEEN ? AND ?
            ORDER BY id DESC
        """, (start, end)).fetchall()
    else:
        rows = conn.execute("""
            SELECT id, receiving_id, tanggal, supplier, subtotal, pph, total, created_at
            FROM invoice_header
            ORDER BY id DESC
            LIMIT 100
        """).fetchall()

    conn.close()
    return render_template("invoice_list.html", rows=[dict(r) for r in rows], start=start, end=end)
@app.route("/invoice/delete/<int:invoice_id>", methods=["POST"])
def invoice_delete(invoice_id):
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM invoice_detail WHERE invoice_id=?", (invoice_id,))
        cur.execute("DELETE FROM invoice_header WHERE id=?", (invoice_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return f"Gagal hapus invoice: {e}", 500

    conn.close()
    return redirect(url_for("invoice_list"))

@app.route("/receiving/list")
def receiving_list():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_conn()
    rows = conn.execute("""
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
        GROUP BY h.id
        ORDER BY h.id DESC
    """).fetchall()
    conn.close()

    return render_template("receiving_list.html", rows=rows)
@app.route("/receiving/<int:header_id>")
def receiving_detail(header_id):
    if "user" not in session:
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

    # parse timbangan_json -> list
    partai = []
    for r in partai_rows:
        d = dict(r)
        try:
            d["timbangan"] = json.loads(d.get("timbangan_json") or "[]")
        except:
            d["timbangan"] = []
        partai.append(d)

    # total netto semua partai
    total_netto = sum([(p.get("netto") or 0) for p in partai])

    return render_template(
        "receiving_detail.html",
        header=dict(header),
        partai=partai,
        total_netto=total_netto
    )


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
        # 1) insert header
        cur.execute(
            "INSERT INTO receiving_header (tanggal, supplier, jenis, fiber) VALUES (?, ?, ?, ?)",
            (tanggal, supplier, jenis or None, fiber)
        )
        header_id = cur.lastrowid

        # 2) insert detail per partai
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
DEMO_USER = {"username": "admin", "password": "1234"}


@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if username == DEMO_USER["username"] and password == DEMO_USER["password"]:
            session["user"] = username
            return redirect(url_for("dashboard"))
        else:
            error = "Username / password salah"

    return render_template("login.html", error=error)


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html", user=session["user"])


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/menu1")
def menu1():
    return render_template("menu1.html", today=date.today().strftime("%Y-%m-%d"))



@app.route("/menu2")
def menu2():
    return render_template("menu2.html")


@app.route("/menu3")
def menu3():
    return render_template("menu3.html")


@app.route("/menu4")
def menu4():
    return render_template("menu4.html")
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

@app.route("/receiving")
def receiving():
    if "user" not in session:
        return redirect(url_for("login"))
    today = date.today().strftime("%d/%m/%Y")
    return render_template("receiving.html", today=today)

if __name__ == "__main__":
    app.run(debug=True)
