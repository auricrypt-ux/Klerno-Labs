# app/main.py
from datetime import datetime
from io import StringIO
from typing import List, Dict, Any, Optional

import os
import pandas as pd
from fastapi import FastAPI, Security, Header, Request, Body
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr

from . import store
from .models import Transaction, TaggedTransaction, ReportRequest
from .guardian import score_risk
from .compliance import tag_category
from .reporter import csv_export, summary
from .integrations.xrp import xrpl_json_to_transactions, fetch_account_tx
from .security import enforce_api_key, expected_api_key

# =========================
# Email (SendGrid)
# =========================
SENDGRID_KEY = os.getenv("SENDGRID_API_KEY", "").strip()
ALERT_FROM = os.getenv("ALERT_EMAIL_FROM", "").strip()
ALERT_TO = os.getenv("ALERT_EMAIL_TO", "").strip()

def _send_email(subject: str, text: str, to_email: Optional[str] = None) -> Dict[str, Any]:
    """Send email via SendGrid. Returns diagnostic dict (never raises)."""
    recipient = to_email or ALERT_TO
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

    subject = f"[Custowell Alert] {tagged.category or 'unknown'} — risk {round(tagged.risk_score or 0, 3)}"
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
        f"Notes:      {tagged.notes or '—'}",
    ]
    return _send_email(subject, "\n".join(lines))

# =========================
# FastAPI
# =========================
app = FastAPI(title="Custowell Copilot API (MVP) — XRPL First")

# Templates (for dashboard/alerts UI)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
templates.env.globals["url_path_for"] = app.url_path_for

# Init DB
store.init_db()

# ---------------- Home (Quick Links) ----------------
@app.get("/", include_in_schema=False)
def home():
    html = """
    <!doctype html><html><head><meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width,initial-scale=1"/>
    <title>Custowell Copilot — Quick Links</title>
    <style>body{font-family:system-ui,sans-serif;background:#0b1020;color:#e8ecf3;text-align:center;padding:40px}
    a.button{display:inline-block;margin:10px;padding:12px 24px;border-radius:8px;background:#6c63ff;color:#fff;text-decoration:none}
    a.button:hover{background:#574bdb}</style></head><body>
    <h1>Custowell Copilot</h1><p>Use your API key to access Dashboard, Metrics, or Docs.</p>
    <a class="button" href="/dashboard">📈 Dashboard</a>
    <a class="button" href="/metrics">📊 Metrics</a>
    <a class="button" href="/docs">📜 API Docs</a>
    </body></html>
    """
    return HTMLResponse(content=html)

# ---------------- Core API ----------------
@app.get("/health")
def health(auth: bool = Security(enforce_api_key)):
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

@app.post("/analyze/tx", response_model=TaggedTransaction)
def analyze_tx(tx: Transaction, auth: bool = Security(enforce_api_key)):
    risk, flags = score_risk(tx); category = tag_category(tx)
    return TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category)

@app.post("/analyze/batch")
def analyze_batch(txs: List[Transaction], auth: bool = Security(enforce_api_key)):
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx); category = tag_category(tx)
        tagged.append(TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category))
    return {"summary": summary(tagged).model_dump(), "items": [t.model_dump() for t in tagged]}

@app.post("/report/csv")
def report_csv(req: ReportRequest, auth: bool = Security(enforce_api_key)):
    df = pd.read_csv(os.path.join(os.path.dirname(__file__), "..", "data", "sample_transactions.csv"))
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    mask = ((df["timestamp"] >= req.start) & (df["timestamp"] <= req.end) &
            (df["to_addr"].isin(req.wallet_addresses) | df["from_addr"].isin(req.wallet_addresses)))
    selected = df[mask]
    items: List[TaggedTransaction] = []
    for _, row in selected.iterrows():
        tx = Transaction(**row.to_dict())
        risk, flags = score_risk(tx); category = tag_category(tx)
        items.append(TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category))
    return {"csv": csv_export(items)}

# ---------------- XRPL parse (posted JSON) ----------------
@app.post("/integrations/xrpl/parse")
def parse_xrpl(account: str, payload: List[Dict[str, Any]], auth: bool = Security(enforce_api_key)):
    txs = xrpl_json_to_transactions(account, payload)
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx); category = tag_category(tx)
        tagged.append(TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category))
    return {"summary": summary(tagged).model_dump(), "items": [t.model_dump() for t in tagged]}

@app.post("/analyze/sample")
def analyze_sample(auth: bool = Security(enforce_api_key)):
    df = pd.read_csv(os.path.join(os.path.dirname(__file__), "..", "data", "sample_transactions.csv"))
    txs = [Transaction(**row.to_dict()) for _, row in df.iterrows()]
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx); category = tag_category(tx)
        tagged.append(TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category))
    return {"summary": summary(tagged).model_dump(), "items": [t.model_dump() for t in tagged]}

# ---------------- “Memory” (DB) + email on save ----------------
@app.post("/analyze_and_save/tx")
def analyze_and_save_tx(tx: Transaction, auth: bool = Security(enforce_api_key)):
    risk, flags = score_risk(tx); category = tag_category(tx)
    tagged = TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category)
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
        risk, flags = score_risk(tx); category = tag_category(tx)
        tagged.append(TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category))
    return {"count": len(tagged), "items": [t.model_dump() for t in tagged]}

@app.post("/integrations/xrpl/fetch_and_save")
def xrpl_fetch_and_save(account: str, limit: int = 10, auth: bool = Security(enforce_api_key)):
    raw = fetch_account_tx(account, limit=limit)
    txs = xrpl_json_to_transactions(account, raw)
    saved = 0; tagged_items: List[Dict[str, Any]] = []; emails: List[Dict[str, Any]] = []
    for tx in txs:
        risk, flags = score_risk(tx); category = tag_category(tx)
        tagged = TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category)
        store.save_tagged(tagged.model_dump()); saved += 1
        tagged_items.append(tagged.model_dump())
        emails.append(notify_if_alert(tagged))
    return {
        "account": account, "requested": limit, "fetched": len(txs),
        "saved": saved, "threshold": float(os.getenv("RISK_THRESHOLD", "0.75")),
        "items": tagged_items, "emails": emails,
    }

# ---------------- CSV export (DB) ----------------
@app.get("/export/csv")
def export_csv_from_db(wallet: str | None = None, limit: int = 1000, auth: bool = Security(enforce_api_key)):
    rows = store.list_by_wallet(wallet, limit=limit) if wallet else store.list_all(limit=limit)
    if not rows:
        return {"rows": 0, "csv": ""}
    df = pd.DataFrame(rows)
    return {"rows": len(rows), "csv": df.to_csv(index=False)}

@app.get("/export/csv/download")
def export_csv_download(wallet: str | None = None, limit: int = 1000, auth: bool = Security(enforce_api_key)):
    rows = store.list_by_wallet(wallet, limit=limit) if wallet else store.list_all(limit=limit)
    df = pd.DataFrame(rows); buf = StringIO(); df.to_csv(buf, index=False); buf.seek(0)
    return StreamingResponse(iter([buf.read()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=export.csv"})

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
    return {"total": total, "alerts": len(alerts), "avg_risk": round(avg_risk, 3),
            "categories": categories, "series_by_day": series}

# ---------------- UI auth helper ----------------
def _ui_auth(request: Request) -> bool:
    key = request.query_params.get("key") or ""
    expected = expected_api_key() or ""
    return key == expected

# ---------------- UI: Dashboard & Alerts ----------------
@app.get("/dashboard", name="ui_dashboard", include_in_schema=False)
def ui_dashboard(request: Request):
    if not _ui_auth(request):
        return HTMLResponse(content="Unauthorized. Append ?key=YOUR_API_KEY", status_code=401)
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
        {"request": request, "title": "Dashboard", "key": request.query_params.get("key"),
         "metrics": metrics_data, "rows": rows, "threshold": threshold}
    )

@app.get("/alerts-ui", name="ui_alerts", include_in_schema=False)
def ui_alerts(request: Request):
    if not _ui_auth(request):
        return HTMLResponse(content="Unauthorized. Append ?key=YOUR_API_KEY", status_code=401)
    threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    rows = store.list_alerts(threshold=threshold, limit=500)
    return templates.TemplateResponse(
        "alerts.html",
        {"request": request, "title": f"Alerts (≥ {threshold})",
         "key": request.query_params.get("key"), "rows": rows}
    )

# ---------------- Admin / Email tests ----------------
@app.get("/admin/test-email", include_in_schema=False)
def admin_test_email(request: Request):
    if not _ui_auth(request):
        return HTMLResponse(content="Unauthorized. Append ?key=YOUR_API_KEY", status_code=401)
    tx = Transaction(
        tx_id="TEST-ALERT-123", timestamp=datetime.utcnow().isoformat(), chain="XRPL",
        from_addr="rTEST_FROM", to_addr="rTEST_TO", amount=123.45, symbol="XRP",
        direction="out", memo="Test email", fee=0.0001,
    )
    risk, flags = 0.99, ["test_high_risk"]
    tagged = TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category="test-alert")
    return {"ok": True, "email": notify_if_alert(tagged)}

class NotifyRequest(BaseModel):
    email: EmailStr

@app.post("/notify/test")
def notify_test(payload: NotifyRequest = Body(...), auth: bool = Security(enforce_api_key)):
    return _send_email("Custowell Copilot Test",
                       "✅ Your Custowell Copilot email system is working!",
                       payload.email)

# ---------------- Debug ----------------
@app.get("/_debug/api_key")
def debug_api_key(x_api_key: str | None = Header(default=None)):
    exp = expected_api_key()
    preview = (exp[:4] + "..." + exp[-4:]) if exp else ""
    return {"received_header": x_api_key, "expected_loaded_from_env": bool(exp),
            "expected_length": len(exp or ""), "expected_preview": preview}

@app.get("/_debug/routes", include_in_schema=False)
def list_routes():
    return {"routes": [r.path for r in app.router.routes]}
