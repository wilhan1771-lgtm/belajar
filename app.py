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
            SUM(p.netto) AS total_netto,
            COUNT(p.id) AS jml_partai
        FROM receiving_header h
        LEFT JOIN receiving_partai p ON p.header_id = h.id
        GROUP BY h.id
        ORDER BY h.id DESC
    """).fetchall()
    conn.close()

    return render_template("receiving_list.html", rows=rows)

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

@app.route("/receiving")
def receiving():
    if "user" not in session:
        return redirect(url_for("login"))
    today = date.today().strftime("%d/%m/%Y")
    return render_template("receiving.html", today=today)

if __name__ == "__main__":
    app.run(debug=True)
