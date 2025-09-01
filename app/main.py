# app/main.py
from fastapi import FastAPI, Security, Header
from datetime import datetime
from typing import List, Dict, Any
import os
import pandas as pd

from .models import Transaction, TaggedTransaction, ReportRequest
from .guardian import score_risk
from .compliance import tag_category
from .reporter import csv_export, summary
from .integrations.xrp import xrpl_json_to_transactions, fetch_account_tx
from .security import enforce_api_key, expected_api_key
from . import store
from fastapi.responses import StreamingResponse, RedirectResponse
from io import StringIO

app = FastAPI(title="Custowell Copilot API (MVP) — XRPL First")

# Initialize the small SQLite database
store.init_db()

# -------- Friendly root (redirect to docs) --------
@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/docs")

# ---------------- Core ----------------

@app.get("/health")
def health(auth: bool = Security(enforce_api_key)):
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

@app.post("/analyze/tx", response_model=TaggedTransaction)
def analyze_tx(tx: Transaction, auth: bool = Security(enforce_api_key)):
    risk, flags = score_risk(tx)
    category = tag_category(tx)
    return TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category)

@app.post("/analyze/batch")
def analyze_batch(txs: List[Transaction], auth: bool = Security(enforce_api_key)):
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged.append(TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category))
    return {"summary": summary(tagged).model_dump(), "items": [t.model_dump() for t in tagged]}

@app.post("/report/csv")
def report_csv(req: ReportRequest, auth: bool = Security(enforce_api_key)):
    df = pd.read_csv(os.path.join(os.path.dirname(__file__), "..", "data", "sample_transactions.csv"))
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    mask = (
        (df["timestamp"] >= req.start)
        & (df["timestamp"] <= req.end)
        & (df["to_addr"].isin(req.wallet_addresses) | df["from_addr"].isin(req.wallet_addresses))
    )
    selected = df[mask]
    items: List[TaggedTransaction] = []
    for _, row in selected.iterrows():
        tx = Transaction(**row.to_dict())
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        items.append(TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category))
    csv_data = csv_export(items)
    return {"csv": csv_data}

# ---------------- XRPL parse (from posted JSON) ----------------

@app.post("/integrations/xrpl/parse")
def parse_xrpl(account: str, payload: List[Dict[str, Any]], auth: bool = Security(enforce_api_key)):
    txs = xrpl_json_to_transactions(account, payload)
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged.append(TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category))
    return {"summary": summary(tagged).model_dump(), "items": [t.model_dump() for t in tagged]}

@app.post("/analyze/sample")
def analyze_sample(auth: bool = Security(enforce_api_key)):
    df = pd.read_csv(os.path.join(os.path.dirname(__file__), "..", "data", "sample_transactions.csv"))
    txs = [Transaction(**row.to_dict()) for _, row in df.iterrows()]
    tagged: List[TaggedTransaction] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged.append(TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category))
    return {"summary": summary(tagged).model_dump(), "items": [t.model_dump() for t in tagged]}

# ---------------- “Memory” (DB) ----------------

@app.post("/analyze_and_save/tx")
def analyze_and_save_tx(tx: Transaction, auth: bool = Security(enforce_api_key)):
    risk, flags = score_risk(tx)
    category = tag_category(tx)
    tagged = TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category)
    store.save_tagged(tagged.model_dump())
    return {"saved": True, "item": tagged.model_dump()}

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
        tagged.append(TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category))
    return {"count": len(tagged), "items": [t.model_dump() for t in tagged]}

@app.post("/integrations/xrpl/fetch_and_save")
def xrpl_fetch_and_save(account: str, limit: int = 10, auth: bool = Security(enforce_api_key)):
    raw = fetch_account_tx(account, limit=limit)
    txs = xrpl_json_to_transactions(account, raw)
    saved = 0
    tagged_items: List[Dict[str, Any]] = []
    for tx in txs:
        risk, flags = score_risk(tx)
        category = tag_category(tx)
        tagged = TaggedTransaction(**tx.model_dump(), risk_score=risk, risk_flags=flags, category=category)
        store.save_tagged(tagged.model_dump())
        saved += 1
        tagged_items.append(tagged.model_dump())
    return {
        "account": account,
        "requested": limit,
        "fetched": len(txs),
        "saved": saved,
        "threshold": float(os.getenv("RISK_THRESHOLD", "0.75")),
        "items": tagged_items,
    }

# ---------------- CSV export (DB) ----------------

@app.get("/export/csv")
def export_csv_from_db(wallet: str | None = None, limit: int = 1000, auth: bool = Security(enforce_api_key)):
    rows = store.list_by_wallet(wallet, limit=limit) if wallet else store.list_all(limit=limit)
    if not rows:
        return {"rows": 0, "csv": ""}
    df = pd.DataFrame(rows)
    csv_text = df.to_csv(index=False)
    return {"rows": len(rows), "csv": csv_text}

@app.get("/export/csv/download")
def export_csv_download(wallet: str | None = None, limit: int = 1000, auth: bool = Security(enforce_api_key)):
    rows = store.list_by_wallet(wallet, limit=limit) if wallet else store.list_all(limit=limit)
    df = pd.DataFrame(rows)
    buf = StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=export.csv"},
    )

# ---------------- Metrics (simple JSON) ----------------

@app.get("/metrics")
def metrics(auth: bool = Security(enforce_api_key)):
    rows = store.list_all(limit=10000)  # sample last N transactions
    total = len(rows)
    if total == 0:
        return {"total": 0, "alerts": 0, "avg_risk": 0, "categories": {}}

    threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    alerts = [r for r in rows if (r.get("risk_score") or 0) >= threshold]
    avg_risk = sum((r.get("risk_score") or 0) for r in rows) / total

    categories: Dict[str, int] = {}
    for r in rows:
        cat = r.get("category") or "unknown"
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "total": total,
        "alerts": len(alerts),
        "avg_risk": round(avg_risk, 3),
        "categories": categories,
    }

# ---------------- Debug (no key required) ----------------

@app.get("/_debug/api_key")
def debug_api_key(x_api_key: str | None = Header(default=None)):
    exp = expected_api_key()
    preview = (exp[:4] + "..." + exp[-4:]) if exp else ""
    return {
        "received_header": x_api_key,
        "expected_loaded_from_env": bool(exp),
        "expected_length": len(exp),
        "expected_preview": preview
    }

@app.get("/audit")
def get_audit(limit: int = 50, auth: bool = Security(enforce_api_key)):
    return {"items": store.list_audit(limit=limit)}
@app.get("/_debug/routes", include_in_schema=False)
def list_routes():
    return {"routes": [r.path for r in app.router.routes]}
