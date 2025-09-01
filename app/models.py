
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime

class Transaction(BaseModel):
    tx_id: str
    timestamp: datetime
    chain: str = Field(description="e.g., XRP, ETH, BTC, HBAR, XLM")
    from_addr: str
    to_addr: str
    amount: float
    symbol: str = Field(description="Token symbol, e.g., XRP, ETH")
    direction: Literal["in", "out"]
    memo: Optional[str] = None
    fee: Optional[float] = 0.0

class TaggedTransaction(Transaction):
    category: Literal["trade","transfer","income","expense","fee","unknown"] = "unknown"
    risk_score: float = 0.0
    risk_flags: List[str] = []
    notes: Optional[str] = None

class ReportRequest(BaseModel):
    wallet_addresses: List[str]
    start: datetime
    end: datetime

class ReportSummary(BaseModel):
    total_in: float
    total_out: float
    fees: float
    suspicious_count: int
    transactions: int
