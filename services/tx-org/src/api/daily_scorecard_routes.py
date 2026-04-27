"""日KPI得分卡 + 绩效奖金 + 门店生命周期 API路由

10个端点，覆盖：
  - 日得分卡计算/查询/排行/推送
  - 月度奖金预览/计算/规则管理
  - 门店生命周期概览/详情

金额单位：分(fen)，API响应同时提供_yuan浮点。
"""

from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.bonus_calculator_service import BonusCalculatorService
from ..services.daily_scorecard_service import DailyScorecardService
from ..services.store_lifecycle_service import StoreLifecycleService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org/scorecard", tags=["daily-scorecard"])
bonus_router = APIRouter(prefix="/api/v1/org/bonus", tags=["bonus"])
lifecycle_router = APIRouter(prefix="/api/v1/org/lifecycle", tags=["store-lifecycle"])

_scorecard_svc = DailyScorecardService()
_bonus_svc = BonusCalculatorService()
_lifecycle_svc = StoreLifecycleService()


# ── Pydantic 请求/响应模型 ──────────────────────────────────────────


class ComputeRequest(BaseModel):
    score_date: Optional[date] = None


class BonusRuleUpdate(BaseModel):
    role: str
    base_amount_fen: int = Field(ge=0)
    tier_config: list[dict] = Field(
        default_factory=lambda: [
            {"min_score": 90, "max_score": 100, "multiplier": 1.5},
            {"min_score": 80, "max_score": 89, "multiplier": 1.2},
            {"min_score": 70, "max_score": 79, "multiplier": 1.0},
            {"min_score": 0, "max_score": 69, "multiplier": 0.8},
        ]
    )


# ── 日得分卡端点 ────────────────────────────────────────────────────


@router.post("/{store_id}/compute")
async def compute_daily_scorecards(
    store_id: UUID,
    body: ComputeRequest = ComputeRequest(),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """计算指定门店当日(或指定日期)所有员工的日得分卡"""
    try:
        target_date = body.score_date or date.today()
        result = await _scorecard_svc.compute_daily_scores(
            db, UUID(store_id.hex), UUID(x_tenant_id), target_date
        )
        return {"ok": True, "data": {"score_date": str(target_date), "scorecards": result}}
    except SQLAlchemyError as exc:
        logger.error("compute_scorecards_failed", store_id=str(store_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Internal database error") from exc


@router.get("/{store_id}/today")
async def get_today_ranking(
    store_id: UUID,
    role: Optional[str] = Query(None, description="按角色筛选: waiter/chef/purchaser/manager"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """今日门店排行榜"""
    try:
        result = await _scorecard_svc.get_store_ranking(
            db, UUID(store_id.hex), UUID(x_tenant_id), date.today(), role=role
        )
        return {"ok": True, "data": {"date": str(date.today()), "ranking": result}}
    except SQLAlchemyError as exc:
        logger.error("get_ranking_failed", store_id=str(store_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Internal database error") from exc


@router.get("/{store_id}/employee/{employee_id}")
async def get_employee_scorecard_history(
    store_id: UUID,
    employee_id: UUID,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """个人得分卡历史"""
    try:
        result = await _scorecard_svc.get_scorecard(
            db,
            UUID(store_id.hex),
            UUID(x_tenant_id),
            UUID(employee_id.hex),
            start_date=start_date,
            end_date=end_date,
        )
        return {"ok": True, "data": {"employee_id": str(employee_id), "records": result}}
    except SQLAlchemyError as exc:
        logger.error("get_scorecard_failed", employee_id=str(employee_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Internal database error") from exc


@router.post("/{store_id}/push")
async def push_daily_scorecards(
    store_id: UUID,
    body: ComputeRequest = ComputeRequest(),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """推送日得分卡到企微/钉钉/飞书"""
    try:
        target_date = body.score_date or date.today()
        pushed_count = await _scorecard_svc.push_scorecards_via_im(
            db, UUID(store_id.hex), UUID(x_tenant_id), target_date
        )
        return {"ok": True, "data": {"pushed_count": pushed_count, "score_date": str(target_date)}}
    except SQLAlchemyError as exc:
        logger.error("push_scorecards_failed", store_id=str(store_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Internal database error") from exc


# ── 奖金端点 ────────────────────────────────────────────────────────


@bonus_router.get("/{store_id}/preview")
async def preview_monthly_bonus(
    store_id: UUID,
    year: int = Query(..., ge=2020, le=2099),
    month: int = Query(..., ge=1, le=12),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """月度奖金预览（基于截至今日的得分预估）"""
    try:
        result = await _bonus_svc.preview_bonus(
            db, UUID(store_id.hex), UUID(x_tenant_id), year, month
        )
        return {"ok": True, "data": result}
    except SQLAlchemyError as exc:
        logger.error("preview_bonus_failed", store_id=str(store_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Internal database error") from exc


@bonus_router.post("/{store_id}/calculate")
async def calculate_monthly_bonus(
    store_id: UUID,
    year: int = Query(..., ge=2020, le=2099),
    month: int = Query(..., ge=1, le=12),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """计算月度绩效奖金"""
    try:
        result = await _bonus_svc.calculate_monthly_bonus(
            db, UUID(store_id.hex), UUID(x_tenant_id), year, month
        )
        return {"ok": True, "data": {"year": year, "month": month, "bonuses": result}}
    except SQLAlchemyError as exc:
        logger.error("calculate_bonus_failed", store_id=str(store_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Internal database error") from exc


@bonus_router.get("/rules")
async def get_bonus_rules(
    store_id: Optional[UUID] = Query(None, description="门店级规则，NULL=品牌级"),
    role: Optional[str] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取奖金规则"""
    try:
        result = await _bonus_svc.get_rules(
            db, UUID(x_tenant_id), store_id=store_id, role=role
        )
        return {"ok": True, "data": {"rules": result}}
    except SQLAlchemyError as exc:
        logger.error("get_bonus_rules_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Internal database error") from exc


@bonus_router.put("/rules")
async def update_bonus_rules(
    body: BonusRuleUpdate,
    store_id: Optional[UUID] = Query(None, description="门店级规则，NULL=品牌级"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """更新奖金规则"""
    try:
        result = await _bonus_svc.upsert_rule(
            db,
            UUID(x_tenant_id),
            store_id=store_id,
            role=body.role,
            base_amount_fen=body.base_amount_fen,
            tier_config=body.tier_config,
        )
        return {"ok": True, "data": result}
    except SQLAlchemyError as exc:
        logger.error("update_bonus_rules_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Internal database error") from exc


# ── 门店生命周期端点 ────────────────────────────────────────────────


@lifecycle_router.get("/overview")
async def get_lifecycle_overview(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """所有门店生命周期概览（总部视角）"""
    try:
        result = await _lifecycle_svc.get_lifecycle_overview(db, UUID(x_tenant_id))
        return {"ok": True, "data": {"stores": result}}
    except SQLAlchemyError as exc:
        logger.error("get_lifecycle_overview_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Internal database error") from exc


@lifecycle_router.get("/{store_id}")
async def get_store_lifecycle(
    store_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """单店生命周期详情"""
    try:
        result = await _lifecycle_svc.determine_stage(
            db, UUID(store_id.hex), UUID(x_tenant_id)
        )
        return {"ok": True, "data": result}
    except SQLAlchemyError as exc:
        logger.error("get_store_lifecycle_failed", store_id=str(store_id), error=str(exc))
        raise HTTPException(status_code=500, detail="Internal database error") from exc
