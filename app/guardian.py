from __future__ import annotations
from decimal import Decimal
from typing import Any, Iterable, Optional

SUSPICIOUS_WORDS = {
    "scam", "phish", "hack", "fraud", "ransom", "malware",
    "blackmail", "mixer", "tornado", "sanction", "darknet",
}

def _as_decimal(x: Any, default: str = "0") -> Decimal:
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal(default)

def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()

def _get(tx: Any, name: str, default=None):
    if hasattr(tx, name):
        return getattr(tx, name)
    if isinstance(tx, dict):
        return tx.get(name, default)
    return default

def score_risk(tx: Any) -> tuple[float, list[str]]:
    """
    Returns (score, flags). Score is clamped to [0,1].
    Flags explain which signals contributed; useful for tests & auditing.
    """
    memo = _norm(_get(tx, "memo", ""))
    amount = _as_decimal(_get(tx, "amount", 0))
    fee = _as_decimal(_get(tx, "fee", 0))
    direction = _norm(_get(tx, "direction", ""))
    is_internal = bool(_get(tx, "is_internal", False))

    tags: Iterable[str] = _get(tx, "tags", []) or []
    tags = {_norm(t) for t in tags}

    score = Decimal("0.10")
    flags: list[str] = []

    # Direction & magnitude (keeps your thresholds; adds flags)
    if direction in {"out", "outgoing", "debit"}:
        flags.append("outgoing")
        mag = abs(amount)
        if mag > 0:
            score += Decimal("0.10")
        if mag > 100:
            score += Decimal("0.10"); flags.append("medium_outgoing")
        if mag > 1000:
            score += Decimal("0.15"); flags.append("large_outgoing")
        if mag > 10000:
            score += Decimal("0.15"); flags.append("very_large_outgoing")
    elif direction in {"in", "incoming", "credit"}:
        flags.append("incoming")
        score -= Decimal("0.05")

    # Fee pressure
    if fee > 0:
        score += Decimal("0.05"); flags.append("fee_present")
        if amount != 0:
            ratio = (fee / abs(amount)) if abs(amount) > 0 else Decimal("0")
            if ratio > Decimal("0.01"):
                score += Decimal("0.05"); flags.append("high_fee_ratio")
            if ratio > Decimal("0.05"):
                score += Decimal("0.10"); flags.append("very_high_fee_ratio")

    # Suspicious memo keywords
    if memo:
        hits = sum(1 for w in SUSPICIOUS_WORDS if w in memo)
        if hits:
            score += Decimal("0.20") + Decimal("0.05") * hits
            flags.append("suspicious_memo")

    # Tag-based adjustments
    if "sanctioned" in tags or "mixer" in tags:
        score += Decimal("0.20"); flags.append("sanctioned_or_mixer")

    # Internal transfers reduce risk
    if is_internal:
        score -= Decimal("0.25"); flags.append("internal_transfer")

    # Clamp to [0, 1]
    if score < 0:
        score = Decimal("0")
    if score > 1:
        score = Decimal("1")

    return float(score), flags

# Back-compat: old callers that expect just a float can use this.
def score_risk_value(tx: Any) -> float:
    return score_risk(tx)[0]
