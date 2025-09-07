# app/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict


# ----------------------------
# Dataclass used in tests / core logic
# ----------------------------
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


# ----------------------------
# Pydantic models for API I/O
# ----------------------------
class TaggedTransaction(BaseModel):
    """
    Transaction + tagging results for API responses.
    Supports inputs with either 'from_addr'/'to_addr' or 'from_address'/'to_address'.
    """
    # allow validating from dataclass/ORM objects and accept aliases
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    # Base tx fields
    tx_id: str
    timestamp: datetime
    chain: str = "XRP"

    # Canonical fields are from_addr/to_addr; accept alias inputs too
    from_addr: Optional[str] = Field(default=None, alias="from_address")
    to_addr: Optional[str] = Field(default=None, alias="to_address")

    amount: Decimal
    symbol: str = "XRP"
    direction: str

    fee: Decimal = Decimal("0")
    memo: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    is_internal: bool = False

    # Tagging outputs
    category: Optional[str] = None
    score: Optional[float] = None
    flags: List[str] = Field(default_factory=list)

    # Convenience accessors so code can read .from_address/.to_address too
    @property
    def from_address(self) -> Optional[str]:
        return self.from_addr

    @property
    def to_address(self) -> Optional[str]:
        return self.to_addr


class ReportRequest(BaseModel):
    """
    Minimal report request model; extend as your endpoints require.
    """
    model_config = ConfigDict(populate_by_name=True)

    address: Optional[str] = None
    chain: Optional[str] = "XRP"
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
