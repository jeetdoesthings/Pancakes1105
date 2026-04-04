import sqlite3
import os
from contextlib import contextmanager
from app.config import settings
from app.rfp_schema import UniversalRFP
from typing import List, Optional

DB_PATH = os.path.join(settings.DATA_DIR, "rfp_database.sqlite")

def init_db():
    """Initializes the SQLite Database with tables and FTS virtual tables."""
    os.makedirs(settings.DATA_DIR, exist_ok=True)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Core structured table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS rfps (
            rfpId TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            productName TEXT NOT NULL,
            category TEXT,
            quantity INTEGER,
            unit TEXT,
            deadline DATE,
            budget REAL,
            currency TEXT,
            taxRate REAL,
            location TEXT,
            description TEXT
        )
        ''')
        
        # FTS5 Virtual Table for Search
        cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS rfps_fts USING fts5(
            rfpId, title, productName, description, content='rfps', content_rowid='rowid'
        )
        ''')
        
        # Triggers to keep FTS table in sync
        cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS rfps_ai AFTER INSERT ON rfps BEGIN
            INSERT INTO rfps_fts(rowid, rfpId, title, productName, description)
            VALUES (new.rowid, new.rfpId, new.title, new.productName, new.description);
        END;
        ''')
        
        cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS rfps_ad AFTER DELETE ON rfps BEGIN
            INSERT INTO rfps_fts(rfps_fts, rowid, rfpId, title, productName, description)
            VALUES ('delete', old.rowid, old.rfpId, old.title, old.productName, old.description);
        END;
        ''')
        
        cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS rfps_au AFTER UPDATE ON rfps BEGIN
            INSERT INTO rfps_fts(rfps_fts, rowid, rfpId, title, productName, description)
            VALUES ('delete', old.rowid, old.rfpId, old.title, old.productName, old.description);
            INSERT INTO rfps_fts(rowid, rfpId, title, productName, description)
            VALUES (new.rowid, new.rfpId, new.title, new.productName, new.description);
        END;
        ''')
        
        conn.commit()

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def insert_rfp(rfp: UniversalRFP) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO rfps (rfpId, title, productName, category, quantity, unit, deadline, budget, currency, taxRate, location, description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            rfp.rfpId, rfp.title, rfp.productName, rfp.category, rfp.quantity,
            rfp.unit, rfp.deadline.isoformat(), rfp.budget, rfp.currency,
            rfp.taxRate, rfp.location, rfp.description
        ))
        conn.commit()

def get_rfp_by_id(rfp_id: str) -> Optional[UniversalRFP]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM rfps WHERE rfpId = ?", (rfp_id,))
        row = cursor.fetchone()
        if row:
            return UniversalRFP(**dict(row))
        return None
