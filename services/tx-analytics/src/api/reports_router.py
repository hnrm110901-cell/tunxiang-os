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
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..reports.p0_reports import P0Reports
from ..reports.target_achievement import target_achievement_report
from ..services.report_engine import ReportEngine
from ..services.report_registry import create_default_registry

log = structlog.get_logger()
router = APIRouter(tags=["p0-reports"])
_p0 = P0Reports()
_registry = create_default_registry()
_engine = ReportEngine(registry=_registry)


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


# ──────────────────────────────────────────────
# 9. 最低消费补齐报表
# ──────────────────────────────────────────────

@router.get("/api/v1/analytics/reports/min-spend-supplement")
async def api_min_spend_supplement(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """最低消费补齐报表（P0）

    - 统计设有最低消费的桌台订单，计算实际消费与最低消费差额
    - 字段：门店/桌台/最低消费/实际消费/补齐金额/日期
    """
    tenant_id = _require_tenant(x_tenant_id)
    start = _parse_date(date_from)
    end = _parse_date(date_to)

    try:
        result = await _engine.execute_report(
            report_id="min_spend_supplement",
            params={"store_id": store_id, "start_date": str(start), "end_date": str(end)},
            tenant_id=tenant_id,
            db=None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Report min_spend_supplement not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": {"items": result.rows, "summary": result.summary}}


# ──────────────────────────────────────────────
# 10. 开钱箱统计
# ──────────────────────────────────────────────

@router.get("/api/v1/analytics/reports/cash-drawer-log")
async def api_cash_drawer_log(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """开钱箱统计（P0）

    - 按门店按收银员统计每日开钱箱次数及时段分布
    - 字段：门店/收银员/开箱次数/首次/末次/时段分布
    """
    tenant_id = _require_tenant(x_tenant_id)
    start = _parse_date(date_from)
    end = _parse_date(date_to)

    try:
        result = await _engine.execute_report(
            report_id="cash_drawer_log",
            params={"store_id": store_id, "start_date": str(start), "end_date": str(end)},
            tenant_id=tenant_id,
            db=None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Report cash_drawer_log not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": {"items": result.rows, "summary": result.summary}}


# ──────────────────────────────────────────────
# 11. 预定明细统计
# ──────────────────────────────────────────────

@router.get("/api/v1/analytics/reports/reservation-detail")
async def api_reservation_detail(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """预定明细统计（P0）

    - 按门店按日期统计预定量，按状态和时段分布
    - 字段：门店/日期/总量/已确认/已入座/已取消/未到店/到店率/时段分布
    """
    tenant_id = _require_tenant(x_tenant_id)
    start = _parse_date(date_from)
    end = _parse_date(date_to)

    try:
        result = await _engine.execute_report(
            report_id="reservation_detail",
            params={"store_id": store_id, "start_date": str(start), "end_date": str(end)},
            tenant_id=tenant_id,
            db=None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Report reservation_detail not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": {"items": result.rows, "summary": result.summary}}


# ──────────────────────────────────────────────
# 12. 外卖单统计
# ──────────────────────────────────────────────

@router.get("/api/v1/analytics/reports/delivery-stats")
async def api_delivery_order_stats(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """外卖单统计（P0）

    - 按门店按外卖平台统计订单量、营收、佣金、净收入
    - 字段：门店/平台/订单数/完成数/取消数/退款数/营收/佣金/配送费/净收入/客单价/佣金率
    """
    tenant_id = _require_tenant(x_tenant_id)
    start = _parse_date(date_from)
    end = _parse_date(date_to)

    try:
        result = await _engine.execute_report(
            report_id="delivery_order_stats",
            params={"store_id": store_id, "start_date": str(start), "end_date": str(end)},
            tenant_id=tenant_id,
            db=None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Report delivery_order_stats not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": {"items": result.rows, "summary": result.summary}}


# ──────────────────────────────────────────────
# 13. 平台外卖对账表
# ──────────────────────────────────────────────

@router.get("/api/v1/analytics/reports/delivery-reconciliation")
async def api_delivery_reconciliation(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """平台外卖对账表（P0）

    - 对比系统内外卖订单金额与平台结算金额，识别差异单据
    - 字段：门店/日期/平台/平台单号/系统金额/平台金额/差额/对账状态
    """
    tenant_id = _require_tenant(x_tenant_id)
    start = _parse_date(date_from)
    end = _parse_date(date_to)

    try:
        result = await _engine.execute_report(
            report_id="delivery_reconciliation",
            params={"store_id": store_id, "start_date": str(start), "end_date": str(end)},
            tenant_id=tenant_id,
            db=None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Report delivery_reconciliation not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": {"items": result.rows, "summary": result.summary}}


# ──────────────────────────────────────────────
# 14. 挂账统计
# ──────────────────────────────────────────────

@router.get("/api/v1/analytics/reports/credit-account-stats")
async def api_credit_account_stats(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """挂账统计（P0）

    - 按门店统计企业挂账客户的信用额度使用情况
    - 字段：门店/客户名/公司/额度/已用/余额/使用率/期间消费/期间还款/最后交易时间
    """
    tenant_id = _require_tenant(x_tenant_id)
    start = _parse_date(date_from)
    end = _parse_date(date_to)

    try:
        result = await _engine.execute_report(
            report_id="credit_account_stats",
            params={"store_id": store_id, "start_date": str(start), "end_date": str(end)},
            tenant_id=tenant_id,
            db=None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Report credit_account_stats not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": {"items": result.rows, "summary": result.summary}}


# ──────────────────────────────────────────────
# 15. 会员消费分析
# ──────────────────────────────────────────────

@router.get("/api/v1/analytics/reports/member-consumption")
async def api_member_consumption(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """会员消费分析（P0）

    - 按会员维度汇总消费频次、总消费额、客单价、最近到店日期
    - 字段：门店/会员ID/会员号/姓名/手机/等级/到店次数/总消费/客均/折扣总额/首次/末次/消费频率
    """
    tenant_id = _require_tenant(x_tenant_id)
    start = _parse_date(date_from)
    end = _parse_date(date_to)

    try:
        result = await _engine.execute_report(
            report_id="member_consumption",
            params={"store_id": store_id, "start_date": str(start), "end_date": str(end)},
            tenant_id=tenant_id,
            db=None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Report member_consumption not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": {"items": result.rows, "summary": result.summary}}


# ──────────────────────────────────────────────
# 16. 团购券消费分析
# ──────────────────────────────────────────────

@router.get("/api/v1/analytics/reports/coupon-consumption")
async def api_coupon_consumption(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """团购券消费分析（P0）

    - 按团购券类型和来源平台统计核销量、面值总额、实际成本、盈亏
    - 字段：门店/日期/券类型/平台/核销量/面值总额/实际成本/结算额/盈亏/核销率/均面值/均结算价
    """
    tenant_id = _require_tenant(x_tenant_id)
    start = _parse_date(date_from)
    end = _parse_date(date_to)

    try:
        result = await _engine.execute_report(
            report_id="coupon_consumption",
            params={"store_id": store_id, "start_date": str(start), "end_date": str(end)},
            tenant_id=tenant_id,
            db=None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Report coupon_consumption not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": {"items": result.rows, "summary": result.summary}}


# ──────────────────────────────────────────────
# DB 依赖（目标达成报表需要真实 session）
# ──────────────────────────────────────────────

async def _get_tenant_session(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ──────────────────────────────────────────────
# 18. 门店经营目标达成
# ──────────────────────────────────────────────

@router.get("/api/v1/analytics/reports/target-achievement")
async def api_target_achievement(
    store_id: str = Query(..., description="门店ID（必填）"),
    date: Optional[str] = Query(None, description="基准日期 YYYY-MM-DD，默认今日"),
    period: str = Query("month", description="汇总粒度 day|week|month（默认 month）"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_session),
):
    """门店经营目标达成报表

    比对门店经营目标（7 个 target 字段）与实际经营数据。
    返回 6 项 KPI 的目标值、实际值、达成率、趋势，以及综合达成率。

    KPI 列表：
      1. 营收目标 — 完成订单金额 vs monthly_revenue_target_fen
      2. 日客流目标 — 日均订单数 vs daily_customer_target
      3. 成本率 — 采购成本/营收 vs cost_ratio_target
      4. 人工成本率 — 人工成本/营收 vs labor_cost_ratio_target
      5. 翻台率 — 订单数/桌数/天数 vs turnover_rate_target
      6. 损耗率 — 报废金额/采购金额 vs waste_rate_target
    """
    tenant_id = _require_tenant(x_tenant_id)
    base_date = _parse_date(date)

    if period not in ("day", "week", "month"):
        raise HTTPException(status_code=422, detail="period must be day, week, or month")

    try:
        result = await target_achievement_report(
            store_id=store_id,
            period=period,
            tenant_id=tenant_id,
            db=db,
            base_date=base_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"ok": True, "data": result}
