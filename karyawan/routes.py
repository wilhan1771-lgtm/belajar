from flask import Blueprint, render_template, request, redirect, url_for, json ,jsonify
from helpers.db import get_conn
from datetime import date
from helpers.auth import login_required, role_required
from absensi.rules import hitung_gaji_harian_row

karyawan_bp = Blueprint("karyawan",__name__,url_prefix="/karyawan", template_folder="templates")

@karyawan_bp.route("/")
def karyawan_index():
    return render_template("karyawan/index.html")

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
@login_required
@role_required("admin","absensi")
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
# letakkan di atas (di bawah import)

def clean_value(val):
    if val is None:
        return ""
    val = str(val).strip()
    if val.lower() == "none":
        return ""
    return val

@karyawan_bp.route("/employees/add", methods=["GET", "POST"])
def employee_add():
    error = None

    if request.method == "POST":
        no_id = request.form.get("no_id", "").strip()
        nama = request.form.get("nama", "").strip()
        bagian = request.form.get("bagian", "").strip()
        jabatan = request.form.get("jabatan", "").strip()
        status_aktif = request.form.get("status_aktif", "1").strip()
        tanggal_masuk = request.form.get("tanggal_masuk", "").strip()
        fingerprint_id = clean_value(request.form.get("fingerprint_id"))
        no_hp = request.form.get("no_hp", "").strip()
        catatan = request.form.get("catatan", "").strip()
        tipe_gaji = request.form.get("tipe_gaji", "").strip()
        area_kerja = request.form.get("area_kerja", "").strip()
        shift_default = request.form.get("shift_default", "").strip()
        gaji_harian = request.form.get("gaji_harian")
        gaji_harian = int(gaji_harian) if gaji_harian else None

        with get_conn() as conn:
            # cek no_id dobel
            cek_no_id = conn.execute("""
                SELECT id FROM employees
                WHERE no_id = ?
                LIMIT 1
            """, (no_id,)).fetchone()

            if cek_no_id:
                error = f"No ID {no_id} sudah dipakai."
                return render_template(
                    "karyawan/employee_form.html",
                    employee=None,
                    error=error
                )

            # cek fingerprint dobel, abaikan kalau kosong
            if fingerprint_id:
                cek_fp = conn.execute("""
                    SELECT id FROM employees
                    WHERE fingerprint_id = ?
                    LIMIT 1
                """, (fingerprint_id,)).fetchone()

                if cek_fp:
                    error = f"Fingerprint ID {fingerprint_id} sudah dipakai."
                    return render_template(
                        "karyawan/employee_form.html",
                        employee=None,
                        error=error
                    )

            conn.execute("""
                INSERT INTO employees (
                    no_id, nama, bagian, jabatan,
                    status_aktif, tanggal_masuk,
                    fingerprint_id, no_hp, catatan,
                    created_at, updated_at,
                    tipe_gaji, area_kerja, shift_default, gaji_harian
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, ?, ?)
            """, (
                no_id,
                nama,
                bagian or None,
                jabatan or None,
                int(status_aktif) if status_aktif else 1,
                tanggal_masuk or None,
                fingerprint_id or None,
                no_hp or None,
                catatan or None,
                tipe_gaji or None,
                area_kerja or None,
                shift_default or None,
                gaji_harian
            ))
        conn.commit()

        return redirect(url_for("karyawan.employees_list"))

    return render_template("karyawan/employee_form.html", employee=None, error=error)

@karyawan_bp.route("/employees/<int:id>/edit", methods=["GET", "POST"])
def employee_edit(id):
    conn = get_conn()

    if request.method == "POST":
        no_id = request.form.get("no_id", "").strip()
        nama = request.form.get("nama", "").strip()
        bagian = request.form.get("bagian", "").strip()
        jabatan = request.form.get("jabatan", "").strip()
        status_aktif = request.form.get("status_aktif", "1").strip()
        tanggal_masuk = request.form.get("tanggal_masuk", "").strip()
        fingerprint_id = clean_value(request.form.get("fingerprint_id"))
        no_hp = request.form.get("no_hp", "").strip()
        catatan = request.form.get("catatan", "").strip()
        tipe_gaji = request.form.get("tipe_gaji", "").strip()
        area_kerja = request.form.get("area_kerja", "").strip()
        shift_default = request.form.get("shift_default", "").strip()
        gaji_harian = request.form.get("gaji_harian")
        gaji_harian = int(gaji_harian) if gaji_harian else None

        # cek no_id dobel selain dirinya sendiri
        cek_no_id = conn.execute("""
            SELECT id FROM employees
            WHERE no_id = ?
              AND id != ?
            LIMIT 1
        """, (no_id, id)).fetchone()

        if cek_no_id:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id = ?",
                (id,)
            ).fetchone()
            conn.close()
            return render_template(
                "karyawan/employee_form.html",
                employee=employee,
                error=f"No ID {no_id} sudah dipakai."
            )

        # cek fingerprint dobel selain dirinya sendiri
        if fingerprint_id:
            cek_fp = conn.execute("""
                SELECT id FROM employees
                WHERE fingerprint_id = ?
                  AND id != ?
                LIMIT 1
            """, (fingerprint_id, id)).fetchone()

            if cek_fp:
                employee = conn.execute(
                    "SELECT * FROM employees WHERE id = ?",
                    (id,)
                ).fetchone()
                conn.close()
                return render_template(
                    "karyawan/employee_form.html",
                    employee=employee,
                    error=f"Fingerprint ID {fingerprint_id} sudah dipakai."
                )

        conn.execute("""
            UPDATE employees
            SET
                no_id = ?,
                nama = ?,
                bagian = ?,
                jabatan = ?,
                status_aktif = ?,
                tanggal_masuk = ?,
                fingerprint_id = ?,
                no_hp = ?,
                catatan = ?,
                updated_at = CURRENT_TIMESTAMP,
                tipe_gaji = ?,
                area_kerja = ?,
                shift_default = ?,
                gaji_harian = ?
            WHERE id = ?
        """, (
            no_id,
            nama,
            bagian or None,
            jabatan or None,
            int(status_aktif) if status_aktif else 1,
            tanggal_masuk or None,
            fingerprint_id or None,
            no_hp or None,
            catatan or None,
            tipe_gaji or None,
            area_kerja or None,
            shift_default or None,
            gaji_harian or None,
            id
        ))

        conn.commit()
        conn.close()
        return redirect(url_for("karyawan.employees_list"))

    employee = conn.execute(
        "SELECT * FROM employees WHERE id = ?",
        (id,)
    ).fetchone()
    conn.close()

    return render_template("karyawan/employee_form.html", employee=employee, error=None)

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

@karyawan_bp.route("/absensi")
def absensi_index():
    from datetime import date
    from absensi.rules import hitung_gaji_harian_row

    conn = get_conn()

    tanggal = request.args.get("tanggal")
    status = request.args.get("status")
    bagian = request.args.get("bagian")

    if not tanggal:
        tanggal = date.today().isoformat()

    rows = conn.execute("""
        SELECT
            e.no_id,
            e.nama,
            e.bagian,
            e.shift_default AS shift_code,
            COALESCE(e.gaji_harian, 100000) AS gaji_harian,
            a.id AS attendance_id,
            a.work_date,
            a.period1_in,
            a.period1_out,
            a.period2_in,
            a.period2_out,
            a.period3_in,
            a.period3_out,
            a.actual_hours,
            a.late_minutes,
            a.early_leave_minutes,
            a.overtime_hours,
            a.status_hadir,
            COALESCE(a.insentif_malam, 0) AS insentif_malam,
            COALESCE(a.insentif_hari_besar, 0) AS insentif_hari_besar,
            COALESCE(a.total_insentif, 0) AS total_insentif
        FROM employees e
        LEFT JOIN attendance_daily a
            ON e.id = a.employee_id
           AND a.work_date = ?
        WHERE e.status_aktif = 1
        ORDER BY CAST(e.no_id AS INTEGER)
    """, (tanggal,)).fetchall()

    rows = [dict(r) for r in rows]

    # default status
    for r in rows:
        if not r["status_hadir"]:
            r["status_hadir"] = "tidak_hadir"

    # filter status
    if status:
        rows = [r for r in rows if r["status_hadir"] == status]

    # filter bagian
    if bagian:
        rows = [r for r in rows if r["bagian"] == bagian]

    # hitung gaji runtime
    for r in rows:
        hasil = hitung_gaji_harian_row(r)

        r["work_type"] = hasil["work_type"]
        r["gaji_pokok"] = hasil["gaji_pokok"]
        r["gaji_lembur"] = hasil["gaji_lembur"]
        r["insentif"] = hasil["insentif"]
        r["potongan_telat"] = hasil["potongan_telat"]
        r["gaji_final"] = hasil["gaji_final"]
        r["note"] = hasil["note"]
        r["is_valid"] = hasil["is_valid"]

        # biar template lama tetap jalan
        r["gaji_draft"] = hasil["gaji_final"]

    total = {
        "gaji": sum(int(r.get("gaji_final") or 0) for r in rows),
        "gaji_pokok": sum(int(r.get("gaji_pokok") or 0) for r in rows),
        "lembur": sum(int(r.get("gaji_lembur") or 0) for r in rows),
        "insentif": sum(int(r.get("insentif") or 0) for r in rows),
    }

    summary = {
        "hadir": sum(
            0.5 if r.get("work_type") == "half"
            else 1 if r["status_hadir"] == "hadir"
            else 0
            for r in rows
        ),
        "hadir_full": sum(
            1 for r in rows
            if r["status_hadir"] == "hadir"
            and r.get("work_type") == "full"
        ),
        "hadir_half": sum(
            1 for r in rows
            if r["status_hadir"] == "hadir"
            and r.get("work_type") == "half"
        ),
        "tidak_hadir": sum(
            1 for r in rows
            if r["status_hadir"] == "tidak_hadir"
        ),
        "borongan_masuk": sum(
            1 for r in rows
            if r["status_hadir"] == "hadir"
            and r["bagian"] == "Borongan"
        ),
        "borongan_beku": sum(
            1 for r in rows
            if r["status_hadir"] == "tidak_hadir"
            and r["bagian"] == "Borongan"
        ),
    }

    tidak_hadir = [
        r for r in rows
        if r["status_hadir"] == "tidak_hadir"
    ]

    conn.close()

    return render_template(
        "karyawan/absensi.html",
        rows=rows,
        tanggal=tanggal,
        summary=summary,
        tidak_hadir=tidak_hadir,
        total=total
    )
@karyawan_bp.route("/rekap-mingguan")
def rekap_mingguan():
    from datetime import date, timedelta

    conn = get_conn()

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    if not end_date:
        end_date = date.today().isoformat()

    if not start_date:
        start_date = (date.fromisoformat(end_date) - timedelta(days=6)).isoformat()

    rows = conn.execute("""
        SELECT
            e.no_id,
            e.nama,
            e.bagian,
            SUM(CASE WHEN a.status_hadir = 'hadir' THEN 1 ELSE 0 END) as hadir_count,
            SUM(CASE WHEN a.status_hadir = 'tidak_hadir' OR a.status_hadir IS NULL THEN 1 ELSE 0 END) as tidak_hadir_count,
            SUM(COALESCE(a.actual_hours, 0)) as total_hours,
            SUM(COALESCE(a.late_minutes, 0)) as total_late,
            SUM(COALESCE(a.overtime_hours, 0)) as total_overtime
        FROM employees e
        LEFT JOIN attendance_daily a
            ON e.id = a.employee_id
            AND a.work_date BETWEEN ? AND ?
        WHERE e.status_aktif = 1
        GROUP BY e.id, e.no_id, e.nama, e.bagian
        ORDER BY CAST(e.no_id AS INTEGER)
    """, (start_date, end_date)).fetchall()

    rows = [dict(r) for r in rows]

    summary = {
        "total_hadir": sum(r["hadir_count"] or 0 for r in rows),
        "total_tidak_hadir": sum(r["tidak_hadir_count"] or 0 for r in rows),
        "total_telat": sum(r["total_late"] or 0 for r in rows),
        "total_lembur": sum(r["total_overtime"] or 0 for r in rows),
    }

    conn.close()

    return render_template(
        "karyawan/rekap_mingguan.html",
        rows=rows,
        start_date=start_date,
        end_date=end_date,
        summary=summary
    )

def cek_tinggal_di_mes(conn, employee_id, work_date):
    row = conn.execute("""
        SELECT id
        FROM employee_mes_history
        WHERE employee_id = ?
          AND tanggal_mulai <= ?
          AND (
                tanggal_selesai IS NULL
                OR tanggal_selesai = ''
                OR tanggal_selesai > ?
              )
        LIMIT 1
    """, (employee_id, work_date, work_date)).fetchone()

    return row is not None

@karyawan_bp.route("/payroll", methods=["GET"])

def payroll_index():
    tanggal_awal = request.args.get("tanggal_awal", "")
    tanggal_akhir = request.args.get("tanggal_akhir", "")
    bagian = request.args.get("bagian", "").strip()

    rows = []
    summary = {
        "total_karyawan": 0,
        "total_upah_borongan": 0,
        "total_gaji_pokok": 0,
        "total_lembur": 0,
        "total_insentif": 0,
        "total_potongan": 0,
        "total_potongan_barang": 0,
        "total_gaji": 0,
    }

    if tanggal_awal and tanggal_akhir:
        conn = get_conn()

        query = """
            SELECT
                e.id AS employee_id,
                e.no_id,
                e.nama,
                e.bagian,
                e.shift_default AS shift_code,
                COALESCE(e.gaji_harian, 100000) AS gaji_harian,
                COALESCE(e.tinggal_di_mes, 0) AS tinggal_di_mes,

                a.work_date,
                a.period1_in,
                a.period1_out,
                a.period2_in,
                a.period2_out,
                a.period3_in,
                a.period3_out,
                a.actual_hours,
                a.late_minutes,
                a.early_leave_minutes,
                a.overtime_hours,
                a.status_hadir,

                COALESCE(b.total_upah, 0) AS total_upah_borongan

            FROM employees e
            LEFT JOIN attendance_daily a
                ON e.id = a.employee_id
               AND a.work_date BETWEEN ? AND ?
            LEFT JOIN (
                SELECT
                     no_id,
                     tanggal,
                     SUM(total_upah) AS total_upah
              FROM borongan_logs
             GROUP BY no_id, tanggal
            ) b
    ON b.no_id = e.no_id
    AND b.tanggal = a.work_date
            WHERE e.status_aktif = 1
        """

        params = [tanggal_awal, tanggal_akhir]

        if bagian and bagian.lower() != "semua":
            query += " AND LOWER(TRIM(e.bagian)) = ? "
            params.append(bagian.lower())

        query += " ORDER BY CAST(e.no_id AS INTEGER), a.work_date "

        data = conn.execute(query, params).fetchall()
        data = [dict(r) for r in data]

        grouped = {}

        for r in data:
            emp_id = r["employee_id"]

            if emp_id not in grouped:
                grouped[emp_id] = {
                    "employee_id": emp_id,
                    "no_id": r["no_id"],
                    "nama": r["nama"],
                    "bagian": r["bagian"],
                    "hari_masuk": 0,
                    "total_upah_borongan": 0,
                    "total_gaji_pokok": 0,
                    "total_lembur": 0,
                    "total_insentif": 0,
                    "total_potongan": 0,
                    "total_potongan_barang": 0,  # ✅ tambah ini
                    "total_gaji": 0,
                }

            # hitung absensi runtime
            # inject status mes dari history (per hari)
            if r.get("work_date"):
                r["tinggal_di_mes"] = 1 if cek_tinggal_di_mes(
                    conn,
                    r["employee_id"],
                    r["work_date"]
                ) else 0
            else:
                r["tinggal_di_mes"] = 0

            # hitung absensi runtime
            hasil = hitung_gaji_harian_row(r)

            if hasil["work_type"] == "full":
                grouped[emp_id]["hari_masuk"] += 1

            grouped[emp_id]["total_upah_borongan"] += int(round(r.get("total_upah_borongan") or 0))
            grouped[emp_id]["total_gaji_pokok"] += int(round(hasil["gaji_pokok"] or 0))
            grouped[emp_id]["total_lembur"] += int(round(hasil["gaji_lembur"] or 0))
            grouped[emp_id]["total_insentif"] += int(round(hasil["insentif"] or 0))

            grouped[emp_id]["total_potongan"] += (
                    int(round(hasil.get("potongan_telat", 0) or 0))
                    + int(round(hasil.get("potongan_mes", 0) or 0))

            )

            grouped[emp_id]["total_gaji"] += (
                    int(round(r.get("total_upah_borongan") or 0))
                    + int(round(hasil["gaji_pokok"] or 0))
                    + int(round(hasil["gaji_lembur"] or 0))
                    + int(round(hasil["insentif"] or 0))
                    - int(round(hasil.get("potongan_telat", 0) or 0))
                    - int(round(hasil.get("potongan_mes", 0) or 0))
            )
        # =========================
        # POTONGAN BARANG PER PERIODE
        # hitung sekali per karyawan, bukan per hari
        # =========================
        for emp_id, g in grouped.items():
            potongan_barang = conn.execute("""
                SELECT
                    COALESCE(SUM(
                        CASE
                            WHEN metode_potong = 'sekali' THEN total
                            WHEN metode_potong = 'cicilan' THEN
                                CASE
                                    WHEN sisa < cicilan_per_minggu THEN sisa
                                    ELSE cicilan_per_minggu
                                END
                            ELSE 0
                        END
                    ), 0) AS total
                FROM employee_items
                WHERE employee_id = ?
                  AND status = 'aktif'
                  AND tanggal BETWEEN ? AND ?
            """, (
                emp_id,
                tanggal_awal,
                tanggal_akhir
            )).fetchone()["total"]

            potongan_barang = int(potongan_barang or 0)

            g["total_potongan_barang"] = potongan_barang
            g["total_potongan"] += potongan_barang
            g["total_gaji"] -= potongan_barang
        rows = list(grouped.values())
        bagian_order = {
            "borongan": 1,
            "produksi": 2,
            "beku": 3,
            "coldroom": 4,
            "kebersihan": 5,
            "malam": 6,
        }

        rows.sort(
            key=lambda x: (
                bagian_order.get((x["bagian"] or "").strip().lower(), 99),
                int(x["no_id"]) if str(x["no_id"]).isdigit() else 999999
            )
        )

        summary["total_karyawan"] = len(rows)
        summary["total_upah_borongan"] = sum(r["total_upah_borongan"] for r in rows)
        summary["total_gaji_pokok"] = sum(r["total_gaji_pokok"] for r in rows)
        summary["total_lembur"] = sum(r["total_lembur"] for r in rows)
        summary["total_insentif"] = sum(r["total_insentif"] for r in rows)
        summary["total_potongan"] = sum(r["total_potongan"] for r in rows)
        summary["total_gaji"] = sum(r["total_gaji"] for r in rows)

        conn.close()

    return render_template(
        "karyawan/payroll.html",
        rows=rows,
        tanggal_awal=tanggal_awal,
        tanggal_akhir=tanggal_akhir,
        bagian=bagian,
        summary=summary
    )

@karyawan_bp.route("/absensi/<int:id>/edit", methods=["GET", "POST"])
def absensi_edit(id):
    conn = get_conn()

    if request.method == "POST":
        def fix_time(t):
            if t and len(t) == 5:  # format HH:MM
                return t + ":00"
            return t

        period1_in = fix_time(request.form.get("period1_in"))
        period1_out = fix_time(request.form.get("period1_out"))
        period2_in = fix_time(request.form.get("period2_in"))
        period2_out = fix_time(request.form.get("period2_out"))
        period3_in = fix_time(request.form.get("period3_in"))
        period3_out = fix_time(request.form.get("period3_out"))
        status_hadir = request.form.get("status_hadir") or "tidak_hadir"

        conn.execute("""
            UPDATE attendance_daily
            SET
                period1_in = ?,
                period1_out = ?,
                period2_in = ?,
                period2_out = ?,
                period3_in = ?,
                period3_out = ?,
                status_hadir = ?
            WHERE id = ?
        """, (
            period1_in,
            period1_out,
            period2_in,
            period2_out,
            period3_in,
            period3_out,
            status_hadir,
            id
        ))
        conn.commit()
        conn.close()
        next_url = request.form.get("next")

        if next_url:
            return redirect(next_url)

        return redirect(url_for("karyawan.absensi_index"))

    row = conn.execute("""
        SELECT *
        FROM attendance_daily
        WHERE id = ?
    """, (id,)).fetchone()

    conn.close()

    if not row:
        return redirect(url_for("karyawan.absensi_index"))

    return render_template("karyawan/absensi_edit.html", row=row)
def fix_time(t):
    if not t:
        return None
    if len(t) == 5:
        return t + ":00"
    return t


@karyawan_bp.route("/absensi/input-manual", methods=["GET", "POST"])
def absensi_input_manual():
    conn = get_conn()

    no_id = request.args.get("no_id")
    tanggal = request.args.get("tanggal")

    if request.method == "POST":
        employee_id = request.form.get("employee_id")
        fingerprint_id = request.form.get("fingerprint_id") or None
        work_date = request.form.get("work_date")
        shift_code = request.form.get("shift_code")
        status_hadir = request.form.get("status_hadir") or "hadir"

        period1_in = fix_time(request.form.get("period1_in"))
        period1_out = fix_time(request.form.get("period1_out"))
        period2_in = fix_time(request.form.get("period2_in"))
        period2_out = fix_time(request.form.get("period2_out"))
        period3_in = fix_time(request.form.get("period3_in"))
        period3_out = fix_time(request.form.get("period3_out"))

        cek = conn.execute("""
            SELECT id
            FROM attendance_daily
            WHERE employee_id = ?
              AND work_date = ?
            LIMIT 1
        """, (employee_id, work_date)).fetchone()

        if cek:
            conn.execute("""
                UPDATE attendance_daily
                SET
                    fingerprint_id = ?,
                    shift_code = ?,
                    period1_in = ?,
                    period1_out = ?,
                    period2_in = ?,
                    period2_out = ?,
                    period3_in = ?,
                    period3_out = ?,
                    status_hadir = ?,
                    sumber = ?,
                    catatan = ?
                WHERE id = ?
            """, (
                fingerprint_id,
                shift_code,
                period1_in,
                period1_out,
                period2_in,
                period2_out,
                period3_in,
                period3_out,
                status_hadir,
                "manual",
                "Update manual dari absensi",
                cek["id"]
            ))
        else:
            conn.execute("""
                INSERT INTO attendance_daily (
                    employee_id, fingerprint_id, work_date, shift_code,
                    period1_in, period1_out,
                    period2_in, period2_out,
                    period3_in, period3_out,
                    normal_hours, actual_hours, overtime_hours,
                    late_minutes, early_leave_minutes,
                    status_hadir, sumber, catatan, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                employee_id,
                fingerprint_id,
                work_date,
                shift_code,
                period1_in, period1_out,
                period2_in, period2_out,
                period3_in, period3_out,
                0, 0, 0,
                0, 0,
                status_hadir,
                "manual",
                "Input manual dari absensi"
            ))

        conn.commit()
        conn.close()
        return redirect(url_for("karyawan.absensi_index", tanggal=work_date))

    emp = conn.execute("""
        SELECT id, no_id, nama, bagian, fingerprint_id, shift_default
        FROM employees
        WHERE no_id = ?
        LIMIT 1
    """, (no_id,)).fetchone()

    conn.close()

    if not emp:
        return redirect(url_for("karyawan.absensi_index", tanggal=tanggal))

    return render_template(
        "karyawan/absensi_input_manual.html",
        emp=emp,
        tanggal=tanggal
    )
@karyawan_bp.route("/employee-items", methods=["GET", "POST"])
def employee_items():
    conn = get_conn()

    item_options = [
        "Seragam",
        "Baju",
        "Celana",
        "Topi",
        "Apron",
        "Masker",
        "Sepatu Cewek",
        "Sepatu Cowok",
        "Sarung Tangan Kain",
        "Sarung Tangan Karet",
        "Materai",
    ]

    if request.method == "POST":
        tanggal = request.form.get("tanggal")
        nama_item = request.form.get("nama_item")
        harga_satuan = int(request.form.get("harga_satuan") or 0)
        qty = int(request.form.get("qty") or 1)
        metode_potong = request.form.get("metode_potong") or "sekali"
        cicilan_per_minggu = int(request.form.get("cicilan_per_minggu") or 0)
        keterangan = request.form.get("keterangan") or ""
        no_ids_text = request.form.get("no_ids") or ""

        total = harga_satuan * qty
        no_ids = [
            x.strip()
            for x in no_ids_text.replace(",", "\n").splitlines()
            if x.strip()
        ]

        berhasil = 0
        gagal = []

        for no_id in no_ids:
            emp = conn.execute("""
                SELECT id, no_id, nama
                FROM employees
                WHERE no_id = ?
                  AND status_aktif = 1
                LIMIT 1
            """, (no_id,)).fetchone()

            if not emp:
                gagal.append(no_id)
                continue

            sisa = total if metode_potong == "cicilan" else 0

            conn.execute("""
                INSERT INTO employee_items (
                    employee_id, no_id, nama, tanggal,
                    nama_item, qty, harga_satuan, total,
                    metode_potong, cicilan_per_minggu, sisa,
                    status, keterangan, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                emp["id"],
                emp["no_id"],
                emp["nama"],
                tanggal,
                nama_item,
                qty,
                harga_satuan,
                total,
                metode_potong,
                cicilan_per_minggu,
                sisa,
                "aktif",
                keterangan
            ))

            berhasil += 1

        conn.commit()
        conn.close()

        return redirect(url_for("karyawan.employee_items"))

    rows = conn.execute("""
        SELECT *
        FROM employee_items
        ORDER BY tanggal DESC, id DESC
        LIMIT 100
    """).fetchall()

    rows = [dict(r) for r in rows]
    conn.close()

    return render_template(
        "karyawan/employee_items.html",
        rows=rows,
        item_options=item_options
    )
@karyawan_bp.route("/payroll/finalize", methods=["POST"])
def payroll_finalize():
    from absensi.rules import hitung_gaji_harian_row

    conn = get_conn()

    tanggal_awal = request.form.get("tanggal_awal")
    tanggal_akhir = request.form.get("tanggal_akhir")
    bagian = request.form.get("bagian", "").strip()

    if not tanggal_awal or not tanggal_akhir:
        conn.close()
        return redirect(url_for("karyawan.payroll_index"))

    # hapus history lama untuk periode yang sama agar tidak dobel finalize
    conn.execute("""
        DELETE FROM payroll_items
        WHERE payroll_id IN (
            SELECT id FROM payroll_history
            WHERE tanggal_awal = ?
              AND tanggal_akhir = ?
        )
    """, (tanggal_awal, tanggal_akhir))

    conn.execute("""
        DELETE FROM payroll_history
        WHERE tanggal_awal = ?
          AND tanggal_akhir = ?
    """, (tanggal_awal, tanggal_akhir))

    query = """
        SELECT
            e.id AS employee_id,
            e.no_id,
            e.nama,
            e.bagian,
            e.shift_default AS shift_code,
            COALESCE(e.gaji_harian, 100000) AS gaji_harian,
            COALESCE(e.tinggal_di_mes, 0) AS tinggal_di_mes,

            a.work_date,
            a.period1_in,
            a.period1_out,
            a.period2_in,
            a.period2_out,
            a.period3_in,
            a.period3_out,
            a.actual_hours,
            a.late_minutes,
            a.early_leave_minutes,
            a.overtime_hours,
            a.status_hadir,

            COALESCE(b.total_upah, 0) AS total_upah_borongan

        FROM employees e
        LEFT JOIN attendance_daily a
            ON e.id = a.employee_id
           AND a.work_date BETWEEN ? AND ?
        LEFT JOIN borongan_logs b
            ON b.no_id = e.no_id
           AND b.tanggal = a.work_date
        WHERE e.status_aktif = 1
    """

    params = [tanggal_awal, tanggal_akhir]

    if bagian and bagian.lower() != "semua":
        query += " AND LOWER(TRIM(e.bagian)) = ? "
        params.append(bagian.lower())

    query += " ORDER BY CAST(e.no_id AS INTEGER), a.work_date "

    data = conn.execute(query, params).fetchall()
    data = [dict(r) for r in data]

    grouped = {}

    for r in data:
        emp_id = r["employee_id"]

        if emp_id not in grouped:
            grouped[emp_id] = {
                "employee_id": emp_id,
                "no_id": r["no_id"],
                "nama": r["nama"],
                "bagian": r["bagian"],
                "hari_masuk": 0,
                "total_upah_borongan": 0,
                "total_gaji_pokok": 0,
                "total_lembur": 0,
                "total_insentif": 0,
                "total_potongan": 0,
                "total_potongan_barang": 0,
                "total_gaji": 0,
                "items": [],
            }

        if r.get("work_date"):
            r["tinggal_di_mes"] = 1 if cek_tinggal_di_mes(
                conn,
                r["employee_id"],
                r["work_date"]
            ) else 0
        else:
            r["tinggal_di_mes"] = 0

        hasil = hitung_gaji_harian_row(r)

        if hasil["work_type"] == "full":
            grouped[emp_id]["hari_masuk"] += 1
        elif hasil["work_type"] == "half":
            grouped[emp_id]["hari_masuk"] += 0.5

        upah_borongan = int(round(r.get("total_upah_borongan") or 0))
        gaji_pokok = int(round(hasil.get("gaji_pokok") or 0))
        gaji_lembur = int(round(hasil.get("gaji_lembur") or 0))
        insentif = int(round(hasil.get("insentif") or 0))
        potongan_telat = int(round(hasil.get("potongan_telat") or 0))
        potongan_mes = int(round(hasil.get("potongan_mes") or 0))

        grouped[emp_id]["total_upah_borongan"] += upah_borongan
        grouped[emp_id]["total_gaji_pokok"] += gaji_pokok
        grouped[emp_id]["total_lembur"] += gaji_lembur
        grouped[emp_id]["total_insentif"] += insentif

        grouped[emp_id]["total_potongan"] += potongan_telat + potongan_mes

        grouped[emp_id]["total_gaji"] += (
            upah_borongan
            + gaji_pokok
            + gaji_lembur
            + insentif
            - potongan_telat
            - potongan_mes
        )

        if upah_borongan > 0:
            grouped[emp_id]["items"].append({
                "tanggal": r.get("work_date"),
                "jenis": "pendapatan",
                "keterangan": "Upah Borongan",
                "nominal": upah_borongan,
            })

        if gaji_pokok > 0:
            grouped[emp_id]["items"].append({
                "tanggal": r.get("work_date"),
                "jenis": "pendapatan",
                "keterangan": "Gaji Pokok",
                "nominal": gaji_pokok,
            })

        if gaji_lembur > 0:
            grouped[emp_id]["items"].append({
                "tanggal": r.get("work_date"),
                "jenis": "insentif",
                "keterangan": "Lembur",
                "nominal": gaji_lembur,
            })

        if insentif > 0:
            grouped[emp_id]["items"].append({
                "tanggal": r.get("work_date"),
                "jenis": "insentif",
                "keterangan": "Insentif Libur / Tambahan",
                "nominal": insentif,
            })

        if potongan_telat > 0:
            grouped[emp_id]["items"].append({
                "tanggal": r.get("work_date"),
                "jenis": "potongan",
                "keterangan": "Potongan Telat",
                "nominal": potongan_telat,
            })

        if potongan_mes > 0:
            grouped[emp_id]["items"].append({
                "tanggal": r.get("work_date"),
                "jenis": "potongan",
                "keterangan": "Potongan Mes",
                "nominal": potongan_mes,
            })

    # potongan barang per karyawan
    for emp_id, g in grouped.items():
        barang_rows = conn.execute("""
            SELECT
                id,
                tanggal,
                nama_item,
                total,
                metode_potong,
                cicilan_per_minggu,
                sisa
            FROM employee_items
            WHERE employee_id = ?
              AND status = 'aktif'
              AND tanggal BETWEEN ? AND ?
        """, (emp_id, tanggal_awal, tanggal_akhir)).fetchall()

        for item in barang_rows:
            if item["metode_potong"] == "sekali":
                nominal = int(item["total"] or 0)
            elif item["metode_potong"] == "cicilan":
                nominal = min(
                    int(item["sisa"] or 0),
                    int(item["cicilan_per_minggu"] or 0)
                )
            else:
                nominal = 0

            if nominal <= 0:
                continue

            g["total_potongan_barang"] += nominal
            g["total_potongan"] += nominal
            g["total_gaji"] -= nominal

            g["items"].append({
                "tanggal": item["tanggal"],
                "jenis": "potongan_barang",
                "keterangan": item["nama_item"],
                "nominal": nominal,
            })

    # simpan payroll_history dan payroll_items
    for emp_id, g in grouped.items():
        cur = conn.execute("""
            INSERT INTO payroll_history (
                employee_id, no_id, nama, bagian,
                tanggal_awal, tanggal_akhir,
                hari_masuk,
                total_upah_borongan,
                total_gaji_pokok,
                total_lembur,
                total_insentif,
                total_potongan,
                total_potongan_barang,
                total_gaji
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            g["employee_id"],
            g["no_id"],
            g["nama"],
            g["bagian"],
            tanggal_awal,
            tanggal_akhir,
            g["hari_masuk"],
            g["total_upah_borongan"],
            g["total_gaji_pokok"],
            g["total_lembur"],
            g["total_insentif"],
            g["total_potongan"],
            g["total_potongan_barang"],
            g["total_gaji"],
        ))

        payroll_id = cur.lastrowid

        for item in g["items"]:
            conn.execute("""
                INSERT INTO payroll_items (
                    payroll_id,
                    employee_id,
                    tanggal,
                    jenis,
                    keterangan,
                    nominal
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                payroll_id,
                g["employee_id"],
                item["tanggal"],
                item["jenis"],
                item["keterangan"],
                item["nominal"],
            ))

    # potongan sekali: tandai sudah dipotong
    # COMMENT sementara
    # conn.execute("""
    #     UPDATE employee_items
    #     SET status = 'paid'
    #     WHERE metode_potong = 'sekali'
    #       AND status = 'aktif'
    #       AND tanggal BETWEEN ? AND ?
    # """, (tanggal_awal, tanggal_akhir))
    # cicilan: kurangi sisa
    items = conn.execute("""
        SELECT id, sisa, cicilan_per_minggu
        FROM employee_items
        WHERE metode_potong = 'cicilan'
          AND status = 'aktif'
    """).fetchall()

    for item in items:
        potong = min(
            int(item["sisa"] or 0),
            int(item["cicilan_per_minggu"] or 0)
        )
        sisa_baru = int(item["sisa"] or 0) - potong
        status_baru = "lunas" if sisa_baru <= 0 else "aktif"

        # COMMENT dulu
        # for item in items:
        #     ...
        #     conn.execute("""
        #         UPDATE employee_items
        #         SET sisa = ?, status = ?
        #         WHERE id = ?
        #     """, ...)

    conn.commit()
    conn.close()

    return redirect(url_for(
        "karyawan.payroll_index",
        tanggal_awal=tanggal_awal,
        tanggal_akhir=tanggal_akhir,
        bagian=bagian
    ))
@karyawan_bp.route("/mes", methods=["GET", "POST"])
def mes_index():
    conn = get_conn()

    if request.method == "POST":
        no_id = request.form.get("no_id", "").strip()
        tanggal_mulai = request.form.get("tanggal_mulai", "").strip()
        tanggal_selesai = request.form.get("tanggal_selesai", "").strip()
        keterangan = request.form.get("keterangan", "").strip()

        emp = conn.execute("""
            SELECT id, no_id, nama
            FROM employees
            WHERE no_id = ?
              AND status_aktif = 1
            LIMIT 1
        """, (no_id,)).fetchone()

        if emp and tanggal_mulai:
            conn.execute("""
                INSERT INTO employee_mes_history (
                    employee_id, no_id, nama,
                    tanggal_mulai, tanggal_selesai,
                    status, keterangan, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                emp["id"],
                emp["no_id"],
                emp["nama"],
                tanggal_mulai,
                tanggal_selesai or None,
                "keluar" if tanggal_selesai else "aktif",
                keterangan or None
            ))
            conn.commit()

        conn.close()
        return redirect(url_for("karyawan.mes_index"))

    rows = conn.execute("""
        SELECT *
        FROM employee_mes_history
        ORDER BY 
            CASE WHEN status = 'aktif' THEN 0 ELSE 1 END,
            tanggal_mulai DESC,
            CAST(no_id AS INTEGER)
    """).fetchall()

    rows = [dict(r) for r in rows]
    conn.close()

    return render_template(
        "karyawan/mes.html",
        rows=rows
    )
@karyawan_bp.route("/mes/<int:id>/keluar", methods=["POST"])
def mes_keluar(id):
    conn = get_conn()

    tanggal_selesai = request.form.get("tanggal_selesai", "").strip()
    keterangan = request.form.get("keterangan", "").strip()

    conn.execute("""
        UPDATE employee_mes_history
        SET
            tanggal_selesai = ?,
            status = 'keluar',
            keterangan = COALESCE(?, keterangan)
        WHERE id = ?
    """, (
        tanggal_selesai or None,
        keterangan or None,
        id
    ))

    conn.commit()
    conn.close()

    return redirect(url_for("karyawan.mes_index"))

@karyawan_bp.route("/payroll/history")
def payroll_history():
    conn = get_conn()

    rows = conn.execute("""
        SELECT
            tanggal_awal,
            tanggal_akhir,
            COUNT(*) AS total_karyawan,
            SUM(total_gaji) AS total_gaji,
            SUM(total_potongan) AS total_potongan,
            MAX(created_at) AS finalized_at
        FROM payroll_history
        GROUP BY tanggal_awal, tanggal_akhir
        ORDER BY tanggal_awal DESC
    """).fetchall()

    rows = [dict(r) for r in rows]
    conn.close()

    return render_template(
        "karyawan/payroll_history.html",
        rows=rows
    )
@karyawan_bp.route("/payroll/history/detail")
def payroll_history_detail():
    conn = get_conn()

    tanggal_awal = request.args.get("tanggal_awal")
    tanggal_akhir = request.args.get("tanggal_akhir")
    bagian = request.args.get("bagian", "").strip().lower()

    if not tanggal_awal or not tanggal_akhir:
        conn.close()
        return redirect(url_for("karyawan.payroll_history"))

    query = """
        SELECT *
        FROM payroll_history
        WHERE tanggal_awal = ?
          AND tanggal_akhir = ?
    """

    params = [tanggal_awal, tanggal_akhir]

    if bagian:
        query += " AND LOWER(TRIM(bagian)) = ? "
        params.append(bagian)

    query += """
        ORDER BY
          CASE LOWER(TRIM(bagian))
            WHEN 'borongan' THEN 1
            WHEN 'produksi' THEN 2
            WHEN 'beku' THEN 3
            WHEN 'coldroom' THEN 4
            WHEN 'kebersihan' THEN 5
            WHEN 'malam' THEN 6
            ELSE 99
          END,
          CAST(no_id AS INTEGER)
    """

    rows = conn.execute(query, params).fetchall()

    rows = [dict(r) for r in rows]
    conn.close()

    return render_template(
        "karyawan/payroll_history_detail.html",
        rows=rows,
        tanggal_awal=tanggal_awal,
        tanggal_akhir=tanggal_akhir
    )
@karyawan_bp.route("/payroll/history/<int:payroll_id>")
def payroll_slip(payroll_id):
    conn = get_conn()

    payroll = conn.execute("""
        SELECT *
        FROM payroll_history
        WHERE id = ?
    """, (payroll_id,)).fetchone()

    items = conn.execute("""
        SELECT *
        FROM payroll_items
        WHERE payroll_id = ?
        ORDER BY tanggal, id
    """, (payroll_id,)).fetchall()
    items = [dict(i) for i in items]

    summary_items = {
        "potongan_mes": sum(i["nominal"] for i in items if i["keterangan"] == "Potongan Mes"),
        "potongan_telat": sum(i["nominal"] for i in items if i["keterangan"] == "Potongan Telat"),
        "potongan_barang": sum(i["nominal"] for i in items if i["jenis"] == "potongan_barang"),
    }

    return render_template(
        "karyawan/payroll_slip.html",
        payroll=dict(payroll),
        items=items,
        summary_items=summary_items
    )

    conn.close()

    return render_template(
        "karyawan/payroll_slip.html",
        payroll=dict(payroll),
        items=[dict(i) for i in items]
    )
@karyawan_bp.route("/payroll/history/print")
def payroll_print_bulk():
    conn = get_conn()

    tanggal_awal = request.args.get("tanggal_awal")
    tanggal_akhir = request.args.get("tanggal_akhir")

    rows = conn.execute("""
        SELECT *
        FROM payroll_history
        WHERE tanggal_awal = ?
          AND tanggal_akhir = ?
          AND total_gaji != 0
        ORDER BY
          CASE LOWER(TRIM(bagian))
            WHEN 'borongan' THEN 1
            WHEN 'produksi' THEN 2
            WHEN 'beku' THEN 3
            WHEN 'coldroom' THEN 4
            WHEN 'malam' THEN 5
            WHEN 'umum' THEN 6
            WHEN 'kebersihan' THEN 7
            ELSE 99
          END,
          CAST(no_id AS INTEGER)
    """, (tanggal_awal, tanggal_akhir)).fetchall()

    rows = [dict(r) for r in rows]

    for r in rows:
        items = conn.execute("""
            SELECT *
            FROM payroll_items
            WHERE payroll_id = ?
        """, (r["id"],)).fetchall()

        items = [dict(i) for i in items]

        r["potongan_telat"] = sum(
            int(i["nominal"] or 0)
            for i in items
            if i["keterangan"] == "Potongan Telat"
        )

        r["potongan_mes"] = sum(
            int(i["nominal"] or 0)
            for i in items
            if i["keterangan"] == "Potongan Mes"
        )

        r["potongan_barang"] = sum(
            int(i["nominal"] or 0)
            for i in items
            if i["jenis"] == "potongan_barang"
        )

    conn.close()

    return render_template(
        "karyawan/payroll_print_bulk.html",
        rows=rows
    )
@karyawan_bp.route("/payroll/history/receipt")
def payroll_receipt_print():
    conn = get_conn()

    tanggal_awal = request.args.get("tanggal_awal")
    tanggal_akhir = request.args.get("tanggal_akhir")

    rows = conn.execute("""
        SELECT *
        FROM payroll_history
        WHERE tanggal_awal = ?
          AND tanggal_akhir = ?
          AND total_gaji != 0
        ORDER BY
          CASE LOWER(TRIM(bagian))
            WHEN 'borongan' THEN 1
            WHEN 'produksi' THEN 2
            WHEN 'beku' THEN 3
            WHEN 'coldroom' THEN 4
            WHEN 'malam' THEN 5
            WHEN 'umum' THEN 6
            WHEN 'kebersihan' THEN 7
            ELSE 99
          END,
          CAST(no_id AS INTEGER)
    """, (tanggal_awal, tanggal_akhir)).fetchall()

    rows = [dict(r) for r in rows]
    conn.close()

    return render_template(
        "karyawan/payroll_receipt_print.html",
        rows=rows,
        tanggal_awal=tanggal_awal,
        tanggal_akhir=tanggal_akhir
    )
@karyawan_bp.route("/payroll/confirm", methods=["POST"])
def payroll_confirm():
    conn = get_conn()

    tanggal_awal = request.form.get("tanggal_awal")
    tanggal_akhir = request.form.get("tanggal_akhir")

    if not tanggal_awal or not tanggal_akhir:
        conn.close()
        return redirect(url_for("karyawan.payroll_index"))

    conn.execute("""
        UPDATE employee_items
        SET status = 'paid'
        WHERE metode_potong = 'sekali'
          AND status = 'aktif'
          AND tanggal BETWEEN ? AND ?
    """, (tanggal_awal, tanggal_akhir))

    items = conn.execute("""
        SELECT id, sisa, cicilan_per_minggu
        FROM employee_items
        WHERE metode_potong = 'cicilan'
          AND status = 'aktif'
    """).fetchall()

    for item in items:
        potong = min(
            int(item["sisa"] or 0),
            int(item["cicilan_per_minggu"] or 0)
        )

        sisa_baru = int(item["sisa"] or 0) - potong
        status_baru = "lunas" if sisa_baru <= 0 else "aktif"

        conn.execute("""
            UPDATE employee_items
            SET sisa = ?, status = ?
            WHERE id = ?
        """, (sisa_baru, status_baru, item["id"]))

    conn.execute("""
        UPDATE payroll_history
        SET status = 'paid'
        WHERE tanggal_awal = ?
          AND tanggal_akhir = ?
    """, (tanggal_awal, tanggal_akhir))

    conn.commit()
    conn.close()

    return redirect(url_for(
        "karyawan.payroll_history_detail",
        tanggal_awal=tanggal_awal,
        tanggal_akhir=tanggal_akhir
    ))
@karyawan_bp.route("/raw")
def raw_index():

    conn = get_conn()

    tanggal = request.args.get("tanggal")
    no_id = request.args.get("no_id")

    query = """
        SELECT
            tanggal,
            waktu,
            fingerprint_id,
            no_id,
            tipe_scan,
            status_absen,
            sumber,
            processed
        FROM attendance_raw
        WHERE 1=1
    """

    params = []

    if tanggal:
        query += " AND tanggal = ?"
        params.append(tanggal)

    if no_id:
        query += " AND no_id = ?"
        params.append(no_id)

    query += " ORDER BY waktu DESC LIMIT 500"

    rows = conn.execute(query, params).fetchall()

    conn.close()

    return render_template(
        "karyawan/raw_index.html",
        rows=rows,
        tanggal=tanggal,
        no_id=no_id
    )