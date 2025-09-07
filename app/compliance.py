# app/compliance.py
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Pattern, Literal, Any, Optional

import yaml

# ----- Paths / config loading -----
ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "automation" / "tagging.yaml"

Category = Literal["income", "expense", "fee", "trade", "transfer", "unknown"]

DEFAULT_KEYWORDS: Dict[str, List[str]] = {
    "income":   ["salary", "airdrop", "reward", "interest", "yield"],
    "fee":      ["fee", "gas", "network"],
    "trade":    ["swap", "trade", "exchange"],
    "transfer": ["transfer", "send", "receive"],
}
DEFAULT_PRIORITY: List[Category] = ["fee", "trade", "income", "transfer"]

def _load_tagging_config(path: Path) -> tuple[Dict[str, List[str]], List[Category]]:
    if not path.exists():
        return DEFAULT_KEYWORDS, DEFAULT_PRIORITY
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    kw = data.get("keywords") or DEFAULT_KEYWORDS
    pr = data.get("priority") or DEFAULT_PRIORITY
    return kw, pr

KEYWORDS, PRIORITY = _load_tagging_config(CONFIG_PATH)
KEYWORD_PATTERNS: Dict[str, List[Pattern[str]]] = {
    cat: [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in words]
    for cat, words in KEYWORDS.items()
}

# ----- Helpers -----
def _as_decimal(x) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal("0")

def _norm(text: Optional[str]) -> str:
    return (text or "").strip()

# ----- Multi-label results (explainable) -----
@dataclass
class TagReason:
    category: str
    reason: str

@dataclass
class TagResult:
    category: str
    score: float
    reasons: List[TagReason]

class AddressBook:
    """Track owned addresses to detect internal transfers."""
    def __init__(self, owned: set[str] | None = None) -> None:
        self.owned = {a.lower() for a in (owned or set())}

    def is_owned(self, addr: Optional[str]) -> bool:
        return bool(addr) and addr.lower() in self.owned

def _is_internal_transfer(tx, book: AddressBook | None) -> bool:
    if not book:
        return False
    fa = _norm(getattr(tx, "from_address", None)).lower()
    ta = _norm(getattr(tx, "to_address", None)).lower()
    return bool(fa and ta and book.is_owned(fa) and book.is_owned(ta))

# ----- Public API -----
def tag_categories(tx, address_book: AddressBook | None = None) -> List[TagResult]:
    """
    Multi-label: return every category that triggers, with score + reasons.
    Compatible with any Transaction that has .memo, .fee, .amount, .direction.
    """
    memo = _norm(getattr(tx, "memo", None))
    fee = _as_decimal(getattr(tx, "fee", None))
    amount = _as_decimal(getattr(tx, "amount", None))
    direction = _norm(getattr(tx, "direction", None)).lower()

    results: List[TagResult] = []

    weights = {
        "keyword": 0.6,
        "fee_signal": 1.0,
        "direction_in": 0.4,
        "direction_out": 0.4,
        "internal_transfer": 1.0,
    }

    # 1) Fees heuristic
    if fee > 0 and amount <= 0:
        results.append(TagResult(
            category="fee",
            score=weights["fee_signal"],
            reasons=[TagReason("fee", "Positive fee + nonpositive amount")]
        ))

    # 2) Keyword hits per category
    for cat, patterns in KEYWORD_PATTERNS.items():
        for pat in patterns:
            if pat.search(memo):
                found = next((r for r in results if r.category == cat), None)
                if found:
                    found.score += weights["keyword"]
                    found.reasons.append(TagReason(cat, f"Keyword match: {pat.pattern}"))
                else:
                    results.append(TagResult(
                        category=cat,
                        score=weights["keyword"],
                        reasons=[TagReason(cat, f"Keyword match: {pat.pattern}")]
                    ))

    # 3) Internal transfers boost
    if _is_internal_transfer(tx, address_book):
        found = next((r for r in results if r.category == "transfer"), None)
        if found:
            found.score += weights["internal_transfer"]
            found.reasons.append(TagReason("transfer", "Internal transfer (same owner)"))
        else:
            results.append(TagResult(
                category="transfer",
                score=weights["internal_transfer"],
                reasons=[TagReason("transfer", "Internal transfer (same owner)")]
            ))

    # 4) Direction soft signal
    if direction in {"in", "incoming", "credit"}:
        found = next((r for r in results if r.category == "income"), None)
        if found:
            found.score += weights["direction_in"]
            found.reasons.append(TagReason("income", "Direction suggests inbound"))
        else:
            results.append(TagResult(
                category="income",
                score=weights["direction_in"],
                reasons=[TagReason("income", "Direction suggests inbound")]
            ))
    elif direction in {"out", "outgoing", "debit"}:
        found = next((r for r in results if r.category == "expense"), None)
        if found:
            found.score += weights["direction_out"]
            found.reasons.append(TagReason("expense", "Direction suggests outbound"))
        else:
            results.append(TagResult(
                category="expense",
                score=weights["direction_out"],
                reasons=[TagReason("expense", "Direction suggests outbound")]
            ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results

def tag_category(tx, address_book: AddressBook | None = None) -> Category:
    """Pick a single winner (scores first; PRIORITY breaks ties)."""
    results = tag_categories(tx, address_book=address_book)
    if not results:
        return "unknown"

    top_score = results[0].score
    contenders = [r for r in results if r.score == top_score]
    if len(contenders) == 1:
        return contenders[0].category

    for pref in PRIORITY + ["expense", "unknown"]:
        for r in contenders:
            if r.category == pref:
                return r.category
    return contenders[0].category
