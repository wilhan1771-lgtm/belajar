from flask import render_template, request, redirect, url_for, jsonify, session
from datetime import date
import json
from flask import current_app
from . import receiving_bp

from helpers.auth import require_login, login_required
from helpers.db import init_db, get_conn
from helpers.number_utils import to_int, to_float
from helpers.db import get_conn, DB_PATH
from receiving.calculator import hitung_partai
from receiving.service import update_receiving
from invoice.service import create_invoice_from_receiving
from invoice.repository import get_invoice_by_receiving

@receiving_bp.get("/")
def receiving():
    if not require_login():
        return redirect(url_for("login"))

    today = date.today().strftime("%Y-%m-%d")
    return render_template("receiving/receiving.html", today=today)
print("DB Path aktif:", DB_PATH)
@receiving_bp.post("/save")
def receiving_save():
    print("MASUK ROUTE RECEIVING_SAVE")
    print("DB Path aktif:", DB_PATH)
    if not require_login():
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401

    data = request.get_json(force=True) or {}
    print("DATA MASUK:", data)

    tanggal = data.get("tanggal")
    supplier = data.get("supplier")
    jenis = data.get("jenis")
    partai_list = data.get("partai", [])

    if not tanggal or not supplier:
        return jsonify({"ok": False, "msg": "Header kosong"}), 400

    if not partai_list:
        return jsonify({"ok": False, "msg": "Partai kosong"}), 400

    total_fiber = sum(float(p.get("fiber") or 0) for p in partai_list)

    conn = get_conn()
    cur = conn.cursor()

    try:
        # ===== GENERATE RECEIVING_NO =====
        row = cur.execute(
            "SELECT COALESCE(MAX(receiving_no), 0) + 1 AS next_no FROM receiving_header"
        ).fetchone()
        receiving_no = row["next_no"]

        # ===== INSERT HEADER =====
        cur.execute("""
            INSERT INTO receiving_header
            (receiving_no, tanggal, supplier, jenis, fiber)
            VALUES (?, ?, ?, ?, ?)
        """, (
            receiving_no,
            tanggal,
            supplier,
            jenis,
            total_fiber
        ))

        header_id = cur.lastrowid

        # ===== INSERT PARTAI =====
        for p in partai_list:
            timbangan = p.get("timbangan") or []

            h = hitung_partai({
                **p,
                "timbangan": timbangan
            })

            cur.execute("""
                INSERT INTO receiving_item (
                    header_id,
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
                    kategori_kupasan,
                    fiber
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                header_id,
                p.get("partai_no"),
                p.get("pcs"),
                p.get("kg_sample"),
                h.get("size"),
                h.get("round_size"),
                h.get("keranjang"),
                p.get("tara_per_keranjang"),
                h.get("bruto"),
                h.get("total_tara"),
                h.get("netto"),
                p.get("note"),
                json.dumps(timbangan),
                p.get("kategori_kupasan"),
                p.get("fiber")
            ))

        conn.commit()
        return jsonify({
            "ok": True,
            "id": header_id,
            "receiving_no": receiving_no
        })

    except Exception as e:
        conn.rollback()
        print("ERROR SAVE RECEIVING:", e)
        return jsonify({"ok": False, "msg": str(e)}), 500

    finally:
        conn.close()

@receiving_bp.post("/update/<int:header_id>")
def receiving_update(header_id):

    if not require_login():
        return jsonify({"ok": False, "msg": "Unauthorized"}), 401

    data = request.get_json(force=True) or {}
    header = data.get("header")
    partai_list = data.get("partai", [])

    if not partai_list:
        return jsonify({"ok": False, "msg": "Partai kosong"}), 400

    conn = get_conn()
    cur = conn.cursor()

    try:
        # ===== UPDATE HEADER (opsional) =====
        if header:
            cur.execute("""
                UPDATE receiving_header
                SET tanggal = ?, supplier = ?, jenis = ?, fiber = ?
                WHERE id = ?
            """, (
                header.get("tanggal"),
                header.get("supplier"),
                header.get("jenis"),
                header.get("fiber"),
                header_id
            ))

        # ===== AMBIL DATA LAMA UNTUK KUPASAN + EXISTING IDS =====
        old_kupasan = {}
        existing_ids = set()

        rows = cur.execute("""
            SELECT id, partai_no, kategori_kupasan
            FROM receiving_item
            WHERE header_id = ?
        """, (header_id,)).fetchall()

        for r in rows:
            existing_ids.add(r["id"])
            old_kupasan[r["partai_no"]] = r["kategori_kupasan"]

        # ===== UPSERT ITEM =====
        incoming_existing_ids = set()

        for p in partai_list:
            pid = p.get("id")  # bisa negatif (baru) atau positif (existing)
            timbangan = p.get("timbangan") or []

            h = hitung_partai({**p, "timbangan": timbangan})

            kategori = p.get("kategori_kupasan")
            if header and header.get("jenis") == "kupasan" and not kategori:
                kategori = old_kupasan.get(p.get("partai_no"))

            if pid and isinstance(pid, (int, float)) and int(pid) > 0:
                pid = int(pid)

                # UPDATE (id tetap)
                cur.execute("""
                    UPDATE receiving_item SET
                        partai_no = ?,
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
                    p.get("partai_no"),
                    p.get("pcs"),
                    p.get("kg_sample"),
                    h.get("size"),
                    h.get("round_size"),
                    h.get("keranjang"),
                    p.get("tara_per_keranjang"),
                    h.get("bruto"),
                    h.get("total_tara"),
                    h.get("netto"),
                    p.get("note"),
                    json.dumps(timbangan),
                    kategori,
                    p.get("fiber"),
                    pid,
                    header_id
                ))

                incoming_existing_ids.add(pid)

            else:
                # INSERT baru (id baru dibuat DB)
                cur.execute("""
                    INSERT INTO receiving_item (
                        header_id,
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
                        kategori_kupasan,
                        fiber
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    header_id,
                    p.get("partai_no"),
                    p.get("pcs"),
                    p.get("kg_sample"),
                    h.get("size"),
                    h.get("round_size"),
                    h.get("keranjang"),
                    p.get("tara_per_keranjang"),
                    h.get("bruto"),
                    h.get("total_tara"),
                    h.get("netto"),
                    p.get("note"),
                    json.dumps(timbangan),
                    kategori,
                    p.get("fiber")
                ))

        # ===== DELETE YANG TIDAK ADA DI PAYLOAD (kalau user hapus partai) =====
        ids_to_delete = existing_ids - incoming_existing_ids
        if ids_to_delete:
            placeholders = ",".join(["?"] * len(ids_to_delete))
            cur.execute(
                f"DELETE FROM receiving_item WHERE header_id = ? AND id IN ({placeholders})",
                (header_id, *ids_to_delete)
            )

        conn.commit()
        return jsonify({"ok": True})

    except Exception as e:
        conn.rollback()
        print("ERROR UPDATE RECEIVING:", e)
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
        LEFT JOIN receiving_item p ON p.header_id = h.id
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
        SELECT * FROM receiving_item
        WHERE header_id=?
        ORDER BY partai_no
    """, (header_id,)).fetchall()

    conn.close()

    partai = []
    total_netto = 0
    total_fiber = 0
    total_size = 0

    for r in partai_rows:
        d = dict(r)
        d["timbangan"] = json.loads(d.get("timbangan_json") or "[]")
        total_netto += d.get("netto") or 0
        total_fiber += d.get("fiber") or 0
        total_size += d.get("kg_sample") or 0   # size bisa diganti sesuai formula kamu
        partai.append(d)

    invoice_existing = get_invoice_by_receiving(header["id"])
    return render_template(
        "receiving/receiving_detail.html",
        header=dict(header),
        partai=partai,
        total_netto=total_netto,
        total_fiber=total_fiber,
        total_size=total_size,
        invoice_existing=invoice_existing,
    )