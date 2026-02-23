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
        CREATE TABLE IF NOT EXISTS invoice_header (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
        
            receiving_id INTEGER NOT NULL UNIQUE,
        
            invoice_no TEXT UNIQUE,             
            tanggal TEXT NOT NULL,
            supplier TEXT NOT NULL,
        
            price_points_json TEXT,               
            subtotal REAL DEFAULT 0,
            total REAL DEFAULT 0,
           
            pph_rate REAL DEFAULT 0,
            pph_amount REAL DEFAULT 0,
                   
            cash_deduct_per_kg REAL DEFAULT 0,
            cash_deduct_total REAL DEFAULT 0,
            reject_kg REAL DEFAULT 0,
            reject_price REAL DEFAULT 0,
            reject_total REAL DEFAULT 0,
        
            payment_type TEXT DEFAULT 'CASH',   
            tempo_hari INTEGER DEFAULT 0,
            due_date TEXT,
            status TEXT NOT NULL DEFAULT 'POSTED',         
        
            total_kg REAL DEFAULT 0,
        
            created_at TEXT DEFAULT (datetime('now','localtime')),
        
            FOREIGN KEY (receiving_id)
                REFERENCES receiving_header(id)
                ON DELETE CASCADE
            );
            
         CREATE TABLE IF NOT EXISTS invoice_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
        
            invoice_id INTEGER NOT NULL,
        
            partai_no INTEGER NOT NULL,         
            round_size INTEGER,
            size_round TEXT,
        
            berat_netto REAL NOT NULL DEFAULT 0,
            harga REAL NOT NULL DEFAULT 0,
            total_harga REAL NOT NULL DEFAULT 0,
        
            created_at TEXT DEFAULT (datetime('now','localtime')),
        
            FOREIGN KEY (invoice_id)
                REFERENCES invoice_header(id)
                ON DELETE CASCADE,
        
            UNIQUE (invoice_id, partai_no)
            );
            CREATE TABLE IF NOT EXISTS supplier (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              nama TEXT NOT NULL UNIQUE,
              aktif INTEGER NOT NULL DEFAULT 1,
              created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS udang_jenis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nama TEXT NOT NULL UNIQUE,
                aktif INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
        """)
        conn.commit()
        print("✅ Database baru siap:", DB_PATH)
    finally:
        conn.close()

