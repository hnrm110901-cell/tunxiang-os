"""意见反馈 API"""

from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/member", tags=["suggestion"])


class SuggestionReq(BaseModel):
    type: str = "suggestion"  # suggestion / complaint / bug / other
    content: str
    image_urls: List[str] = []
    contact_phone: str = ""
    store_id: str = ""
    customer_id: str = ""


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


@router.post("/suggestions")
async def create_suggestion(
    req: SuggestionReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """提交意见反馈"""
    try:
        await _set_tenant(db, x_tenant_id)
        store_id: Optional[UUID] = UUID(req.store_id) if req.store_id else None
        customer_id: Optional[UUID] = UUID(req.customer_id) if req.customer_id else None
        result = await db.execute(
            text("""
                INSERT INTO customer_suggestions
                    (tenant_id, store_id, customer_id, category, content, contact_phone)
                VALUES
                    (:tenant_id, :store_id, :customer_id, :category, :content, :contact_phone)
                RETURNING id, created_at
            """),
            {
                "tenant_id": UUID(x_tenant_id),
                "store_id": store_id,
                "customer_id": customer_id,
                "category": req.type,
                "content": req.content,
                "contact_phone": req.contact_phone or None,
            },
        )
        await db.commit()
        row = result.fetchone()
        logger.info(
            "suggestion_created",
            suggestion_id=str(row.id),
            type=req.type,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": {"id": str(row.id), "created_at": row.created_at.isoformat()}}
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("suggestion_create_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误") from exc


@router.get("/suggestions")
async def list_suggestions(
    store_id: Optional[str] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取意见反馈列表"""
    try:
        await _set_tenant(db, x_tenant_id)
        if store_id:
            result = await db.execute(
                text("""
                    SELECT id, category, content, contact_phone, store_id,
                           customer_id, status, reply, replied_at, created_at
                    FROM customer_suggestions
                    WHERE is_deleted = FALSE
                      AND store_id = :store_id
                    ORDER BY created_at DESC
                    LIMIT 50
                """),
                {"store_id": UUID(store_id)},
            )
        else:
            result = await db.execute(
                text("""
                    SELECT id, category, content, contact_phone, store_id,
                           customer_id, status, reply, replied_at, created_at
                    FROM customer_suggestions
                    WHERE is_deleted = FALSE
                    ORDER BY created_at DESC
                    LIMIT 50
                """),
            )
        rows = result.fetchall()
        items = [
            {
                "id": str(r.id),
                "category": r.category,
                "content": r.content,
                "contact_phone": r.contact_phone,
                "store_id": str(r.store_id) if r.store_id else None,
                "customer_id": str(r.customer_id) if r.customer_id else None,
                "status": r.status,
                "reply": r.reply,
                "replied_at": r.replied_at.isoformat() if r.replied_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except SQLAlchemyError as exc:
        logger.error("suggestion_list_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误") from exc
