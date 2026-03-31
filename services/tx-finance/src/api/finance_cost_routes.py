"""财务成本 API 路由（成本核算引擎 v2）

端点：
  GET  /api/v1/finance/cost/daily?store_id=&date=
       → 日成本快报（食材成本/成本率/毛利率/健康度）

  GET  /api/v1/finance/cost/breakdown?store_id=&start_date=&end_date=
       → 成本明细（各菜品成本占比 TOP10）

  GET  /api/v1/finance/health/cost-rate?store_id=&date=
       → 成本健康指数（与目标值对比，红黄绿信号）

  GET  /api/v1/finance/store-cost-config?store_id=
       → 门店固定成本配置读取

  PUT  /api/v1/finance/store-cost-config
       → 门店固定成本配置写入
"""
import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant
from services.tx_finance.src.services.cost_engine_service import (
    CostEngineService,
    calculate_cost_health_score,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["finance-cost"])

_cost_svc = CostEngineService()


# ─── 请求模型 ─────────────────────────────────────────────────────────────────

class StoreCostConfigRequest(BaseModel):
    store_id: str = Field(..., description="门店ID（UUID）")
    monthly_rent_fen: int = Field(ge=0, description="月租金（分）")
    monthly_utility_fen: int = Field(ge=0, description="月水电费（分）")
    monthly_other_fixed_fen: int = Field(ge=0, description="月其他固定费（分）")


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


def _parse_date_param(d: str) -> date:
    if d == "today":
        return date.today()
    try:
        return date.fromisoformat(d)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"日期格式错误: {d}，请使用 YYYY-MM-DD"
        ) from exc


# ─── GET /cost/daily ──────────────────────────────────────────────────────────

@router.get("/cost/daily", summary="日成本快报")
async def get_daily_cost(
    store_id: str = Query(..., description="门店ID"),
    date: str = Query("today", description="业务日期 YYYY-MM-DD 或 today"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """门店日成本快报

    返回：
    - food_cost_fen: 食材成本（分，BOM展开或30%估算）
    - food_cost_rate: 食材成本率（目标≤30%）
    - gross_profit_fen: 毛利
    - gross_margin_rate: 毛利率（目标≥70%）
    - is_estimated: 是否使用估算值
    - cost_breakdown: TOP10 菜品成本占比
    - health: 成本健康度评分（绿/黄/橙/红）
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    biz_date = _parse_date_param(date)

    try:
        report = await _cost_svc.get_daily_cost_report(sid, biz_date, tid, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": report.to_dict()}


# ─── GET /cost/breakdown ──────────────────────────────────────────────────────

@router.get("/cost/breakdown", summary="成本明细（菜品占比）")
async def get_cost_breakdown(
    store_id: str = Query(..., description="门店ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    top_n: int = Query(10, ge=1, le=50, description="TOP N 菜品"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """成本明细报表

    按菜品聚合成本，返回 TOP N：
    - total_cost_fen: 该菜品总成本
    - avg_cost_fen: 平均单份成本
    - cost_ratio: 占总成本比例
    - total_revenue_fen: 该菜品营收贡献
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    start = _parse_date_param(start_date)
    end = _parse_date_param(end_date)

    if start > end:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    try:
        report = await _cost_svc.get_cost_breakdown(sid, start, end, tid, db, top_n=top_n)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": report.to_dict()}


# ─── GET /health/cost-rate ────────────────────────────────────────────────────

@router.get("/health/cost-rate", summary="成本健康指数")
async def get_cost_health(
    store_id: str = Query(..., description="门店ID"),
    date: str = Query("today", description="业务日期 YYYY-MM-DD 或 today"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """成本健康指数

    根据实际食材成本率计算健康度评分：
    - ≤28%: 绿色（优秀）score=90-100
    - 28-32%: 黄色（正常）score=70-89
    - 32-36%: 橙色（偏高）score=50-69
    - >36%: 红色（危险）score=0-49

    返回与目标值（30%）的差距，给出改善建议信号。
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    biz_date = _parse_date_param(date)

    try:
        report = await _cost_svc.get_daily_cost_report(sid, biz_date, tid, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    health = report.health

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "biz_date": str(biz_date),
            "revenue_fen": report.revenue_fen,
            "food_cost_fen": report.food_cost_fen,
            "is_estimated": report.is_estimated,
            **(health.to_dict() if health else {}),
        },
    }


# ─── GET /store-cost-config ───────────────────────────────────────────────────

@router.get("/store-cost-config", summary="门店固定成本配置读取")
async def get_store_cost_config(
    store_id: str = Query(..., description="门店ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """读取门店月度固定成本配置（房租/水电/其他）

    金额单位：分（fen）。
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    try:
        config = await _cost_svc.get_store_cost_config(sid, tid, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": config}


# ─── PUT /store-cost-config ───────────────────────────────────────────────────

@router.put("/store-cost-config", summary="门店固定成本配置写入")
async def update_store_cost_config(
    body: StoreCostConfigRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """写入门店月度固定成本配置

    Body:
    - store_id: 门店ID
    - monthly_rent_fen: 月租金（分）
    - monthly_utility_fen: 月水电费（分）
    - monthly_other_fixed_fen: 月其他固定费（分）

    这些配置用于 P&L 损益表中的经营费用按天摊销。
    """
    sid = _parse_uuid(body.store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    try:
        config = await _cost_svc.update_store_cost_config(
            store_id=sid,
            tenant_id=tid,
            monthly_rent_fen=body.monthly_rent_fen,
            monthly_utility_fen=body.monthly_utility_fen,
            monthly_other_fixed_fen=body.monthly_other_fixed_fen,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": config}
