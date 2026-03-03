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
        
        CREATE INDEX IF NOT EXISTS idx_production_packing_pid
        ON production_packing(production_id);

        CREATE INDEX IF NOT EXISTS idx_invoice_line_invoice
            ON invoice_line(invoice_id);      
              """)
        # ensure kolom mode ada
        ensure_column(conn, "master_jenis", "mode", "TEXT DEFAULT 'udang_size'")

        # update mode untuk data lama
        conn.execute("""
            UPDATE master_jenis
            SET mode='kupasan'
            WHERE LOWER(nama)='kupasan'
        """)

        conn.execute("""
            UPDATE master_jenis
            SET mode='udang_size'
            WHERE LOWER(nama) IN ('vannamei','dogol')
        """)
        ensure_column(conn, "receiving_item", "grade_manual", "TEXT")
        conn.commit()
        print("✅ Database baru siap:", DB_PATH)
    finally:
        conn.close()

