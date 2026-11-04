import sqlite3
import json
from datetime import datetime
from config import DATABASE_PATH


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        bin TEXT,
        tax_regime TEXT DEFAULT 'USN',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS periods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        quarter TEXT NOT NULL,
        year INTEGER NOT NULL,
        status TEXT DEFAULT 'draft',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(client_id) REFERENCES clients(id)
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period_id INTEGER NOT NULL,
        date TEXT,
        amount REAL NOT NULL,
        direction TEXT NOT NULL,
        counterparty TEXT,
        description TEXT,
        raw_data TEXT,
        category TEXT,
        subcategory TEXT,
        llm_suggestion TEXT,
        llm_subcategory TEXT,
        llm_confidence REAL,
        llm_reasoning TEXT,
        needs_review INTEGER DEFAULT 1,
        review_status TEXT DEFAULT 'pending',
        approved_by TEXT,
        approved_at TIMESTAMP,
        FOREIGN KEY(period_id) REFERENCES periods(id)
    );

    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id INTEGER,
        period_id INTEGER,
        file_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_type TEXT,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(transaction_id) REFERENCES transactions(id),
        FOREIGN KEY(period_id) REFERENCES periods(id)
    );

    CREATE TABLE IF NOT EXISTS risks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period_id INTEGER NOT NULL,
        transaction_id INTEGER,
        risk_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        description TEXT NOT NULL,
        llm_explanation TEXT,
        status TEXT DEFAULT 'open',
        resolved_by TEXT,
        resolved_at TIMESTAMP,
        FOREIGN KEY(period_id) REFERENCES periods(id),
        FOREIGN KEY(transaction_id) REFERENCES transactions(id)
    );

    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT DEFAULT 'accountant',
        action TEXT NOT NULL,
        entity_type TEXT,
        entity_id INTEGER,
        details TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Lightweight migration for databases created before these columns existed
    existing = {r["name"] for r in cur.execute("PRAGMA table_info(transactions)")}
    for col, ddl in (("llm_subcategory", "TEXT"), ("review_status", "TEXT DEFAULT 'pending'")):
        if col not in existing:
            cur.execute(f"ALTER TABLE transactions ADD COLUMN {col} {ddl}")
    cur.execute("UPDATE transactions SET review_status = 'accepted' WHERE approved_by IS NOT NULL AND review_status = 'pending'")

    conn.commit()
    conn.close()


def log_action(action: str, entity_type: str = None, entity_id: int = None, details: dict = None):
    conn = get_connection()
    conn.execute(
        "INSERT INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
        (action, entity_type, entity_id, json.dumps(details or {}, ensure_ascii=False))
    )
    conn.commit()
    conn.close()


def get_period_with_client(period_id: int):
    conn = get_connection()
    row = conn.execute("""
        SELECT p.*, c.name as client_name, c.bin, c.tax_regime
        FROM periods p JOIN clients c ON p.client_id = c.id
        WHERE p.id = ?
    """, (period_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_transactions(period_id: int):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM transactions WHERE period_id = ? ORDER BY date, id",
        (period_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_risks(period_id: int):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM risks WHERE period_id = ? ORDER BY severity DESC",
        (period_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def calculate_tax_summary(period_id: int, tax_rate: float = 0.03):
    conn = get_connection()
    rows = conn.execute(
        "SELECT category, SUM(amount) as total FROM transactions WHERE period_id = ? GROUP BY category",
        (period_id,)
    ).fetchall()
    conn.close()

    income = 0.0
    expenses = 0.0
    personal = 0.0
    unclassified = 0.0

    for row in rows:
        cat = row["category"] or ""
        if cat == "income":
            income += row["total"]
        elif cat == "expense":
            expenses += row["total"]
        elif cat == "personal":
            personal += row["total"]
        else:
            unclassified += row["total"]

    tax = income * tax_rate

    return {
        "income": round(income, 2),
        "expenses": round(expenses, 2),
        "personal": round(personal, 2),
        "unclassified": round(unclassified, 2),
        "tax": round(tax, 2),
        "tax_rate": tax_rate,
    }


def refresh_period_status(period_id: int) -> str:
    """Period is 'reviewed' when it has transactions and all are approved, else 'draft'."""
    conn = get_connection()
    total, pending = conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN approved_by IS NULL THEN 1 ELSE 0 END) FROM transactions WHERE period_id = ?",
        (period_id,),
    ).fetchone()
    status = "reviewed" if total and not pending else "draft"
    conn.execute("UPDATE periods SET status = ? WHERE id = ?", (status, period_id))
    conn.commit()
    conn.close()
    return status
