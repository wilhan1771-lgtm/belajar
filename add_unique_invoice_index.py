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
        FROM receiving_item
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
            has_size=has_size,  # <-- tambahan: dipakai untuk switch UI
            required_sizes=required_sizes,  # <-- sudah sorted list
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
        FROM receiving_item
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
        FROM receiving_item
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
