# app/store.py
import sqlite3, json, os
from typing import List, Dict, Any, Optional

# Database file lives in: <project>/data/copilot.db
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "copilot.db")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

def _conn() -> sqlite3.Connection:
    """Return a SQLite connection, creating the data folder if needed."""
    os.makedirs(DATA_DIR, exist_ok=True)
    return sqlite3.connect(DB_PATH)

# ------------------------------
# Core TX storage (existing)
# ------------------------------

def init_db():
    """Create core tables if they do not exist (txs + audit_log)."""
    con = _conn(); cur = con.cursor()
    # Main transactions table (your original schema)
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
    con.commit()
    con.close()

    # Also ensure audit table exists
    init_audit()

def save_tagged(t: Dict[str, Any]) -> None:
    """Insert one analyzed (tagged) transaction into the DB."""
    con = _conn(); cur = con.cursor()
    cur.execute("""
      INSERT INTO txs (tx_id,timestamp,chain,from_addr,to_addr,amount,symbol,direction,memo,fee,category,risk_score,risk_flags,notes)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        t["tx_id"], str(t["timestamp"]), t["chain"], t["from_addr"], t["to_addr"],
        float(t["amount"]), t["symbol"], t["direction"], t.get("memo"),
        float(t.get("fee") or 0.0), t.get("category","unknown"),
        float(t.get("risk_score") or 0.0), json.dumps(t.get("risk_flags", [])),
        t.get("notes")
    ))
    con.commit(); con.close()

def list_by_wallet(wallet: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Return most recent transactions where address is sender or receiver."""
    con = _conn(); cur = con.cursor()
    cur.execute("""
      SELECT tx_id,timestamp,chain,from_addr,to_addr,amount,symbol,direction,memo,fee,category,risk_score,risk_flags,notes
      FROM txs
      WHERE from_addr = ? OR to_addr = ?
      ORDER BY id DESC LIMIT ?
    """, (wallet, wallet, limit))
    rows = cur.fetchall(); con.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "tx_id": r[0], "timestamp": r[1], "chain": r[2],
            "from_addr": r[3], "to_addr": r[4], "amount": r[5], "symbol": r[6],
            "direction": r[7], "memo": r[8], "fee": r[9], "category": r[10],
            "risk_score": r[11], "risk_flags": json.loads(r[12] or "[]"),
            "notes": r[13]
        })
    return out

def list_alerts(threshold: float = 0.75, limit: int = 100) -> List[Dict[str, Any]]:
    """Return most recent transactions with risk >= threshold."""
    con = _conn(); cur = con.cursor()
    cur.execute("""
      SELECT tx_id,timestamp,chain,from_addr,to_addr,amount,symbol,direction,memo,fee,category,risk_score,risk_flags,notes
      FROM txs
      WHERE risk_score >= ?
      ORDER BY id DESC LIMIT ?
    """, (threshold, limit))
    rows = cur.fetchall(); con.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "tx_id": r[0], "timestamp": r[1], "chain": r[2],
            "from_addr": r[3], "to_addr": r[4], "amount": r[5], "symbol": r[6],
            "direction": r[7], "memo": r[8], "fee": r[9], "category": r[10],
            "risk_score": r[11], "risk_flags": json.loads(r[12] or "[]"),
            "notes": r[13]
        })
    return out

def list_all(limit: int = 1000) -> List[Dict[str, Any]]:
    """Return up to `limit` most recent transactions from the DB (all wallets)."""
    con = _conn(); cur = con.cursor()
    cur.execute("""
      SELECT tx_id,timestamp,chain,from_addr,to_addr,amount,symbol,direction,memo,fee,category,risk_score,risk_flags,notes
      FROM txs
      ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = cur.fetchall(); con.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "tx_id": r[0], "timestamp": r[1], "chain": r[2],
            "from_addr": r[3], "to_addr": r[4], "amount": r[5], "symbol": r[6],
            "direction": r[7], "memo": r[8], "fee": r[9], "category": r[10],
            "risk_score": r[11], "risk_flags": json.loads(r[12] or "[]"),
            "notes": r[13]
        })
    return out

# ------------------------------
# NEW: Audit log storage (Step 1A)
# ------------------------------

def init_audit():
    """Create the audit_log table if it does not exist."""
    con = _conn(); cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        route TEXT NOT NULL,
        wallet TEXT,
        tx_hash TEXT,
        category TEXT,
        risk_score REAL,
        risk_flags TEXT,
        status_code INTEGER NOT NULL,
        duration_ms REAL NOT NULL,
        note TEXT
    )
    """)
    con.commit()
    con.close()

def save_audit(
    ts: str,
    route: str,
    wallet: Optional[str],
    tx_hash: Optional[str],
    category: Optional[str],
    risk_score: Optional[float],
    risk_flags: Optional[list[str]],
    status_code: int,
    duration_ms: float,
    note: Optional[str] = None,
) -> None:
    """Insert one audit row (best-effort; never raises)."""
    try:
        con = _conn(); cur = con.cursor()
        cur.execute("""
        INSERT INTO audit_log (ts, route, wallet, tx_hash, category, risk_score, risk_flags, status_code, duration_ms, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ts, route, wallet, tx_hash, category,
            float(risk_score) if risk_score is not None else None,
            json.dumps(risk_flags or []),
            int(status_code),
            float(duration_ms),
            note,
        ))
        con.commit()
    except Exception:
        # Never break callers because audit failed
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass

def list_audit(limit: int = 100) -> List[Dict[str, Any]]:
    """Return most recent audit entries (newest first)."""
    con = _conn(); cur = con.cursor()
    cur.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    con.close()
    # risk_flags stored as JSON string; decode for convenience
    for r in rows:
        try:
            r["risk_flags"] = json.loads(r.get("risk_flags") or "[]")
        except Exception:
            r["risk_flags"] = []
    return rows
