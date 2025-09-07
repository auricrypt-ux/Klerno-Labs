from fastapi import APIRouter, Depends
from decimal import Decimal
from typing import Any

from ..deps import require_user
from ..schemas import TagResultOut
from ..compliance import tag_categories, AddressBook

router = APIRouter(prefix="/compliance", tags=["compliance"])

@router.post("/tx", response_model=list[TagResultOut])
def analyze_tx(tx: dict[str, Any], user=Depends(require_user)):
    """
    Accepts a Transaction-like dict with at least:
    memo: str | None
    fee: number | None
    amount: number | None
    direction: "in" | "out" | ...
    from_address/to_address: optional
    """
    class Tx:
        # lightweight adapter; your real Transaction model works too
        memo = tx.get("memo")
        fee = tx.get("fee")
        amount = tx.get("amount")
        direction = tx.get("direction")
        from_address = tx.get("from_address")
        to_address = tx.get("to_address")

    # TODO: pass a real AddressBook from your DB
    book = AddressBook(owned=set())
    results = tag_categories(Tx, address_book=book)

    return [
        {
            "category": r.category,
            "score": float(r.score),
            "reasons": [{"category": rr.category, "reason": rr.reason} for rr in r.reasons],
        }
        for r in results
    ]
