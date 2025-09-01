# app/store.py
import os, json, sqlite3
from typing import List, Dict, Any, Iterable

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
    # return dict-like rows to unify handling
    con.row_factory = sqlite3.Row
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


# --- Schema management --------------------------------------------------------

def init_db() -> None:
    """Create main 'txs' table if it does not exist."""
    con = _conn(); cur = con.cursor()

    if USING_POSTGRES:
        # Postgres DDL
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
        )
        """)
    else:
        # SQLite DDL
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
        )
        """)

    con.commit(); con.close()


# --- Helpers ------------------------------------------------------------------

def _rows_to_dicts(rows: Iterable) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        # r can be psycopg2 RealDictRow (dict) or sqlite3.Row (mapping-like)
        if isinstance(r, dict):
            d = dict(r)
        else:
            # sqlite3.Row behaves like a mapping
            d = {k: r[k] for k in r.keys()}

        # normalize risk_flags to a list
        raw = d.get("risk_flags")
        try:
            d["risk_flags"] = json.loads(raw) if isinstance(raw, (str, bytes)) else (raw or [])
        except Exception:
            d["risk_flags"] = []

        out.append(d)
    return out


def _ph() -> str:
    """Return the correct SQL placeholder for the active backend."""
    return "%s" if USING_POSTGRES else "?"


# --- Public API ---------------------------------------------------------------

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
