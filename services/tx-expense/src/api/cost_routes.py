"""
成本归集 API 路由

负责每日成本归集日报查询、手工调整、归集明细、趋势分析及手动触发归集。
共 6 个端点，覆盖成本归集全生命周期（自动归集→人工核查→调整→趋势分析）。

金额约定：所有金额字段单位为分(fen)，1元=100分，展示层负责转换。
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# 依赖注入
# ---------------------------------------------------------------------------

async def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的租户ID格式")


# ---------------------------------------------------------------------------
# Pydantic Schema
# ---------------------------------------------------------------------------

class DailyCostReportResponse(BaseModel):
    """日报响应 Schema"""
    id: UUID
    tenant_id: UUID
    store_id: UUID
    report_date: date
    total_revenue_fen: int
    table_count: int
    customer_count: int
    food_cost_fen: int
    labor_cost_fen: int
    other_cost_fen: int
    total_cost_fen: int
    food_cost_rate: Optional[float] = None
    labor_cost_rate: Optional[float] = None
    gross_margin_rate: Optional[float] = None
    pos_data_source: Optional[str] = None
    data_status: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ManualAdjustRequest(BaseModel):
    """手工调整日报请求 Schema"""
    food_cost_fen: Optional[int] = Field(None, ge=0, description="食材成本（分）")
    labor_cost_fen: Optional[int] = Field(None, ge=0, description="人力成本（分）")
    other_cost_fen: Optional[int] = Field(None, ge=0, description="其他费用（分）")
    total_revenue_fen: Optional[int] = Field(None, ge=0, description="营收（分），可手工录入")
    notes: Optional[str] = Field(None, max_length=500, description="调整说明（必填建议）")


class CostAttributionItemResponse(BaseModel):
    """归集明细响应 Schema"""
    id: UUID
    tenant_id: UUID
    report_id: Optional[UUID] = None
    expense_application_id: Optional[UUID] = None
    store_id: UUID
    attribution_date: date
    cost_type: Optional[str] = None
    amount_fen: int
    description: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CostTrendItem(BaseModel):
    """成本趋势月度数据项"""
    month: str                              # YYYY-MM
    store_id: UUID
    total_revenue_fen: int
    total_cost_fen: int
    food_cost_fen: int
    labor_cost_fen: int
    other_cost_fen: int
    avg_food_cost_rate: Optional[float] = None
    avg_labor_cost_rate: Optional[float] = None
    avg_gross_margin_rate: Optional[float] = None
    report_days: int                        # 当月有数据的天数


class RunAttributionRequest(BaseModel):
    """手动触发成本归集请求 Schema"""
    store_id: UUID = Field(..., description="门店UUID")
    target_date: Optional[date] = Field(None, description="归集日期，默认当日")


# ---------------------------------------------------------------------------
# 端点1：GET /costs/daily-reports — 日报列表
# ---------------------------------------------------------------------------

@router.get(
    "/daily-reports",
    response_model=Dict[str, Any],
    summary="成本归集日报列表",
    description="查询日报列表，支持按门店和日期范围过滤。分页参数：page/size。",
)
async def list_daily_reports(
    store_id: Optional[UUID] = Query(None, description="门店UUID过滤"),
    start: Optional[date] = Query(None, description="开始日期（含）"),
    end: Optional[date] = Query(None, description="结束日期（含）"),
    data_status: Optional[str] = Query(None, description="数据状态过滤：pending/complete/manual_adjusted"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页条数"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        from ..models.cost_report import DailyCostReport

        conditions = [
            DailyCostReport.tenant_id == tenant_id,
            DailyCostReport.is_deleted.is_(False),
        ]
        if store_id:
            conditions.append(DailyCostReport.store_id == store_id)
        if start:
            conditions.append(DailyCostReport.report_date >= start)
        if end:
            conditions.append(DailyCostReport.report_date <= end)
        if data_status:
            conditions.append(DailyCostReport.data_status == data_status)

        # 总数
        count_stmt = select(func.count()).select_from(DailyCostReport).where(*conditions)
        total = (await db.execute(count_stmt)).scalar_one()

        # 分页查询
        offset = (page - 1) * size
        stmt = (
            select(DailyCostReport)
            .where(*conditions)
            .order_by(DailyCostReport.report_date.desc(), DailyCostReport.store_id)
            .offset(offset)
            .limit(size)
        )
        result = await db.execute(stmt)
        reports = result.scalars().all()

        return {
            "ok": True,
            "data": {
                "items": [_report_to_dict(r) for r in reports],
                "total": total,
                "page": page,
                "size": size,
            },
        }

    except SQLAlchemyError as exc:
        logger.error(
            "list_daily_reports_db_error",
            tenant_id=str(tenant_id),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="数据库查询失败")


# ---------------------------------------------------------------------------
# 端点2：GET /costs/daily-reports/{date}/{store_id} — 某日某店日报
# ---------------------------------------------------------------------------

@router.get(
    "/daily-reports/{report_date}/{store_id}",
    response_model=Dict[str, Any],
    summary="查询某日某门店成本日报",
)
async def get_daily_report(
    report_date: date,
    store_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        from ..models.cost_report import DailyCostReport

        stmt = select(DailyCostReport).where(
            DailyCostReport.tenant_id == tenant_id,
            DailyCostReport.store_id == store_id,
            DailyCostReport.report_date == report_date,
            DailyCostReport.is_deleted.is_(False),
        )
        result = await db.execute(stmt)
        report = result.scalar_one_or_none()

        if report is None:
            raise HTTPException(
                status_code=404,
                detail=f"未找到 {report_date} 门店 {store_id} 的成本日报",
            )

        return {"ok": True, "data": _report_to_dict(report)}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error(
            "get_daily_report_db_error",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            report_date=str(report_date),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="数据库查询失败")


# ---------------------------------------------------------------------------
# 端点3：POST /costs/daily-reports/{date}/{store_id}/adjust — 手工调整
# ---------------------------------------------------------------------------

@router.post(
    "/daily-reports/{report_date}/{store_id}/adjust",
    response_model=Dict[str, Any],
    summary="手工调整成本日报",
    description="人工核查后手工调整成本数据，状态自动更新为 manual_adjusted。",
)
async def adjust_daily_report(
    report_date: date,
    store_id: UUID,
    body: ManualAdjustRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        from ..models.cost_report import DailyCostReport
        from decimal import Decimal

        stmt = select(DailyCostReport).where(
            DailyCostReport.tenant_id == tenant_id,
            DailyCostReport.store_id == store_id,
            DailyCostReport.report_date == report_date,
            DailyCostReport.is_deleted.is_(False),
        )
        result = await db.execute(stmt)
        report = result.scalar_one_or_none()

        if report is None:
            raise HTTPException(
                status_code=404,
                detail=f"未找到 {report_date} 门店 {store_id} 的成本日报",
            )

        # 应用调整
        if body.food_cost_fen is not None:
            report.food_cost_fen = body.food_cost_fen
        if body.labor_cost_fen is not None:
            report.labor_cost_fen = body.labor_cost_fen
        if body.other_cost_fen is not None:
            report.other_cost_fen = body.other_cost_fen
        if body.total_revenue_fen is not None:
            report.total_revenue_fen = body.total_revenue_fen
        if body.notes is not None:
            report.notes = body.notes

        # 重新计算成本率
        report.total_cost_fen = report.food_cost_fen + report.labor_cost_fen + report.other_cost_fen
        report.compute_rates()
        report.data_status = "manual_adjusted"
        report.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(report)

        logger.info(
            "daily_report_manually_adjusted",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            report_date=str(report_date),
        )

        return {"ok": True, "data": _report_to_dict(report)}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "adjust_daily_report_db_error",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            report_date=str(report_date),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="调整失败，请重试")


# ---------------------------------------------------------------------------
# 端点4：GET /costs/attribution-items — 归集明细
# ---------------------------------------------------------------------------

@router.get(
    "/attribution-items",
    response_model=Dict[str, Any],
    summary="成本归集明细列表",
    description="查询成本归集明细，支持按门店、日期、成本类型过滤。",
)
async def list_attribution_items(
    store_id: Optional[UUID] = Query(None, description="门店UUID"),
    start: Optional[date] = Query(None, description="开始日期（含）"),
    end: Optional[date] = Query(None, description="结束日期（含）"),
    cost_type: Optional[str] = Query(None, description="成本类型：food/labor/rent/utility/other"),
    report_id: Optional[UUID] = Query(None, description="日报UUID过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        from ..models.cost_report import CostAttributionItem

        conditions = [CostAttributionItem.tenant_id == tenant_id]
        if store_id:
            conditions.append(CostAttributionItem.store_id == store_id)
        if start:
            conditions.append(CostAttributionItem.attribution_date >= start)
        if end:
            conditions.append(CostAttributionItem.attribution_date <= end)
        if cost_type:
            conditions.append(CostAttributionItem.cost_type == cost_type)
        if report_id:
            conditions.append(CostAttributionItem.report_id == report_id)

        count_stmt = select(func.count()).select_from(CostAttributionItem).where(*conditions)
        total = (await db.execute(count_stmt)).scalar_one()

        offset = (page - 1) * size
        stmt = (
            select(CostAttributionItem)
            .where(*conditions)
            .order_by(
                CostAttributionItem.attribution_date.desc(),
                CostAttributionItem.created_at.desc(),
            )
            .offset(offset)
            .limit(size)
        )
        result = await db.execute(stmt)
        items = result.scalars().all()

        return {
            "ok": True,
            "data": {
                "items": [_item_to_dict(i) for i in items],
                "total": total,
                "page": page,
                "size": size,
            },
        }

    except SQLAlchemyError as exc:
        logger.error(
            "list_attribution_items_db_error",
            tenant_id=str(tenant_id),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="数据库查询失败")


# ---------------------------------------------------------------------------
# 端点5：GET /costs/trends — 成本趋势（月度）
# ---------------------------------------------------------------------------

@router.get(
    "/trends",
    response_model=Dict[str, Any],
    summary="月度成本趋势",
    description="查询指定门店指定月份范围的月度成本趋势，用于可视化图表。",
)
async def get_cost_trends(
    store_id: Optional[UUID] = Query(None, description="门店UUID，不传则返回所有门店汇总"),
    months: int = Query(6, ge=1, le=24, description="查询最近N个月"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        from ..models.cost_report import DailyCostReport
        from sqlalchemy import cast, String, extract
        from sqlalchemy.sql.expression import label
        import sqlalchemy as sa

        # 按月聚合
        month_expr = sa.func.to_char(DailyCostReport.report_date, "YYYY-MM").label("month")
        conditions = [
            DailyCostReport.tenant_id == tenant_id,
            DailyCostReport.is_deleted.is_(False),
            DailyCostReport.data_status.in_(["complete", "manual_adjusted"]),
        ]
        if store_id:
            conditions.append(DailyCostReport.store_id == store_id)

        # 月份截止：今天所在月
        stmt = (
            select(
                month_expr,
                DailyCostReport.store_id,
                sa.func.sum(DailyCostReport.total_revenue_fen).label("total_revenue_fen"),
                sa.func.sum(DailyCostReport.total_cost_fen).label("total_cost_fen"),
                sa.func.sum(DailyCostReport.food_cost_fen).label("food_cost_fen"),
                sa.func.sum(DailyCostReport.labor_cost_fen).label("labor_cost_fen"),
                sa.func.sum(DailyCostReport.other_cost_fen).label("other_cost_fen"),
                sa.func.avg(DailyCostReport.food_cost_rate).label("avg_food_cost_rate"),
                sa.func.avg(DailyCostReport.labor_cost_rate).label("avg_labor_cost_rate"),
                sa.func.avg(DailyCostReport.gross_margin_rate).label("avg_gross_margin_rate"),
                sa.func.count().label("report_days"),
            )
            .where(*conditions)
            .group_by(month_expr, DailyCostReport.store_id)
            .order_by(month_expr.desc(), DailyCostReport.store_id)
            .limit(months * 50)  # 每月最多50家门店
        )

        result = await db.execute(stmt)
        rows = result.fetchall()

        trend_items = []
        for row in rows:
            trend_items.append({
                "month": row.month,
                "store_id": str(row.store_id),
                "total_revenue_fen": int(row.total_revenue_fen or 0),
                "total_cost_fen": int(row.total_cost_fen or 0),
                "food_cost_fen": int(row.food_cost_fen or 0),
                "labor_cost_fen": int(row.labor_cost_fen or 0),
                "other_cost_fen": int(row.other_cost_fen or 0),
                "avg_food_cost_rate": float(row.avg_food_cost_rate) if row.avg_food_cost_rate else None,
                "avg_labor_cost_rate": float(row.avg_labor_cost_rate) if row.avg_labor_cost_rate else None,
                "avg_gross_margin_rate": float(row.avg_gross_margin_rate) if row.avg_gross_margin_rate else None,
                "report_days": int(row.report_days),
            })

        return {"ok": True, "data": {"items": trend_items, "total": len(trend_items)}}

    except SQLAlchemyError as exc:
        logger.error(
            "get_cost_trends_db_error",
            tenant_id=str(tenant_id),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="趋势数据查询失败")


# ---------------------------------------------------------------------------
# 端点6：POST /costs/run-attribution — 手动触发归集（调试用）
# ---------------------------------------------------------------------------

@router.post(
    "/run-attribution",
    response_model=Dict[str, Any],
    summary="手动触发成本归集（调试/补录）",
    description=(
        "手动为指定门店指定日期触发成本归集。通常由 Worker 自动执行，此端点仅用于调试或"
        "补录缺漏数据。"
    ),
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_attribution_manually(
    body: RunAttributionRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        from ..workers.daily_cost_attribution import DailyCostAttributionWorker

        worker = DailyCostAttributionWorker()
        target_date = body.target_date or date.today()

        result = await worker.run_for_store(
            db=db,
            tenant_id=tenant_id,
            store_id=body.store_id,
            target_date=target_date,
        )

        logger.info(
            "manual_attribution_triggered",
            tenant_id=str(tenant_id),
            store_id=str(body.store_id),
            target_date=target_date.isoformat(),
            result=result,
        )

        return {"ok": True, "data": result}

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "run_attribution_manually_db_error",
            tenant_id=str(tenant_id),
            store_id=str(body.store_id),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="归集执行失败，请查看日志")
    except Exception as exc:  # noqa: BLE001 — 最外层兜底
        await db.rollback()
        logger.error(
            "run_attribution_manually_unexpected_error",
            tenant_id=str(tenant_id),
            store_id=str(body.store_id),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"归集执行失败：{exc}")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _report_to_dict(report: Any) -> Dict[str, Any]:
    """将 DailyCostReport ORM 对象转为可序列化 dict。"""
    return {
        "id": str(report.id),
        "tenant_id": str(report.tenant_id),
        "store_id": str(report.store_id),
        "report_date": report.report_date.isoformat() if report.report_date else None,
        "total_revenue_fen": report.total_revenue_fen,
        "table_count": report.table_count,
        "customer_count": report.customer_count,
        "food_cost_fen": report.food_cost_fen,
        "labor_cost_fen": report.labor_cost_fen,
        "other_cost_fen": report.other_cost_fen,
        "total_cost_fen": report.total_cost_fen,
        "food_cost_rate": float(report.food_cost_rate) if report.food_cost_rate is not None else None,
        "labor_cost_rate": float(report.labor_cost_rate) if report.labor_cost_rate is not None else None,
        "gross_margin_rate": float(report.gross_margin_rate) if report.gross_margin_rate is not None else None,
        "pos_data_source": report.pos_data_source,
        "data_status": report.data_status,
        "notes": report.notes,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
    }


def _item_to_dict(item: Any) -> Dict[str, Any]:
    """将 CostAttributionItem ORM 对象转为可序列化 dict。"""
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "report_id": str(item.report_id) if item.report_id else None,
        "expense_application_id": str(item.expense_application_id) if item.expense_application_id else None,
        "store_id": str(item.store_id),
        "attribution_date": item.attribution_date.isoformat() if item.attribution_date else None,
        "cost_type": item.cost_type,
        "amount_fen": item.amount_fen,
        "description": item.description,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
