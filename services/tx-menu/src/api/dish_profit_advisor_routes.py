"""菜品利润图谱增强 — API路由

端点：
  GET  /api/v1/dish-profit/advisor/{store_id}/suggestions   — 获取定价建议列表
  POST /api/v1/dish-profit/advisor/{store_id}/apply          — 批量应用建议
  GET  /api/v1/dish-profit/advisor/{store_id}/table-profit    — 桌均利润分析
  GET  /api/v1/dish-profit/advisor/{store_id}/category-mix    — 品类配比
  GET  /api/v1/dish-profit/advisor/{store_id}/co-occurrence   — 菜品共现图谱
  GET  /api/v1/dish-profit/advisor/{store_id}/price-impact    — 食材涨价影响
  POST /api/v1/dish-profit/advisor/{store_id}/weekly-report   — 手动触发周报
"""

from datetime import date, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.dish_pricing_advisor_service import (
    apply_suggestions,
    compute_category_mix,
    compute_dish_co_occurrence,
    compute_ingredient_price_impact,
    compute_table_profit,
    generate_pricing_suggestions,
    get_co_occurrence,
    get_suggestions,
)
from ..services.dish_profit_weekly_worker import DishProfitWeeklyWorker

logger = structlog.get_logger(__name__)
router = APIRouter(
    prefix="/api/v1/dish-profit/advisor",
    tags=["dish-profit-advisor"],
)


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class ApplySuggestionsRequest(BaseModel):
    """批量应用定价建议"""
    suggestion_ids: list[str] = Field(
        ..., min_length=1, max_length=100,
        description="要应用的建议ID列表",
    )


class GenerateSuggestionsRequest(BaseModel):
    """手动生成定价建议"""
    period_days: int = Field(default=14, ge=7, le=90, description="分析周期天数")


class TriggerWeeklyReportRequest(BaseModel):
    """手动触发周报"""
    store_name: Optional[str] = Field(default=None, description="门店名称，不传则自动查询")


# ─── 1. 获取定价建议列表 ──────────────────────────────────────────────────────


@router.get("/{store_id}/suggestions")
async def list_pricing_suggestions(
    store_id: str,
    status: Optional[str] = Query(None, description="筛选状态: pending/accepted/rejected/applied"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取定价建议列表 — 支持按状态筛选和分页"""
    logger.info(
        "dish_profit.list_suggestions",
        store_id=store_id,
        status=status,
        page=page,
    )

    if status and status not in ("pending", "accepted", "rejected", "applied"):
        raise HTTPException(status_code=400, detail=f"无效状态: {status}，可选: pending/accepted/rejected/applied")

    try:
        offset = (page - 1) * size
        result = await get_suggestions(
            db, x_tenant_id, store_id,
            status_filter=status, limit=size, offset=offset,
        )
        return {
            "ok": True,
            "data": {
                "items": result["items"],
                "total": result["total"],
                "page": page,
                "size": size,
            },
        }
    except SQLAlchemyError as exc:
        logger.error("dish_profit.list_suggestions_error", error=str(exc), store_id=store_id)
        raise HTTPException(status_code=500, detail="查询定价建议失败，请重试")


@router.post("/{store_id}/suggestions/generate")
async def generate_suggestions(
    store_id: str,
    body: GenerateSuggestionsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动触发生成定价建议"""
    logger.info(
        "dish_profit.generate_suggestions",
        store_id=store_id,
        period_days=body.period_days,
    )

    try:
        suggestions = await generate_pricing_suggestions(
            db, x_tenant_id, store_id, period_days=body.period_days,
        )
        return {
            "ok": True,
            "data": {
                "items": suggestions,
                "total": len(suggestions),
                "period_days": body.period_days,
            },
        }
    except SQLAlchemyError as exc:
        logger.error("dish_profit.generate_error", error=str(exc), store_id=store_id)
        raise HTTPException(status_code=500, detail="生成定价建议失败，请重试")


# ─── 2. 批量应用建议 ─────────────────────────────────────────────────────────


@router.post("/{store_id}/apply")
async def apply_pricing_suggestions(
    store_id: str,
    body: ApplySuggestionsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量应用定价建议 — 更新菜品价格并标记建议状态

    应用逻辑：
    - raise: 更新菜品 price_fen 为建议价
    - delist: 将菜品 is_available 设为 FALSE
    - promote/bundle/lower: 仅标记状态，不自动修改
    """
    logger.info(
        "dish_profit.apply_suggestions",
        store_id=store_id,
        count=len(body.suggestion_ids),
    )

    try:
        result = await apply_suggestions(
            db, x_tenant_id, store_id, body.suggestion_ids,
        )
        return {"ok": True, "data": result}
    except SQLAlchemyError as exc:
        logger.error("dish_profit.apply_error", error=str(exc), store_id=store_id)
        raise HTTPException(status_code=500, detail="应用定价建议失败，请重试")


# ─── 3. 桌均利润分析 ─────────────────────────────────────────────────────────


@router.get("/{store_id}/table-profit")
async def get_table_profit(
    store_id: str,
    date_from: Optional[date] = Query(None, description="开始日期"),
    date_to: Optional[date] = Query(None, description="结束日期"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """桌均利润分析

    按桌型分组（2人桌/4人桌/6人桌/包厢），计算：
    - 桌均收入/成本/毛利
    - 坪效：每座位小时利润
    """
    d_from = date_from or (date.today() - timedelta(days=30))
    d_to = date_to or date.today()

    logger.info("dish_profit.table_profit", store_id=store_id, date_from=str(d_from), date_to=str(d_to))

    try:
        result = await compute_table_profit(db, x_tenant_id, store_id, d_from, d_to)
        return {"ok": True, "data": result}
    except SQLAlchemyError as exc:
        logger.error("dish_profit.table_profit_error", error=str(exc), store_id=store_id)
        raise HTTPException(status_code=500, detail="查询桌均利润失败，请重试")


# ─── 4. 品类配比 ─────────────────────────────────────────────────────────────


@router.get("/{store_id}/category-mix")
async def get_category_mix(
    store_id: str,
    date_from: Optional[date] = Query(None, description="开始日期"),
    date_to: Optional[date] = Query(None, description="结束日期"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """品类配比健康度

    对标行业标准：凉菜15% / 热菜45% / 主食20% / 饮品20%
    偏差>5%标记异常，酒水占比<15%提醒加强推荐
    """
    d_from = date_from or (date.today() - timedelta(days=30))
    d_to = date_to or date.today()

    logger.info("dish_profit.category_mix", store_id=store_id, date_from=str(d_from), date_to=str(d_to))

    try:
        result = await compute_category_mix(db, x_tenant_id, store_id, d_from, d_to)
        return {"ok": True, "data": result}
    except SQLAlchemyError as exc:
        logger.error("dish_profit.category_mix_error", error=str(exc), store_id=store_id)
        raise HTTPException(status_code=500, detail="查询品类配比失败，请重试")


# ─── 5. 菜品共现图谱 ─────────────────────────────────────────────────────────


@router.get("/{store_id}/co-occurrence")
async def get_dish_co_occurrence(
    store_id: str,
    dish_id: Optional[str] = Query(None, description="指定菜品ID查看关联"),
    date_from: Optional[date] = Query(None, description="开始日期"),
    date_to: Optional[date] = Query(None, description="结束日期"),
    min_score: float = Query(0.1, ge=0.0, le=1.0, description="最低关联度"),
    refresh: bool = Query(False, description="是否重新计算"),
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """菜品共现图谱

    展示菜品间的共现关联（同一订单中同时出现的频次和Jaccard相似度）。
    用于评估下架影响：如果dog菜与star菜共现率>40%，下架可能连带影响。

    refresh=true 时重新从订单数据计算（耗时较长）。
    """
    d_from = date_from or (date.today() - timedelta(days=30))
    d_to = date_to or date.today()

    logger.info(
        "dish_profit.co_occurrence",
        store_id=store_id,
        dish_id=dish_id,
        refresh=refresh,
    )

    try:
        if refresh:
            result = await compute_dish_co_occurrence(
                db, x_tenant_id, store_id, d_from, d_to,
            )
            return {"ok": True, "data": result}

        # 从已有数据查询
        pairs = await get_co_occurrence(
            db, x_tenant_id, store_id,
            dish_id=dish_id, min_score=min_score, limit=limit,
        )
        return {
            "ok": True,
            "data": {
                "pairs": pairs,
                "total_pairs": len(pairs),
                "date_from": str(d_from),
                "date_to": str(d_to),
            },
        }
    except SQLAlchemyError as exc:
        logger.error("dish_profit.co_occurrence_error", error=str(exc), store_id=store_id)
        raise HTTPException(status_code=500, detail="查询共现图谱失败，请重试")


# ─── 6. 食材涨价影响 ─────────────────────────────────────────────────────────


@router.get("/{store_id}/price-impact")
async def get_ingredient_price_impact(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """食材价格→菜品成本联动分析

    分析最近采购价 vs 上月均价的变动，通过BOM展开计算对菜品成本的影响。
    标红毛利跌破30%阈值的菜品。
    """
    logger.info("dish_profit.price_impact", store_id=store_id)

    try:
        result = await compute_ingredient_price_impact(db, x_tenant_id, store_id)
        return {"ok": True, "data": result}
    except SQLAlchemyError as exc:
        logger.error("dish_profit.price_impact_error", error=str(exc), store_id=store_id)
        raise HTTPException(status_code=500, detail="查询食材涨价影响失败，请重试")


# ─── 7. 手动触发周报 ─────────────────────────────────────────────────────────


@router.post("/{store_id}/weekly-report")
async def trigger_weekly_report(
    store_id: str,
    body: TriggerWeeklyReportRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动触发菜品利润周报生成

    正常场景：每周一03:00自动触发。本端点用于手动补发或测试。
    """
    logger.info("dish_profit.trigger_weekly_report", store_id=store_id)

    store_name = body.store_name
    if not store_name:
        # 自动查询门店名称
        from sqlalchemy import text
        from ..services.dish_pricing_advisor_service import _set_rls

        await _set_rls(db, x_tenant_id)
        name_result = await db.execute(
            text("""
                SELECT store_name FROM stores
                WHERE id = :store_id::uuid AND tenant_id = :tenant_id::uuid
                  AND is_deleted = FALSE
            """),
            {"store_id": store_id, "tenant_id": x_tenant_id},
        )
        row = name_result.scalar_one_or_none()
        store_name = row or store_id[:8]

    try:
        worker = DishProfitWeeklyWorker()
        report_md = await worker.generate_weekly_report(
            db, x_tenant_id, store_id, store_name,
        )

        if not report_md:
            return {
                "ok": True,
                "data": {
                    "message": "无足够数据生成周报",
                    "report": None,
                },
            }

        # 推送
        await worker._push_report(db, x_tenant_id, store_id, store_name, report_md)

        return {
            "ok": True,
            "data": {
                "message": "周报已生成并推送",
                "store_name": store_name,
                "report_preview": report_md[:500] + ("..." if len(report_md) > 500 else ""),
                "report_length": len(report_md),
            },
        }
    except SQLAlchemyError as exc:
        logger.error("dish_profit.weekly_report_error", error=str(exc), store_id=store_id)
        raise HTTPException(status_code=500, detail="生成周报失败，请重试")
