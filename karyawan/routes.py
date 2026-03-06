from flask import Blueprint, render_template, request, redirect, url_for, json ,jsonify
from helpers.db import get_conn



karyawan_bp = Blueprint("karyawan",__name__,url_prefix="/karyawan", template_folder="templates")

@karyawan_bp.route("/")
def karyawan_index():
    return render_template("karyawan/index.html")

@karyawan_bp.route("/absensi")
def absensi_index():
    return "Absensi Page"

@karyawan_bp.route("/tarif", methods=["GET", "POST"])
def tarif_index():
    conn = get_conn()

    if request.method == "POST":
        rate_id = request.form["rate_id"]
        harga = request.form["harga"]

        conn.execute("""
            UPDATE work_rates
            SET harga_per_kg = ?
            WHERE id = ?
        """, (harga, rate_id))

        conn.commit()

        return redirect(url_for("karyawan.tarif_index"))

    rates = conn.execute("""
        SELECT
            work_rates.id,
            work_types.nama as work,
            sizes.kode as size,
            work_rates.harga_per_kg
        FROM work_rates
        LEFT JOIN work_types ON work_rates.work_type_id = work_types.id
        LEFT JOIN sizes ON work_rates.size_id = sizes.id
        ORDER BY work_types.id, sizes.urutan
    """).fetchall()

    return render_template("karyawan/tarif.html", rates=rates)


@karyawan_bp.route("/employees", methods=["GET", "POST"])
def employees_list():
    conn = get_conn()

    if request.method == "POST":
        no_id = request.form["no_id"]
        nama = request.form["nama"]
        bagian = request.form.get("bagian")
        jabatan = request.form.get("jabatan")
        fingerprint_id = request.form.get("fingerprint_id")

        conn.execute("""
            INSERT INTO employees (no_id, nama, bagian, jabatan, fingerprint_id)
            VALUES (?, ?, ?, ?, ?)
        """, (no_id, nama, bagian, jabatan, fingerprint_id))
        conn.commit()
        return redirect(url_for("karyawan.employees_list"))

    employees = conn.execute("""
        SELECT * FROM employees
        ORDER BY CAST(no_id AS INTEGER), no_id
    """).fetchall()

    conn.close()
    return render_template("karyawan/employees.html", employees=employees)

@karyawan_bp.route("/borongan", methods=["GET"])
def borongan_index():
    conn = get_conn()

    rates = conn.execute("""
        SELECT
            wt.kode AS work_kode,
            s.kode AS size_kode,
            wr.harga_per_kg
        FROM work_rates wr
        JOIN work_types wt ON wt.id = wr.work_type_id
        JOIN sizes s ON s.id = wr.size_id
        WHERE wr.aktif = 1
        ORDER BY wt.kode, s.urutan
    """).fetchall()

    rate_map = {}
    for r in rates:
        key = f"{r['work_kode']}_{r['size_kode']}"
        rate_map[key] = float(r["harga_per_kg"] or 0)

    recent_summary = conn.execute("""
        SELECT
            tanggal,
            no_id,
            nama,
            total_kg,
            total_upah
        FROM borongan_logs
        ORDER BY tanggal DESC, CAST(no_id AS INTEGER), no_id
        LIMIT 30
    """).fetchall()

    conn.close()

    return render_template(
        "karyawan/borongan.html",
        rate_map_json=json.dumps(rate_map),
        recent_summary=recent_summary
    )
@karyawan_bp.route("/borongan/save", methods=["POST"])
def borongan_save():
    data = request.get_json(silent=True) or {}
    tanggal = (data.get("tanggal") or "").strip()
    rows = data.get("rows") or []

    if not tanggal:
        return jsonify({"ok": False, "message": "Tanggal wajib diisi"}), 400

    if not rows:
        return jsonify({"ok": False, "message": "Data kosong"}), 400

    conn = get_conn()

    emp_rows = conn.execute("""
        SELECT no_id, nama
        FROM employees
        WHERE status_aktif = 1
    """).fetchall()
    emp_map = {r["no_id"]: r["nama"] for r in emp_rows}

    rate_rows = conn.execute("""
        SELECT
            wt.kode AS work_kode,
            s.kode AS size_kode,
            wr.harga_per_kg
        FROM work_rates wr
        JOIN work_types wt ON wt.id = wr.work_type_id
        JOIN sizes s ON s.id = wr.size_id
        WHERE wr.aktif = 1
    """).fetchall()

    rate_map = {
        f"{r['work_kode']}_{r['size_kode']}": float(r["harga_per_kg"] or 0)
        for r in rate_rows
    }

    insert_rows = []

    for row in rows:
        no_id = str(row.get("no_id", "")).strip()
        if not no_id:
            continue

        if no_id not in emp_map:
            conn.close()
            return jsonify({
                "ok": False,
                "message": f"No ID {no_id} tidak ditemukan di master karyawan"
            }), 400

        nama = emp_map[no_id]

        kupas_xl_koin = float(row.get("kupas_xl", 0) or 0)
        kupas_l_koin  = float(row.get("kupas_l", 0) or 0)
        kupas_m_koin  = float(row.get("kupas_m", 0) or 0)
        kupas_s_koin  = float(row.get("kupas_s", 0) or 0)

        belah_xl_koin = float(row.get("belah_xl", 0) or 0)
        belah_l_koin  = float(row.get("belah_l", 0) or 0)
        belah_m_koin  = float(row.get("belah_m", 0) or 0)
        belah_s_koin  = float(row.get("belah_s", 0) or 0)

        pk_l_kg = float(row.get("pk_l", 0) or 0)
        pk_s_kg = float(row.get("pk_s", 0) or 0)

        qty_total = (
            kupas_xl_koin + kupas_l_koin + kupas_m_koin + kupas_s_koin +
            belah_xl_koin + belah_l_koin + belah_m_koin + belah_s_koin +
            pk_l_kg + pk_s_kg
        )

        if qty_total <= 0:
            continue

        kupas_xl_kg = kupas_xl_koin * 4
        kupas_l_kg  = kupas_l_koin * 4
        kupas_m_kg  = kupas_m_koin * 4
        kupas_s_kg  = kupas_s_koin * 4

        belah_xl_kg = belah_xl_koin * 5
        belah_l_kg  = belah_l_koin * 5
        belah_m_kg  = belah_m_koin * 5
        belah_s_kg  = belah_s_koin * 5

        pk_l_kg_final = pk_l_kg
        pk_s_kg_final = pk_s_kg

        rate_kupas_xl = rate_map.get("KUPAS_XL", 0)
        rate_kupas_l  = rate_map.get("KUPAS_L", 0)
        rate_kupas_m  = rate_map.get("KUPAS_M", 0)
        rate_kupas_s  = rate_map.get("KUPAS_S", 0)

        rate_belah_xl = rate_map.get("BELAH_XL", 0)
        rate_belah_l  = rate_map.get("BELAH_L", 0)
        rate_belah_m  = rate_map.get("BELAH_M", 0)
        rate_belah_s  = rate_map.get("BELAH_S", 0)

        rate_pk_l = rate_map.get("PK_L", 0)
        rate_pk_s = rate_map.get("PK_S", 0)

        subtotal_kupas_xl = kupas_xl_kg * rate_kupas_xl
        subtotal_kupas_l  = kupas_l_kg * rate_kupas_l
        subtotal_kupas_m  = kupas_m_kg * rate_kupas_m
        subtotal_kupas_s  = kupas_s_kg * rate_kupas_s

        subtotal_belah_xl = belah_xl_kg * rate_belah_xl
        subtotal_belah_l  = belah_l_kg * rate_belah_l
        subtotal_belah_m  = belah_m_kg * rate_belah_m
        subtotal_belah_s  = belah_s_kg * rate_belah_s

        subtotal_pk_l = pk_l_kg_final * rate_pk_l
        subtotal_pk_s = pk_s_kg_final * rate_pk_s

        total_kg = (
            kupas_xl_kg + kupas_l_kg + kupas_m_kg + kupas_s_kg +
            belah_xl_kg + belah_l_kg + belah_m_kg + belah_s_kg +
            pk_l_kg_final + pk_s_kg_final
        )

        total_upah = (
            subtotal_kupas_xl + subtotal_kupas_l + subtotal_kupas_m + subtotal_kupas_s +
            subtotal_belah_xl + subtotal_belah_l + subtotal_belah_m + subtotal_belah_s +
            subtotal_pk_l + subtotal_pk_s
        )

        insert_rows.append((
            tanggal, no_id, nama,
            kupas_xl_koin, kupas_l_koin, kupas_m_koin, kupas_s_koin,
            belah_xl_koin, belah_l_koin, belah_m_koin, belah_s_koin,
            pk_l_kg, pk_s_kg,
            kupas_xl_kg, kupas_l_kg, kupas_m_kg, kupas_s_kg,
            belah_xl_kg, belah_l_kg, belah_m_kg, belah_s_kg,
            pk_l_kg_final, pk_s_kg_final,
            rate_kupas_xl, rate_kupas_l, rate_kupas_m, rate_kupas_s,
            rate_belah_xl, rate_belah_l, rate_belah_m, rate_belah_s,
            rate_pk_l, rate_pk_s,
            subtotal_kupas_xl, subtotal_kupas_l, subtotal_kupas_m, subtotal_kupas_s,
            subtotal_belah_xl, subtotal_belah_l, subtotal_belah_m, subtotal_belah_s,
            subtotal_pk_l, subtotal_pk_s,
            total_kg, total_upah
        ))

    if not insert_rows:
        conn.close()
        return jsonify({"ok": False, "message": "Tidak ada data yang diisi"}), 400

    submitted_no_ids = [r[1] for r in insert_rows]
    placeholders = ",".join("?" for _ in submitted_no_ids)

    conn.execute("BEGIN")

    conn.execute(f"""
        DELETE FROM borongan_logs
        WHERE tanggal = ?
          AND no_id IN ({placeholders})
    """, [tanggal] + submitted_no_ids)

    conn.executemany("""
        INSERT INTO borongan_logs (
            tanggal, no_id, nama,
            kupas_xl_koin, kupas_l_koin, kupas_m_koin, kupas_s_koin,
            belah_xl_koin, belah_l_koin, belah_m_koin, belah_s_koin,
            pk_l_kg, pk_s_kg,
            kupas_xl_kg, kupas_l_kg, kupas_m_kg, kupas_s_kg,
            belah_xl_kg, belah_l_kg, belah_m_kg, belah_s_kg,
            pk_l_kg_final, pk_s_kg_final,
            rate_kupas_xl, rate_kupas_l, rate_kupas_m, rate_kupas_s,
            rate_belah_xl, rate_belah_l, rate_belah_m, rate_belah_s,
            rate_pk_l, rate_pk_s,
            subtotal_kupas_xl, subtotal_kupas_l, subtotal_kupas_m, subtotal_kupas_s,
            subtotal_belah_xl, subtotal_belah_l, subtotal_belah_m, subtotal_belah_s,
            subtotal_pk_l, subtotal_pk_s,
            total_kg, total_upah
        )
        VALUES (
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?
        )
    """, insert_rows)

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "message": f"Berhasil simpan {len(insert_rows)} baris borongan"
    })

@karyawan_bp.route("/api/employee/<no_id>")
def api_employee(no_id):
    conn = get_conn()
    emp = conn.execute("""
        SELECT no_id, nama
        FROM employees
        WHERE no_id = ?
    """, (no_id.strip(),)).fetchone()
    conn.close()

    if not emp:
        return jsonify({"ok": False, "message": "Karyawan tidak ditemukan"}), 404

    return jsonify({
        "ok": True,
        "no_id": emp["no_id"],
        "nama": emp["nama"]
    })