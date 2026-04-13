"""员工积分+赛马 API 路由（v253 表）

端点列表（prefix=/api/v1/points）：
  POST /award                        发放积分
  POST /deduct                       扣减积分
  GET  /balance/{employee_id}        查余额
  GET  /history/{employee_id}        积分流水
  GET  /leaderboard                  排行榜
  POST /redeem                       兑换积分
  GET  /rewards                      兑换商品列表
  POST /rewards                      创建兑换商品
  PUT  /rewards/{id}/toggle          启停商品
  GET  /stats                        积分统计概览
  POST /horse-race                   创建赛季
  GET  /horse-race                   赛季列表
  GET  /horse-race/{id}/ranking      赛季排名
  PUT  /horse-race/{id}/status       更新赛季状态

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services import employee_points_service as pts_svc

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/points", tags=["employee-points"])


# ── 辅助 ─────────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> dict:
    raise HTTPException(status_code=code, detail=msg)


# ── 请求模型 ─────────────────────────────────────────────────────────────────


class AwardRequest(BaseModel):
    employee_id: str
    rule_code: str
    reason: str = ""
    operator_id: Optional[str] = None
    source: str = "manual"


class DeductRequest(BaseModel):
    employee_id: str
    rule_code: str
    reason: str = ""
    operator_id: Optional[str] = None
    source: str = "manual"


class RedeemRequest(BaseModel):
    employee_id: str
    reward_id: str


class CreateRewardRequest(BaseModel):
    reward_name: str
    reward_type: str = "leave"
    points_cost: int = Field(..., gt=0)
    stock: int = -1
    description: str = ""


class CreateSeasonRequest(BaseModel):
    season_name: str
    start_date: str  # YYYY-MM-DD
    end_date: str
    scope_type: str = "store"
    scope_id: Optional[str] = None
    ranking_dimension: str = "points"
    prizes: list[dict[str, Any]] = Field(default_factory=list)
    rules: dict[str, Any] = Field(default_factory=dict)


class UpdateSeasonStatusRequest(BaseModel):
    status: str  # upcoming/active/completed


# ── 积分端点 ─────────────────────────────────────────────────────────────────


@router.post("/award")
async def award_points(
    body: AwardRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发放积分"""
    tid = _get_tenant_id(request)
    try:
        result = await pts_svc.award_points_v2(
            db, tid, body.employee_id, body.rule_code,
            reason=body.reason, operator_id=body.operator_id, source=body.source,
        )
        await db.commit()
        return _ok(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/deduct")
async def deduct_points(
    body: DeductRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """扣减积分"""
    tid = _get_tenant_id(request)
    try:
        result = await pts_svc.deduct_points_v2(
            db, tid, body.employee_id, body.rule_code,
            reason=body.reason, operator_id=body.operator_id, source=body.source,
        )
        await db.commit()
        return _ok(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/balance/{employee_id}")
async def get_balance(
    employee_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询积分余额"""
    tid = _get_tenant_id(request)
    try:
        balance = await pts_svc.get_employee_balance_v2(db, tid, employee_id)
        level = pts_svc.compute_level(balance)
        next_name, to_next = pts_svc._next_level_info(balance)
        return _ok({
            "employee_id": employee_id,
            "balance": balance,
            "level": level,
            "next_level": next_name,
            "points_to_next": to_next,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/history/{employee_id}")
async def get_history(
    employee_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """积分流水"""
    tid = _get_tenant_id(request)
    try:
        result = await pts_svc.get_points_history_v2(db, tid, employee_id, page, size)
        return _ok(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/leaderboard")
async def get_leaderboard(
    request: Request,
    scope_type: str = Query("store"),
    scope_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """积分排行榜"""
    tid = _get_tenant_id(request)
    try:
        items = await pts_svc.get_leaderboard_v2(db, tid, scope_type, scope_id, limit)
        return _ok({"items": items, "total": len(items)})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/redeem")
async def redeem_reward(
    body: RedeemRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """兑换积分"""
    tid = _get_tenant_id(request)
    try:
        result = await pts_svc.redeem_reward(db, tid, body.employee_id, body.reward_id)
        await db.commit()
        return _ok(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 兑换商品端点 ─────────────────────────────────────────────────────────────


@router.get("/rewards")
async def list_rewards(
    request: Request,
    active_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """兑换商品列表"""
    tid = _get_tenant_id(request)
    items = await pts_svc.list_rewards(db, tid, active_only)
    return _ok({"items": items, "total": len(items)})


@router.post("/rewards")
async def create_reward(
    body: CreateRewardRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建兑换商品"""
    tid = _get_tenant_id(request)
    result = await pts_svc.create_reward(
        db, tid, body.reward_name, body.reward_type,
        body.points_cost, body.stock, body.description,
    )
    await db.commit()
    return _ok(result)


@router.put("/rewards/{reward_id}/toggle")
async def toggle_reward(
    reward_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """启停商品"""
    tid = _get_tenant_id(request)
    try:
        result = await pts_svc.toggle_reward(db, tid, reward_id)
        await db.commit()
        return _ok(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 统计端点 ─────────────────────────────────────────────────────────────────


@router.get("/stats")
async def get_stats(
    request: Request,
    store_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """积分统计概览"""
    tid = _get_tenant_id(request)
    result = await pts_svc.get_points_stats(db, tid, store_id)
    return _ok(result)


# ── 赛马端点 ─────────────────────────────────────────────────────────────────


@router.post("/horse-race")
async def create_season(
    body: CreateSeasonRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建赛马赛季"""
    tid = _get_tenant_id(request)
    try:
        sd = date.fromisoformat(body.start_date)
        ed = date.fromisoformat(body.end_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"日期格式错误: {e}") from e
    if ed <= sd:
        raise HTTPException(status_code=400, detail="结束日期须晚于开始日期")
    result = await pts_svc.create_horse_race_season(
        db, tid, body.season_name, sd, ed,
        body.scope_type, body.scope_id, body.ranking_dimension,
        body.prizes, body.rules,
    )
    await db.commit()
    return _ok(result)


@router.get("/horse-race")
async def list_seasons(
    request: Request,
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """赛季列表"""
    tid = _get_tenant_id(request)
    items = await pts_svc.list_horse_race_seasons(db, tid, status)
    return _ok({"items": items, "total": len(items)})


@router.get("/horse-race/{season_id}/ranking")
async def get_season_ranking(
    season_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """赛季排名"""
    tid = _get_tenant_id(request)
    try:
        result = await pts_svc.get_horse_race_season_ranking(db, tid, season_id, limit)
        return _ok(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/horse-race/{season_id}/status")
async def update_season_status(
    season_id: str,
    body: UpdateSeasonStatusRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新赛季状态"""
    tid = _get_tenant_id(request)
    try:
        result = await pts_svc.update_horse_race_status(db, tid, season_id, body.status)
        await db.commit()
        return _ok(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
