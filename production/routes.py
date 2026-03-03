from flask import render_template, request, redirect, url_for, jsonify, session
from helpers.db import get_conn
from . import production_bp

@production_bp.route("/list")
def production_list():
    start = (request.args.get("start") or "").strip()
    end = (request.args.get("end") or "").strip()
    supplier = (request.args.get("supplier") or "").strip()
    jenis = (request.args.get("jenis") or "").strip().lower()

    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT
                rh.tanggal,
                rh.id AS receiving_id,
                rh.receiving_no,
                rh.supplier,
                rh.jenis,

                COALESCE(rm.rm_kg, 0) AS rm_kg,
                COALESCE(p.hl_kg, 0) AS hl_kg,
                COALESCE(pack.pd_kg, 0) AS pd_kg,
                COALESCE(pack.fg_kg, 0) AS fg_kg

            FROM receiving_header rh

            LEFT JOIN (
                SELECT header_id, SUM(netto) AS rm_kg
                FROM receiving_item
                GROUP BY header_id
            ) rm ON rm.header_id = rh.id

            LEFT JOIN production p ON p.receiving_id = rh.id

            LEFT JOIN (
                SELECT
                    production_id,
                    SUM(kupas_kg) AS pd_kg,
                    SUM((mc_qty * packs_per_mc + pack_qty) * pack_weight_g / 1000.0) AS fg_kg
                FROM production_packing
                GROUP BY production_id
            ) pack ON pack.production_id = p.id

            WHERE 1=1
              AND (? = '' OR rh.tanggal >= ?)
              AND (? = '' OR rh.tanggal <= ?)
              AND (? = '' OR LOWER(rh.supplier) = LOWER(?))
              AND (? = '' OR LOWER(rh.jenis) = ?)

            ORDER BY rh.tanggal DESC, rh.id DESC
        """, (
            start, start,
            end, end,
            supplier, supplier,
            jenis, jenis
        )).fetchall()
        rows = [dict(r) for r in rows]

        # summary total RM & FG (opsional)
        total_rm = sum((r.get("rm_kg") or 0) for r in rows)
        total_fg = sum((r.get("fg_kg") or 0) for r in rows)

        return render_template(
            "production/list.html",
            rows=rows,
            start=start,
            end=end,
            supplier=supplier,
            jenis=jenis,
            total_rm=total_rm,
            total_fg=total_fg
        )
    finally:
        conn.close()


def _rm_kg_for_receiving(conn, receiving_id: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(netto),0) AS rm_kg FROM receiving_item WHERE header_id=?",
        (receiving_id,),
    ).fetchone()
    return float(row["rm_kg"] or 0)


@production_bp.route("/detail/<int:receiving_id>", methods=["GET"])
def production_detail(receiving_id):
    conn = get_conn()
    try:
        rh = conn.execute(
            "SELECT * FROM receiving_header WHERE id=?",
            (receiving_id,),
        ).fetchone()
        if not rh:
            return "Receiving tidak ditemukan", 404

        rm_kg = _rm_kg_for_receiving(conn, receiving_id)

        prod = conn.execute(
            "SELECT * FROM production WHERE receiving_id=?",
            (receiving_id,),
        ).fetchone()

        packing = []
        if prod:
            packing = conn.execute("""
                SELECT *
                FROM production_packing
                WHERE production_id=?
                ORDER BY id ASC
            """, (prod["id"],)).fetchall()
            packing = [dict(r) for r in packing]

        return render_template(
            "production/detail.html",
            receiving=dict(rh),
            rm_kg=rm_kg,
            production=dict(prod) if prod else None,
            packing=packing,
        )
    finally:
        conn.close()


@production_bp.route("/save/<int:receiving_id>", methods=["POST"])
def production_save(receiving_id):
    data = request.get_json(force=True) or {}

    hl_kg = float(data.get("hl_kg") or 0)
    pd_kg = float(data.get("pd_kg") or 0)
    note = (data.get("note") or "").strip() or None
    packing_rows = data.get("packing_rows") or []

    conn = get_conn()
    try:
        # pastikan receiving ada
        rh = conn.execute("SELECT id FROM receiving_header WHERE id=?", (receiving_id,)).fetchone()
        if not rh:
            return jsonify(ok=False, msg="Receiving tidak ditemukan"), 404

        # upsert production (1 receiving = 1 production)
        prod = conn.execute("SELECT id FROM production WHERE receiving_id=?", (receiving_id,)).fetchone()
        if not prod:
            conn.execute("""
                INSERT INTO production (receiving_id, hl_kg, pd_kg, note, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (receiving_id, hl_kg, pd_kg, note))
            prod_id = conn.execute("SELECT id FROM production WHERE receiving_id=?", (receiving_id,)).fetchone()["id"]
        else:
            prod_id = prod["id"]
            conn.execute("""
                UPDATE production
                SET hl_kg=?, pd_kg=?, note=?, updated_at=datetime('now')
                WHERE id=?
            """, (hl_kg, pd_kg, note, prod_id))

        # replace packing rows
        conn.execute("DELETE FROM production_packing WHERE production_id=?", (prod_id,))

        ins_sql = """
            INSERT INTO production_packing (
              production_id, rm_code, out_size, product_code,
              kupas_kg, mc_qty, pack_qty, packs_per_mc, pack_weight_g, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        for r in packing_rows:
            rm_code = (r.get("rm_code") or "").strip()
            out_size = (r.get("out_size") or "").strip()
            product_code = (r.get("product_code") or "").strip()

            if not rm_code and not out_size and not product_code:
                continue

            kupas_kg = float(r.get("kupas_kg") or 0)
            mc_qty = float(r.get("mc_qty") or 0)
            pack_qty = float(r.get("pack_qty") or 0)
            packs_per_mc = int(r.get("packs_per_mc") or 0) or 8
            pack_weight_g = int(r.get("pack_weight_g") or 0) or 800
            row_note = (r.get("note") or "").strip() or None

            conn.execute(ins_sql, (
                prod_id, rm_code, out_size, product_code,
                kupas_kg, mc_qty, pack_qty, packs_per_mc, pack_weight_g, row_note
            ))

        conn.commit()
        return jsonify(ok=True, production_id=prod_id)
    except Exception as e:
        conn.rollback()
        return jsonify(ok=False, msg=str(e)), 500
    finally:
        conn.close()