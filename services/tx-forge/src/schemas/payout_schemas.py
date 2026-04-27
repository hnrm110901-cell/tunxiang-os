"""提现 Pydantic schemas"""

from datetime import datetime

from pydantic import BaseModel, Field


class PayoutRequest(BaseModel):
    developer_id: str
    amount_fen: int = Field(..., gt=0)
    bank_account: str = Field(..., max_length=200)


class PayoutOut(BaseModel):
    payout_id: str
    developer_id: str
    amount_fen: int
    status: str
    requested_at: datetime

    model_config = {"from_attributes": True}
