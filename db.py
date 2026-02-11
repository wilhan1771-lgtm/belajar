import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "receiving.db")

def get_conn():
    conn = sqlite3.connect(DB_NAME, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def ensure_column(conn, table, col, ddl):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript("""
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
      FOREIGN KEY(header_id) REFERENCES receiving_header(id)
    );

    -- ===================== PRODUKSI =====================
    CREATE TABLE IF NOT EXISTS production_header (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      receiving_id INTEGER NOT NULL UNIQUE,
      tanggal TEXT NOT NULL,
      supplier TEXT NOT NULL,
      jenis TEXT,
      bahan_masuk_kg REAL,
      hl_kg REAL DEFAULT 0,
      kupas_kg REAL DEFAULT 0,
      soaking_kg REAL DEFAULT 0,
      created_at TEXT DEFAULT (datetime('now','localtime')),
      FOREIGN KEY(receiving_id) REFERENCES receiving_header(id)
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
    """)

    conn.commit()
    conn.close()
    print("Database siap, termasuk tabel produksi.")
