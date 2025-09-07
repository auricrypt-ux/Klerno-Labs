# app/llm.py
import os
import json
import math
import statistics as stats
from datetime import datetime
from typing import List, Dict, Any

from dotenv import load_dotenv
load_dotenv()

# ===== OpenAI client (compatible with both legacy 0.28.x and v1+) =====
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
_LLM_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
_DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

_use_v1 = False
_client_v1 = None

# Try the modern SDK first (v1+)
try:
    from openai import OpenAI  # only in v1+
    _client_v1 = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()
    _use_v1 = True
except Exception:
    _use_v1 = False

if not _use_v1:
    # Fall back to legacy 0.28.x
    import openai as _openai_legacy
    if OPENAI_API_KEY:
        _openai_legacy.api_key = OPENAI_API_KEY


def _safe_llm(system: str, user: str, temperature: float = 0.2) -> str:
    """
    Ask the LLM safely. If anything fails, return a graceful fallback string.
    Works with both OpenAI SDK v1+ and legacy 0.28.x.
    """
    if not OPENAI_API_KEY:
        return "LLM not configured: set OPENAI_API_KEY."

    try:
        if _use_v1:
            resp = _client_v1.chat.completions.create(
                model=_LLM_MODEL,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return (resp.choices[0].message.content or "").strip()
        else:
            resp = _openai_legacy.ChatCompletion.create(
                model=_LLM_MODEL if _LLM_MODEL else "gpt-3.5-turbo",
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return (resp["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        if _DEMO_MODE:
            return f"(DEMO MODE fallback; LLM error: {e})"
        return f"(LLM error: {e})"


def _fmt_amount(v):
    try:
        x = float(v)
        if abs(x) >= 1_000_000:
            return f"{x:,.0f}"
        if abs(x) >= 1_000:
            return f"{x:,.2f}"
        return f"{x:.4f}"
    except Exception:
        return str(v)


def _parse_iso(ts: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts))
    except Exception:
        return None


# =========================================================
# 1) Single-transaction explanation
# =========================================================
def explain_tx(tx: Dict[str, Any]) -> str:
    """
    Return a natural-language explanation of a single transaction.
    """
    pre = [
        f"Transaction {tx.get('tx_id', '—')} on {tx.get('chain', 'unknown')}:",
        f"  from {tx.get('from_addr', '—')} to {tx.get('to_addr', '—')}",
        f"  amount: {_fmt_amount(tx.get('amount', 0))} {tx.get('symbol', '')} | direction: {tx.get('direction', '—')}",
        f"  timestamp: {tx.get('timestamp', '—')} | fee: {tx.get('fee', '—')}",
    ]
    preface = "\n".join(pre)

    system = (
        "You are a compliance and risk assistant for crypto transactions. "
        "Explain the transaction succinctly (5-8 sentences), focusing on risk-relevant details, "
        "direction, counterparties, and any anomalies. Avoid hedging."
    )
    user = "Explain this JSON transaction for a compliance analyst:\n" + json.dumps(tx, ensure_ascii=False, indent=2)
    llm = _safe_llm(system, user)
    return preface + "\n\n" + llm


# =========================================================
# 2) Batch explanation
# =========================================================
def explain_batch(txs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    For a list of tx dicts, return:
      { items: [ {tx_id, explanation}, ... ], summary: "..." }
    """
    items = []
    for t in txs:
        text = explain_tx(t)
        items.append({"tx_id": t.get("tx_id"), "explanation": text})

    amounts = [float(t.get("amount", 0) or 0) for t in txs if isinstance(t.get("amount", 0), (int, float, str))]
    risk_scores = [float(t.get("risk_score", 0) or 0) for t in txs]

    total = len(txs)
    total_amt = sum(a for a in amounts if not math.isnan(a))
    avg_risk = round(sum(risk_scores) / len(risk_scores), 3) if risk_scores else 0.0

    system = (
        "You are a senior compliance analyst. Provide a crisp summary (4-7 sentences), "
        "calling out categories, suspicious patterns, and high-level risk signals."
    )
    user = (
        f"Batch size: {total}\n"
        f"Total amount (naive sum): {total_amt}\n"
        f"Average risk score (if any): {avg_risk}\n"
        f"Sample items (trimmed to first 20):\n{json.dumps(txs[:20], ensure_ascii=False, indent=2)}"
    )
    batch_summary = _safe_llm(system, user)
    return {"items": items, "summary": batch_summary}


# =========================================================
# 3) Natural-language filters spec
# =========================================================
def ask_to_filters(question: str) -> Dict[str, Any]:
    """
    Convert a question into a JSON filter spec.
    Keys: date_from, date_to, min_risk, max_risk, categories, include_wallets, exclude_wallets.
    """
    system = (
        "You convert a user's plain-English question into a JSON filter spec for transactions. "
        "Return **only** JSON with keys: date_from, date_to, min_risk, max_risk, categories, "
        "include_wallets, exclude_wallets. Omit keys you don't use."
    )
    user = f"Question: {question}\n\nReturn only JSON, no commentary."
    raw = _safe_llm(system, user)
    try:
        spec = json.loads(raw)
        if not isinstance(spec, dict):
            raise ValueError("Spec was not a dict")
        return spec
    except Exception:
        return {}


# =========================================================
# 4) Apply filters to local rows
# =========================================================
def apply_filters(rows: List[Dict[str, Any]], spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not rows:
        return []

    df = spec  # shorthand
    date_from = _parse_iso(df.get("date_from")) if df.get("date_from") else None
    date_to   = _parse_iso(df.get("date_to"))   if df.get("date_to")   else None
    min_risk  = float(df.get("min_risk", 0)) if df.get("min_risk") is not None else None
    max_risk  = float(df.get("max_risk", 1)) if df.get("max_risk") is not None else None
    cats      = set([str(c).lower() for c in (df.get("categories") or [])])
    inc_w     = set([str(w) for w in (df.get("include_wallets") or [])])
    exc_w     = set([str(w) for w in (df.get("exclude_wallets") or [])])

    out = []
    for r in rows:
        ts = _parse_iso(r.get("timestamp"))
        if date_from and (not ts or ts < date_from):
            continue
        if date_to and (not ts or ts > date_to):
            continue

        risk = None
        try:
            risk = float(r.get("risk_score")) if r.get("risk_score") is not None else None
        except Exception:
            risk = None

        if min_risk is not None and (risk is None or risk < min_risk):
            continue
        if max_risk is not None and (risk is None or risk > max_risk):
            continue

        cat = str(r.get("category", "unknown")).lower()
        if cats and cat not in cats:
            continue

        from_w = str(r.get("from_addr", ""))
        to_w = str(r.get("to_addr", ""))

        if inc_w and not (from_w in inc_w or to_w in inc_w):
            continue
        if exc_w and (from_w in exc_w or to_w in exc_w):
            continue

        out.append(r)

    return out


# =========================================================
# 5) Explain a filtered selection
# =========================================================
def explain_selection(question: str, rows: List[Dict[str, Any]]) -> str:
    n = len(rows)
    if n == 0:
        return "No rows matched the criteria."

    risks = [float(r.get("risk_score", 0) or 0) for r in rows]
    avg_risk = round(sum(risks) / len(risks), 3) if risks else 0.0
    cats: Dict[str, int] = {}
    for r in rows:
        c = r.get("category") or "unknown"
        cats[c] = cats.get(c, 0) + 1

    system = (
        "You are a compliance analyst. Provide a concise, direct answer to the user's question "
        "grounded in the provided selection. 3-6 sentences, call out patterns & risks."
    )
    user = (
        f"Question: {question}\n"
        f"Count: {n}\nAverage risk: {avg_risk}\nCategories: {json.dumps(cats, ensure_ascii=False)}\n"
        f"Sample (first 30):\n{json.dumps(rows[:30], ensure_ascii=False, indent=2)}"
    )
    return _safe_llm(system, user)


# =========================================================
# 6) Summarize rows for dashboard
# =========================================================
def summarize_rows(rows: List[Dict[str, Any]], title: str = "Summary") -> Dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"title": title, "count": 0, "kpis": {}, "commentary": "No recent activity."}

    amounts = []
    risks = []
    cats: Dict[str, int] = {}
    for r in rows:
        try:
            amounts.append(float(r.get("amount", 0) or 0))
        except Exception:
            pass
        try:
            risks.append(float(r.get("risk_score", 0) or 0))
        except Exception:
            pass
        c = r.get("category") or "unknown"
        cats[c] = cats.get(c, 0) + 1

    total_amt = sum(amounts) if amounts else 0.0
    avg_risk = round(sum(risks) / len(risks), 3) if risks else 0.0
    p95_risk = round(stats.quantiles(risks, n=20)[-1], 3) if len(risks) >= 20 else (max(risks) if risks else 0.0)

    kpis = {
        "transactions": n,
        "total_amount": total_amt,
        "avg_risk": avg_risk,
        "p95_risk": p95_risk,
        "top_categories": sorted(cats.items(), key=lambda kv: kv[1], reverse=True)[:5],
    }

    system = (
        "You are a seasoned AML analyst. Provide a compact commentary (4-6 sentences) on the KPIs and patterns, "
        "flagging noteworthy risks and possible next steps."
    )
    user = f"Title: {title}\nKPIs: {json.dumps(kpis, ensure_ascii=False)}\n"
    commentary = _safe_llm(system, user)

    return {"title": title, "count": n, "kpis": kpis, "commentary": commentary}
