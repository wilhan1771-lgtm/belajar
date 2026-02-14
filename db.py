import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "receiving.db")

def ensure_column(conn, table, col, ddl):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn

def init_db():
    conn = get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS supplier (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          nama TEXT NOT NULL UNIQUE,
          aktif INTEGER NOT NULL DEFAULT 1,
          created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        
        CREATE UNIQUE INDEX IF NOT EXISTS idx_production_receiving_unique
        ON production_header(receiving_id);
        
        CREATE TABLE IF NOT EXISTS udang_jenis (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          nama TEXT NOT NULL UNIQUE,
          aktif INTEGER NOT NULL DEFAULT 1
        );

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
          kategori_kupasan TEXT,
          fiber REAL,
          FOREIGN KEY(header_id) REFERENCES receiving_header(id) ON DELETE CASCADE
        );

        -- ===================== PRODUKSI =====================
        CREATE TABLE IF NOT EXISTS production_header (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          receiving_id INTEGER NOT NULL UNIQUE,
          tanggal TEXT NOT NULL,
          supplier TEXT NOT NULL,
          jenis TEXT,
          bahan_masuk REAL DEFAULT 0,
          created_at TEXT DEFAULT (datetime('now','localtime')),
          hl REAL DEFAULT 0,
          kupas REAL DEFAULT 0,
          soaking REAL DEFAULT 0,
          FOREIGN KEY(receiving_id) REFERENCES receiving_header(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS production_packing (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          production_id INTEGER NOT NULL,
          size TEXT,
          kupas_kg REAL DEFAULT 0,
          mc REAL DEFAULT 0,
          berat_per_dus REAL DEFAULT 0,
          total_kg REAL DEFAULT 0,
          yield_ratio REAL,
          created_at TEXT DEFAULT (datetime('now','localtime')),
          FOREIGN KEY(production_id) REFERENCES production_header(id) ON DELETE CASCADE
        );

        -- ===================== INVOICE =====================
        CREATE TABLE IF NOT EXISTS invoice_header (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          receiving_id INTEGER,
          tanggal TEXT,
          supplier TEXT,
          subtotal REAL DEFAULT 0,
          status TEXT DEFAULT 'OK',
          created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS invoice_detail (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          invoice_id INTEGER NOT NULL,
          item TEXT,
          qty REAL DEFAULT 0,
          harga REAL DEFAULT 0,
          total_harga REAL DEFAULT 0,
          created_at TEXT DEFAULT (datetime('now','localtime')),
          FOREIGN KEY(invoice_id) REFERENCES invoice_header(id) ON DELETE CASCADE
        );
        """)

        # --- MIGRASI KECIL (aman kalau sudah ada data lama) ---
        # jika dulu ada bahan_masuk_kg, tetap support: copy ke bahan_masuk bila perlu
        ensure_column(conn, "production_header", "bahan_masuk", "REAL DEFAULT 0")
        ensure_column(conn, "production_header", "hl", "REAL DEFAULT 0")
        ensure_column(conn, "production_header", "kupas", "REAL DEFAULT 0")
        ensure_column(conn, "production_header", "soaking", "REAL DEFAULT 0")

        # kalau ada kolom lama bahan_masuk_kg, isi bahan_masuk kalau bahan_masuk masih 0
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(production_header)")]
        if "bahan_masuk_kg" in cols:
            conn.execute("""
                UPDATE production_header
                SET bahan_masuk = COALESCE(bahan_masuk, 0) + 0
                WHERE bahan_masuk IS NULL
            """)
            conn.execute("""
                UPDATE production_header
                SET bahan_masuk = COALESCE(bahan_masuk_kg, 0)
                WHERE COALESCE(bahan_masuk, 0) = 0
            """)

        conn.commit()

        if os.environ.get("FLASK_ENV") == "development":
            print("DB CONNECT:", DB_PATH)
            print("Database siap (tanpa production_step).")
    finally:
        conn.close()
