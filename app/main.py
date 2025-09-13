from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
from typing import List, Dict, Any, Optional, Callable, Awaitable, Tuple

import os
import hmac
import secrets
import pandas as pd
from dataclasses import asdict, is_dataclass, fields as dc_fields

from fastapi import (
    FastAPI,
    Security,
    Header,
    Request,
    Body,
    HTTPException,
    Depends,
    Form,
    WebSocket,
    Response,
)
from fastapi.responses import (
    StreamingResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

# Fast JSON (fallback to default if ORJSON not installed)
try:
    from fastapi.responses import ORJSONResponse as FastJSON
    DEFAULT_RESP_CLS = FastJSON
except Exception:
    FastJSON = JSONResponse
    DEFAULT_RESP_CLS = JSONResponse

# NEW: for live push hub
import asyncio, json
from functools import lru_cache

from . import store
from .models import Transaction, TaggedTransaction, ReportRequest
from .guardian import score_risk
from .compliance import tag_category
from .reporter import csv_export, summary
from .integrations.xrp import xrpl_json_to_transactions, fetch_account_tx
from .security import enforce_api_key, expected_api_key
from .security_session import hash_pw, verify_pw, issue_jwt

# Auth/Paywall routers
from . import auth as auth_router
from . import paywall_hooks as paywall_hooks
from .deps import require_paid_or_admin, require_user
from .routes.analyze_tags import router as analyze_tags_router
from .admin import router as admin_router  # admin dashboard

# ---------- Optional LLM helpers ----------
try:
    from .llm import (
        explain_tx,
        explain_batch,
        ask_to_filters,
        explain_selection,
        summarize_rows,
        apply_filters as _llm_apply_filters,  # optional
    )
except ImportError:
    from .llm import (
        explain_tx,
        explain_batch,
        ask_to_filters,
        explain_selection,
        summarize_rows,
    )
    _llm_apply_filters = None


def _apply_filters_safe(rows: List[Dict[str, Any]], spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fallback if llm.apply_filters isn't available."""
    if _llm_apply_filters:
        return _llm_apply_filters(rows, spec)
    if not spec:
        return rows
    out = rows
    for k, v in spec.items():
        # simple numeric/date operators
        if k in ("min_amount", "max_amount"):
            key = "amount"
            if k == "min_amount":
                out = [r for r in out if float(r.get(key, 0) or 0) >= float(v)]
            else:
                out = [r for r in out if float(r.get(key, 0) or 0) <= float(v)]
            continue
        if k in ("date_from", "date_to"):
            try:
                dt_key = "timestamp"
                if k == "date_from":
                    out = [r for r in out if _safe_dt(r.get(dt_key)) >= _safe_dt(v)]
                else:
                    out = [r for r in out if _safe_dt(r.get(dt_key)) <= _safe_dt(v)]
            except Exception:
                pass
            continue
        out = [r for r in out if str(r.get(k, "")).lower() == str(v).lower()]
    return out


def _dump(obj: Any) -> Dict[str, Any]:
    """Return a dict from either a Pydantic model or a dataclass (or mapping-like)."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if is_dataclass(obj):
        return asdict(obj)
    try:
        return dict(obj)
    except Exception:
        return {"value": obj}

# ---- helpers
def _safe_dt(x) -> datetime:
    try:
        return datetime.fromisoformat(str(x).replace("Z", ""))
    except Exception:
        return datetime.min

def _risk_bucket(score: float) -> str:
    s = float(score or 0)
    if s < 0.33: return "low"
    if s < 0.66: return "medium"
    return "high"

# unified, NaN-safe reader for old/new score keys
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


# =========================
# Security hardening
# =========================
REQ_ID_HEADER = "X-Request-ID"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.enable_hsts = (os.getenv("ENABLE_HSTS", "true").lower() == "true")

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[HTMLResponse]]):
        resp = await call_next(request)
        # UPDATED CSP: allow jsDelivr for Bootstrap & Chart.js
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src  'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "font-src 'self' data: https://cdn.jsdelivr.net; "
            "connect-src 'self' ws: wss:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        resp.headers.setdefault("Content-Security-Policy", csp)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if self.enable_hsts and request.url.scheme == "https":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
        return resp

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get(REQ_ID_HEADER) or secrets.token_hex(8)
        request.state.request_id = rid
        resp = await call_next(request)
        resp.headers.setdefault(REQ_ID_HEADER, rid)
        return resp

def issue_csrf_cookie(resp: HTMLResponse):
    token = secrets.token_urlsafe(32)
    resp.set_cookie(
        CSRF_COOKIE, token,
        secure=True, samesite="Strict", httponly=False, path="/", max_age=60*60*8
    )
    return token

def verify_csrf(request: Request):
    token_cookie = request.cookies.get(CSRF_COOKIE)
    token_hdr = request.headers.get(CSRF_HEADER)
    if not token_cookie or not token_hdr:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if not hmac.compare_digest(token_cookie, token_hdr):
        raise HTTPException(status_code=403, detail="Bad CSRF token")

async def csrf_protect_ui(request: Request):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        verify_csrf(request)
    return True


# =========================
# FastAPI app + templates
# =========================
app = FastAPI(
    title="Klerno Labs API (MVP) — XRPL First",
    default_response_class=DEFAULT_RESP_CLS,
)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=512)

# Static & templates
BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.globals["url_path_for"] = app.url_path_for

# Config flags for UI auth redirects
ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

# ---- Session cookie config
SESSION_COOKIE = os.getenv("SESSION_COOKIE_NAME", "session")
COOKIE_SECURE_MODE = os.getenv("COOKIE_SECURE", "auto").lower()  # "auto" | "true" | "false"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax").lower()   # "lax" | "strict" | "none"

def _is_secure_request(request: Request) -> bool:
    xf = (request.headers.get("x-forwarded-proto") or "").lower()
    if xf:
        return "https" in xf
    return request.url.scheme == "https"

def _cookie_kwargs(request: Request) -> Dict[str, Any]:
    if COOKIE_SECURE_MODE in ("true", "1", "yes"):
        secure = True
    elif COOKIE_SECURE_MODE in ("false", "0", "no"):
        secure = False
    else:
        secure = _is_secure_request(request)

    samesite = COOKIE_SAMESITE if COOKIE_SAMESITE in ("lax", "strict", "none") else "lax"
    if samesite == "none" and not secure:
        secure = True

    return {
        "httponly": True,
        "secure": secure,
        "samesite": samesite,
        "max_age": 60 * 60 * 24 * 7,  # 7 days
        "path": "/",
    }

# Include routers
from . import paywall  # noqa: E402
app.include_router(paywall.router)
app.include_router(auth_router.router)
app.include_router(paywall_hooks.router)
app.include_router(analyze_tags_router)
app.include_router(admin_router)

# Init DB
store.init_db()

# --- Bootstrap single admin account (email/password) ---
BOOT_ADMIN_EMAIL = "klerno@outlook.com".lower().strip()
BOOT_ADMIN_PASSWORD = "Labs2025"

existing = store.get_user_by_email(BOOT_ADMIN_EMAIL)
if not existing:
    store.create_user(
        BOOT_ADMIN_EMAIL,
        hash_pw(BOOT_ADMIN_PASSWORD),
        role="admin",
        subscription_active=True,
    )

# ---- Live push hub (WebSocket) ----------------------------------------------
class LiveHub:
    """In-process pub/sub for real-time pushes."""
    def __init__(self):
        self._clients: dict[WebSocket, set[str]] = {}
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._clients[ws] = set()

    async def remove(self, ws: WebSocket):
        async with self._lock:
            self._clients.pop(ws, None)

    async def update_watch(self, ws: WebSocket, watch: set[str]):
        async with self._lock:
            if ws in self._clients:
                self._clients[ws] = {w.strip().lower() for w in watch if w}

    async def publish(self, item: dict):
        fa = (item.get("from_addr") or "").lower()
        ta = (item.get("to_addr") or "").lower()
        async with self._lock:
            targets = []
            for ws, watch in self._clients.items():
                if not watch or fa in watch or ta in watch:
                    targets.append(ws)
        dead = []
        for ws in targets:
            try:
                await ws.send_json({"type": "tx", "item": item})
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.remove(ws)

live = LiveHub()

@app.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket):
    await live.add(ws)
    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg) if msg else {}
            except Exception:
                data = {}
            if "watch" in data and isinstance(data["watch"], list):
                watch = {str(x).strip().lower() for x in data["watch"] if isinstance(x, str)}
                await live.update_watch(ws, watch)
                await ws.send_json({"type": "ack", "watch": sorted(list(watch))})
            else:
                await ws.send_json({"type": "pong"})
    finally:
        await live.remove(ws)

# Tiny HTTP probe so hitting /ws/alerts with GET doesn't 404
@app.get("/ws/alerts", include_in_schema=False)
def ws_alerts_probe():
    return {"ok": True, "hint": "connect with WebSocket at ws(s)://<host>/ws/alerts"}


# =========================
# Email (SendGrid)
# =========================
SENDGRID_KEY = os.getenv("SENDGRID_API_KEY", "").strip()
ALERT_FROM = os.getenv("ALERT_EMAIL_FROM", "").strip()
ALERT_TO = os.getenv("ALERT_EMAIL_TO", "").strip()

def _send_email(subject: str, text: str, to_email: Optional[str] = None) -> Dict[str, Any]:
    recipient = (to_email or ALERT_TO).strip()
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

def notify_if_alert(tagged: TaggedTransaction) -> Dict[str, Any]:
    threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    if (tagged.score or 0) < threshold:
        return {"sent": False, "reason": f"score {tagged.score} < threshold {threshold}"}
    subject = f"[Klerno Labs Alert] {tagged.category or 'unknown'} — risk {round(tagged.score or 0, 3)}"
    lines = [
        f"Time:       {tagged.timestamp}",
        f"Chain:      {tagged.chain}",
        f"Tx ID:      {tagged.tx_id}",
        f"From → To:  {tagged.from_addr} → {tagged.to_addr}",
        f"Amount:     {tagged.amount} {tagged.symbol}",
        f"Direction:  {tagged.direction}",
        f"Fee:        {tagged.fee}",
        f"Category:   {tagged.category}",
        f"Risk Score: {round(tagged.score or 0, 3)}",
        f"Risk Bucket:{_risk_bucket(tagged.score or 0)}",
        f"Flags:      {', '.join(tagged.flags or []) or '—'}",
        f"Notes:      {getattr(tagged, 'notes', '') or '—'}",
    ]
    return _send_email(subject, "\n".join(lines))


# ---------------- Landing & health ----------------
@app.get("/", include_in_schema=False)
def landing(request: Request):
    resp = templates.TemplateResponse("landing.html", {"request": request})
    issue_csrf_cookie(resp)
    return resp

@app.head("/", include_in_schema=False)
def root_head():
    return HTMLResponse(status_code=200)

@app.get("/health")
def health(_auth: bool = Security(enforce_api_key)):
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


# ---------------- UI Login / Signup / Logout ----------------
@app.get("/login", include_in_schema=False)
def login_page(request: Request, error: str | None = None):
    resp = templates.TemplateResponse("login.html", {"request": request, "error": error})
    issue_csrf_cookie(resp)
    return resp

@app.post("/login", include_in_schema=False)
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    e = (email or "").lower().strip()
    user = store.get_user_by_email(e)
    if not user or not verify_pw(password, user["password_hash"]):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"}, status_code=400)
    token = issue_jwt(user["id"], user["email"], user["role"])
    is_paid = bool(user.get("subscription_active")) or user.get("role") == "admin" or DEMO_MODE
    dest = "/dashboard" if is_paid else "/paywall"
    resp = RedirectResponse(url=dest, status_code=303)
    resp.set_cookie(SESSION_COOKIE, token, **_cookie_kwargs(request))
    return resp

@app.get("/signup", include_in_schema=False)
def signup_page(request: Request, error: str | None = None):
    resp = templates.TemplateResponse("signup.html", {"request": request, "error": error})
    issue_csrf_cookie(resp)
    return resp

@app.post("/signup", include_in_schema=False)
def signup_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    e = (email or "").lower().strip()
    if store.get_user_by_email(e):
        return templates.TemplateResponse("signup.html", {"request": request, "error": "User already exists"}, status_code=400)
    role = "viewer"
    sub_active = False
    if e == ADMIN_EMAIL or store.users_count() == 0:
        role, sub_active = "admin", True
    user = store.create_user(e, hash_pw(password), role=role, subscription_active=sub_active)
    token = issue_jwt(user["id"], user["email"], user["role"])
    dest = "/dashboard" if (sub_active or role == "admin" or DEMO_MODE) else "/paywall"
    resp = RedirectResponse(url=dest, status_code=303)
    resp.set_cookie(SESSION_COOKIE, token, **_cookie_kwargs(request))
    return resp

@app.get("/logout", include_in_schema=False)
def logout_ui():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# --- User & Settings API ---
class SettingsPayload(BaseModel):
    x_api_key: Optional[str] = None
    risk_threshold: Optional[float] = None
    time_range_days: Optional[int] = None
    ui_prefs: Optional[Dict[str, Any]] = None

@app.get("/me", include_in_schema=False)
def me(user=Depends(require_user)):
    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "subscription_active": bool(user.get("subscription_active")),
    }

@app.get("/me/settings")
def me_settings_get(user=Depends(require_user)):
    return store.get_settings(user["id"])

@app.post("/me/settings")
def me_settings_post(payload: SettingsPayload, user=Depends(require_user)):
    allowed = {"x_api_key", "risk_threshold", "time_range_days", "ui_prefs"}
    patch = {k: v for k, v in payload.model_dump(exclude_none=True).items() if k in allowed}
    if "risk_threshold" in patch:
        patch["risk_threshold"] = max(0.0, min(1.0, float(patch["risk_threshold"])))
    if "time_range_days" in patch:
        patch["time_range_days"] = max(1, int(patch["time_range_days"]))
    store.save_settings(user["id"], patch)
    settings = store.get_settings(user["id"])
    return {"ok": True, "settings": settings}


# ---------------- Core API ----------------
@app.post("/analyze/tx", response_model=TaggedTransaction)
def analyze_tx(tx: Transaction, _auth: bool = Security(enforce_api_key)):
    risk, flags = score_risk(tx)
    category = tag_category(tx)
    return TaggedTransaction(**_dump(tx), score=risk, flags=flags, category=category)

@app.post("/analyze/batch")
def analyze_batch(txs: List[Transaction], _auth: bool = Security(enforce_api_key)):
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged.append(TaggedTransaction(**_dump(tx), score=risk, flags=flags, category=category))
    return {"summary": summary(tagged).model_dump(), "items": [t.model_dump() for t in tagged]}

@app.post("/report/csv")
def report_csv(req: ReportRequest, _auth: bool = Security(enforce_api_key)):
    df = pd.read_csv(os.path.join(BASE_DIR, "..", "data", "sample_transactions.csv"))
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for col in ("from_addr", "to_addr"):
        if col not in df.columns:
            df[col] = ""
    wallets = set(getattr(req, "wallet_addresses", None) or ([] if not getattr(req, "address", None) else [req.address]))
    start = pd.to_datetime(req.start) if getattr(req, "start", None) else df["timestamp"].min()
    end = pd.to_datetime(req.end) if getattr(req, "end", None) else df["timestamp"].max()
    mask_wallet = True if not wallets else (df["to_addr"].isin(wallets) | df["from_addr"].isin(wallets))
    mask = (df["timestamp"] >= start) & (df["timestamp"] <= end) & mask_wallet
    selected = df[mask].copy()
    tx_field_names = {f.name for f in dc_fields(Transaction)}
    items: List[TaggedTransaction] = []
    for _, row in selected.iterrows():
        raw = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        raw.setdefault("memo", ""); raw.setdefault("notes", "")
        clean = {k: v for k, v in raw.items() if k in tx_field_names}
        tx = Transaction(**clean)
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        items.append(TaggedTransaction(**_dump(tx), score=risk, flags=flags, category=category))
    return {"csv": csv_export(items)}


# ---------------- XRPL parse (posted JSON) ----------------
@app.post("/integrations/xrpl/parse")
def parse_xrpl(account: str, payload: List[Dict[str, Any]], _auth: bool = Security(enforce_api_key)):
    txs = xrpl_json_to_transactions(account, payload)
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged.append(TaggedTransaction(**_dump(tx), score=risk, flags=flags, category=category))
    return {"summary": summary(tagged).model_dump(), "items": [t.model_dump() for t in tagged]}

@app.post("/analyze/sample")
def analyze_sample(_auth: bool = Security(enforce_api_key)):
    data_path = os.path.join(BASE_DIR, "..", "data", "sample_transactions.csv")
    df = pd.read_csv(data_path)
    text_cols = ("memo", "notes", "symbol", "direction", "chain", "tx_id", "from_addr", "to_addr")
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%S")
    for col in ("amount", "fee", "risk_score"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    txs: List[Transaction] = []
    tx_field_names = {f.name for f in dc_fields(Transaction)}
    for _, row in df.iterrows():
        raw = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        raw.setdefault("memo", ""); raw.setdefault("notes", "")
        clean = {k: v for k, v in raw.items() if k in tx_field_names}
        txs.append(Transaction(**clean))
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged.append(TaggedTransaction(**_dump(tx), score=risk, flags=flags, category=category))
    return {"summary": summary(tagged).model_dump(), "items": [t.model_dump() for t in tagged]}


# ---------------- “Memory” (DB) + email on save ----------------
@app.post("/analyze_and_save/tx")
async def analyze_and_save_tx(tx: Transaction, _auth: bool = Security(enforce_api_key)):
    risk, flags = score_risk(tx)
    category = tag_category(tx)
    tagged = TaggedTransaction(**_dump(tx), score=risk, flags=flags, category=category)
    d = tagged.model_dump()
    d["risk_score"] = d.get("score")
    d["risk_flags"] = d.get("flags")
    d["risk_bucket"] = _risk_bucket(d.get("risk_score", 0))
    store.save_tagged(d)
    await live.publish(d)
    email_result = notify_if_alert(tagged)
    return {"saved": True, "item": d, "email": email_result}

@app.get("/transactions/{wallet}")
def get_transactions_for_wallet(wallet: str, limit: int = 100, _auth: bool = Security(enforce_api_key)):
    rows = store.list_by_wallet(wallet, limit=limit)
    return {"wallet": wallet, "count": len(rows), "items": rows}

@app.get("/alerts")
def get_alerts(limit: int = 100, _auth: bool = Security(enforce_api_key)):
    threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    rows = store.list_alerts(threshold, limit=limit)
    return {"threshold": threshold, "count": len(rows), "items": rows}


# ---------------- XRPL fetch (read-only) ----------------
@app.get("/integrations/xrpl/fetch")
def xrpl_fetch(account: str, limit: int = 10, _auth: bool = Security(enforce_api_key)):
    raw = fetch_account_tx(account, limit=limit)
    txs = xrpl_json_to_transactions(account, raw)
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged.append(TaggedTransaction(**_dump(tx), score=risk, flags=flags, category=category))
    return {"count": len(tagged), "items": [t.model_dump() for t in tagged]}

@app.post("/integrations/xrpl/fetch_and_save")
async def xrpl_fetch_and_save(account: str, limit: int = 10, _auth: bool = Security(enforce_api_key)):
    raw = fetch_account_tx(account, limit=limit)
    txs = xrpl_json_to_transactions(account, raw)
    saved = 0
    tagged_items: List[Dict[str, Any]] = []
    emails: List[Dict[str, Any]] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged = TaggedTransaction(**_dump(tx), score=risk, flags=flags, category=category)
        d = tagged.model_dump()
        d["risk_score"] = d.get("score")
        d["risk_flags"] = d.get("flags")
        d["risk_bucket"] = _risk_bucket(d.get("risk_score", 0))
        store.save_tagged(d)
        saved += 1
        tagged_items.append(d)
        emails.append(notify_if_alert(tagged))
        await live.publish(d)
    return {
        "account": account,
        "requested": limit,
        "fetched": len(txs),
        "saved": saved,
        "threshold": float(os.getenv("RISK_THRESHOLD", "0.75")),
        "items": tagged_items,
        "emails": emails,
    }


# ---------------- CSV export (DB) ----------------
@app.get("/export/csv")
def export_csv_from_db(wallet: str | None = None, limit: int = 1000, _auth: bool = Security(enforce_api_key)):
    rows = store.list_by_wallet(wallet, limit=limit) if wallet else store.list_all(limit=limit)
    if not rows:
        return {"rows": 0, "csv": ""}
    df = pd.DataFrame(rows)
    return {"rows": len(rows), "csv": df.to_csv(index=False)}


# ---- helper: allow ?key=... or x-api-key header for download ----
def _check_key_param_or_header(key: Optional[str] = None, x_api_key: Optional[str] = Header(default=None)):
    exp = expected_api_key() or ""
    incoming = (key or "").strip() or (x_api_key or "").strip()
    if exp and incoming != exp:
        raise HTTPException(status_code=401, detail="unauthorized")

@app.get("/export/csv/download")
def export_csv_download(wallet: str | None = None, limit: int = 1000, key: Optional[str] = None, x_api_key: Optional[str] = Header(None)):
    _check_key_param_or_header(key=key, x_api_key=x_api_key)
    rows = store.list_by_wallet(wallet, limit=limit) if wallet else store.list_all(limit=limit)
    df = pd.DataFrame(rows)
    buf = StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(iter([buf.read()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=klerno-export.csv"})


# ---------------- CSV export (UI, session-protected) ----------------
@app.get("/uiapi/export/csv/download", include_in_schema=False)
def ui_export_csv_download(
    wallet: str | None = None,
    limit: int = 1000,
    _user = Depends(require_paid_or_admin),
):
    rows = store.list_by_wallet(wallet, limit=limit) if wallet else store.list_all(limit=limit)
    df = pd.DataFrame(rows)
    buf = StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=klerno-export.csv"},
    )


# ---------------- Metrics (JSON) ----------------

# tiny in-proc TTL cache to avoid heavy recompute
_METRICS_CACHE: Dict[Tuple[Optional[float], Optional[int]], Tuple[float, Dict[str, Any]]] = {}
_METRICS_TTL_SEC = 5.0

def _metrics_cached(threshold: Optional[float], days: Optional[int]) -> Optional[Dict[str, Any]]:
    key = (threshold, days)
    item = _METRICS_CACHE.get(key)
    now = datetime.utcnow().timestamp()
    if item and (now - item[0]) <= _METRICS_TTL_SEC:
        return item[1]
    return None

def _metrics_put(threshold: Optional[float], days: Optional[int], data: Dict[str, Any]):
    key = (threshold, days)
    _METRICS_CACHE[key] = (datetime.utcnow().timestamp(), data)

@app.get("/metrics")
def metrics(threshold: float | None = None, days: int | None = None, _auth: bool = Security(enforce_api_key)):
    cached = _metrics_cached(threshold, days)
    if cached is not None:
        return cached

    rows = store.list_all(limit=10000)
    if not rows:
        data = {"total": 0, "alerts": 0, "avg_risk": 0, "categories": {}, "series_by_day": [], "series_by_day_lmh": []}
        _metrics_put(threshold, days, data)
        return data

    env_threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    thr = env_threshold if threshold is None else float(threshold)
    thr = max(0.0, min(1.0, thr))

    cutoff = None
    if days is not None:
        try:
            d = max(1, min(int(days), 365))
            cutoff = datetime.utcnow() - timedelta(days=d)
        except Exception:
            cutoff = None

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["risk_score"] = df.apply(lambda rr: _row_score(rr), axis=1)
    if cutoff is not None:
        df = df[df["timestamp"] >= cutoff]
    if df.empty:
        data = {"total": 0, "alerts": 0, "avg_risk": 0, "categories": {}, "series_by_day": [], "series_by_day_lmh": []}
        _metrics_put(threshold, days, data)
        return data

    total = int(len(df))
    alerts = int((df["risk_score"] >= thr).sum())
    avg_risk = float(df["risk_score"].mean())

    # categories
    categories: Dict[str, int] = {}
    cats_series = (df["category"].fillna("unknown") if "category" in df.columns else pd.Series(["unknown"] * total))
    for cat, cnt in cats_series.value_counts().items():
        categories[str(cat)] = int(cnt)

    df["day"] = df["timestamp"].dt.date
    grp = df.groupby("day").agg(avg_risk=("risk_score", "mean")).reset_index()
    series = [{"date": str(d), "avg_risk": round(float(v), 3)} for d, v in zip(grp["day"], grp["avg_risk"])]

    # Low/Med/High daily counts for stacked chart
    df["bucket"] = df["risk_score"].apply(_risk_bucket)
    crosstab = df.pivot_table(index="day", columns="bucket", values="risk_score", aggfunc="count").fillna(0)
    crosstab = crosstab.reindex(sorted(crosstab.index))
    series_lmh = []
    for d, row in crosstab.iterrows():
        series_lmh.append({
            "date": str(d),
            "low": int(row.get("low", 0)),
            "medium": int(row.get("medium", 0)),
            "high": int(row.get("high", 0)),
        })

    data = {"total": total, "alerts": alerts, "avg_risk": round(avg_risk, 3), "categories": categories, "series_by_day": series, "series_by_day_lmh": series_lmh}
    _metrics_put(threshold, days, data)
    return data


# ---------------- UI API (session-protected; no x-api-key) ----------------
@app.get("/metrics-ui", include_in_schema=False)
def metrics_ui(
    threshold: float | None = None,
    days: int | None = None,
    _user=Depends(require_paid_or_admin),
):
    resp = FastJSON(content=metrics(threshold=threshold, days=days, _auth=True))
    # short client-side caching to cut churn
    resp.headers["Cache-Control"] = "private, max-age=10"
    return resp

@app.get("/alerts-ui/data", include_in_schema=False)
def alerts_ui_data(limit: int = 100, _user=Depends(require_paid_or_admin)):
    threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    rows = store.list_alerts(threshold, limit=limit)
    return {"threshold": threshold, "count": len(rows), "items": rows}

# Save demo/sample data to DB so dashboard shows data, and live-push
@app.post("/uiapi/analyze/sample", include_in_schema=False)
async def ui_analyze_sample(_user=Depends(require_paid_or_admin), _=Depends(csrf_protect_ui)):
    data_path = os.path.join(BASE_DIR, "..", "data", "sample_transactions.csv")
    df = pd.read_csv(data_path)

    text_cols = ("memo", "notes", "symbol", "direction", "chain", "tx_id", "from_addr", "to_addr")
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%S")

    for col in ("amount", "fee", "risk_score"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    tx_field_names = {f.name for f in dc_fields(Transaction)}
    tagged: List[TaggedTransaction] = []
    saved = 0

    for _, row in df.iterrows():
        raw = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        raw.setdefault("memo", ""); raw.setdefault("notes", "")
        clean = {k: v for k, v in raw.items() if k in tx_field_names}
        tx = Transaction(**clean)

        risk, flags = score_risk(tx)
        category = tag_category(tx)
        t = TaggedTransaction(**_dump(tx), score=risk, flags=flags, category=category)
        tagged.append(t)

        d = t.model_dump()
        d["risk_score"] = d.get("score")
        d["risk_flags"] = d.get("flags")
        d["risk_bucket"] = _risk_bucket(d.get("risk_score", 0))
        store.save_tagged(d)
        saved += 1
        await live.publish(d)

    return {"summary": summary(tagged).model_dump(), "saved": saved, "items": [t.model_dump() for t in tagged]}

# Session-protected XRPL fetch used by the dashboard button
@app.post("/uiapi/integrations/xrpl/fetch_and_save", include_in_schema=False)
async def ui_xrpl_fetch_and_save(account: str, limit: int = 10, _user=Depends(require_paid_or_admin), _=Depends(csrf_protect_ui)):
    raw = fetch_account_tx(account, limit=limit)
    txs = xrpl_json_to_transactions(account, raw)
    saved = 0
    tagged_items: List[Dict[str, Any]] = []
    emails: List[Dict[str, Any]] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged = TaggedTransaction(**_dump(tx), score=risk, flags=flags, category=category)
        d = tagged.model_dump()
        d["risk_score"] = d.get("score")
        d["risk_flags"] = d.get("flags")
        d["risk_bucket"] = _risk_bucket(d.get("risk_score", 0))
        store.save_tagged(d)
        saved += 1
        tagged_items.append(d)
        emails.append(notify_if_alert(tagged))
        await live.publish(d)
    return {
        "account": account,
        "requested": limit,
        "fetched": len(txs),
        "saved": saved,
        "threshold": float(os.getenv("RISK_THRESHOLD", "0.75")),
        "items": tagged_items,
        "emails": emails,
    }

# Recent items for the dashboard (all or only alerts)
@app.get("/uiapi/recent", include_in_schema=False)
def ui_recent(limit: int = 50, only_alerts: bool = False, _user=Depends(require_paid_or_admin)):
    if only_alerts:
        thr = float(os.getenv("RISK_THRESHOLD", "0.75"))
        rows = store.list_alerts(threshold=thr, limit=limit)
    else:
        rows = store.list_all(limit=limit)
    return {"items": rows}

# Powerful transactions search for folders + filters UI
@app.get("/uiapi/transactions/search", include_in_schema=False)
def ui_search_transactions(
    wallet_from: Optional[str] = None,
    wallet_to: Optional[str] = None,
    tx_type: Optional[str] = None,   # 'sale'|'purchase' -> 'out'|'in'; or 'in'|'out'
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    category: Optional[str] = None,
    risk_bucket: Optional[str] = None,  # low|medium|high
    limit: int = 1000,
    _user=Depends(require_paid_or_admin),
):
    rows = store.list_all(limit=10000)

    def _type_ok(r):
        if not tx_type: return True
        t = tx_type.lower().strip()
        want = {"sale": "out", "purchase": "in"}.get(t, t)
        return str(r.get("direction","")).lower() == want

    def _between_dt(r):
        ts = _safe_dt(r.get("timestamp"))
        if date_from and ts < _safe_dt(date_from): return False
        if date_to and ts > _safe_dt(date_to): return False
        return True

    def _amt_ok(r):
        a = float(r.get("amount") or 0)
        if min_amount is not None and a < float(min_amount): return False
        if max_amount is not None and a > float(max_amount): return False
        return True

    def _bucket_ok(r):
        if not risk_bucket: return True
        b = r.get("risk_bucket") or _risk_bucket(_row_score(r))
        return str(b).lower() == risk_bucket.lower()

    sel = []
    for r in rows:
        if wallet_from and str(r.get("from_addr","")).lower() != wallet_from.lower(): continue
        if wallet_to   and str(r.get("to_addr","")).lower()   != wallet_to.lower():   continue
        if category and str(r.get("category","")).lower() != category.lower():       continue
        if not _type_ok(r): continue
        if not _between_dt(r): continue
        if not _amt_ok(r): continue
        if not _bucket_ok(r): continue
        sel.append(r)

    sel.sort(key=lambda x: _safe_dt(x.get("timestamp")), reverse=True)
    return {"count": len(sel[:limit]), "items": sel[:limit]}

# Profile / Transactions / Years + QuickBooks export
@app.get("/uiapi/profile/years", include_in_schema=False)
def ui_profile_years(_user=Depends(require_paid_or_admin)):
    rows = store.list_all(limit=50000)
    years = set()
    cutoff = datetime.utcnow() - timedelta(days=730)  # 2 years window
    for r in rows:
        ts = _safe_dt(r.get("timestamp"))
        if ts >= cutoff:
            years.add(ts.year)
    return {"years": sorted(years, reverse=True)}

@app.get("/uiapi/profile/year/{year}", include_in_schema=False)
def ui_profile_year(year: int, limit: int = 10000, _user=Depends(require_paid_or_admin)):
    rows = store.list_all(limit=50000)
    yr_rows = []
    for r in rows:
        ts = _safe_dt(r.get("timestamp"))
        if ts.year == int(year):
            yr_rows.append(r)
    yr_rows.sort(key=lambda x: _safe_dt(x.get("timestamp")), reverse=True)
    return {"year": int(year), "count": len(yr_rows[:limit]), "items": yr_rows[:limit]}

@app.get("/uiapi/profile/year/{year}/export", include_in_schema=False)
def ui_profile_year_export(year: int, format: str = "qb", _user=Depends(require_paid_or_admin)):
    rows = ui_profile_year(year=year, _user=_user)["items"]
    if not rows:
        return StreamingResponse(iter([""]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=Transactions-{year}.csv"})
    df = pd.DataFrame(rows)

    for c in ("timestamp","tx_id","from_addr","to_addr","amount","symbol","direction","fee","category","memo","notes","risk_score"):
        if c not in df.columns: df[c] = None

    out = pd.DataFrame({
        "Date": pd.to_datetime(df["timestamp"], errors="coerce").dt.strftime("%Y-%m-%d"),
        "Time": pd.to_datetime(df["timestamp"], errors="coerce").dt.strftime("%H:%M:%S"),
        "Type": df["direction"].fillna(""),
        "From": df["from_addr"].fillna(""),
        "To": df["to_addr"].fillna(""),
        "Amount": pd.to_numeric(df["amount"], errors="coerce").fillna(0.0),
        "Currency": df["symbol"].fillna(""),
        "Fee": pd.to_numeric(df["fee"], errors="coerce").fillna(0.0),
        "Category": df["category"].fillna("unknown"),
        "Risk Score": df["risk_score"].apply(lambda x: float(x) if pd.notna(x) else 0.0),
        "Risk Bucket": df["risk_score"].apply(lambda x: _risk_bucket(x if pd.notna(x) else 0.0)),
        "Description": df["memo"].fillna("") + (" " + df["notes"].fillna("")),
        "Tx ID": df["tx_id"].fillna(""),
    })

    buf = StringIO()
    out.to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=Transactions-{year}-QuickBooks.csv"},
    )


# ---------------- UI: Dashboard & Alerts ----------------
@app.get("/dashboard", name="ui_dashboard", include_in_schema=False)
def ui_dashboard(request: Request, _user=Depends(require_paid_or_admin)):
    rows = store.list_all(limit=200)
    total = len(rows)
    threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    alerts = [r for r in rows if _row_score(r) >= threshold]
    avg_risk = round(sum(_row_score(r) for r in rows) / total, 3) if total else 0.0
    cats: Dict[str, int] = {}
    for r in rows:
        c = r.get("category") or "unknown"
        cats[c] = cats.get(c, 0) + 1
    metrics_data = {"total": total, "alerts": len(alerts), "avg_risk": avg_risk, "categories": cats}
    resp = templates.TemplateResponse("dashboard.html", {
        "request": request,
        "title": "Dashboard",
        "key": None,
        "metrics": metrics_data,
        "rows": rows,
        "threshold": threshold
    })
    issue_csrf_cookie(resp)
    return resp

@app.get("/alerts-ui", name="ui_alerts", include_in_schema=False)
def ui_alerts(request: Request, _user=Depends(require_paid_or_admin)):
    threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    rows = store.list_alerts(threshold=threshold, limit=500)
    return templates.TemplateResponse("alerts.html", {"request": request, "title": f"Alerts (≥ {threshold})", "key": None, "rows": rows})


# ---------------- Admin / Email tests ----------------
@app.get("/admin/test-email", include_in_schema=False)
def admin_test_email(request: Request):
    key = request.query_params.get("key") or ""
    expected = expected_api_key() or ""
    if key != expected:
        return HTMLResponse(content="Unauthorized. Append ?key=YOUR_API_KEY", status_code=401)
    tx = Transaction(
        tx_id="TEST-ALERT-123",
        timestamp=datetime.utcnow().isoformat(),
        chain="XRPL",
        from_addr="rTEST_FROM",
        to_addr="rTEST_TO",
        amount=123.45,
        symbol="XRP",
        direction="out",
        memo="Test email",
        fee=0.0001,
    )
    tagged = TaggedTransaction(**_dump(tx), score=0.99, flags=["test_high_risk"], category="test-alert")
    return {"ok": True, "email": notify_if_alert(tagged)}

class NotifyRequest(BaseModel):
    email: EmailStr

@app.post("/notify/test")
def notify_test(payload: NotifyRequest = Body(...), _auth: bool = Security(enforce_api_key)):
    return _send_email("Klerno Labs Test", "✅ Your Klerno Labs email system is working!", payload.email)


# ---------------- Debug ----------------
@app.get("/_debug/api_key")
def debug_api_key(x_api_key: str | None = Header(default=None)):
    exp = expected_api_key()
    preview = (exp[:4] + "..." + exp[-4:]) if exp else ""
    return {"received_header": x_api_key, "expected_loaded_from_env": bool(exp), "expected_length": len(exp or ""), "expected_preview": preview}

@app.get("/_debug/routes", include_in_schema=False)
def list_routes():
    return {"routes": [r.path for r in app.router.routes]}


# ---------------- LLM Explain & AI Endpoints ----------------
class AskRequest(BaseModel):
    question: str

class BatchTx(BaseModel):
    items: List[Transaction]

@app.post("/explain/tx")
def explain_tx_endpoint(tx: Transaction, _auth: bool = Security(enforce_api_key)):
    try:
        text = explain_tx(_dump(tx))
        return {"explanation": text}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/explain/batch")
def explain_batch_endpoint(payload: BatchTx, _auth: bool = Security(enforce_api_key)):
    try:
        txs = [_dump(t) for t in payload.items]
        result = explain_batch(txs)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/ask")
def ask_endpoint(req: AskRequest, _auth: bool = Security(enforce_api_key)):
    try:
        rows = store.list_all(limit=10000)
        spec = ask_to_filters(req.question)
        filtered = _apply_filters_safe(rows, spec)
        answer = explain_selection(req.question, filtered)
        preview = filtered[:50]
        return {"filters": spec, "count": len(filtered), "preview": preview, "answer": answer}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/explain/summary")
def explain_summary(days: int = 7, wallet: str | None = None, _auth: bool = Security(enforce_api_key)):
    try:
        rows = store.list_by_wallet(wallet, limit=5000) if wallet else store.list_all(limit=5000)
        cutoff = datetime.utcnow() - timedelta(days=max(1, min(days, 90)))
        recent = []
        for r in rows:
            try:
                t = datetime.fromisoformat(str(r.get("timestamp")))
                if t >= cutoff:
                    recent.append(r)
            except Exception:
                continue
        return summarize_rows(recent, title=f"Last {days} days summary")
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# NLQ → filters + AI search wrappers (session-protected for UI)
class NLQRequest(BaseModel):
    query: str

@app.post("/ai/nlq-to-filters", include_in_schema=False)
def ai_nlq_to_filters(req: NLQRequest, _user=Depends(require_paid_or_admin)):
    try:
        spec = ask_to_filters(req.query)
        return {"filters": spec}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/ai/search", include_in_schema=False)
def ai_search(req: NLQRequest, _user=Depends(require_paid_or_admin)):
    try:
        spec = ask_to_filters(req.query)
        rows = store.list_all(limit=10000)
        filtered = _apply_filters_safe(rows, spec)
        return {"filters": spec, "count": len(filtered), "items": filtered[:1000]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# simple anomaly scoring (z-score on amounts)
@app.get("/ai/anomaly/scores", include_in_schema=False)
def ai_anomaly_scores(limit: int = 100, _user=Depends(require_paid_or_admin)):
    rows = store.list_all(limit=20000)
    if not rows: return {"count": 0, "items": []}
    df = pd.DataFrame(rows)
    if "amount" not in df.columns: return {"count": 0, "items": []}
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    if df["amount"].std(ddof=0) == 0:
        df["anomaly_score"] = 0.0
    else:
        df["anomaly_score"] = (df["amount"] - df["amount"].mean()) / (df["amount"].std(ddof=0) or 1)
    df["anomaly_score"] = df["anomaly_score"].abs()
    df.sort_values(["anomaly_score", "timestamp"], ascending=[False, False], inplace=True)
    items = df.head(limit).to_dict(orient="records")
    return {"count": len(items), "items": items}