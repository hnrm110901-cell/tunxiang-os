"""拼单API — 社群拼单功能

前缀: /api/v1/trade/group-orders

端点:
  POST /                   — 创建拼单
  GET  /{code}             — 查看拼单详情
  POST /{code}/join        — 加入拼单
  POST /{code}/lock        — 锁定拼单（停止加人，准备结算）
  POST /{code}/cancel      — 取消拼单
"""

from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/trade/group-orders", tags=["group-order"])


class CreateGroupOrderRequest(BaseModel):
    store_id: str
    min_people: int = Field(default=2, ge=2, le=20)
    max_people: int = Field(default=8, ge=2, le=20)
    discount_rate: float = Field(default=0.95, ge=0.5, le=1.0)


class GroupOrderResponse(BaseModel):
    id: str
    code: str
    store_id: str
    store_name: str
    creator_name: str
    status: str
    min_people: int
    max_people: int
    discount_rate: float
    participants: list[dict]
    total_fen: int
    expires_at: str


# 内存存储（生产环境→DB）
_groups: dict[str, GroupOrderResponse] = {}


def _gen_code() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def _require_tenant(tid: Optional[str]) -> str:
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID required")
    return tid


@router.post("")
async def create_group_order(
    req: CreateGroupOrderRequest,
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
):
    """创建拼单"""
    tid = _require_tenant(x_tenant_id)
    gid = str(uuid.uuid4())
    code = _gen_code()
    now = datetime.now(timezone.utc)

    group = GroupOrderResponse(
        id=gid,
        code=code,
        store_id=req.store_id,
        store_name="徐记海鲜",
        creator_name="发起人",
        status="open",
        min_people=req.min_people,
        max_people=req.max_people,
        discount_rate=req.discount_rate,
        participants=[
            {
                "user_id": tid,
                "nickname": "发起人",
                "avatar_url": "",
                "item_count": 0,
                "subtotal_fen": 0,
                "is_ready": False,
            }
        ],
        total_fen=0,
        expires_at=(now + timedelta(minutes=30)).isoformat(),
    )
    _groups[code] = group
    logger.info("group_order_created", code=code, store=req.store_id)
    return {"ok": True, "data": group.model_dump()}


@router.get("/{code}")
async def get_group_order(
    code: str,
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
):
    """查看拼单"""
    _require_tenant(x_tenant_id)
    group = _groups.get(code)
    if not group:
        raise HTTPException(status_code=404, detail="拼单不存在")
    return {"ok": True, "data": group.model_dump()}


@router.post("/{code}/join")
async def join_group_order(
    code: str,
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
):
    """加入拼单"""
    tid = _require_tenant(x_tenant_id)
    group = _groups.get(code)
    if not group:
        raise HTTPException(status_code=404, detail="拼单不存在")
    if group.status != "open":
        raise HTTPException(status_code=400, detail="拼单已锁定或已结束")
    if len(group.participants) >= group.max_people:
        raise HTTPException(status_code=400, detail="拼单人数已满")

    group.participants.append(
        {
            "user_id": tid,
            "nickname": f"参与者{len(group.participants) + 1}",
            "avatar_url": "",
            "item_count": 0,
            "subtotal_fen": 0,
            "is_ready": False,
        }
    )
    logger.info("group_order_joined", code=code, user=tid, count=len(group.participants))
    return {"ok": True, "data": group.model_dump()}


@router.post("/{code}/lock")
async def lock_group_order(
    code: str,
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
):
    """锁定拼单"""
    _require_tenant(x_tenant_id)
    group = _groups.get(code)
    if not group:
        raise HTTPException(status_code=404, detail="拼单不存在")
    group.status = "locked"
    return {"ok": True, "data": group.model_dump()}


@router.post("/{code}/cancel")
async def cancel_group_order(
    code: str,
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
):
    """取消拼单"""
    _require_tenant(x_tenant_id)
    group = _groups.get(code)
    if not group:
        raise HTTPException(status_code=404, detail="拼单不存在")
    group.status = "cancelled"
    return {"ok": True, "data": {"code": code, "status": "cancelled"}}
