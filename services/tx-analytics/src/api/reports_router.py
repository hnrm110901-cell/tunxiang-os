"""P0 报表 API 路由 — 每日必看的 8 张核心报表

GET /api/v1/analytics/reports/daily-revenue      营业收入汇总
GET /api/v1/analytics/reports/payment-discount   付款折扣表
GET /api/v1/analytics/reports/cashflow-by-store  收款分门店
GET /api/v1/analytics/reports/dish-sales         菜品销售统计
GET /api/v1/analytics/reports/billing-audit      账单稽核
GET /api/v1/analytics/reports/realtime           实时营业统计
GET /api/v1/analytics/reports/daily-cashflow     日现金流
GET /api/v1/analytics/daily-summary              日汇总（供经营诊断 Agent 调用）

公共参数：
  ?store_id=<UUID>          门店ID（部分接口必填）
  ?date=YYYY-MM-DD          业务日期（默认今日）
  ?period=day|week|month    汇总粒度（部分接口适用）

响应格式：{ok: bool, data: {}}
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query

from ..reports.p0_reports import P0Reports

log = structlog.get_logger()
router = APIRouter(tags=["p0-reports"])
_p0 = P0Reports()


# ──────────────────────────────────────────────
# 公共辅助
# ──────────────────────────────────────────────


def _require_tenant(tenant_id: Optional[str]) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return tenant_id


def _parse_date(date_str: Optional[str]) -> date:
    """解析日期参数，缺省为今日"""
    if not date_str:
        return date.today()
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format '{date_str}', expected YYYY-MM-DD",
        )


def _period_to_date_range(period: str, base: date) -> tuple[date, date]:
    """将 period 参数转换为 (start_date, end_date)"""
    if period == "week":
        return base - timedelta(days=6), base
    if period == "month":
        return base.replace(day=1), base
    return base, base  # day


def _require_store(store_id: Optional[str]) -> str:
    if not store_id:
        raise HTTPException(status_code=400, detail="store_id query parameter is required")
    return store_id


# ──────────────────────────────────────────────
# 1. 营业收入汇总
# ──────────────────────────────────────────────


@router.get("/api/v1/analytics/reports/daily-revenue")
async def api_daily_revenue(
    date: Optional[str] = Query(None, description="业务日期 YYYY-MM-DD，默认今日"),
    store_id: Optional[str] = Query(None, description="门店ID，不传则汇总全部门店"),
    period: str = Query("day", description="汇总粒度 day|week|month（week/month 取起始日至 date）"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """营业收入汇总表（P0）

    - 多门店汇总 / 单店明细两种模式
    - 字段：门店/营业额/桌次/人均/同比昨天/同比上周同日
    """
    tenant_id = _require_tenant(x_tenant_id)
    target_date = _parse_date(date)
    store_ids = [store_id] if store_id else None

    try:
        result = await _p0.daily_revenue_summary(
            tenant_id=tenant_id,
            store_ids=store_ids,
            target_date=target_date,
            db=None,  # 实际部署通过 Depends(get_db) 注入
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": result.model_dump(mode="json")}


# ──────────────────────────────────────────────
# 2. 付款折扣表
# ──────────────────────────────────────────────


@router.get("/api/v1/analytics/reports/payment-discount")
async def api_payment_discount(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date: Optional[str] = Query(None, description="业务日期 YYYY-MM-DD，默认今日"),
    period: str = Query("day", description="汇总粒度 day|week|month"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """门店付款折扣表（P0）

    - 各折扣类型：会员折扣/员工折扣/活动折扣/手动折扣
    - 字段：折扣类型/使用次数/折扣金额/占比
    """
    tenant_id = _require_tenant(x_tenant_id)
    sid = _require_store(store_id)
    target_date = _parse_date(date)

    try:
        result = await _p0.payment_discount_report(
            tenant_id=tenant_id,
            store_id=sid,
            target_date=target_date,
            db=None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": result.model_dump(mode="json")}


# ──────────────────────────────────────────────
# 3. 收款分门店
# ──────────────────────────────────────────────


@router.get("/api/v1/analytics/reports/cashflow-by-store")
async def api_cashflow_by_store(
    date: Optional[str] = Query(None, description="业务日期 YYYY-MM-DD，默认今日"),
    store_id: Optional[str] = Query(None, description="门店ID，不传则汇总全部门店"),
    period: str = Query("day", description="汇总粒度 day|week|month"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """门店日现金流报表（P0）

    - 按支付方式分类（现金/微信/支付宝/刷卡/挂账）
    - 字段：门店/支付方式/收款金额/退款金额/净收款
    """
    tenant_id = _require_tenant(x_tenant_id)
    target_date = _parse_date(date)

    try:
        result = await _p0.cashflow_by_store(
            tenant_id=tenant_id,
            target_date=target_date,
            db=None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": result.model_dump(mode="json")}


# ──────────────────────────────────────────────
# 4. 菜品销售统计
# ──────────────────────────────────────────────


@router.get("/api/v1/analytics/reports/dish-sales")
async def api_dish_sales(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date: Optional[str] = Query(None, description="业务日期 YYYY-MM-DD，默认今日"),
    period: str = Query("day", description="汇总粒度 day|week|month"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """菜品销售统计表（P0）

    - 字段：菜品名/分类/售价/销量/销售额/占比/同比
    - 排序：按销售额降序
    """
    tenant_id = _require_tenant(x_tenant_id)
    sid = _require_store(store_id)
    target_date = _parse_date(date)

    try:
        result = await _p0.dish_sales_stats(
            tenant_id=tenant_id,
            store_id=sid,
            target_date=target_date,
            db=None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": result.model_dump(mode="json")}


# ──────────────────────────────────────────────
# 5. 账单稽核
# ──────────────────────────────────────────────


@router.get("/api/v1/analytics/reports/billing-audit")
async def api_billing_audit(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date: Optional[str] = Query(None, description="业务日期 YYYY-MM-DD，默认今日"),
    period: str = Query("day", description="汇总粒度 day|week|month"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """账单稽核表（P0）

    - 异常订单检测：退单/折扣异常/时间异常/金额异常
    - 字段：订单号/桌号/金额/异常类型/操作员/时间
    """
    tenant_id = _require_tenant(x_tenant_id)
    sid = _require_store(store_id)
    target_date = _parse_date(date)

    try:
        result = await _p0.billing_audit(
            tenant_id=tenant_id,
            store_id=sid,
            target_date=target_date,
            db=None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": result.model_dump(mode="json")}


# ──────────────────────────────────────────────
# 6. 实时营业统计
# ──────────────────────────────────────────────


@router.get("/api/v1/analytics/reports/realtime")
async def api_realtime_stats(
    store_id: Optional[str] = Query(None, description="门店ID"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """门店实时营业统计（P0，今日截至当前）

    - 实时营业额/桌次/在台桌数/等位人数/今日人均
    - 无 date/period 参数，始终返回今日实时数据
    """
    tenant_id = _require_tenant(x_tenant_id)
    sid = _require_store(store_id)

    try:
        result = await _p0.realtime_store_stats(
            tenant_id=tenant_id,
            store_id=sid,
            db=None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": result.model_dump(mode="json")}


# ──────────────────────────────────────────────
# 7. 日现金流
# ──────────────────────────────────────────────


@router.get("/api/v1/analytics/reports/daily-cashflow")
async def api_daily_cashflow(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date: Optional[str] = Query(None, description="业务日期 YYYY-MM-DD，默认今日"),
    period: str = Query("day", description="汇总粒度 day|week|month"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """门店日现金流报表（P0）— 含找零/备用金

    - 按支付方式分类，含现金找零和备用金明细
    - 字段：支付方式/收款/退款/净收款/备用金/找零
    """
    tenant_id = _require_tenant(x_tenant_id)
    sid = _require_store(store_id)
    target_date = _parse_date(date)

    try:
        result = await _p0.cashflow_daily(
            tenant_id=tenant_id,
            store_id=sid,
            target_date=target_date,
            db=None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": result.model_dump(mode="json")}


# ──────────────────────────────────────────────
# 8. 日汇总（供经营诊断 Agent 调用）
# ──────────────────────────────────────────────


@router.get("/api/v1/analytics/daily-summary")
async def api_daily_summary(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date: Optional[str] = Query(None, description="业务日期 YYYY-MM-DD，默认今日"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """日汇总（P0 — 供经营诊断 Agent 调用）

    聚合当日核心指标：营收/折扣/实时上座/稽核异常/TOP10菜品。
    返回结构化 dict，便于 Agent prompt 直接消费。
    """
    tenant_id = _require_tenant(x_tenant_id)
    sid = _require_store(store_id)
    target_date = _parse_date(date)

    try:
        result = await _p0.daily_summary_for_agent(
            tenant_id=tenant_id,
            store_id=sid,
            target_date=target_date,
            db=None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": result}
