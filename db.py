
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "receiving.db")

def get_conn():
    conn = sqlite3.connect(
        DB_NAME,
        timeout=10,              # tunggu 10 detik sebelum error
        isolation_level=None     # autocommit mode (lebih aman utk web)
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")  # penting!
    return conn

def ensure_column(conn, table, col, ddl):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # =====================
    # CREATE TABLES (SQL ONLY)
    # =====================
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
    -- Invoice
    -- =====================
    CREATE TABLE IF NOT EXISTS invoice_header (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      receiving_id INTEGER NOT NULL,
      tanggal TEXT NOT NULL,
      supplier TEXT NOT NULL,
      subtotal REAL NOT NULL DEFAULT 0,
      pph_rate REAL NOT NULL DEFAULT 0,
      pph REAL NOT NULL DEFAULT 0,
      total REAL NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'DRAFT',
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
    """)

    # =====================
    # ALTER TABLE (PYTHON)
    # =====================

    ensure_column(conn, "receiving_partai","kategori_kupasan","TEXT")
    ensure_column(conn, "receiving_header", "is_test", "INTEGER DEFAULT 0")
    ensure_column(conn, "invoice_detail", "round_size", "INTEGER")
    conn.execute("""
                 UPDATE invoice_detail
                 SET round_size = size_round
                 WHERE round_size IS NULL
                   AND size_round IS NOT NULL
                 """)

    ensure_column(conn, "invoice_header", "payment_type", "TEXT")
    ensure_column(conn, "invoice_header", "tempo_hari", "INTEGER DEFAULT 0")
    ensure_column(conn, "invoice_header", "due_date", "TEXT")
    ensure_column(conn, "invoice_header", "pph_amount", "REAL DEFAULT 0")

    ensure_column(conn, "invoice_header", "cash_deduct_per_kg", "REAL DEFAULT 0")
    ensure_column(conn, "invoice_header", "cash_deduct_total", "REAL DEFAULT 0")

    ensure_column(conn, "invoice_header", "reject_kg", "REAL DEFAULT 0")
    ensure_column(conn, "invoice_header", "reject_price", "REAL DEFAULT 0")
    ensure_column(conn, "invoice_header", "reject_total", "REAL DEFAULT 0")

    ensure_column(conn, "invoice_header", "total_kg", "REAL DEFAULT 0")

    conn.commit()
    conn.close()
