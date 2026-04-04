"""意见反馈 API — Mock 实现，待接入真实数据库"""
from typing import List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Header
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/member", tags=["suggestion"])


class SuggestionReq(BaseModel):
    type: str = "suggestion"  # suggestion / complaint / bug / other
    content: str
    image_urls: List[str] = []
    contact_phone: str = ""
    store_id: str = ""
    customer_id: str = ""


# Mock 数据
_mock_suggestions: list = []


@router.post("/suggestions")
async def create_suggestion(
    req: SuggestionReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """提交意见反馈"""
    suggestion_id = str(uuid4())
    item = {
        "id": suggestion_id,
        "type": req.type,
        "content": req.content,
        "image_urls": req.image_urls,
        "contact_phone": req.contact_phone,
        "store_id": req.store_id,
        "customer_id": req.customer_id,
        "status": "pending",
    }
    _mock_suggestions.append(item)
    logger.info(
        "suggestion_created",
        suggestion_id=suggestion_id,
        type=req.type,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": {"id": suggestion_id}}


@router.get("/suggestions")
async def list_suggestions(
    page: int = 1,
    size: int = 20,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取意见反馈列表"""
    start = (page - 1) * size
    items = _mock_suggestions[start : start + size]
    return {"ok": True, "data": {"items": items, "total": len(_mock_suggestions)}}
