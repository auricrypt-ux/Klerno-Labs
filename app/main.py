# app/main.py
from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
from typing import List, Dict, Any, Optional

import os
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
        out = [r for r in out if str(r.get(k, "")).lower() == str(v).lower()]
    return out


def _dump(obj: Any) -> Dict[str, Any]:
    """Return a dict from either a Pydantic model or a dataclass (or mapping-like)."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if is_dataclass(obj):
        return asdict(obj)
    try:
        return dict(obj)  # last-ditch
    except Exception:
        return {"value": obj}


# =========================
# FastAPI app + templates
# =========================
app = FastAPI(title="Klerno Labs API (MVP) — XRPL First")

# Static & templates
BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.globals["url_path_for"] = app.url_path_for

# Config flags for UI auth redirects
ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

# Include routers
from . import paywall  # noqa: E402
app.include_router(paywall.router)
app.include_router(auth_router.router)
app.include_router(paywall_hooks.router)
app.include_router(analyze_tags_router)

# Init DB
store.init_db()


# =========================
# Email (SendGrid)
# =========================
SENDGRID_KEY = os.getenv("SENDGRID_API_KEY", "").strip()
ALERT_FROM = os.getenv("ALERT_EMAIL_FROM", "").strip()
ALERT_TO = os.getenv("ALERT_EMAIL_TO", "").strip()


def _send_email(subject: str, text: str, to_email: Optional[str] = None) -> Dict[str, Any]:
    """Send email via SendGrid. Returns diagnostic dict (never raises)."""
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
    """If risk >= threshold, email an alert."""
    threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    if (tagged.risk_score or 0) < threshold:
        return {"sent": False, "reason": f"risk_score {tagged.risk_score} < threshold {threshold}"}

    subject = f"[Klerno Labs Alert] {tagged.category or 'unknown'} — risk {round(tagged.risk_score or 0, 3)}"
    lines = [
        f"Time:       {tagged.timestamp}",
        f"Chain:      {tagged.chain}",
        f"Tx ID:      {tagged.tx_id}",
        f"From → To:  {tagged.from_addr} → {tagged.to_addr}",
        f"Amount:     {tagged.amount} {tagged.symbol}",
        f"Direction:  {tagged.direction}",
        f"Fee:        {tagged.fee}",
        f"Category:   {tagged.category}",
        f"Risk Score: {round(tagged.risk_score or 0, 3)}",
        f"Flags:      {', '.join(tagged.risk_flags or []) or '—'}",
        f"Notes:      {getattr(tagged, 'notes', '') or '—'}",
    ]
    return _send_email(subject, "\n".join(lines))


# ---------------- Landing & health ----------------
@app.get("/", include_in_schema=False)
def landing(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})


@app.head("/", include_in_schema=False)
def root_head():
    # Satisfy Render's HEAD check with 200
    return HTMLResponse(status_code=200)


@app.get("/health")
def health(auth: bool = Security(enforce_api_key)):
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


# ---------------- UI Login / Signup / Logout ----------------
@app.get("/login", include_in_schema=False)
def login_page(request: Request, error: str | None = None):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@app.post("/login", include_in_schema=False)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):
    e = (email or "").lower().strip()
    user = store.get_user_by_email(e)
    if not user or not verify_pw(password, user["password_hash"]):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid credentials"},
            status_code=400,
        )
    token = issue_jwt(user["id"], user["email"], user["role"])
    is_paid = bool(user.get("subscription_active")) or user.get("role") == "admin" or DEMO_MODE
    dest = "/dashboard" if is_paid else "/paywall"
    resp = RedirectResponse(url=dest, status_code=303)
    # secure=True is fine on Render (HTTPS); switch to False only for local HTTP testing
    resp.set_cookie("session", token, httponly=True, secure=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return resp


@app.get("/signup", include_in_schema=False)
def signup_page(request: Request, error: str | None = None):
    return templates.TemplateResponse("signup.html", {"request": request, "error": error})


@app.post("/signup", include_in_schema=False)
def signup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):
    e = (email or "").lower().strip()
    if store.get_user_by_email(e):
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "error": "User already exists"},
            status_code=400,
        )
    role = "viewer"
    sub_active = False
    # Bootstrap: first user or ADMIN_EMAIL becomes admin + active sub
    if e == ADMIN_EMAIL or store.users_count() == 0:
        role, sub_active = "admin", True
    user = store.create_user(e, hash_pw(password), role=role, subscription_active=sub_active)
    token = issue_jwt(user["id"], user["email"], user["role"])
    dest = "/dashboard" if (sub_active or role == "admin" or DEMO_MODE) else "/paywall"
    resp = RedirectResponse(url=dest, status_code=303)
    resp.set_cookie("session", token, httponly=True, secure=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return resp


@app.get("/logout", include_in_schema=False)
def logout_ui():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("session")
    return resp


# ---------------- Core API ----------------
@app.post("/analyze/tx", response_model=TaggedTransaction)
def analyze_tx(tx: Transaction, auth: bool = Security(enforce_api_key)):
    risk, flags = score_risk(tx)
    category = tag_category(tx)
    return TaggedTransaction(**_dump(tx), risk_score=risk, risk_flags=flags, category=category)


@app.post("/analyze/batch")
def analyze_batch(txs: List[Transaction], auth: bool = Security(enforce_api_key)):
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged.append(TaggedTransaction(**_dump(tx), risk_score=risk, risk_flags=flags, category=category))
    return {"summary": summary(tagged).model_dump(), "items": [t.model_dump() for t in tagged]}


@app.post("/report/csv")
def report_csv(req: ReportRequest, auth: bool = Security(enforce_api_key)):
    df = pd.read_csv(os.path.join(BASE_DIR, "..", "data", "sample_transactions.csv"))

    # normalize timestamp to datetime for filtering
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    # Basic guards for missing fields
    for col in ("from_addr", "to_addr"):
        if col not in df.columns:
            df[col] = ""

    # Support both wallet_addresses and single address field
    wallets = set(getattr(req, "wallet_addresses", None) or ([] if not getattr(req, "address", None) else [req.address]))

    start = pd.to_datetime(req.start) if getattr(req, "start", None) else df["timestamp"].min()
    end = pd.to_datetime(req.end) if getattr(req, "end", None) else df["timestamp"].max()

    mask_wallet = True if not wallets else (df["to_addr"].isin(wallets) | df["from_addr"].isin(wallets))
    mask = (df["timestamp"] >= start) & (df["timestamp"] <= end) & mask_wallet
    selected = df[mask].copy()

    # Build Transaction safely: keep only dataclass fields
    tx_field_names = {f.name for f in dc_fields(Transaction)}
    items: List[TaggedTransaction] = []
    for _, row in selected.iterrows():
        raw = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        raw.setdefault("memo", "")
        raw.setdefault("notes", "")
        clean = {k: v for k, v in raw.items() if k in tx_field_names}
        tx = Transaction(**clean)
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        items.append(TaggedTransaction(**_dump(tx), risk_score=risk, risk_flags=flags, category=category))

    return {"csv": csv_export(items)}


# ---------------- XRPL parse (posted JSON) ----------------
@app.post("/integrations/xrpl/parse")
def parse_xrpl(account: str, payload: List[Dict[str, Any]], auth: bool = Security(enforce_api_key)):
    txs = xrpl_json_to_transactions(account, payload)
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged.append(TaggedTransaction(**_dump(tx), risk_score=risk, risk_flags=flags, category=category))
    return {"summary": summary(tagged).model_dump(), "items": [t.model_dump() for t in tagged]}


@app.post("/analyze/sample")
def analyze_sample(auth: bool = Security(enforce_api_key)):
    data_path = os.path.join(BASE_DIR, "..", "data", "sample_transactions.csv")
    df = pd.read_csv(data_path)

    # Coerce text columns and normalize
    text_cols = ("memo", "notes", "symbol", "direction", "chain", "tx_id", "from_addr", "to_addr")
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)

    # Normalize timestamp (Pydantic can parse ISO strings)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%S")

    # Numeric
    for col in ("amount", "fee", "risk_score"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Build transactions (dataclass)
    txs: List[Transaction] = []
    tx_field_names = {f.name for f in dc_fields(Transaction)}
    for _, row in df.iterrows():
        raw = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        raw.setdefault("memo", "")
        raw.setdefault("notes", "")
        clean = {k: v for k, v in raw.items() if k in tx_field_names}
        txs.append(Transaction(**clean))

    # Score + tag
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged.append(TaggedTransaction(**_dump(tx), risk_score=risk, risk_flags=flags, category=category))

    return {"summary": summary(tagged).model_dump(), "items": [t.model_dump() for t in tagged]}


# ---------------- “Memory” (DB) + email on save ----------------
@app.post("/analyze_and_save/tx")
def analyze_and_save_tx(tx: Transaction, auth: bool = Security(enforce_api_key)):
    risk, flags = score_risk(tx)
    category = tag_category(tx)
    tagged = TaggedTransaction(**_dump(tx), risk_score=risk, risk_flags=flags, category=category)
    store.save_tagged(tagged.model_dump())
    email_result = notify_if_alert(tagged)
    return {"saved": True, "item": tagged.model_dump(), "email": email_result}


@app.get("/transactions/{wallet}")
def get_transactions_for_wallet(wallet: str, limit: int = 100, auth: bool = Security(enforce_api_key)):
    rows = store.list_by_wallet(wallet, limit=limit)
    return {"wallet": wallet, "count": len(rows), "items": rows}


@app.get("/alerts")
def get_alerts(limit: int = 100, auth: bool = Security(enforce_api_key)):
    threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    rows = store.list_alerts(threshold, limit=limit)
    return {"threshold": threshold, "count": len(rows), "items": rows}


# ---------------- XRPL fetch (read-only) ----------------
@app.get("/integrations/xrpl/fetch")
def xrpl_fetch(account: str, limit: int = 10, auth: bool = Security(enforce_api_key)):
    raw = fetch_account_tx(account, limit=limit)
    txs = xrpl_json_to_transactions(account, raw)
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged.append(TaggedTransaction(**_dump(tx), risk_score=risk, risk_flags=flags, category=category))
    return {"count": len(tagged), "items": [t.model_dump() for t in tagged]}


@app.post("/integrations/xrpl/fetch_and_save")
def xrpl_fetch_and_save(account: str, limit: int = 10, auth: bool = Security(enforce_api_key)):
    raw = fetch_account_tx(account, limit=limit)
    txs = xrpl_json_to_transactions(account, raw)
    saved = 0
    tagged_items: List[Dict[str, Any]] = []
    emails: List[Dict[str, Any]] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged = TaggedTransaction(**_dump(tx), risk_score=risk, risk_flags=flags, category=category)
        store.save_tagged(tagged.model_dump())
        saved += 1
        tagged_items.append(tagged.model_dump())
        emails.append(notify_if_alert(tagged))
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
def export_csv_from_db(wallet: str | None = None, limit: int = 1000, auth: bool = Security(enforce_api_key)):
    rows = store.list_by_wallet(wallet, limit=limit) if wallet else store.list_all(limit=limit)
    if not rows:
        return {"rows": 0, "csv": ""}
    df = pd.DataFrame(rows)
    return {"rows": len(rows), "csv": df.to_csv(index=False)}


# ---- helper: allow ?key=... or x-api-key header for download ----
def _check_key_param_or_header(key: Optional[str] = None, x_api_key: Optional[str] = Header(default=None)):
    """Allow auth via ?key=... or x-api-key header (used by dashboard's window.open)."""
    exp = expected_api_key() or ""
    incoming = (key or "").strip() or (x_api_key or "").strip()
    if exp and incoming != exp:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/export/csv/download")
def export_csv_download(
    wallet: str | None = None,
    limit: int = 1000,
    key: Optional[str] = None,
    x_api_key: Optional[str] = Header(None),
):
    _check_key_param_or_header(key=key, x_api_key=x_api_key)

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
@app.get("/metrics")
def metrics(auth: bool = Security(enforce_api_key)):
    rows = store.list_all(limit=10000)
    total = len(rows)
    if total == 0:
        return {"total": 0, "alerts": 0, "avg_risk": 0, "categories": {}, "series_by_day": []}
    threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    alerts = [r for r in rows if (r.get("risk_score") or 0) >= threshold]
    avg_risk = sum((r.get("risk_score") or 0) for r in rows) / total
    categories: Dict[str, int] = {}
    for r in rows:
        cat = r.get("category") or "unknown"
        categories[cat] = categories.get(cat, 0) + 1
    try:
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df["risk_score"] = pd.to_numeric(df["risk_score"], errors="coerce").fillna(0.0)
        df["day"] = df["timestamp"].dt.date
        grp = df.groupby("day").agg(avg_risk=("risk_score", "mean")).reset_index()
        series = [{"date": str(d), "avg_risk": round(float(v), 3)} for d, v in zip(grp["day"], grp["avg_risk"])]
    except Exception:
        series = []
    return {
        "total": total,
        "alerts": len(alerts),
        "avg_risk": round(avg_risk, 3),
        "categories": categories,
        "series_by_day": series,
    }


# ---------------- UI: Dashboard & Alerts ----------------
@app.get("/dashboard", name="ui_dashboard", include_in_schema=False)
def ui_dashboard(request: Request, user=Depends(require_paid_or_admin)):
    rows = store.list_all(limit=200)
    total = len(rows)
    threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    alerts = [r for r in rows if (r.get("risk_score") or 0) >= threshold]
    avg_risk = round(sum((r.get("risk_score") or 0) for r in rows) / total, 3) if total else 0.0
    cats: Dict[str, int] = {}
    for r in rows:
        c = r.get("category") or "unknown"
        cats[c] = cats.get(c, 0) + 1
    metrics_data = {"total": total, "alerts": len(alerts), "avg_risk": avg_risk, "categories": cats}
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "title": "Dashboard", "key": None, "metrics": metrics_data, "rows": rows, "threshold": threshold},
    )


@app.get("/alerts-ui", name="ui_alerts", include_in_schema=False)
def ui_alerts(request: Request, user=Depends(require_paid_or_admin)):
    threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    rows = store.list_alerts(threshold=threshold, limit=500)
    return templates.TemplateResponse(
        "alerts.html", {"request": request, "title": f"Alerts (≥ {threshold})", "key": None, "rows": rows}
    )


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
    risk, flags = 0.99, ["test_high_risk"]
    tagged = TaggedTransaction(**_dump(tx), risk_score=risk, risk_flags=flags, category="test-alert")
    return {"ok": True, "email": notify_if_alert(tagged)}


class NotifyRequest(BaseModel):
    email: EmailStr


@app.post("/notify/test")
def notify_test(payload: NotifyRequest = Body(...), auth: bool = Security(enforce_api_key)):
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
def explain_tx_endpoint(tx: Transaction, auth: bool = Security(enforce_api_key)):
    try:
        text = explain_tx(_dump(tx))
        return {"explanation": text}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/explain/batch")
def explain_batch_endpoint(payload: BatchTx, auth: bool = Security(enforce_api_key)):
    try:
        txs = [_dump(t) for t in payload.items]
        result = explain_batch(txs)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/ask")
def ask_endpoint(req: AskRequest, auth: bool = Security(enforce_api_key)):
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
def explain_summary(days: int = 7, wallet: str | None = None, auth: bool = Security(enforce_api_key)):
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
