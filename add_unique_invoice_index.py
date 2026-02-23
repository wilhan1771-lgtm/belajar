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
                        INSERT INTO receiving_item
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
        LEFT JOIN receiving_item p ON p.header_id = h.id
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
        SELECT * FROM receiving_item
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
        SELECT * FROM receiving_item
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
                UPDATE receiving_item
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
