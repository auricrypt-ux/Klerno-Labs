# app/main.py
from datetime import datetime
from io import StringIO
from typing import List, Dict, Any, Optional

import os
import pandas as pd
from fastapi import FastAPI, Security, Header, Request, Body
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel, EmailStr

from . import store
from .models import Transaction, TaggedTransaction, ReportRequest
from .guardian import score_risk
from .compliance import tag_category
from .reporter import csv_export, summary
from .integrations.xrp import xrpl_json_to_transactions, fetch_account_tx
from .security import enforce_api_key, expected_api_key

# =====================================================
# Email (SendGrid): Step 3 wiring
# =====================================================
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

def notify_if_alert(tagged: TaggedTransaction) -> Optional[Dict[str, Any]]:
    """
    If tagged.risk_score >= RISK_THRESHOLD, send an email alert via SendGrid.
    """
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

# =====================================================
# FastAPI app
# =====================================================
app = FastAPI(title="Custowell Copilot API (MVP) — XRPL First")

# Initialize DB
store.init_db()

# -----------------------------------------------------
# Home (Quick Links) — simple helper page
# -----------------------------------------------------
@app.get("/", include_in_schema=False)
def home():
    html = """
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8"/>
      <meta name="viewport" content="width=device-width,initial-scale=1"/>
      <title>Custowell Copilot — Quick Links</title>
      <style>
        body { font-family: system-ui, sans-serif; background:#0b1020; color:#e8ecf3; text-align:center; padding:40px; }
        a.button, button { display:inline-block; margin:10px; padding:12px 24px; border-radius:8px; background:#6c63ff; color:white; text-decoration:none; border:0; cursor:pointer; }
        a.button:hover, button:hover { background:#574bdb; }
        input { padding:10px; border-radius:6px; border:1px solid #2a3a72; background:#0b1020; color:#e8ecf3; }
      </style>
    </head>
    <body>
      <h1>Custowell Copilot</h1>
      <p>Use your API key for protected endpoints.</p>

      <div style="margin:20px 0;">
        <input id="apikey" type="password" placeholder="x-api-key for Docs/Auth"/>
        <a class="button" href="/docs" onclick="saveKey()">📜 Open API Docs</a>
        <a class="button" href="/health">✅ Health</a>
      </div>

      <div>
        <button id="btnTest">✉️ Send Admin Test Email</button>
      </div>

      <script>
        function saveKey(){
          const k = document.getElementById('apikey').value.trim();
          if (k) localStorage.setItem('cw_api_key', k);
        }
        document.getElementById('btnTest').addEventListener('click', () => {
          const k = (document.getElementById('apikey').value || localStorage.getItem('cw_api_key') || '').trim();
          if (!k) { alert('Paste your API key above first.'); return; }
          window.location.href = '/admin/test-email?key=' + encodeURIComponent(k);
        });
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

# -----------------------------------------------------
# Core API
# -----------------------------------------------------
@app.get("/health")
def health(auth: bool = Security(enforce_api_key)):
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

@app.post("/analyze/tx", response_model=TaggedTransaction)
def analyze_tx(tx: Transaction, auth: bool = Security(enforce_api_key)):
    risk, flags = score_risk(tx)
    category = tag_category(tx)
    tagged = TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category)
    return tagged

@app.post("/analyze_and_save/tx")
def analyze_and_save_tx(tx: Transaction, auth: bool = Security(enforce_api_key)):
    risk, flags = score_risk(tx)
    category = tag_category(tx)
    tagged = TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category)
    store.save_tagged(tagged.model_dump())
    email_result = notify_if_alert(tagged)
    return {"saved": True, "item": tagged.model_dump(), "email": email_result}

# -----------------------------------------------------
# Admin: test email delivery (browser: /admin/test-email?key=YOUR_API_KEY)
# -----------------------------------------------------
def _ui_auth(request: Request) -> bool:
    key = request.query_params.get("key") or ""
    expected = expected_api_key() or ""
    return key == expected

@app.get("/admin/test-email", include_in_schema=False)
def admin_test_email(request: Request):
    if not _ui_auth(request):
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
    tagged = TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category="test-alert")
    result = notify_if_alert(tagged)
    return {"ok": True, "email": result}

# -----------------------------------------------------
# API: explicit test email (requires x-api-key)
# -----------------------------------------------------
class NotifyRequest(BaseModel):
    email: EmailStr

@app.post("/notify/test")
def notify_test(payload: NotifyRequest = Body(...), auth: bool = Security(enforce_api_key)):
    """Send a simple test email to any recipient (independent of alerts)."""
    return _send_email(
        "Custowell Copilot Test",
        "✅ Your Custowell Copilot email system is working!",
        payload.email,
    )
