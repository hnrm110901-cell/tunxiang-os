"""CEO今日经营驾驶舱 API 路由 — Sprint G6

端点列表：
  GET /api/v1/ceo-cockpit/{store_id}/today          — 单店今日驾驶舱(完整数据)
  GET /api/v1/ceo-cockpit/{store_id}/daypart         — 时段P&L明细
  GET /api/v1/ceo-cockpit/{store_id}/delivery-profit — 外卖真实利润
  GET /api/v1/ceo-cockpit/{store_id}/decisions       — AI决策卡片
  GET /api/v1/ceo-cockpit/{store_id}/anomalies       — 异常高亮
  GET /api/v1/ceo-cockpit/{store_id}/month-progress  — 月度进度
  GET /api/v1/ceo-cockpit/overview                   — 多店概览(总部)

鉴权：X-Tenant-ID header 必填
响应格式：{ "ok": bool, "data": {}, "error": {} }
"""

from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.ceo_cockpit_service import CEOCockpitService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/ceo-cockpit", tags=["ceo-cockpit"])

_svc = CEOCockpitService()


# ─── 1. 单店今日驾驶舱（完整数据） ───────────────────────────


@router.get("/{store_id}/today")
async def api_ceo_cockpit_today(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """单店今日经营驾驶舱 -- CEO打开看到的完整画面"""
    try:
        data = await _svc.get_today_cockpit(db=db, store_id=store_id, tenant_id=x_tenant_id)
        return {"ok": True, "data": data}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("api_ceo_cockpit_today.error", store_id=store_id, exc_info=True)
        raise HTTPException(status_code=500, detail="数据库查询失败，请稍后重试") from exc


# ─── 2. 时段P&L明细 ─────────────────────────────────────


@router.get("/{store_id}/daypart")
async def api_ceo_cockpit_daypart(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """时段P&L明细 — 午市/下午茶/晚市/夜宵独立核算"""
    try:
        data = await _svc._compute_daypart_pnl(
            db=db, store_id=store_id, tenant_id=x_tenant_id, target_date=date.today()
        )
        return {"ok": True, "data": data}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("api_ceo_cockpit_daypart.error", store_id=store_id, exc_info=True)
        raise HTTPException(status_code=500, detail="时段P&L查询失败") from exc


# ─── 3. 外卖真实利润 ────────────────────────────────────


@router.get("/{store_id}/delivery-profit")
async def api_ceo_cockpit_delivery_profit(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """外卖真实利润 — 扣佣金(美团18%/饿了么20%/抖音10%)+包装+补贴"""
    try:
        data = await _svc._compute_delivery_real_profit(
            db=db, store_id=store_id, tenant_id=x_tenant_id, target_date=date.today()
        )
        return {"ok": True, "data": data}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("api_ceo_cockpit_delivery_profit.error", store_id=store_id, exc_info=True)
        raise HTTPException(status_code=500, detail="外卖利润查询失败") from exc


# ─── 4. AI决策卡片 ──────────────────────────────────────


@router.get("/{store_id}/decisions")
async def api_ceo_cockpit_decisions(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """AI决策卡片 — 最多3条，按优先级排序"""
    try:
        data = await _svc._generate_ai_decisions(
            db=db, store_id=store_id, tenant_id=x_tenant_id, target_date=date.today()
        )
        return {"ok": True, "data": {"decisions": data, "count": len(data)}}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("api_ceo_cockpit_decisions.error", store_id=store_id, exc_info=True)
        raise HTTPException(status_code=500, detail="AI决策查询失败") from exc


# ─── 5. 异常高亮 ────────────────────────────────────────


@router.get("/{store_id}/anomalies")
async def api_ceo_cockpit_anomalies(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """异常高亮 — 只显示偏离基线(±20%/±35%)的指标"""
    try:
        data = await _svc._detect_anomalies(
            db=db, store_id=store_id, tenant_id=x_tenant_id, target_date=date.today()
        )
        return {
            "ok": True,
            "data": {
                "anomalies": data,
                "count": len(data),
                "has_critical": any(a["severity"] == "critical" for a in data),
            },
        }
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("api_ceo_cockpit_anomalies.error", store_id=store_id, exc_info=True)
        raise HTTPException(status_code=500, detail="异常检测查询失败") from exc


# ─── 6. 月度进度 ────────────────────────────────────────


@router.get("/{store_id}/month-progress")
async def api_ceo_cockpit_month_progress(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """月度目标进度条 — ahead/on_track/behind节奏判断"""
    try:
        data = await _svc._compute_month_progress(
            db=db, store_id=store_id, tenant_id=x_tenant_id, target_date=date.today()
        )
        return {"ok": True, "data": data}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("api_ceo_cockpit_month_progress.error", store_id=store_id, exc_info=True)
        raise HTTPException(status_code=500, detail="月度进度查询失败") from exc


# ─── 7. 多店概览（总部视角） ─────────────────────────────


@router.get("/overview")
async def api_ceo_cockpit_overview(
    brand_id: Optional[str] = Query(None, description="品牌ID（可选）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """多店概览（总部视角）— 门店排行+失血门店"""
    try:
        data = await _svc.get_multi_store_cockpit(
            db=db, tenant_id=x_tenant_id, brand_id=brand_id
        )
        return {"ok": True, "data": data}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("api_ceo_cockpit_overview.error", tenant_id=x_tenant_id, exc_info=True)
        raise HTTPException(status_code=500, detail="多店概览查询失败") from exc
