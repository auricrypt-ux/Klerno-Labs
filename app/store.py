# app/store.py
import os, json, sqlite3
from typing import List, Dict, Any, Iterable, Optional

# --- Config & detection -------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL") or ""
PLACEHOLDER = "?"  # default for SQLite

# psycopg2 might not be installed locally; handle gracefully
try:
    import psycopg2  # type: ignore[import-not-found]
    from psycopg2.extras import RealDictCursor  # type: ignore[import-not-found]
    PSYCOPG2_AVAILABLE = True
except Exception:
    PSYCOPG2_AVAILABLE = False

USING_POSTGRES = bool(DATABASE_URL) and PSYCOPG2_AVAILABLE


# --- Connection factories -----------------------------------------------------

def _sqlite_conn() -> sqlite3.Connection:
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, "copilot.db")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row  # return dict-like rows to unify handling
    return con


def _postgres_conn():
    # RealDictCursor returns dict rows (keyed by column name)
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)  # type: ignore[name-defined]


def _conn():
    """
    Return a DB connection:
    - Postgres if DATABASE_URL & psycopg2 are available
    - else SQLite
    """
    return _postgres_conn() if USING_POSTGRES else _sqlite_conn()


def _ph() -> str:
    """Return the correct SQL placeholder for the active backend."""
    return "%s" if USING_POSTGRES else "?"


# --- Schema management --------------------------------------------------------

def init_db() -> None:
    """
    Create tables if they do not exist:
      - txs     : your existing transactions store
      - users   : auth/accounts (email unique, password hash, role, subscription flag)
    """
    con = _conn(); cur = con.cursor()

    # ---- TXS TABLE ----
    if USING_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS txs (
            id SERIAL PRIMARY KEY,
            tx_id TEXT,
            timestamp TEXT,
            chain TEXT,
            from_addr TEXT,
            to_addr TEXT,
            amount DOUBLE PRECISION,
            symbol TEXT,
            direction TEXT,
            memo TEXT,
            fee DOUBLE PRECISION,
            category TEXT,
            risk_score DOUBLE PRECISION,
            risk_flags TEXT,
            notes TEXT
        );""")
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS txs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_id TEXT,
            timestamp TEXT,
            chain TEXT,
            from_addr TEXT,
            to_addr TEXT,
            amount REAL,
            symbol TEXT,
            direction TEXT,
            memo TEXT,
            fee REAL,
            category TEXT,
            risk_score REAL,
            risk_flags TEXT,
            notes TEXT
        );""")

    # ---- USERS TABLE ----
    if USING_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',              -- 'admin' | 'analyst' | 'viewer'
            subscription_active BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );""")
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',              -- 'admin' | 'analyst' | 'viewer'
            subscription_active INTEGER NOT NULL DEFAULT 0,   -- 0/1 for SQLite
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""")

    con.commit(); con.close()


# --- Row helpers --------------------------------------------------------------

def _rows_to_dicts(rows: Iterable) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        # r can be psycopg2 RealDictRow (dict) or sqlite3.Row (mapping-like)
        if isinstance(r, dict):
            d = dict(r)
        else:
            d = {k: r[k] for k in r.keys()}

        # normalize risk_flags to a list
        raw = d.get("risk_flags")
        try:
            d["risk_flags"] = json.loads(raw) if isinstance(raw, (str, bytes)) else (raw or [])
        except Exception:
            d["risk_flags"] = []

        out.append(d)
    return out


def _row_to_user(row) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    if isinstance(row, dict):
        d = dict(row)
    else:
        d = {k: row[k] for k in row.keys()}
    d["subscription_active"] = bool(d.get("subscription_active"))
    return {
        "id": d.get("id"),
        "email": d.get("email"),
        "password_hash": d.get("password_hash"),
        "role": d.get("role") or "viewer",
        "subscription_active": d.get("subscription_active"),
        "created_at": d.get("created_at"),
    }


# --- Transactions API (existing) ---------------------------------------------

def save_tagged(t: Dict[str, Any]) -> None:
    con = _conn(); cur = con.cursor()
    p = _ph()
    cur.execute(f"""
      INSERT INTO txs (
        tx_id, timestamp, chain, from_addr, to_addr, amount, symbol, direction,
        memo, fee, category, risk_score, risk_flags, notes
      )
      VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
    """, (
        t["tx_id"], str(t["timestamp"]), t["chain"], t["from_addr"], t["to_addr"],
        float(t["amount"]), t["symbol"], t["direction"], t.get("memo"),
        float(t.get("fee") or 0.0), t.get("category", "unknown"),
        float(t.get("risk_score") or 0.0), json.dumps(t.get("risk_flags", [])),
        t.get("notes"),
    ))
    con.commit(); con.close()


def list_by_wallet(wallet: str, limit: int = 100) -> List[Dict[str, Any]]:
    con = _conn(); cur = con.cursor()
    p = _ph()
    cur.execute(f"""
      SELECT
        tx_id, timestamp, chain, from_addr, to_addr, amount, symbol, direction,
        memo, fee, category, risk_score, risk_flags, notes
      FROM txs
      WHERE from_addr = {p} OR to_addr = {p}
      ORDER BY id DESC
      LIMIT {p}
    """, (wallet, wallet, limit))
    rows = cur.fetchall(); con.close()
    return _rows_to_dicts(rows)


def list_alerts(threshold: float = 0.75, limit: int = 100) -> List[Dict[str, Any]]:
    con = _conn(); cur = con.cursor()
    p = _ph()
    cur.execute(f"""
      SELECT
        tx_id, timestamp, chain, from_addr, to_addr, amount, symbol, direction,
        memo, fee, category, risk_score, risk_flags, notes
      FROM txs
      WHERE risk_score >= {p}
      ORDER BY id DESC
      LIMIT {p}
    """, (threshold, limit))
    rows = cur.fetchall(); con.close()
    return _rows_to_dicts(rows)


def list_all(limit: int = 1000) -> List[Dict[str, Any]]:
    con = _conn(); cur = con.cursor()
    p = _ph()
    cur.execute(f"""
      SELECT
        tx_id, timestamp, chain, from_addr, to_addr, amount, symbol, direction,
        memo, fee, category, risk_score, risk_flags, notes
      FROM txs
      ORDER BY id DESC
      LIMIT {p}
    """, (limit,))
    rows = cur.fetchall(); con.close()
    return _rows_to_dicts(rows)


# --- Users API (new for Step 2) ----------------------------------------------

def users_count() -> int:
    con = _conn(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM users")
    row = cur.fetchone(); con.close()
    if isinstance(row, dict):
        return int(row.get("n", 0))
    return int(row[0]) if row else 0


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    con = _conn(); cur = con.cursor()
    p = _ph()
    cur.execute(f"""
        SELECT id, email, password_hash, role, subscription_active, created_at
        FROM users WHERE email = {p}
    """, (email,))
    row = cur.fetchone(); con.close()
    return _row_to_user(row)


def get_user_by_id(uid: int) -> Optional[Dict[str, Any]]:
    con = _conn(); cur = con.cursor()
    p = _ph()
    cur.execute(f"""
        SELECT id, email, password_hash, role, subscription_active, created_at
        FROM users WHERE id = {p}
    """, (uid,))
    row = cur.fetchone(); con.close()
    return _row_to_user(row)


def create_user(email: str, password_hash: str, role: str = "viewer", subscription_active: bool = False) -> Dict[str, Any]:
    con = _conn(); cur = con.cursor()
    p = _ph()
    # created_at default handled by DB, but we set it explicitly for Postgres portability
    if USING_POSTGRES:
        cur.execute(f"""
            INSERT INTO users (email, password_hash, role, subscription_active, created_at)
            VALUES ({p},{p},{p},{p}, NOW())
            RETURNING id
        """, (email, password_hash, role, subscription_active))
        new_id = cur.fetchone()["id"]
    else:
        cur.execute(f"""
            INSERT INTO users (email, password_hash, role, subscription_active, created_at)
            VALUES ({p},{p},{p},{p}, datetime('now'))
        """, (email, password_hash, role, 1 if subscription_active else 0))
        new_id = cur.lastrowid
    con.commit(); con.close()
    return get_user_by_id(int(new_id))


def set_subscription_active(email: str, active: bool) -> None:
    con = _conn(); cur = con.cursor()
    p = _ph()
    cur.execute(f"UPDATE users SET subscription_active = {p} WHERE email = {p}",
                (True if USING_POSTGRES else (1 if active else 0), email) if USING_POSTGRES
                else (1 if active else 0, email))
    if USING_POSTGRES:
        # In Postgres we already passed True/False above; adjust nothing.
        pass
    con.commit(); con.close()


def set_role(email: str, role: str) -> None:
    con = _conn(); cur = con.cursor()
    p = _ph()
    cur.execute(f"UPDATE users SET role = {p} WHERE email = {p}", (role, email))
    con.commit(); con.close()
