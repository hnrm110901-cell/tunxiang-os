"""
费控汇总报表 & 集团去重 API 路由

8 个端点：
  GET  /monthly             月度汇总报表
  GET  /trend               费用趋势
  GET  /top-spenders        TOP 消费员工
  GET  /abnormal            异常费用检测
  GET  /export              导出报表
  GET  /dedup/suspicious    可疑重复发票列表
  GET  /dedup/stats         去重统计
  POST /dedup/{group_id}/resolve  标记去重处理

统一响应格式：{"ok": bool, "data": {}, "error": {}}
所有接口通过 X-Tenant-ID / X-User-ID header 鉴权（与其他路由一致）。
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from src.api.expense_routes import get_current_user, get_tenant_id
from src.services.expense_report_service import expense_report_service
from src.services.invoice_dedup_service import invoice_dedup_service

router = APIRouter()
log = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schema
# ─────────────────────────────────────────────────────────────────────────────


class ResolveRequest(BaseModel):
    """标记去重处理请求体"""

    note: str = Field(..., min_length=1, max_length=500, description="处理备注（确认合规原因或驳回理由）")


# ─────────────────────────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────────────────────────


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _current_year_month() -> tuple[int, int]:
    """返回当前年月（用于默认参数）。"""
    from datetime import date

    today = date.today()
    return today.year, today.month


# ─────────────────────────────────────────────────────────────────────────────
# 月度汇总报表
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/monthly",
    summary="月度费控汇总报表",
    description="三维度报表：按门店/按科目/按申请人，含与上月环比。",
)
async def get_monthly_report(
    year: Optional[int] = Query(None, ge=2020, le=2030, description="年份，默认当年"),
    month: Optional[int] = Query(None, ge=1, le=12, description="月份，默认当月"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    _year, _month = _current_year_month()
    year = year or _year
    month = month or _month

    try:
        report = await expense_report_service.generate_monthly_report(
            db=db,
            tenant_id=tenant_id,
            year=year,
            month=month,
        )
    except Exception as exc:
        log.error(
            "report_monthly_api_error",
            error=str(exc),
            tenant_id=str(tenant_id),
            year=year,
            month=month,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"生成月度报表失败：{exc}",
        )

    return _ok(report)


# ─────────────────────────────────────────────────────────────────────────────
# 费用趋势
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/trend",
    summary="费用趋势分析",
    description="最近 N 个月费用趋势，含月均/环比。",
)
async def get_expense_trend(
    months: int = Query(6, ge=1, le=24, description="统计月数，默认6个月"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        trend = await expense_report_service.generate_expense_trend(
            db=db,
            tenant_id=tenant_id,
            months=months,
        )
    except Exception as exc:
        log.error(
            "report_trend_api_error",
            error=str(exc),
            tenant_id=str(tenant_id),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"生成趋势报表失败：{exc}",
        )

    return _ok(trend)


# ─────────────────────────────────────────────────────────────────────────────
# TOP 消费员工
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/top-spenders",
    summary="TOP 消费员工排行",
    description="当月按审批通过金额降序排列 TOP N 员工。",
)
async def get_top_spenders(
    year: Optional[int] = Query(None, ge=2020, le=2030, description="年份，默认当年"),
    month: Optional[int] = Query(None, ge=1, le=12, description="月份，默认当月"),
    limit: int = Query(10, ge=1, le=50, description="返回条数，默认10，最多50"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    _year, _month = _current_year_month()
    year = year or _year
    month = month or _month

    try:
        spenders = await expense_report_service.get_top_spenders(
            db=db,
            tenant_id=tenant_id,
            year=year,
            month=month,
            limit=limit,
        )
    except Exception as exc:
        log.error(
            "report_top_spenders_api_error",
            error=str(exc),
            tenant_id=str(tenant_id),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取 TOP 消费员工失败：{exc}",
        )

    return _ok({"year": year, "month": month, "limit": limit, "items": spenders})


# ─────────────────────────────────────────────────────────────────────────────
# 异常费用检测
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/abnormal",
    summary="异常费用检测",
    description=(
        "三条规则检测异常费用：\n"
        "1. 单笔超过本人上季度平均的3倍\n"
        "2. 同一天同一科目多次报销\n"
        "3. 节假日/周末大额报销（>2000元）"
    ),
)
async def get_abnormal_expenses(
    year: Optional[int] = Query(None, ge=2020, le=2030, description="年份，默认当年"),
    month: Optional[int] = Query(None, ge=1, le=12, description="月份，默认当月"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    _year, _month = _current_year_month()
    year = year or _year
    month = month or _month

    try:
        anomalies = await expense_report_service.get_abnormal_expenses(
            db=db,
            tenant_id=tenant_id,
            year=year,
            month=month,
        )
    except Exception as exc:
        log.error(
            "report_abnormal_api_error",
            error=str(exc),
            tenant_id=str(tenant_id),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"异常费用检测失败：{exc}",
        )

    return _ok(
        {
            "year": year,
            "month": month,
            "total": len(anomalies),
            "items": anomalies,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# 导出报表
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/export",
    summary="导出报表数据",
    description="导出指定维度的报表数据（JSON 格式，可用于前端生成 Excel/CSV）。dimension: store/category/person/all",
)
async def export_report(
    year: Optional[int] = Query(None, ge=2020, le=2030, description="年份，默认当年"),
    month: Optional[int] = Query(None, ge=1, le=12, description="月份，默认当月"),
    dimension: str = Query("all", description="导出维度：store/category/person/all"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    _year, _month = _current_year_month()
    year = year or _year
    month = month or _month

    valid_dimensions = {"store", "category", "person", "all"}
    if dimension not in valid_dimensions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"dimension 参数无效，必须是 {valid_dimensions} 之一",
        )

    try:
        export_data = await expense_report_service.export_to_dict(
            db=db,
            tenant_id=tenant_id,
            year=year,
            month=month,
            dimension=dimension,
        )
    except Exception as exc:
        log.error(
            "report_export_api_error",
            error=str(exc),
            tenant_id=str(tenant_id),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导出报表失败：{exc}",
        )

    return _ok(export_data)


# ─────────────────────────────────────────────────────────────────────────────
# 集团去重 — 可疑发票列表
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/dedup/suspicious",
    summary="可疑跨品牌重复发票列表",
    description="查询本租户涉及的可疑跨品牌重复发票（分页，按上报时间倒序）。",
)
async def get_suspicious_invoices(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await invoice_dedup_service.get_suspicious_invoices(
            db=db,
            tenant_id=tenant_id,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:
        log.error(
            "dedup_suspicious_api_error",
            error=str(exc),
            tenant_id=str(tenant_id),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取可疑发票列表失败：{exc}",
        )

    return _ok(result)


# ─────────────────────────────────────────────────────────────────────────────
# 集团去重 — 统计
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/dedup/stats",
    summary="发票集团去重统计",
    description="统计本租户发票去重检查情况：总检测数/重复数/跨品牌重复数/已处理/待处理。",
)
async def get_dedup_stats(
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        stats = await invoice_dedup_service.get_dedup_stats(
            db=db,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        log.error(
            "dedup_stats_api_error",
            error=str(exc),
            tenant_id=str(tenant_id),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取去重统计失败：{exc}",
        )

    return _ok(stats)


# ─────────────────────────────────────────────────────────────────────────────
# 集团去重 — 标记处理
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/dedup/{group_id}/resolve",
    summary="标记去重记录已处理",
    description=(
        "人工确认该去重组为合规（如：同一票据合法用于两个品牌核销）或标记为违规驳回。\n"
        "操作不可逆，请在 note 中详细说明处理原因。"
    ),
    status_code=status.HTTP_200_OK,
)
async def resolve_dedup(
    group_id: str,
    body: ResolveRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await invoice_dedup_service.mark_resolved(
            db=db,
            group_id=group_id,
            resolved_by=current_user_id,
            note=body.note,
        )
        await db.commit()
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        log.error(
            "dedup_resolve_api_error",
            error=str(exc),
            group_id=group_id,
            tenant_id=str(tenant_id),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"标记处理失败：{exc}",
        )

    log.info(
        "dedup_resolved",
        group_id=group_id,
        tenant_id=str(tenant_id),
        resolved_by=str(current_user_id),
    )

    return _ok(
        {
            "group_id": group_id,
            "resolved_by": str(current_user_id),
            "message": "去重记录已标记为已处理",
        }
    )
