"""日清 E1-E8 API

GET  /api/v1/daily-review/today        — 获取今日日清状态
POST /api/v1/daily-review/complete-node — 手动标记节点完成
GET  /api/v1/daily-review/multi-store  — 多门店日清汇总
"""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ..services.daily_review_service import DailyReviewService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/daily-review", tags=["daily-review"])


@router.get("/today")
async def get_today_review(
    store_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> dict:
    """获取今日日清状态"""
    state = DailyReviewService.get_today_state(x_tenant_id, store_id)
    return {
        "ok": True,
        "data": {
            "date": state.date,
            "store_id": state.store_id,
            "completion_rate": state.completion_rate,
            "health_score": state.health_score,
            "overdue_count": len(state.overdue_nodes),
            "nodes": [
                {
                    "node_id": n.node_id,
                    "name": n.name,
                    "deadline": n.deadline.strftime("%H:%M"),
                    "status": n.status,
                    "completed_at": n.completed_at,
                    "completed_by": n.completed_by,
                    "notes": n.notes,
                }
                for n in state.nodes
            ],
        },
    }


class ManualCompleteRequest(BaseModel):
    store_id: str
    node_id: str
    notes: Optional[str] = None
    operator_id: str


@router.post("/complete-node")
async def manually_complete_node(
    req: ManualCompleteRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> dict:
    """手动标记节点完成（管理员操作）"""
    success = DailyReviewService.mark_node_completed(
        tenant_id=x_tenant_id,
        store_id=req.store_id,
        node_id=req.node_id,
        completed_by=req.operator_id,
        notes=req.notes,
    )
    if not success:
        raise HTTPException(status_code=400, detail="节点不存在或已完成")
    return {"ok": True, "data": {"message": f"节点 {req.node_id} 已标记完成"}}


@router.get("/multi-store")
async def get_multi_store_summary(
    store_ids: str,  # 逗号分隔
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> dict:
    """多门店日清汇总"""
    ids = [s.strip() for s in store_ids.split(",") if s.strip()]
    summary = DailyReviewService.get_multi_store_summary(x_tenant_id, ids)
    return {"ok": True, "data": {"items": summary}}
