# app/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

@dataclass
class Transaction:
    # Fields your tests pass in
    tx_id: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    chain: str = "XRP"
    from_addr: Optional[str] = None
    to_addr: Optional[str] = None
    amount: Decimal = Decimal("0")
    symbol: str = "XRP"
    direction: str = "out"

    # Common extras used by your code
    fee: Decimal = Decimal("0")
    memo: Optional[str] = ""
    tags: List[str] = field(default_factory=list)
    is_internal: bool = False

    # Back-compat for code that expects from_address/to_address
    @property
    def from_address(self) -> Optional[str]:
        return self.from_addr

    @property
    def to_address(self) -> Optional[str]:
        return self.to_addr
