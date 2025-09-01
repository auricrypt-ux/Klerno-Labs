
import pandas as pd
from io import StringIO
from .models import TaggedTransaction, ReportSummary

def to_dataframe(txs: list[TaggedTransaction]) -> pd.DataFrame:
    return pd.DataFrame([t.model_dump() for t in txs])

def summary(txs: list[TaggedTransaction]) -> ReportSummary:
    total_in = sum(t.amount for t in txs if t.direction=="in")
    total_out = sum(t.amount for t in txs if t.direction=="out")
    fees = sum((t.fee or 0.0) for t in txs)
    suspicious_count = sum(1 for t in txs if t.risk_score >= 0.75)
    return ReportSummary(
        total_in=total_in, total_out=total_out, fees=fees,
        suspicious_count=suspicious_count, transactions=len(txs)
    )

def csv_export(txs: list[TaggedTransaction]) -> str:
    df = to_dataframe(txs)
    buf = StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()
