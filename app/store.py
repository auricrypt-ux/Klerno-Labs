# app/store.py
import os, json, sqlite3
from typing import List, Dict, Any, Iterable, Optional

# --- Config & detection -------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL") or ""

# Persistent SQLite path (fallback if not using Postgres)
BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "..", "data", "klerno.db"))

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
    # honor DB_PATH and ensure directory exists
    data_dir = os.path.dirname(os.path.abspath(DB_PATH))
    os.makedirs(data_dir, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
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
      - txs           : transactions store
      - users         : auth/accounts
      - user_settings : per-user persisted settings (x_api_key, thresholds, etc.)
    Also adds helpful indexes.
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_txs_from_addr ON txs (from_addr);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_txs_to_addr   ON txs (to_addr);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_txs_timestamp ON txs (timestamp);")
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_txs_from_addr ON txs (from_addr);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_txs_to_addr   ON txs (to_addr);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_txs_timestamp ON txs (timestamp);")

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

    # ---- USER_SETTINGS TABLE (normalized columns) ----
    if USING_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            x_api_key TEXT,
            risk_threshold DOUBLE PRECISION,
            time_range_days INTEGER,
            ui_prefs JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );""")
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            x_api_key TEXT,
            risk_threshold REAL,
            time_range_days INTEGER,
            ui_prefs TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
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


# --- Transactions API ---------------------------------------------------------

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


# --- Users API ----------------------------------------------------------------

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
    value = (True if USING_POSTGRES else (1 if active else 0)) if USING_POSTGRES else (1 if active else 0)
    cur.execute(f"UPDATE users SET subscription_active = {p} WHERE email = {p}", (value, email))
    con.commit(); con.close()


def set_role(email: str, role: str) -> None:
    con = _conn(); cur = con.cursor()
    p = _ph()
    cur.execute(f"UPDATE users SET role = {p} WHERE email = {p}", (role, email))
    con.commit(); con.close()


# --- User Settings API (normalized columns) ----------------------------------

def get_settings_for_user(user_id: int) -> Dict[str, Any]:
    """
    Return user's saved settings or {} if none.
    Keys: x_api_key (str), risk_threshold (float|None), time_range_days (int|None), ui_prefs (dict)
    """
    con = _conn(); cur = con.cursor()
    p = _ph()
    cur.execute(f"""
      SELECT x_api_key, risk_threshold, time_range_days, ui_prefs
      FROM user_settings
      WHERE user_id = {p}
    """, (user_id,))
    row = cur.fetchone(); con.close()
    if not row:
        return {}
    if not isinstance(row, dict):
        row = {k: row[k] for k in row.keys()}
    out: Dict[str, Any] = {
        "x_api_key": row.get("x_api_key") or None,
        "risk_threshold": float(row["risk_threshold"]) if row.get("risk_threshold") is not None else None,
        "time_range_days": int(row["time_range_days"]) if row.get("time_range_days") is not None else None,
    }
    # ui_prefs as JSON
    prefs_raw = row.get("ui_prefs")
    try:
        out["ui_prefs"] = (
            json.loads(prefs_raw) if isinstance(prefs_raw, (str, bytes))
            else (prefs_raw if isinstance(prefs_raw, dict) else {})
        )
    except Exception:
        out["ui_prefs"] = {}
    return out


def save_settings_for_user(user_id: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upsert user settings with provided keys only.
    Accepts: x_api_key, risk_threshold, time_range_days, ui_prefs (dict)
    Returns the merged row.
    """
    # Load current
    current = get_settings_for_user(user_id)

    # Merge with light coercion
    merged = dict(current)
    if "x_api_key" in patch:
        merged["x_api_key"] = (patch["x_api_key"] or "").strip() or None
    if "risk_threshold" in patch and patch["risk_threshold"] is not None:
        try:
            merged["risk_threshold"] = float(patch["risk_threshold"])
        except Exception:
            pass
    if "time_range_days" in patch and patch["time_range_days"] is not None:
        try:
            merged["time_range_days"] = int(patch["time_range_days"])
        except Exception:
            pass
    if "ui_prefs" in patch and patch["ui_prefs"] is not None:
        prefs = patch["ui_prefs"]
        if not isinstance(prefs, (dict, list)):
            try:
                prefs = json.loads(str(prefs))
            except Exception:
                prefs = {}
        merged["ui_prefs"] = prefs

    # Normalize for storage
    x_api_key = merged.get("x_api_key")
    risk_threshold = merged.get("risk_threshold")
    time_range_days = merged.get("time_range_days")
    ui_prefs_json = json.dumps(merged.get("ui_prefs") or {})

    con = _conn(); cur = con.cursor()
    p = _ph()
    if USING_POSTGRES:
        cur.execute(f"""
          INSERT INTO user_settings (user_id, x_api_key, risk_threshold, time_range_days, ui_prefs, created_at, updated_at)
          VALUES ({p},{p},{p},{p},{p}, NOW(), NOW())
          ON CONFLICT (user_id) DO UPDATE SET
            x_api_key = EXCLUDED.x_api_key,
            risk_threshold = EXCLUDED.risk_threshold,
            time_range_days = EXCLUDED.time_range_days,
            ui_prefs = EXCLUDED.ui_prefs,
            updated_at = NOW()
        """, (user_id, x_api_key, risk_threshold, time_range_days, ui_prefs_json))
    else:
        cur.execute(f"""
          INSERT INTO user_settings (user_id, x_api_key, risk_threshold, time_range_days, ui_prefs, created_at, updated_at)
          VALUES ({p},{p},{p},{p},{p}, datetime('now'), datetime('now'))
          ON CONFLICT(user_id) DO UPDATE SET
            x_api_key = excluded.x_api_key,
            risk_threshold = excluded.risk_threshold,
            time_range_days = excluded.time_range_days,
            ui_prefs = excluded.ui_prefs,
            updated_at = datetime('now')
        """, (user_id, x_api_key, risk_threshold, time_range_days, ui_prefs_json))
    con.commit(); con.close()
    return get_settings_for_user(user_id)


# --- Back-compat wrappers (optional) ------------------------------------------

def get_settings(user_id: int) -> Dict[str, Any]:
    """Deprecated: use get_settings_for_user."""
    return get_settings_for_user(user_id)


def save_settings(user_id: int, data: Dict[str, Any]) -> None:
    """Deprecated: use save_settings_for_user (no return)."""
    save_settings_for_user(user_id, data)
