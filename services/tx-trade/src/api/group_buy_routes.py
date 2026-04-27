"""拼团 API — 7个端点

1. POST   /api/v1/group-buy/activities            创建拼团活动
2. GET    /api/v1/group-buy/activities            活动列表
3. POST   /api/v1/group-buy/teams                 发起拼团（开团）
4. POST   /api/v1/group-buy/teams/{id}/join       参与拼团
5. GET    /api/v1/group-buy/teams/{id}            拼团详情
6. POST   /api/v1/group-buy/expire-check          超时处理（定时任务）
7. GET    /api/v1/group-buy/activities/{id}       活动详情
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..services import group_buy_service

router = APIRouter(prefix="/api/v1/group-buy", tags=["group-buy"])


async def get_db() -> AsyncSession:  # type: ignore[override]
    raise NotImplementedError("DB session dependency not configured")


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str, status: int = 400) -> dict:
    return {"ok": False, "error": {"message": msg}}


# ── 请求模型 ──────────────────────────────────────────────────


class CreateActivityReq(BaseModel):
    name: str
    product_id: str
    product_name: str
    original_price_fen: int = Field(ge=1)
    group_price_fen: int = Field(ge=1)
    group_size: int = Field(ge=2, le=20, default=2)
    time_limit_minutes: int = Field(ge=10, default=1440)
    max_teams: int = Field(ge=1, default=100)
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class CreateTeamReq(BaseModel):
    activity_id: str
    initiator_id: str


class JoinTeamReq(BaseModel):
    customer_id: str


# ── 1. 创建拼团活动 ──────────────────────────────────────────


@router.post("/activities")
async def create_activity(
    body: CreateActivityReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await group_buy_service.create_activity(
            name=body.name,
            product_id=body.product_id,
            product_name=body.product_name,
            original_price_fen=body.original_price_fen,
            group_price_fen=body.group_price_fen,
            group_size=body.group_size,
            time_limit_minutes=body.time_limit_minutes,
            max_teams=body.max_teams,
            start_time=body.start_time,
            end_time=body.end_time,
            tenant_id=x_tenant_id,
            db=db,
        )
        await db.commit()
        return ok_response(result)
    except ValueError as exc:
        return error_response(str(exc))


# ── 2. 活动列表 ──────────────────────────────────────────────


@router.get("/activities")
async def list_activities(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await group_buy_service.list_activities(
        tenant_id=x_tenant_id,
        db=db,
        status=status,
        page=page,
        size=size,
    )
    return ok_response(result)


# ── 3. 发起拼团 ──────────────────────────────────────────────


@router.post("/teams")
async def create_team(
    body: CreateTeamReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await group_buy_service.create_team(
            activity_id=body.activity_id,
            initiator_id=body.initiator_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        await db.commit()
        return ok_response(result)
    except ValueError as exc:
        return error_response(str(exc))


# ── 4. 参与拼团 ──────────────────────────────────────────────


@router.post("/teams/{team_id}/join")
async def join_team(
    team_id: str,
    body: JoinTeamReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await group_buy_service.join_team(
            team_id=team_id,
            customer_id=body.customer_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        await db.commit()
        return ok_response(result)
    except ValueError as exc:
        return error_response(str(exc))


# ── 5. 拼团详情 ──────────────────────────────────────────────


@router.get("/teams/{team_id}")
async def get_team_detail(
    team_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await group_buy_service.get_team_detail(
        team_id=team_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    if result is None:
        return error_response("team_not_found")
    return ok_response(result)


# ── 6. 超时处理 ──────────────────────────────────────────────


@router.post("/expire-check")
async def expire_check(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await group_buy_service.expire_teams(
        tenant_id=x_tenant_id,
        db=db,
    )
    await db.commit()
    return ok_response(result)
