
from .models import Transaction

KEYWORDS = {
    "income": ["salary","airdrop","reward","interest","yield"],
    "fee": ["fee","gas","network"],
    "trade": ["swap","trade","exchange"],
    "transfer": ["transfer","send","receive"]
}

def tag_category(tx: Transaction) -> str:
    memo = (tx.memo or "").lower()
    if tx.fee and tx.fee > 0 and tx.amount <= 0:
        return "fee"
    for cat, words in KEYWORDS.items():
        if any(word in memo for word in words):
            return cat
    if tx.direction == "in":
        return "income"
    if tx.direction == "out":
        return "expense"
    return "unknown"
