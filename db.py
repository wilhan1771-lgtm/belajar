# db.py
import sqlite3

DB_NAME = "receiving.db"

def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
                CREATE TABLE IF NOT EXISTS invoice_header
                (
                    id
                    INTEGER
                    PRIMARY
                    KEY
                    AUTOINCREMENT,
                    receiving_id
                    INTEGER
                    NOT
                    NULL,
                    tanggal
                    TEXT
                    NOT
                    NULL,
                    supplier
                    TEXT
                    NOT
                    NULL,
                    price_points_json
                    TEXT, -- simpan patokan 40/50/60/70 dalam JSON
                    pph_rate
                    REAL
                    DEFAULT
                    0.0025,
                    subtotal
                    REAL
                    DEFAULT
                    0,
                    pph
                    REAL
                    DEFAULT
                    0,
                    total
                    REAL
                    DEFAULT
                    0,
                    created_at
                    TEXT
                    DEFAULT (
                    datetime
                (
                    'now',
                    'localtime'
                )),
                    FOREIGN KEY
                (
                    receiving_id
                ) REFERENCES receiving_header
                (
                    id
                )
                    )
                """)

    cur.execute("""
                CREATE TABLE IF NOT EXISTS invoice_detail
                (
                    id
                    INTEGER
                    PRIMARY
                    KEY
                    AUTOINCREMENT,
                    invoice_id
                    INTEGER
                    NOT
                    NULL,
                    partai_no
                    INTEGER,
                    size_round
                    INTEGER,
                    berat_netto
                    REAL,
                    harga
                    INTEGER,
                    total_harga
                    REAL,
                    FOREIGN
                    KEY
                (
                    invoice_id
                ) REFERENCES invoice_header
                (
                    id
                )
                    )
                """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS receiving_header (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tanggal TEXT NOT NULL,
            supplier TEXT NOT NULL,
            jenis TEXT,
            fiber REAL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    cur.execute("""
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
        )
    """)

    conn.commit()
    conn.close()
