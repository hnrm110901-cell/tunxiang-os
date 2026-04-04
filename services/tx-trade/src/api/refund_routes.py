"""退款申请 API 路由（Mock 实现）

小程序顾客端提交退款申请、查询退款状态。
后续接入真实退款流程（微信支付退款 + 审批工作流）。
"""
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/trade/refunds", tags=["refund"])

# ─── 内存 Mock 存储（后续替换为数据库） ───
_mock_refunds: dict = {}


class RefundItemRequest(BaseModel):
    item_id: str
    name: str
    quantity: int
    amount_fen: int


class SubmitRefundRequest(BaseModel):
    order_id: str
    refund_type: str  # "full" | "partial"
    refund_amount_fen: int
    reasons: List[str]
    description: Optional[str] = ""
    items: Optional[List[RefundItemRequest]] = []
    image_urls: Optional[List[str]] = []


class RefundResponse(BaseModel):
    refund_id: str
    order_id: str
    status: str  # "pending" | "approved" | "rejected" | "refunded"
    refund_amount_fen: int
    created_at: str


@router.post("")
async def submit_refund(
    req: SubmitRefundRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """提交退款申请（Mock：直接返回成功）"""
    if req.refund_amount_fen <= 0:
        raise HTTPException(status_code=400, detail="退款金额必须大于0")

    refund_id = "RF" + uuid.uuid4().hex[:12].upper()
    now = datetime.utcnow().isoformat() + "Z"

    refund_record = {
        "refund_id": refund_id,
        "order_id": req.order_id,
        "refund_type": req.refund_type,
        "refund_amount_fen": req.refund_amount_fen,
        "reasons": req.reasons,
        "description": req.description,
        "items": [item.dict() for item in (req.items or [])],
        "image_urls": req.image_urls or [],
        "status": "pending",
        "created_at": now,
        "tenant_id": x_tenant_id or "",
    }
    _mock_refunds[refund_id] = refund_record

    return {
        "ok": True,
        "data": {
            "refund_id": refund_id,
            "order_id": req.order_id,
            "status": "pending",
            "refund_amount_fen": req.refund_amount_fen,
            "created_at": now,
            "message": "退款申请已提交，预计1-3个工作日内审核",
        },
    }


@router.get("/{refund_id}")
async def get_refund_status(
    refund_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """查询退款状态（Mock）"""
    record = _mock_refunds.get(refund_id)
    if not record:
        # Mock 降级：返回一个默认状态
        return {
            "ok": True,
            "data": {
                "refund_id": refund_id,
                "status": "pending",
                "message": "退款审核中",
            },
        }

    return {
        "ok": True,
        "data": {
            "refund_id": record["refund_id"],
            "order_id": record["order_id"],
            "status": record["status"],
            "refund_amount_fen": record["refund_amount_fen"],
            "created_at": record["created_at"],
        },
    }
