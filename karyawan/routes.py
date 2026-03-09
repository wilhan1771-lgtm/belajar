from flask import Blueprint, render_template, request, redirect, url_for, json ,jsonify
from helpers.db import get_conn
from datetime import date


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

@karyawan_bp.route("/borongan", methods=["GET"])
def borongan_index():
    conn = get_conn()
    setting_rows = conn.execute("""
        SELECT kode, nilai
        FROM payroll_settings
        WHERE aktif = 1
    """).fetchall()

    setting_map = {r["kode"]: float(r["nilai"] or 0) for r in setting_rows}
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
        rate_map_json=json.dumps(rate_map),setting_map_json=json.dumps(setting_map),
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
    try:
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
        setting_rows = conn.execute("""
            SELECT kode, nilai
            FROM payroll_settings
            WHERE aktif = 1
        """).fetchall()

        setting_map = {r["kode"]: float(r["nilai"] or 0) for r in setting_rows}
        insert_rows = []
        payroll_rows = []

        for row in rows:
            no_id = str(row.get("no_id", "")).strip()
            if not no_id:
                continue

            if no_id not in emp_map:
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
            hadir = int(row.get("hadir", 0) or 0)
            hari_libur = int(row.get("hari_libur", 0) or 0)
            lembur = int(row.get("lembur", 0) or 0)
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
            insentif_kehadiran = setting_map.get("KEHADIRAN", 0) if hadir == 1 else 0
            insentif_libur = setting_map.get("LIBUR", 0) if hari_libur == 1 else 0
            insentif_lembur = setting_map.get("LEMBUR", 0) if lembur == 1 else 0

            total_insentif = insentif_kehadiran + insentif_libur + insentif_lembur
            grand_total = total_upah + total_insentif
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
                total_kg, total_upah,
                hadir, hari_libur, lembur,
                insentif_kehadiran, insentif_libur, insentif_lembur,
                total_insentif, grand_total
            ))
            payroll_rows.append((
                tanggal,
                no_id,
                total_kg,
                total_upah,
                insentif_kehadiran,
                insentif_lembur,
                insentif_libur,
                0,
                grand_total,
                "HADIR" if hadir == 1 else "ALPHA",
                0
            ))

        if not insert_rows:
            return jsonify({"ok": False, "message": "Tidak ada data yang diisi"}), 400

        submitted_no_ids = sorted(set(r[1] for r in insert_rows))
        placeholders = ",".join("?" for _ in submitted_no_ids)

        conn.execute("BEGIN IMMEDIATE")

        conn.execute("""
            DELETE FROM borongan_logs
            WHERE tanggal = ?
        """, (tanggal,))
        conn.execute("""
        DELETE FROM payroll_daily
        WHERE tanggal = ?
        """, (tanggal,))
        print("insert_rows sample:", insert_rows[0] if insert_rows else None)
        print("payroll_rows sample:", payroll_rows[0] if payroll_rows else None)
        print("len insert_rows[0] =", len(insert_rows[0]) if insert_rows else 0)
        print("len payroll_rows[0] =", len(payroll_rows[0]) if payroll_rows else 0)
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
                total_kg, total_upah,
                hadir, hari_libur, lembur,
                insentif_kehadiran, insentif_libur, insentif_lembur,
                total_insentif, grand_total
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
                ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?
            )
        """, insert_rows)
        conn.executemany("""
            INSERT INTO payroll_daily (
                tanggal, no_id, total_kg, total_upah_borongan,
                uang_hadir, uang_lembur, bonus, potongan,
                total_bayar, status_hadir, total_jam_kerja
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, payroll_rows)
        conn.commit()

        return jsonify({
            "ok": True,
            "message": f"Berhasil simpan {len(insert_rows)} baris borongan"
        })

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"ok": False, "message": f"Gagal simpan: {str(e)}"}), 500
    finally:
        conn.close()

@karyawan_bp.route("/employees")
def employees_list():
    conn = get_conn()

    q = request.args.get("q", "").strip()
    bagian = request.args.get("bagian", "").strip()
    jabatan = request.args.get("jabatan", "").strip()
    sort = request.args.get("sort", "no_id")

    order_map = {
        "no_id": "CAST(no_id AS INTEGER), no_id",
        "nama": "nama",
        "bagian": "bagian, nama",
        "jabatan": "jabatan, nama"
    }
    order_by = order_map.get(sort, "CAST(no_id AS INTEGER), no_id")

    sql = "SELECT * FROM employees WHERE 1=1"
    params = []

    if q:
        sql += " AND (no_id LIKE ? OR nama LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])

    if bagian:
        sql += " AND bagian = ?"
        params.append(bagian)

    if jabatan:
        sql += " AND jabatan = ?"
        params.append(jabatan)

    sql += f" ORDER BY {order_by}"

    employees = conn.execute(sql, params).fetchall()
    conn.close()

    return render_template("karyawan/employees.html", employees=employees)

@karyawan_bp.route("/employees/add", methods=["GET", "POST"])
def employee_add():
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
        conn.close()
        return redirect(url_for("karyawan.employees_list"))

    conn.close()
    return render_template("karyawan/employee_form.html", employee=None)

@karyawan_bp.route("/employees/<int:id>/edit", methods=["GET", "POST"])
def employee_edit(id):
    conn = get_conn()

    if request.method == "POST":
        no_id = request.form["no_id"]
        nama = request.form["nama"]
        bagian = request.form.get("bagian")
        jabatan = request.form.get("jabatan")
        fingerprint_id = request.form.get("fingerprint_id")

        conn.execute("""
            UPDATE employees
            SET no_id = ?, nama = ?, bagian = ?, jabatan = ?, fingerprint_id = ?
            WHERE id = ?
        """, (no_id, nama, bagian, jabatan, fingerprint_id, id))
        conn.commit()
        conn.close()
        return redirect(url_for("karyawan.employees_list"))

    employee = conn.execute("SELECT * FROM employees WHERE id = ?", (id,)).fetchone()
    conn.close()

    return render_template("karyawan/employee_form.html", employee=employee)

@karyawan_bp.route("/employees/<int:id>/delete", methods=["POST"])
def employee_delete(id):
    conn = get_conn()
    conn.execute("DELETE FROM employees WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for("karyawan.employees_list"))

@karyawan_bp.route("/api/employee/<no_id>")
def api_employee(no_id):
    conn = get_conn()
    try:
        emp = conn.execute("""
            SELECT no_id, nama
            FROM employees
            WHERE TRIM(no_id) = TRIM(?)
            LIMIT 1
        """, (no_id,)).fetchone()

        if not emp:
            return jsonify({
                "ok": False,
                "message": f"No ID {no_id} tidak ditemukan"
            }), 404

        return jsonify({
            "ok": True,
            "no_id": emp["no_id"],
            "nama": emp["nama"]
        })
    finally:
        conn.close()

@karyawan_bp.route("/borongan/rekap")
def borongan_rekap():
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    sort = request.args.get("sort", "no_id")
    mode = request.args.get("mode", "rekap")
    no_id = request.args.get("no_id", "").strip()

    if not date_from:
        date_from = date.today().isoformat()

    if not date_to:
        date_to = date_from

    conn = get_conn()

    if mode == "detail":
        order_map = {
            "no_id": "CAST(no_id AS INTEGER), no_id, tanggal",
            "nama": "nama, tanggal",
            "upah": "total_upah DESC, tanggal",
            "kg": "total_kg DESC, tanggal",
            "tanggal": "tanggal, CAST(no_id AS INTEGER), no_id"
        }
        order_by = order_map.get(sort, "CAST(no_id AS INTEGER), no_id, tanggal")

        sql = f"""
            SELECT
                tanggal,
                no_id,
                nama,
                (kupas_xl_koin + kupas_l_koin + kupas_m_koin + kupas_s_koin) AS total_kupas,
                (belah_xl_koin + belah_l_koin + belah_m_koin + belah_s_koin) AS total_belah,
                (pk_l_kg + pk_s_kg) AS total_pk,
                total_kg,
                total_upah,
                hadir,
                lembur,
                hari_libur,
                total_insentif,
                grand_total
            FROM borongan_logs
            WHERE tanggal BETWEEN ? AND ?
        """
        params = [date_from, date_to]

        if no_id:
            sql += " AND no_id = ?"
            params.append(no_id)

        sql += f" ORDER BY {order_by}"

        rows = conn.execute(sql, params).fetchall()

        summary = {
            "total_kupas": sum((r["total_kupas"] or 0) for r in rows),
            "total_belah": sum((r["total_belah"] or 0) for r in rows),
            "total_pk": sum((r["total_pk"] or 0) for r in rows),
            "total_kg": sum((r["total_kg"] or 0) for r in rows),
            "total_upah": sum((r["total_upah"] or 0) for r in rows),
            "total_insentif": sum((r["total_insentif"] or 0) for r in rows),
            "total_grand": sum((r["grand_total"] or 0) for r in rows),
        }

    else:
        order_map = {
            "no_id": "CAST(no_id AS INTEGER), no_id",
            "nama": "nama",
            "upah": "sum_total_upah DESC",
            "kg": "sum_total_kg DESC"
        }
        order_by = order_map.get(sort, "CAST(no_id AS INTEGER), no_id")

        sql = f"""
            SELECT
                no_id,
                nama,
                SUM(kupas_xl_koin) AS kupas_xl,
                SUM(kupas_l_koin) AS kupas_l,
                SUM(kupas_m_koin) AS kupas_m,
                SUM(kupas_s_koin) AS kupas_s,
                SUM(belah_xl_koin) AS belah_xl,
                SUM(belah_l_koin) AS belah_l,
                SUM(belah_m_koin) AS belah_m,
                SUM(belah_s_koin) AS belah_s,
                SUM(pk_l_kg) AS pk_l,
                SUM(pk_s_kg) AS pk_s,
                SUM(kupas_xl_koin + kupas_l_koin + kupas_m_koin + kupas_s_koin) AS sum_total_kupas,
                SUM(belah_xl_koin + belah_l_koin + belah_m_koin + belah_s_koin) AS sum_total_belah,
                SUM(pk_l_kg + pk_s_kg) AS sum_total_pk,
                SUM(total_kg) AS sum_total_kg,
                SUM(total_upah) AS sum_total_upah,
                SUM(hadir) AS sum_hadir,
                SUM(lembur) AS sum_lembur,
                SUM(hari_libur) AS sum_libur,
                SUM(insentif_kehadiran) AS sum_insentif_kehadiran,
                SUM(insentif_libur) AS sum_insentif_libur,
                SUM(insentif_lembur) AS sum_insentif_lembur,
                SUM(total_insentif) AS sum_insentif,
                SUM(grand_total) AS sum_grand_total
            FROM borongan_logs
            WHERE tanggal BETWEEN ? AND ?
        """
        params = [date_from, date_to]

        if no_id:
            sql += " AND no_id = ?"
            params.append(no_id)

        sql += f"""
            GROUP BY no_id, nama
            ORDER BY {order_by}
        """

        rows = conn.execute(sql, params).fetchall()

        summary = {
            "total_kupas": sum((r["sum_total_kupas"] or 0) for r in rows),
            "total_belah": sum((r["sum_total_belah"] or 0) for r in rows),
            "total_pk": sum((r["sum_total_pk"] or 0) for r in rows),
            "total_kg": sum((r["sum_total_kg"] or 0) for r in rows),
            "total_upah": sum((r["sum_total_upah"] or 0) for r in rows),
            "total_insentif": sum((r["sum_insentif"] or 0) for r in rows),
            "total_grand": sum((r["sum_grand_total"] or 0) for r in rows),
        }

    conn.close()

    return render_template(
        "karyawan/rekap_borongan.html",
        rows=rows,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        mode=mode,
        no_id=no_id,
        summary=summary
    )

@karyawan_bp.route("/api/borongan/<tanggal>")
def api_borongan_tanggal(tanggal):
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT *
            FROM borongan_logs
            WHERE tanggal = ?
            ORDER BY CAST(no_id AS INTEGER), no_id
        """, (tanggal,)).fetchall()

        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()

@karyawan_bp.route("/borongan/delete/<tanggal>", methods=["DELETE"])
def borongan_delete_tanggal(tanggal):
    conn = get_conn()
    try:
        conn.execute("""
            DELETE FROM borongan_logs
            WHERE tanggal = ?
        """, (tanggal,))

        conn.execute("""
            DELETE FROM payroll_daily
            WHERE tanggal = ?
        """, (tanggal,))

        conn.commit()

        return jsonify({
            "ok": True,
            "message": f"Data tanggal {tanggal} berhasil dihapus"
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "message": str(e)
        }), 500

    finally:
        conn.close()