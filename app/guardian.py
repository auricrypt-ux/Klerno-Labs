
import os
from dotenv import load_dotenv
load_dotenv()
from typing import List, Tuple
from .models import Transaction

RISK_THRESHOLD = float(os.getenv("RISK_THRESHOLD", "0.75"))

KNOWN_BAD = {
    "ETH": {"0xBAD1", "0xSCAM2"},
    "XRP": {"rBadAddr1", "rScam2"},
    "BTC": {"1Bad...", "1Scam..."}
}

def score_risk(tx: Transaction) -> Tuple[float, List[str]]:
    flags: List[str] = []
    score = 0.0

    if tx.direction == "out" and tx.amount > 5000:
        score += 0.35
        flags.append("large_outgoing")

    bad_set = KNOWN_BAD.get(tx.chain.upper(), set())
    if tx.to_addr in bad_set or tx.from_addr in bad_set:
        score += 0.6
        flags.append("known_bad_party")

    if tx.direction == "out" and tx.amount > 1000 and not tx.memo:
        score += 0.1
        flags.append("no_context")

    return min(score, 1.0), flags

def is_risky(score: float) -> bool:
    return score >= RISK_THRESHOLD
