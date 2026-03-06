import sqlite3
import os

# 1️⃣ Cek environment variable dulu
DB_PATH = os.environ.get("RECEIVING_DB")

# 2️⃣ Kalau tidak ada, pakai default relatif terhadap folder project
if not DB_PATH:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_PATH = os.path.join(BASE_DIR, "..", "receiving.db")

print("🗄️ Database aktif:", DB_PATH)  # optional: untuk debug


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def ensure_column(conn, table, column, definition):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        print(f"✔ Column '{column}' added to {table}")


def seed_master_data(conn: sqlite3.Connection) -> None:
        """
        Isi master default jika belum ada.
        """
        cursor = conn.cursor()

        # work_types default
        default_work_types = [
            ("KUPAS", "Kupas", "koin", 4),
            ("BELAH", "Belah", "koin", 5),
            ("PK", "PK / Deheading", "kg", 1),
        ]

        for kode, nama, satuan_input, konversi_ke_kg in default_work_types:
            cursor.execute("""
                INSERT OR IGNORE INTO work_types (kode, nama, satuan_input, konversi_ke_kg, aktif)
                VALUES (?, ?, ?, ?, 1)
                """, (kode, nama, satuan_input, konversi_ke_kg))

        # sizes default
        default_sizes = [
            ("XL", 1),
            ("L", 2),
            ("M", 3),
            ("S", 4),
        ]

        for kode, urutan in default_sizes:
            cursor.execute("""
                INSERT OR IGNORE INTO sizes (kode, urutan, aktif)
                VALUES (?, ?, 1)
                """, (kode, urutan))

def init_db():
    conn = get_conn()
    try:
        conn.executescript("""
        
        -- ================= RECEIVING =================
        CREATE TABLE IF NOT EXISTS receiving_header (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receiving_no INTEGER NOT NULL UNIQUE,
            tanggal TEXT NOT NULL,
            supplier TEXT NOT NULL,
            jenis TEXT NOT NULL,
            fiber REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS receiving_item (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                header_id INTEGER NOT NULL,
                partai_no INTEGER NOT NULL,
            
                pcs INTEGER,
                kg_sample REAL,
            
                size REAL,
                round_size INTEGER,
            
                keranjang INTEGER,
                tara_per_keranjang REAL,
            
                bruto REAL,
                total_tara REAL,
                netto REAL,
            
                note TEXT,
                timbangan_json TEXT,
            
                kategori_kupasan TEXT,
                fiber REAL,
            
                FOREIGN KEY(header_id)
                    REFERENCES receiving_header(id)
                    ON DELETE CASCADE
            );
                -- ================= INVOICE =================

        CREATE TABLE IF NOT EXISTS invoice_header (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            receiving_id INTEGER NOT NULL UNIQUE, -- 1 receiving = 1 invoice
            tanggal TEXT NOT NULL DEFAULT (date('now','localtime')),
            supplier TEXT NOT NULL,
            price_points_json TEXT NOT NULL,
            payment_type TEXT NOT NULL
                CHECK (payment_type IN ('cash','transfer')),
            tempo_hari INTEGER DEFAULT 0,
            due_date TEXT,

            -- Cash deduct per kg (hanya berlaku kalau cash)
            cash_deduct_per_kg_rp INTEGER DEFAULT 0,
            cash_deduct_total_rp INTEGER DEFAULT 0,
            -- PPh (siap dipakai nanti, 0.25% = 25)
            pph_rate_bp INTEGER DEFAULT 0,
            pph_amount_rp INTEGER DEFAULT 0,
            -- Total Supplier
            subtotal_rp INTEGER DEFAULT 0,
            total_payable_rp INTEGER DEFAULT 0,
            total_paid_g INTEGER DEFAULT 0,
            status TEXT DEFAULT 'draft'
                CHECK (status IN ('draft','issued','paid','void')),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(receiving_id)
                REFERENCES receiving_header(id)
                ON DELETE CASCADE
        );


        CREATE TABLE IF NOT EXISTS invoice_line (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            invoice_id INTEGER NOT NULL,
            receiving_item_id INTEGER NOT NULL UNIQUE,

            partai_no INTEGER NOT NULL,

            -- Simpan gram supaya presisi (anti float)
            net_g INTEGER NOT NULL,
            paid_g INTEGER NOT NULL,
            round_size INTEGER,
            price_per_kg_rp INTEGER NOT NULL,
            line_total_rp INTEGER NOT NULL,
            note TEXT,

            FOREIGN KEY(invoice_id)
                REFERENCES invoice_header(id)
                ON DELETE CASCADE,

            FOREIGN KEY(receiving_item_id)
                REFERENCES receiving_item(id)
                ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS supplier (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              nama TEXT NOT NULL UNIQUE,
              phone TEXT,
              address TEXT,
              bank_name TEXT,
              bank_account_name TEXT,
              bank_account_number TEXT,
              created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS master_jenis (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  nama TEXT NOT NULL UNIQUE,
                  mode TEXT DEFAULT 'udang_size',
                  is_active INTEGER NOT NULL DEFAULT 1,
                  sort_order INTEGER NOT NULL DEFAULT 0
                );
                INSERT OR IGNORE INTO master_jenis (nama, mode, sort_order)
                VALUES ('cumi', 'manual_grade', 4);
                -- seed contoh (sesuaikan)
                INSERT OR IGNORE INTO master_jenis (nama, sort_order) VALUES
                ('vannamei', 1),
                ('dogol', 2),
                ('kupasan', 3);
                -- =========================
                -- PRODUCTION HEADER
                -- =========================
                CREATE TABLE IF NOT EXISTS production (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  receiving_id INTEGER NOT NULL UNIQUE,
                
                  hl_kg REAL NOT NULL DEFAULT 0,
                  pd_kg REAL NOT NULL DEFAULT 0,
                
                  note TEXT,
                
                  created_at TEXT NOT NULL DEFAULT (datetime('now')),
                  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                
                  FOREIGN KEY(receiving_id) REFERENCES receiving_header(id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_production_receiving
                ON production(receiving_id);
                
                
                -- =========================
                -- PRODUCTION PACKING DETAIL
                -- =========================
                CREATE TABLE IF NOT EXISTS production_packing (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  production_id INTEGER NOT NULL,
                
                  rm_code TEXT NOT NULL,        -- VN / MS
                  out_size TEXT NOT NULL,       -- 31/40
                  product_code TEXT NOT NULL,   -- PTO / SJ
                
                  kupas_kg REAL NOT NULL DEFAULT 0,  -- optional analisa per size
                
                  mc_qty REAL NOT NULL DEFAULT 0,
                  pack_qty REAL NOT NULL DEFAULT 0,
                
                  packs_per_mc INTEGER NOT NULL DEFAULT 8,
                  pack_weight_g INTEGER NOT NULL DEFAULT 800,
                
                  note TEXT,
                
                  FOREIGN KEY(production_id) REFERENCES production(id)
                );
                    -- =========================
                    -- 1. employees
                    --  =========================
                    
                    CREATE TABLE IF NOT EXISTS employees (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        no_id TEXT NOT NULL UNIQUE,
                        nama TEXT NOT NULL,
                        bagian TEXT,
                        jabatan TEXT,
                        status_aktif INTEGER NOT NULL DEFAULT 1,
                        tanggal_masuk TEXT,
                        fingerprint_id TEXT,
                        no_hp TEXT,
                        catatan TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                  

                    -- =========================
                    -- 2. work_types
                    -- =========================
                     CREATE TABLE IF NOT EXISTS work_types (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        kode TEXT NOT NULL UNIQUE,
                        nama TEXT NOT NULL,
                        satuan_input TEXT NOT NULL,
                        konversi_ke_kg REAL,
                        aktif INTEGER NOT NULL DEFAULT 1
                    );
                 
                        -- =========================
                        -- 3. sizes
                        -- =========================
                    
                        CREATE TABLE IF NOT EXISTS sizes (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            kode TEXT NOT NULL UNIQUE,
                            urutan INTEGER NOT NULL DEFAULT 0,
                            aktif INTEGER NOT NULL DEFAULT 1
                        );

                        -- =========================
                        -- 4. work_rates
                        -- =========================
                        CREATE TABLE IF NOT EXISTS work_rates (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            work_type_id INTEGER NOT NULL,
                            size_id INTEGER,
                            harga_per_kg REAL NOT NULL DEFAULT 0,
                            aktif INTEGER NOT NULL DEFAULT 1,
                            berlaku_mulai TEXT,
                            berlaku_sampai TEXT,
                            catatan TEXT,
                            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (work_type_id) REFERENCES work_types(id),
                            FOREIGN KEY (size_id) REFERENCES sizes(id)
                        );

                    -- =========================
                    -- 5. borongan_inputs
                    -- 1 baris input per orang per tanggal
                    -- =========================
                
                    CREATE TABLE IF NOT EXISTS borongan_inputs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tanggal TEXT NOT NULL,
                        no_id TEXT NOT NULL,
                        kupas_xl_koin REAL NOT NULL DEFAULT 0,
                        kupas_l_koin REAL NOT NULL DEFAULT 0,
                        kupas_m_koin REAL NOT NULL DEFAULT 0,
                        kupas_s_koin REAL NOT NULL DEFAULT 0,
                        belah_xl_koin REAL NOT NULL DEFAULT 0,
                        belah_l_koin REAL NOT NULL DEFAULT 0,
                        belah_m_koin REAL NOT NULL DEFAULT 0,
                        belah_s_koin REAL NOT NULL DEFAULT 0,
                        pk_kg REAL NOT NULL DEFAULT 0,
                        catatan TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (tanggal, no_id)
                    );
                
                    -- =========================
                    -- 6. borongan_logs
                    -- hasil pecahan detail dari borongan_inputs
                    -- =========================
                    CREATE TABLE IF NOT EXISTS borongan_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tanggal TEXT NOT NULL,
                        no_id TEXT NOT NULL,
                        nama TEXT NOT NULL,
                    
                        kupas_xl_koin REAL NOT NULL DEFAULT 0,
                        kupas_l_koin REAL NOT NULL DEFAULT 0,
                        kupas_m_koin REAL NOT NULL DEFAULT 0,
                        kupas_s_koin REAL NOT NULL DEFAULT 0,
                    
                        belah_xl_koin REAL NOT NULL DEFAULT 0,
                        belah_l_koin REAL NOT NULL DEFAULT 0,
                        belah_m_koin REAL NOT NULL DEFAULT 0,
                        belah_s_koin REAL NOT NULL DEFAULT 0,
                    
                        pk_l_kg REAL NOT NULL DEFAULT 0,
                        pk_s_kg REAL NOT NULL DEFAULT 0,
                    
                        kupas_xl_kg REAL NOT NULL DEFAULT 0,
                        kupas_l_kg REAL NOT NULL DEFAULT 0,
                        kupas_m_kg REAL NOT NULL DEFAULT 0,
                        kupas_s_kg REAL NOT NULL DEFAULT 0,
                    
                        belah_xl_kg REAL NOT NULL DEFAULT 0,
                        belah_l_kg REAL NOT NULL DEFAULT 0,
                        belah_m_kg REAL NOT NULL DEFAULT 0,
                        belah_s_kg REAL NOT NULL DEFAULT 0,
                    
                        pk_l_kg_final REAL NOT NULL DEFAULT 0,
                        pk_s_kg_final REAL NOT NULL DEFAULT 0,
                    
                        rate_kupas_xl REAL NOT NULL DEFAULT 0,
                        rate_kupas_l REAL NOT NULL DEFAULT 0,
                        rate_kupas_m REAL NOT NULL DEFAULT 0,
                        rate_kupas_s REAL NOT NULL DEFAULT 0,
                    
                        rate_belah_xl REAL NOT NULL DEFAULT 0,
                        rate_belah_l REAL NOT NULL DEFAULT 0,
                        rate_belah_m REAL NOT NULL DEFAULT 0,
                        rate_belah_s REAL NOT NULL DEFAULT 0,
                    
                        rate_pk_l REAL NOT NULL DEFAULT 0,
                        rate_pk_s REAL NOT NULL DEFAULT 0,
                    
                        subtotal_kupas_xl REAL NOT NULL DEFAULT 0,
                        subtotal_kupas_l REAL NOT NULL DEFAULT 0,
                        subtotal_kupas_m REAL NOT NULL DEFAULT 0,
                        subtotal_kupas_s REAL NOT NULL DEFAULT 0,
                    
                        subtotal_belah_xl REAL NOT NULL DEFAULT 0,
                        subtotal_belah_l REAL NOT NULL DEFAULT 0,
                        subtotal_belah_m REAL NOT NULL DEFAULT 0,
                        subtotal_belah_s REAL NOT NULL DEFAULT 0,
                    
                        subtotal_pk_l REAL NOT NULL DEFAULT 0,
                        subtotal_pk_s REAL NOT NULL DEFAULT 0,
                    
                        total_kg REAL NOT NULL DEFAULT 0,
                        total_upah REAL NOT NULL DEFAULT 0,
                    
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    
                        UNIQUE (tanggal, no_id)
                    );
                        -- =========================
                        -- 7. attendance_raw
                        -- log mentah dari fingerprint / csv / import manual
                        -- =========================

                        CREATE TABLE IF NOT EXISTS attendance_raw (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            tanggal TEXT NOT NULL,
                            waktu TEXT NOT NULL,
                            fingerprint_id TEXT,
                            no_id TEXT,
                            nama_terbaca TEXT,
                            tipe_scan TEXT,
                            sumber TEXT,
                            raw_payload TEXT,
                            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                        );
 
                    -- =========================
                    -- 8. attendance_daily
                    -- hasil rangkuman absensi harian
                    -- =========================
                
                    CREATE TABLE IF NOT EXISTS attendance_daily (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tanggal TEXT NOT NULL,
                        no_id TEXT NOT NULL,
                        jam_masuk TEXT,
                        jam_pulang TEXT,
                        total_jam_kerja REAL NOT NULL DEFAULT 0,
                        status_hadir TEXT NOT NULL DEFAULT 'ALPHA',
                        terlambat_menit REAL NOT NULL DEFAULT 0,
                        lembur_menit REAL NOT NULL DEFAULT 0,
                        uang_hadir REAL NOT NULL DEFAULT 0,
                        catatan TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (tanggal, no_id)
                    );


            -- =========================
            -- 9. payroll_daily
            -- gabungan absensi + borongan per hari
            -- =========================
            CREATE TABLE IF NOT EXISTS payroll_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tanggal TEXT NOT NULL,
                no_id TEXT NOT NULL,
                total_kg REAL NOT NULL DEFAULT 0,
                total_upah_borongan REAL NOT NULL DEFAULT 0,
                uang_hadir REAL NOT NULL DEFAULT 0,
                uang_lembur REAL NOT NULL DEFAULT 0,
                bonus REAL NOT NULL DEFAULT 0,
                potongan REAL NOT NULL DEFAULT 0,
                total_bayar REAL NOT NULL DEFAULT 0,
                status_hadir TEXT,
                total_jam_kerja REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tanggal, no_id)
            );
                
        CREATE INDEX IF NOT EXISTS idx_production_packing_pid
        ON production_packing(production_id);
        CREATE INDEX IF NOT EXISTS idx_invoice_line_invoice
        ON invoice_line(invoice_id);      
        CREATE INDEX IF NOT EXISTS idx_employees_no_id
        ON employees(no_id);
        CREATE INDEX IF NOT EXISTS idx_borongan_inputs_tanggal_no_id
        ON borongan_inputs(tanggal, no_id);
        CREATE INDEX IF NOT EXISTS idx_attendance_raw_tanggal_fingerprint
        ON attendance_raw(tanggal, fingerprint_id);
        CREATE INDEX IF NOT EXISTS idx_attendance_daily_tanggal_no_id
        ON attendance_daily(tanggal, no_id);
        CREATE INDEX IF NOT EXISTS idx_payroll_daily_tanggal_no_id
        ON payroll_daily(tanggal, no_id);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_rates_unique
        ON work_rates(work_type_id, size_id);
        DELETE FROM work_rates
        WHERE work_type_id = (
    SELECT id FROM work_types WHERE kode = 'PK'
        )
AND size_id IS NULL;
              """)
        # ensure kolom mode ada
        ensure_column(conn, "master_jenis", "mode", "TEXT DEFAULT 'udang_size'")
        ensure_column(conn, "borongan_inputs", "pk_l_kg", "REAL NOT NULL DEFAULT 0")
        ensure_column(conn, "borongan_inputs", "pk_s_kg", "REAL NOT NULL DEFAULT 0")
        # update mode untuk data lama
        conn.execute("""
        UPDATE master_jenis
        SET mode='manual_grade'
        WHERE LOWER(nama)='kupasan'
        """)

        conn.execute("""
            UPDATE master_jenis
            SET mode='udang_size'
            WHERE LOWER(nama) IN ('vannamei','dogol')
        """)
        ensure_column(conn, "receiving_item", "grade_manual", "TEXT")
        ensure_column(conn,"invoice_header", "grade_prices_json", "TEXT")
        seed_master_data(conn)
        conn.commit()
        print("✅ Database baru siap:", DB_PATH)
    finally:
        conn.close()

