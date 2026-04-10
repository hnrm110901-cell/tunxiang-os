"""退款申请 API 路由（DB版，v167）

端点：
  POST /api/v1/trade/refunds        — 提交退款申请
  GET  /api/v1/trade/refunds/{id}   — 查询退款状态
"""
import json
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/trade/refunds", tags=["refund"])


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


@router.post("")
async def submit_refund(
    req: SubmitRefundRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """提交退款申请，写入 refund_requests 表"""
    if req.refund_amount_fen <= 0:
        raise HTTPException(status_code=400, detail="退款金额必须大于0")

    tenant_id = x_tenant_id or ""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        result = await db.execute(
            text("""
                INSERT INTO refund_requests
                    (tenant_id, order_id, refund_type, refund_amount_fen,
                     reasons, description, items, image_urls, status)
                VALUES
                    (:tenant_id, :order_id, :refund_type, :refund_amount_fen,
                     :reasons::jsonb, :description, :items::jsonb, :image_urls::jsonb, 'pending')
                RETURNING id, created_at
            """),
            {
                "tenant_id": tenant_id,
                "order_id": str(req.order_id),
                "refund_type": req.refund_type,
                "refund_amount_fen": req.refund_amount_fen,
                "reasons": json.dumps(req.reasons, ensure_ascii=False),
                "description": req.description or "",
                "items": json.dumps([item.model_dump() for item in (req.items or [])], ensure_ascii=False),
                "image_urls": json.dumps(req.image_urls or [], ensure_ascii=False),
            },
        )
        row = result.mappings().one()
        await db.commit()

        return {
            "ok": True,
            "data": {
                "refund_id": str(row["id"]),
                "order_id": req.order_id,
                "status": "pending",
                "refund_amount_fen": req.refund_amount_fen,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "message": "退款申请已提交，预计1-3个工作日内审核",
            },
        }
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("submit_refund_db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="退款申请提交失败，请稍后重试")


@router.get("/{refund_id}")
async def get_refund_status(
    refund_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询退款状态"""
    tenant_id = x_tenant_id or ""
    try:
        # 验证 UUID 格式
        UUID(refund_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="refund_id 格式无效")

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        result = await db.execute(
            text("""
                SELECT id, order_id, status, refund_amount_fen, refund_type,
                       review_note, reviewed_at, created_at
                FROM refund_requests
                WHERE id = :rid
            """),
            {"rid": refund_id},
        )
        row = result.mappings().one_or_none()

        if not row:
            raise HTTPException(status_code=404, detail="退款申请不存在")

        data = {
            "refund_id": str(row["id"]),
            "order_id": str(row["order_id"]),
            "status": row["status"],
            "refund_amount_fen": int(row["refund_amount_fen"]),
            "refund_type": row["refund_type"],
            "review_note": row["review_note"] or "",
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        if row["reviewed_at"]:
            data["reviewed_at"] = row["reviewed_at"].isoformat()

        return {"ok": True, "data": data}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("get_refund_status_db_error", refund_id=refund_id, error=str(exc))
        raise HTTPException(status_code=500, detail="查询退款状态失败")
