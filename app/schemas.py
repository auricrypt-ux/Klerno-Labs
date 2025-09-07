from pydantic import BaseModel

class TagReasonOut(BaseModel):
    category: str
    reason: str

class TagResultOut(BaseModel):
    category: str
    score: float
    reasons: list[TagReasonOut]
