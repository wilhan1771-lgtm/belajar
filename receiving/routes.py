from flask import render_template, request, redirect, url_for, jsonify, session
from datetime import date
import json

from . import receiving_bp

from helpers.auth import require_login, login_required

from helpers.number_utils import to_int, to_float
from helpers.db import get_conn
from receiving.calculator import hitung_partai
from receiving.service import update_receiving
from invoice.service import sync_invoice_from_receiving

@receiving_bp.get("/")
def receiving():
    if not require_login():
        return redirect(url_for("login"))

    today = date.today().strftime("%Y-%m-%d")
    return render_template("receiving/receiving.html", today=today)

@receiving_bp.post("/save")
def receiving_save():
    if not require_login():
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401

    data = request.get_json(force=True)
    header = data["header"]
    partai_list = data["partai"]

    conn = get_conn()
    cur = conn.cursor()

    try:
        # ===== INSERT HEADER =====
        cur.execute("""
            INSERT INTO receiving_header
            (tanggal, supplier, jenis, fiber)
            VALUES (?, ?, ?, ?)
        """, (
            header["tanggal"],
            header["supplier"],
            header["jenis"],
            header.get("fiber")
        ))

        header_id = cur.lastrowid

        # ===== INSERT PARTAI =====
        for p in partai_list:
            h = hitung_partai(p)

            cur.execute("""
                INSERT INTO receiving_partai
                (header_id, partai_no, pcs, kg_sample,
                 size, round_size,
                 keranjang, tara_per_keranjang,
                 bruto, total_tara, netto,
                 note, timbangan_json,
                 kategori_kupasan, fiber)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                header_id,
                p["partai_no"],
                p.get("pcs"),
                p.get("kg_sample"),
                h["size"],              # vannamei / dogol
                h["round_size"],
                h["keranjang"],
                p.get("tara_per_keranjang"),
                h["bruto"],
                h["total_tara"],
                h["netto"],
                p.get("note"),
                h["timbangan_json"],
                p.get("kategori_kupasan"),  # kupasan
                p.get("fiber")
            ))

        conn.commit()
        return jsonify({"ok": True, "id": header_id})

    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "msg": str(e)}), 500
    finally:
        conn.close()
@receiving_bp.post("/update/<int:header_id>")
def receiving_update(header_id):
    if not require_login():
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401

    data = request.get_json(force=True) or {}
    partai_list = data.get("partai", [])

    if not partai_list:
        return jsonify({"ok": False, "msg": "Partai kosong"}), 400

    conn = get_conn()
    cur = conn.cursor()

    try:
        for p in partai_list:
            partai_id = p.get("id")
            if not partai_id:
                continue

            h = hitung_partai(p)

            cur.execute("""
                UPDATE receiving_partai
                SET
                    pcs = ?,
                    kg_sample = ?,
                    size = ?,
                    round_size = ?,
                    keranjang = ?,
                    tara_per_keranjang = ?,
                    bruto = ?,
                    total_tara = ?,
                    netto = ?,
                    note = ?,
                    timbangan_json = ?,
                    kategori_kupasan = ?,
                    fiber = ?
                WHERE id = ? AND header_id = ?
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
                p.get("kategori_kupasan"),
                p.get("fiber"),
                partai_id,
                header_id
            ))

        conn.commit()
        return jsonify({"ok": True})

    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "msg": str(e)}), 500
    finally:
        conn.close()

@receiving_bp.get("/list")
def receiving_list():
    if not require_login():
        return redirect(url_for("login"))
    print("SESSION RECEIVING:", dict(session))
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
        "receiving/receiving_list.html",
        rows=[dict(r) for r in rows],
        start=start,
        end=end,
        supplier=supplier_q,
        jenis=jenis_q,     # 🔥 PENTING
        total_berat=total_berat
    )

@receiving_bp.get("/<int:header_id>")
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

    conn.close()

    partai, total_netto = [], 0
    for r in partai_rows:
        d = dict(r)
        d["timbangan"] = json.loads(d.get("timbangan_json") or "[]")
        total_netto += d.get("netto") or 0
        partai.append(d)

    return render_template(
        "receiving/receiving_detail.html",
        header=dict(header),
        partai=partai,
        total_netto=total_netto
    )
