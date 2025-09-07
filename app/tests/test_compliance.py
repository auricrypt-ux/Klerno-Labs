from decimal import Decimal
from app.compliance import tag_category, tag_categories, AddressBook

class T:
    def __init__(self, **kw):
        self.memo = kw.get("memo", "")
        self.fee = kw.get("fee", Decimal("0"))
        self.amount = kw.get("amount", Decimal("0"))
        self.direction = kw.get("direction", "out")
        self.from_address = kw.get("from_address")
        self.to_address = kw.get("to_address")

def test_fee_detection():
    tx = T(memo="network fee", amount=Decimal("-1"), fee=Decimal("0.1"), direction="out")
    assert tag_category(tx) == "fee"

def test_keyword_boundary():
    tx = T(memo="gasoline purchase", amount=Decimal("-10"), fee=Decimal("0"))
    assert tag_category(tx) != "fee"

def test_internal_transfer():
    book = AddressBook(owned={"rA", "rB"})
    tx = T(memo="move funds", from_address="rA", to_address="rB")
    cats = tag_categories(tx, address_book=book)
    assert cats[0].category in {"transfer", "income", "expense"}
