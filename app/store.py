# app/store.py
import sqlite3, json, os
from typing import List, Dict, Any

# Database file lives in: <project>/data/copilot.db
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "copilot.db")

def _conn():
    # Ensure the data folder exists
    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data"), exist_ok=True)
    return sqlite3.connect(DB_PATH)

def init_db():
    """Create the table if it does not exist."""
    con = _conn(); cur = con.cursor()
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
    out = []
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
    out = []
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
    out = []
    for r in rows:
        out.append({
            "tx_id": r[0], "timestamp": r[1], "chain": r[2],
            "from_addr": r[3], "to_addr": r[4], "amount": r[5], "symbol": r[6],
            "direction": r[7], "memo": r[8], "fee": r[9], "category": r[10],
            "risk_score": r[11], "risk_flags": json.loads(r[12] or "[]"),
            "notes": r[13]
        })
    return out

