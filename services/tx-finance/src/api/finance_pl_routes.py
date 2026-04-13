"""P&L 损益表 API 路由（v2 完整实现）

端点：
  GET  /api/v1/finance/pl/store?store_id=&start_date=&end_date=
       → 门店 P&L 损益表（完整格式）

  GET  /api/v1/finance/pl/brand?brand_id=&month=
       → 品牌级 P&L（多门店汇总）

  GET  /api/v1/finance/pl/monthly?store_id=&month=
       → 月度门店 P&L（YYYY-MM 快捷端点，无需手算首尾日期）

  GET  /api/v1/finance/pl/monthly-trend?store_id=&months=12
       → 月度 P&L 趋势序列（最近 N 个月逐月汇总，前端折线图数据源）

  GET  /api/v1/finance/pl/mom?store_id=&month=
       → 月度环比分析（当月 vs 上月 vs 同期去年）
"""
import calendar
import uuid
from datetime import date

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from services.tx_finance.src.services.pl_service import PLService
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["finance-pl"])

_pl_svc = PLService()


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


def _validate_month(month: str) -> str:
    """验证 YYYY-MM 格式"""
    if len(month) != 7 or month[4] != "-":
        raise HTTPException(
            status_code=400, detail=f"month 格式错误: {month}，请使用 YYYY-MM"
        )
    try:
        int(month[:4])
        int(month[5:7])
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"month 格式错误: {month}"
        ) from exc
    return month


# ─── GET /pl/store ────────────────────────────────────────────────────────────

@router.get("/pl/store", summary="门店 P&L 损益表")
async def get_store_pl(
    store_id: str = Query(..., description="门店ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """门店 P&L 损益表（完整格式）

    损益表结构：
    营业收入
      - 堂食收入
      - 外卖收入
      - 储值卡充值（收现）
      - 其他收入
    = 总营收

    营业成本
      - 食材成本（BOM计算，无数据时用30%估算）
      - 食材损耗
    = 食材总成本

    毛利 = 总营收 - 食材总成本
    毛利率

    经营费用
      - 人工成本（来自薪资表）
      - 房租（门店月配置 × 天数摊销）
      - 水电（门店月配置 × 天数摊销）
      - 其他固定费用

    经营利润 = 毛利 - 经营费用
    经营利润率
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    start = _parse_date_param(start_date)
    end = _parse_date_param(end_date)

    if start > end:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    max_days = 366
    if (end - start).days > max_days:
        raise HTTPException(
            status_code=400, detail=f"查询区间不能超过 {max_days} 天"
        )

    try:
        pl = await _pl_svc.get_store_pl(sid, start, end, tid, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": pl.to_dict()}


# ─── GET /pl/brand ────────────────────────────────────────────────────────────

@router.get("/pl/brand", summary="品牌级 P&L（多门店汇总）")
async def get_brand_pl(
    brand_id: str = Query(..., description="品牌ID"),
    month: str = Query(..., description="月份 YYYY-MM"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """品牌级 P&L 损益表

    汇总品牌下所有激活门店的月度 P&L，按毛利率降序排列门店。
    适用场景：
    - 品牌运营总览
    - 门店间横向对标
    - 发现高成本门店

    返回：
    - summary: 品牌级汇总指标
    - cost_health: 整体成本健康度
    - store_details: 各门店明细（按毛利率降序）
    """
    _validate_month(month)
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    try:
        brand_pl = await _pl_svc.get_brand_pl(brand_id, month, tid, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": brand_pl.to_dict()}


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _month_to_date_range(month: str) -> tuple[date, date]:
    """YYYY-MM → (首日, 末日)"""
    _validate_month(month)
    year, mon = int(month[:4]), int(month[5:7])
    start = date(year, mon, 1)
    end = date(year, mon, calendar.monthrange(year, mon)[1])
    return start, end


def _prev_month(month: str) -> str:
    """YYYY-MM → 上月 YYYY-MM"""
    year, mon = int(month[:4]), int(month[5:7])
    if mon == 1:
        return f"{year - 1}-12"
    return f"{year}-{mon - 1:02d}"


def _same_month_last_year(month: str) -> str:
    """YYYY-MM → 去年同月 YYYY-MM"""
    year, mon = int(month[:4]), int(month[5:7])
    return f"{year - 1}-{mon:02d}"


def _pl_summary(pl_dict: dict) -> dict:
    """从完整 P&L 响应中提取月度对比所需核心指标"""
    return {
        "total_revenue_fen": pl_dict["revenue"]["total_fen"],
        "gross_profit_fen": pl_dict["gross_profit_fen"],
        "gross_margin_rate_pct": pl_dict["gross_margin_rate_pct"],
        "food_cost_rate_pct": pl_dict["food_cost_rate_pct"],
        "operating_profit_fen": pl_dict["operating_profit_fen"],
        "operating_margin_rate_pct": pl_dict["operating_margin_rate_pct"],
        "opex_total_fen": pl_dict["opex"]["total_fen"],
        "is_estimated": pl_dict["cost"]["is_estimated"],
    }


def _pct_change(current: int | float, previous: int | float) -> float | None:
    if not previous:
        return None
    return round((current - previous) / abs(previous) * 100, 1)


# ─── GET /pl/monthly ──────────────────────────────────────────────────────────

@router.get("/pl/monthly", summary="月度门店 P&L（便捷端点）")
async def get_monthly_store_pl(
    store_id: str = Query(..., description="门店ID"),
    month: str = Query(..., description="月份 YYYY-MM"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """门店月度 P&L 损益表（YYYY-MM 快捷端点）

    等价于 /pl/store?start_date=YYYY-MM-01&end_date=YYYY-MM-31，
    无需调用方手算首尾日期。
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    start, end = _month_to_date_range(month)

    try:
        pl = await _pl_svc.get_store_pl(sid, start, end, tid, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    data = pl.to_dict()
    data["month"] = month
    return {"ok": True, "data": data}


# ─── GET /pl/monthly-trend ────────────────────────────────────────────────────

@router.get("/pl/monthly-trend", summary="月度 P&L 趋势序列")
async def get_monthly_pl_trend(
    store_id: str = Query(..., description="门店ID"),
    months: int = Query(12, ge=1, le=24, description="返回月数（默认12个月）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """门店月度 P&L 趋势序列

    返回最近 N 个月逐月 P&L 核心指标，按月份升序，供折线图使用。
    字段：month / total_revenue_fen / gross_profit_fen / gross_margin_rate_pct /
          operating_profit_fen / operating_margin_rate_pct / is_estimated
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    today = date.today()
    # 从当月往前推 months 个月
    results = []
    year, mon = today.year, today.month
    for _ in range(months):
        m_str = f"{year}-{mon:02d}"
        start, end = _month_to_date_range(m_str)
        try:
            pl = await _pl_svc.get_store_pl(sid, start, end, tid, db)
            entry = _pl_summary(pl.to_dict())
            entry["month"] = m_str
            results.append(entry)
        except ValueError:
            results.append({"month": m_str, "error": "query_failed"})

        # 上一个月
        if mon == 1:
            year -= 1
            mon = 12
        else:
            mon -= 1

    results.reverse()  # 升序返回
    return {"ok": True, "data": results, "meta": {"store_id": store_id, "months": months}}


# ─── GET /pl/mom ──────────────────────────────────────────────────────────────

@router.get("/pl/mom", summary="月度环比分析（当月 vs 上月 vs 去年同月）")
async def get_pl_mom(
    store_id: str = Query(..., description="门店ID"),
    month: str = Query(..., description="目标月份 YYYY-MM"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """门店月度环比分析

    返回目标月份、上月、去年同月的 P&L 核心指标及变化率（%）。
    变化率字段：prev_mom_pct（环比）/ prev_yoy_pct（同比）
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _validate_month(month)

    prev_m = _prev_month(month)
    yoy_m = _same_month_last_year(month)

    async def _fetch(m: str) -> dict | None:
        s, e = _month_to_date_range(m)
        try:
            pl = await _pl_svc.get_store_pl(sid, s, e, tid, db)
            d = _pl_summary(pl.to_dict())
            d["month"] = m
            return d
        except ValueError:
            return None

    current, prev, yoy = (
        await _fetch(month),
        await _fetch(prev_m),
        await _fetch(yoy_m),
    )

    def _diff(curr: dict | None, base: dict | None, key: str) -> float | None:
        if curr is None or base is None:
            return None
        return _pct_change(curr[key], base[key])

    return {
        "ok": True,
        "data": {
            "month": month,
            "current": current,
            "prev_month": prev,
            "yoy_month": yoy,
            "mom_changes": {
                "revenue_pct": _diff(current, prev, "total_revenue_fen"),
                "gross_profit_pct": _diff(current, prev, "gross_profit_fen"),
                "gross_margin_rate_pct_delta": (
                    round(current["gross_margin_rate_pct"] - prev["gross_margin_rate_pct"], 2)
                    if current and prev else None
                ),
                "operating_profit_pct": _diff(current, prev, "operating_profit_fen"),
            },
            "yoy_changes": {
                "revenue_pct": _diff(current, yoy, "total_revenue_fen"),
                "gross_profit_pct": _diff(current, yoy, "gross_profit_fen"),
                "gross_margin_rate_pct_delta": (
                    round(current["gross_margin_rate_pct"] - yoy["gross_margin_rate_pct"], 2)
                    if current and yoy else None
                ),
                "operating_profit_pct": _diff(current, yoy, "operating_profit_fen"),
            },
        },
    }
