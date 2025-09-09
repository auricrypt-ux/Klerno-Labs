# app/admin.py
from __future__ import annotations

import os, json
from io import StringIO
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from . import store
from .deps import require_user
from .guardian import score_risk
from .compliance import tag_category
from pydantic import BaseModel, EmailStr


# Optional email (SendGrid) — same envs your app already uses
SENDGRID_KEY = os.getenv("SENDGRID_API_KEY", "").strip()
ALERT_FROM   = os.getenv("ALERT_EMAIL_FROM", "").strip()
DEFAULT_TO   = os.getenv("ALERT_EMAIL_TO", "").strip()

BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

router = APIRouter(prefix="/admin", tags=["Admin"])


def require_admin(user=Depends(require_user)):
    """Allow only role=admin."""
    if (user.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user


def _row_score(r: Dict[str, Any]) -> float:
    try:
        val = r.get("score", None)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            val = r.get("risk_score", 0)
        if isinstance(val, float) and pd.isna(val):
            val = 0
        return float(val or 0)
    except Exception:
        return 0.0


def _send_email(subject: str, text: str, to_email: Optional[str] = None) -> Dict[str, Any]:
    """Lightweight SendGrid helper used only in admin routes."""
    recipient = (to_email or DEFAULT_TO).strip()
    if not (SENDGRID_KEY and ALERT_FROM and recipient):
        return {"sent": False, "reason": "missing SENDGRID_API_KEY/ALERT_EMAIL_FROM/ALERT_EMAIL_TO"}
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content
        msg = Mail(
            from_email=Email(ALERT_FROM),
            to_emails=To(recipient),
            subject=subject,
            plain_text_content=Content("text/plain", text),
        )
        sg = SendGridAPIClient(SENDGRID_KEY)
        resp = sg.send(msg)
        ok = 200 <= resp.status_code < 300
        return {"sent": ok, "status_code": resp.status_code, "to": recipient}
    except Exception as e:
        return {"sent": False, "error": str(e)}


# ---------------- UI ----------------

@router.get("", include_in_schema=False)
def admin_home(request: Request, user=Depends(require_admin)):
    return templates.TemplateResponse("admin.html", {"request": request, "title": "Admin"})

# ---------------- JSON: Overview / Stats ----------------

@router.get("/api/stats")
def admin_stats(user=Depends(require_admin)):
    rows = store.list_all(limit=100000)
    total = len(rows)
    threshold = float(os.getenv("RISK_THRESHOLD", "0.75") or 0.75)
    alerts = [r for r in rows if _row_score(r) >= threshold]
    avg_risk = round(sum(_row_score(r) for r in rows) / total, 3) if total else 0.0
    cats: Dict[str, int] = {}
    for r in rows:
        c = r.get("category") or "unknown"
        cats[c] = cats.get(c, 0) + 1

    backend = "postgres" if store.USING_POSTGRES else "sqlite"
    return {
        "backend": backend,
        "db_path": getattr(store, "DB_PATH", None),
        "total": total,
        "alerts": len(alerts),
        "avg_risk": avg_risk,
        "threshold": threshold,
        "categories": cats,
        "server_time": pd.Timestamp.utcnow().isoformat(),
    }

# ---------------- JSON: Users ----------------

def _list_users() -> List[Dict[str, Any]]:
    # Avoid adding new store fn: use a direct query against existing table
    con = store._conn(); cur = con.cursor()
    cur.execute("""
        SELECT id, email, password_hash, role, subscription_active, created_at
        FROM users
        ORDER BY created_at DESC
    """)
    rows = cur.fetchall(); con.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        if isinstance(r, dict):
            d = dict(r)
        else:
            d = {k: r[k] for k in r.keys()}
        d["subscription_active"] = bool(d.get("subscription_active"))
        d.pop("password_hash", None)  # never return hashes
        out.append(d)
    return out


@router.get("/api/users")
def admin_users(user=Depends(require_admin)):
    return {"items": _list_users()}


class UpdateRolePayload(BaseModel):
    role: str

class UpdateSubPayload(BaseModel):
    active: bool

# Pydantic BaseModel import for request bodies
from pydantic import BaseModel

@router.post("/api/users/{user_id}/role")
def admin_set_role(user_id: int, payload: UpdateRolePayload, user=Depends(require_admin)):
    u = store.get_user_by_id(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    role = (payload.role or "").lower().strip()
    if role not in {"admin", "analyst", "viewer"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    store.set_role(u["email"], role)
    return {"ok": True, "user": store.get_user_by_id(user_id)}

@router.post("/api/users/{user_id}/subscription")
def admin_set_subscription(user_id: int, payload: UpdateSubPayload, user=Depends(require_admin)):
    u = store.get_user_by_id(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    store.set_subscription_active(u["email"], bool(payload.active))
    return {"ok": True, "user": store.get_user_by_id(user_id)}

# ---------------- JSON: Data tools ----------------

class SeedDemoPayload(BaseModel):
    # Optional: number of rows to take from sample
    limit: Optional[int] = None

@router.post("/api/data/seed_demo")
def admin_seed_demo(payload: SeedDemoPayload = Body(default=None), user=Depends(require_admin)):
    data_path = os.path.join(BASE_DIR, "..", "data", "sample_transactions.csv")
    if not os.path.exists(data_path):
        raise HTTPException(status_code=404, detail="sample_transactions.csv not found")

    df = pd.read_csv(data_path)
    if payload and payload.limit:
        df = df.head(int(payload.limit))

    # Normalize
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%S")
    for col in ("memo", "notes", "symbol", "direction", "chain", "tx_id", "from_addr", "to_addr"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
    for col in ("amount", "fee"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    saved = 0
    for _, row in df.iterrows():
        tx = {
            "tx_id": row.get("tx_id"),
            "timestamp": row.get("timestamp"),
            "chain": row.get("chain") or "XRPL",
            "from_addr": row.get("from_addr") or "",
            "to_addr": row.get("to_addr") or "",
            "amount": float(row.get("amount") or 0),
            "symbol": row.get("symbol") or "XRP",
            "direction": row.get("direction") or "out",
            "memo": row.get("memo") or "",
            "fee": float(row.get("fee") or 0),
            "category": row.get("category") or None,
            "notes": row.get("notes") or "",
        }
        risk, flags = score_risk(tx)  # accepts dict-like
        cat = tx.get("category") or tag_category(tx)
        d = {
            **tx,
            "risk_score": risk,
            "risk_flags": flags,
            "category": cat,
        }
        store.save_tagged(d)
        saved += 1

    return {"ok": True, "saved": saved}

class PurgePayload(BaseModel):
    confirm: str

@router.post("/api/data/purge")
def admin_purge(payload: PurgePayload, user=Depends(require_admin)):
    if (payload.confirm or "").upper() != "DELETE":
        raise HTTPException(status_code=400, detail='Type "DELETE" to confirm')
    con = store._conn(); cur = con.cursor()
    cur.execute("DELETE FROM txs")
    con.commit(); con.close()
    return {"ok": True, "deleted": True}

# ---------------- JSON: Utilities ----------------

class TestEmailPayload(BaseModel):
    email: Optional[str] = None

@router.post("/api/email/test")
def admin_email_test(payload: TestEmailPayload = Body(default=None), user=Depends(require_admin)):
    to = payload.email if payload and payload.email else DEFAULT_TO
    res = _send_email("Klerno Admin Test", "✅ Admin test email from Klerno.")
    return {"ok": bool(res.get("sent")), "result": res}

class XRPLPingPayload(BaseModel):
    account: str
    limit: Optional[int] = 1

@router.post("/api/xrpl/ping")
def admin_xrpl_ping(payload: XRPLPingPayload, user=Depends(require_admin)):
    from .integrations.xrp import fetch_account_tx
    try:
        raw = fetch_account_tx(payload.account, limit=int(payload.limit or 1))
        n = len(raw or [])
        return {"ok": True, "fetched": n}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

# app/admin.py (append these)
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from .deps import require_user
from .security import rotate_api_key, preview_api_key

router = APIRouter(prefix="/admin", tags=["admin"])

class ApiKeyRotateResponse(BaseModel):
    api_key: str  # returned ONCE so the admin can copy it

def _ensure_admin(user=Depends(require_user)):
    if (user or {}).get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return user

@router.post("/api-key/rotate", response_model=ApiKeyRotateResponse)
def admin_rotate_api_key(user=Depends(_ensure_admin)):
    """
    Generates a fresh API key and persists it to data/api_key.secret.
    NOTE: If you set X_API_KEY in ENV, that still takes precedence.
    """
    new_key = rotate_api_key()
    return {"api_key": new_key}

@router.get("/api-key/preview")
def admin_preview_api_key(user=Depends(_ensure_admin)):
    """
    Returns masked preview & metadata, never the full key.
    """
    return preview_api_key()
