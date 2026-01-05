# db.py
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "receiving.db")

def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # aktifkan foreign key
    cur.execute("PRAGMA foreign_keys = ON;")

    cur.executescript("""
    -- =====================
    -- Master tables
    -- =====================
    CREATE TABLE IF NOT EXISTS supplier (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      nama TEXT NOT NULL UNIQUE,
      aktif INTEGER NOT NULL DEFAULT 1,
      created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS udang_jenis (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      nama TEXT NOT NULL UNIQUE,
      aktif INTEGER NOT NULL DEFAULT 1
    );

    INSERT OR IGNORE INTO udang_jenis (nama) VALUES ('Vannamei');
    INSERT OR IGNORE INTO udang_jenis (nama) VALUES ('Dogol');
    INSERT OR IGNORE INTO udang_jenis (nama) VALUES ('Kupasan');

    -- =====================
    -- Receiving
    -- =====================
    CREATE TABLE IF NOT EXISTS receiving_header (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      tanggal TEXT NOT NULL,
      supplier TEXT NOT NULL,
      jenis TEXT,
      fiber REAL,
      created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS receiving_partai (
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
      FOREIGN KEY(header_id) REFERENCES receiving_header(id)
    );

    -- =====================
    -- Production
    -- =====================
    CREATE TABLE IF NOT EXISTS production_header (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      receiving_id INTEGER NOT NULL UNIQUE,
      tanggal TEXT NOT NULL,
      supplier TEXT NOT NULL,
      jenis TEXT,
      bahan_masuk_kg REAL NOT NULL DEFAULT 0,
      created_at TEXT DEFAULT (datetime('now','localtime')),
      FOREIGN KEY(receiving_id) REFERENCES receiving_header(id)
    );

    CREATE TABLE IF NOT EXISTS production_step (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      production_id INTEGER NOT NULL,
      step_name TEXT NOT NULL,
      berat_kg REAL NOT NULL DEFAULT 0,
      yield_pct REAL,
      created_at TEXT DEFAULT (datetime('now','localtime')),
      UNIQUE(production_id, step_name),
      FOREIGN KEY(production_id) REFERENCES production_header(id)
    );
        
      
        
    CREATE TABLE IF NOT EXISTS production_packing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    production_id INTEGER NOT NULL,
    size TEXT,
        
    kupas_kg REAL NOT NULL DEFAULT 0,      -- basis yield per baris
     mc REAL NOT NULL DEFAULT 0,            -- jumlah dus/pack
     berat_per_dus REAL NOT NULL DEFAULT 0, -- kg per dus
        
     total_kg REAL NOT NULL DEFAULT 0,      -- mc * berat_per_dus
    yield_ratio REAL,                     -- total_kg / kupas_kg (contoh 1.120)
        
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY(production_id) REFERENCES production_header(id)
        );
        
            CREATE INDEX IF NOT EXISTS idx_production_packing_prod_id
          ON production_packing(production_id);



    -- =====================
    -- Indexes (SETELAH table ada)
    -- =====================
    CREATE INDEX IF NOT EXISTS idx_receiving_header_tanggal
      ON receiving_header(tanggal);

    CREATE INDEX IF NOT EXISTS idx_receiving_header_supplier
      ON receiving_header(supplier);

    CREATE INDEX IF NOT EXISTS idx_production_header_receiving_id
      ON production_header(receiving_id);

    CREATE INDEX IF NOT EXISTS idx_production_packing_prod_id
      ON production_packing(production_id);
      
      -- =====================
-- Invoice
-- =====================
CREATE TABLE IF NOT EXISTS invoice_header (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  receiving_id INTEGER NOT NULL,
  tanggal TEXT NOT NULL,
  supplier TEXT NOT NULL,

  price_points_json TEXT,
  subtotal REAL NOT NULL DEFAULT 0,
  pph_rate REAL NOT NULL DEFAULT 0,   -- contoh 0.004 untuk 0.4%
  pph REAL NOT NULL DEFAULT 0,
  total REAL NOT NULL DEFAULT 0,

  status TEXT NOT NULL DEFAULT 'DRAFT',  -- DRAFT / FINAL / VOID
  created_at TEXT DEFAULT (datetime('now','localtime')),

  FOREIGN KEY(receiving_id) REFERENCES receiving_header(id)
);

CREATE TABLE IF NOT EXISTS invoice_detail (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL,
  partai_no INTEGER,
  size_round INTEGER,
  berat_netto REAL,
  harga REAL,
  total_harga REAL,
  FOREIGN KEY(invoice_id) REFERENCES invoice_header(id) ON DELETE CASCADE
);

-- 1 receiving = 1 invoice (selain VOID tetap dianggap ada)
CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_receiving_id
ON invoice_header(receiving_id);

CREATE INDEX IF NOT EXISTS idx_invoice_header_tanggal
ON invoice_header(tanggal);

CREATE INDEX IF NOT EXISTS idx_invoice_detail_invoice_id
ON invoice_detail(invoice_id);

    """)

    conn.commit()
    conn.close()
