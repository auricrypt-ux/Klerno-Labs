# app/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict

from pydantic import BaseModel, Field, ConfigDict, AliasChoices


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
    notes: Optional[str] = ""                     # <─ added so emails/CSV don’t break
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
    Accepts inputs with either 'from_addr'/'to_addr' or 'from_address'/'to_address'.
    Also accepts old 'score'/'flags' but serializes as 'risk_score'/'risk_flags'.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    # Base tx fields
    tx_id: str
    timestamp: datetime
    chain: str = "XRP"

    # Canonical fields are from_addr/to_addr; also accept from_address/to_address
    from_addr: Optional[str] = Field(default=None, alias="from_address")
    to_addr: Optional[str]   = Field(default=None, alias="to_address")

    amount: Decimal
    symbol: str = "XRP"
    direction: str

    fee: Decimal = Decimal("0")
    memo: Optional[str] = None
    notes: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    is_internal: bool = False

    # Tagging outputs
    category: Optional[str] = None

    # Accept both 'risk_score' and legacy 'score' on input; serialize as 'risk_score'
    risk_score: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices("risk_score", "score")
    )
    # Accept both 'risk_flags' and legacy 'flags' on input; serialize as 'risk_flags'
    risk_flags: List[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("risk_flags", "flags")
    )

    # Convenience accessors so code can read .from_address/.to_address or .score/.flags too
    @property
    def from_address(self) -> Optional[str]:
        return self.from_addr

    @property
    def to_address(self) -> Optional[str]:
        return self.to_addr

    @property
    def score(self) -> Optional[float]:
        return self.risk_score

    @property
    def flags(self) -> List[str]:
        return self.risk_flags


class ReportRequest(BaseModel):
    """Input model for generating reports/exports."""
    model_config = ConfigDict(populate_by_name=True)

    address: Optional[str] = None
    chain: Optional[str] = "XRP"
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    wallet_addresses: List[str] = Field(default_factory=list)   # <─ used in /report/csv


class ReportSummary(BaseModel):
    """
    Output model for summary endpoints/exports.
    Flexible defaults so reporter code can set more fields if needed.
    """
    model_config = ConfigDict(extra="allow")  # tolerate extra fields if reporter adds them

    address: Optional[str] = None
    chain: Optional[str] = "XRP"
    start: Optional[datetime] = None
    end: Optional[datetime] = None

    # Totals & counts
    count_in: int = 0
    count_out: int = 0
    total_in: Decimal = Decimal("0")
    total_out: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    net: Decimal = Decimal("0")

    # Optional breakdowns
    categories: Dict[str, int] = Field(default_factory=dict)
