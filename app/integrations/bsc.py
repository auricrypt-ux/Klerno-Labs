import os, requests
from typing import List, Dict, Any
from datetime import datetime
from ..models import Transaction

BSC_API = "https://publicapi.dev/bscscan-api/api"
BSC_KEY = os.getenv("BSC_API_KEY", "").strip()  # set me

def _ts(sec: str | int) -> str:
    try:
        return datetime.utcfromtimestamp(int(sec)).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

def fetch_account_tx(address: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Uses bscscan 'txlist' equivalent (publicapi.dev route)."""
    params = {
        "module": "account",
        "action": "txlist",
        "address": address,
        "startblock": 0,
        "endblock": 99999999,
        "page": 1,
        "offset": max(1, min(limit, 100)),
        "sort": "desc",
        "apikey": BSC_KEY or "free",  # publicapi.dev supports no-key; key recommended
    }
    r = requests.get(BSC_API, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    # Both bscscan and publicapi.dev return {"status":"1","message":"OK","result":[...]} or similar
    return data.get("result") or []

def bsc_json_to_transactions(address: str, payload: List[Dict[str, Any]]) -> List[Transaction]:
    out: List[Transaction] = []
    addr = (address or "").lower()
    for it in payload:
        try:
            from_addr = str(it.get("from","")).lower()
            to_addr   = str(it.get("to","")).lower()
            # native BNB transfer value is in wei
            value_wei = int(it.get("value", 0))
            amount = value_wei / 10**18
            fee = (int(it.get("gasPrice", 0)) * int(it.get("gasUsed", it.get("gas", 0) or 0))) / 10**18
            direction = "in" if to_addr == addr else ("out" if from_addr == addr else "")
            tx = Transaction(
                tx_id = it.get("hash") or "",
                timestamp = _ts(it.get("timeStamp")),
                chain = "BSC",
                from_addr = from_addr,
                to_addr = to_addr,
                amount = float(amount),
                symbol = "BNB",
                direction = direction,
                memo = "",
                fee = float(fee),
            )
            out.append(tx)
        except Exception:
            continue
    return out
