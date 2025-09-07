from app.models import Transaction, TaggedTransaction, ReportRequest, ReportSummary
print("import ok")
t = Transaction(tx_id="1", amount=5, direction="out")
tt = TaggedTransaction(**t.__dict__, risk_score=0.9, risk_flags=["large_outgoing"])
print("Tagged:", tt.risk_score, tt.risk_flags, tt.score, tt.flags)
print("report req ok:", ReportRequest(wallet_addresses=["rAlice","rBob"]))
