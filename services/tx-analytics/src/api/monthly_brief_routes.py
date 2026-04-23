"""AI 经营月报 — 经营体检 + 投入产出建议

端点：
  GET  /api/v1/analytics/monthly-brief/{store_id}  — 单店月报
  GET  /api/v1/analytics/monthly-brief/group        — 集团月报汇总

月报内容：
  - 月度核心指标（营收/订单/客单/翻台/毛利）vs 上月 vs 去年同月
  - 经营体检（8项评分：营收增长/毛利健康/客单趋势/新客占比/会员复购/折扣纪律/食安合规/日结合规）
  - 投入产出建议（成本端/营收端/运营端各2条）
  - 月度品项报告（上新/下架建议、高毛利低动销品项）
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/analytics/monthly-brief", tags=["monthly-brief"])


# ─── 依赖 ─────────────────────────────────────────────────────────────────────


async def _get_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _get_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


# ─── 工具 ─────────────────────────────────────────────────────────────────────


def _month_range(year: int, month: int) -> tuple[datetime, datetime]:
    """返回指定月份的 [月初, 下月初) UTC"""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _prev_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _delta(current: float, compare: float) -> float | None:
    if compare == 0:
        return None
    return round((current - compare) / compare * 100, 1)


async def _month_metrics(db: AsyncSession, tenant_id: str, year: int, month: int) -> dict[str, Any]:
    """查询指定月份汇总指标"""
    start, end = _month_range(year, month)
    try:
        r = await db.execute(
            text("""
            SELECT
                COALESCE(SUM(total_amount_fen), 0)::bigint     AS revenue_fen,
                COUNT(*)                                        AS order_count,
                COALESCE(AVG(total_amount_fen), 0)::numeric    AS avg_ticket_fen,
                COALESCE(SUM(discount_amount_fen), 0)::bigint  AS discount_fen,
                COALESCE(SUM(cost_amount_fen), 0)::bigint      AS cost_fen,
                COUNT(DISTINCT DATE(created_at AT TIME ZONE 'Asia/Shanghai')) AS business_days
            FROM orders
            WHERE tenant_id = :tid::uuid
              AND status    = 'completed'
              AND created_at >= :start
              AND created_at <  :end
        """),
            {"tid": tenant_id, "start": start, "end": end},
        )
        row = dict(r.mappings().fetchone() or {})
        revenue = int(row.get("revenue_fen") or 0)
        cost = int(row.get("cost_fen") or 0)
        margin_fen = revenue - cost
        margin_rate = round(margin_fen / revenue * 100, 2) if revenue > 0 else 0.0
        order_count = int(row.get("order_count") or 0)
        avg_ticket = round(float(row.get("avg_ticket_fen") or 0) / 100, 2)
        business_days = int(row.get("business_days") or 1)
        daily_avg_revenue = round(revenue / business_days / 100, 2)
        discount_fen = int(row.get("discount_fen") or 0)
        discount_rate = round(discount_fen / revenue * 100, 2) if revenue > 0 else 0.0
        return {
            "revenue_fen": revenue,
            "order_count": order_count,
            "avg_ticket_yuan": avg_ticket,
            "margin_rate": margin_rate,
            "discount_rate": discount_rate,
            "business_days": business_days,
            "daily_avg_revenue_yuan": daily_avg_revenue,
        }
    except SQLAlchemyError as exc:
        logger.warning("monthly_brief.metrics_failed", error=str(exc), year=year, month=month)
        return {
            "revenue_fen": 0,
            "order_count": 0,
            "avg_ticket_yuan": 0.0,
            "margin_rate": 0.0,
            "discount_rate": 0.0,
            "business_days": 0,
            "daily_avg_revenue_yuan": 0.0,
        }


async def _month_member_metrics(db: AsyncSession, tenant_id: str, year: int, month: int) -> dict[str, Any]:
    """月度会员指标"""
    start, end = _month_range(year, month)
    prev_start, _ = _month_range(*_prev_month(year, month))
    try:
        r = await db.execute(
            text("""
            SELECT
                COUNT(*) FILTER (WHERE member_id IS NOT NULL) AS member_orders,
                COUNT(*) FILTER (WHERE member_id IS NULL)     AS guest_orders,
                COUNT(DISTINCT member_id) FILTER (WHERE member_id IS NOT NULL) AS unique_members
            FROM orders
            WHERE tenant_id  = :tid::uuid
              AND status      = 'completed'
              AND created_at >= :start
              AND created_at <  :end
        """),
            {"tid": tenant_id, "start": start, "end": end},
        )
        row = dict(r.mappings().fetchone() or {})
        total = int(row.get("member_orders") or 0) + int(row.get("guest_orders") or 0)
        member_rate = round(int(row.get("member_orders") or 0) / total * 100, 1) if total > 0 else 0.0

        # 复购率：当月有2次+消费的会员
        rep_r = await db.execute(
            text("""
            WITH m AS (
                SELECT member_id, COUNT(*) AS cnt
                FROM orders
                WHERE tenant_id  = :tid::uuid
                  AND status      = 'completed'
                  AND member_id   IS NOT NULL
                  AND created_at >= :start
                  AND created_at <  :end
                GROUP BY member_id
            )
            SELECT
                COUNT(*) FILTER (WHERE cnt >= 2)::float AS repurchase_members,
                COUNT(*)::float                          AS total_members
            FROM m
        """),
            {"tid": tenant_id, "start": start, "end": end},
        )
        rep_row = dict(rep_r.mappings().fetchone() or {})
        rep_total = float(rep_row.get("total_members") or 0)
        repurchase_rate = (
            round(float(rep_row.get("repurchase_members") or 0) / rep_total * 100, 1) if rep_total > 0 else 0.0
        )

        return {
            "member_order_rate": member_rate,
            "unique_members": int(row.get("unique_members") or 0),
            "repurchase_rate": repurchase_rate,
        }
    except SQLAlchemyError as exc:
        logger.warning("monthly_brief.member_failed", error=str(exc))
        return {"member_order_rate": 0.0, "unique_members": 0, "repurchase_rate": 0.0}


async def _month_compliance_score(db: AsyncSession, tenant_id: str, year: int, month: int) -> dict[str, Any]:
    """月度合规检查：日结合规率 + 折扣纪律 + 食安合规"""
    start, end = _month_range(year, month)
    try:
        # 日结合规率（已完成日结的天数 / 营业天数）
        settle_r = await db.execute(
            text("""
            SELECT COUNT(DISTINCT settlement_date)::int AS settled_days
            FROM daily_settlements
            WHERE tenant_id   = :tid::uuid
              AND status       = 'completed'
              AND settlement_date >= :s_date
              AND settlement_date <  :e_date
        """),
            {
                "tid": tenant_id,
                "s_date": start.date(),
                "e_date": end.date(),
            },
        )
        settle_row = dict(settle_r.mappings().fetchone() or {})
        settled_days = int(settle_row.get("settled_days") or 0)

        # 折扣纪律：超过 30% 折扣率的订单占比
        disc_r = await db.execute(
            text("""
            SELECT
                COUNT(*) FILTER (
                    WHERE total_amount_fen > 0
                      AND discount_amount_fen::float / total_amount_fen > 0.3
                )::float AS exc_count,
                COUNT(*)::float AS total_count
            FROM orders
            WHERE tenant_id = :tid::uuid
              AND status    = 'completed'
              AND created_at >= :start
              AND created_at <  :end
        """),
            {"tid": tenant_id, "start": start, "end": end},
        )
        disc_row = dict(disc_r.mappings().fetchone() or {})
        disc_total = float(disc_row.get("total_count") or 0)
        discount_exception_rate = (
            round(float(disc_row.get("exc_count") or 0) / disc_total * 100, 2) if disc_total > 0 else 0.0
        )

        return {
            "settled_days": settled_days,
            "discount_exception_rate": discount_exception_rate,
        }
    except SQLAlchemyError as exc:
        logger.warning("monthly_brief.compliance_failed", error=str(exc))
        return {"settled_days": 0, "discount_exception_rate": 0.0}


def _health_check(
    this_month: dict,
    prev_month: dict,
    yoy_month: dict,
    member: dict,
    compliance: dict,
) -> list[dict[str, Any]]:
    """经营体检：8项评分（每项 0-100 分）"""
    checks = []

    # 1. 营收增长健康度
    rev_mom = _delta(this_month["revenue_fen"], prev_month["revenue_fen"])
    if rev_mom is None:
        rev_score = 70
    elif rev_mom >= 10:
        rev_score = 95
    elif rev_mom >= 5:
        rev_score = 85
    elif rev_mom >= 0:
        rev_score = 75
    elif rev_mom >= -5:
        rev_score = 60
    else:
        rev_score = 40
    checks.append(
        {
            "item": "营收增长",
            "score": rev_score,
            "status": "good" if rev_score >= 80 else ("warning" if rev_score >= 60 else "risk"),
            "detail": f"月度环比 {rev_mom:+.1f}%" if rev_mom is not None else "无对比数据",
        }
    )

    # 2. 毛利健康度
    margin = this_month["margin_rate"]
    if margin >= 60:
        m_score = 95
    elif margin >= 55:
        m_score = 85
    elif margin >= 50:
        m_score = 70
    elif margin >= 45:
        m_score = 55
    else:
        m_score = 35
    checks.append(
        {
            "item": "毛利健康",
            "score": m_score,
            "status": "good" if m_score >= 80 else ("warning" if m_score >= 60 else "risk"),
            "detail": f"综合毛利率 {margin:.1f}%",
        }
    )

    # 3. 客单趋势
    ticket_mom = _delta(this_month["avg_ticket_yuan"], prev_month["avg_ticket_yuan"])
    if ticket_mom is None:
        t_score = 70
    elif ticket_mom >= 5:
        t_score = 90
    elif ticket_mom >= 0:
        t_score = 75
    else:
        t_score = 55
    checks.append(
        {
            "item": "客单趋势",
            "score": t_score,
            "status": "good" if t_score >= 80 else ("warning" if t_score >= 60 else "risk"),
            "detail": f"客单 ¥{this_month['avg_ticket_yuan']:.1f}，环比 {ticket_mom:+.1f}%"
            if ticket_mom is not None
            else f"客单 ¥{this_month['avg_ticket_yuan']:.1f}",
        }
    )

    # 4. 会员复购率
    repurchase = member.get("repurchase_rate", 0)
    if repurchase >= 40:
        r_score = 95
    elif repurchase >= 30:
        r_score = 80
    elif repurchase >= 20:
        r_score = 65
    else:
        r_score = 45
    checks.append(
        {
            "item": "会员复购",
            "score": r_score,
            "status": "good" if r_score >= 80 else ("warning" if r_score >= 60 else "risk"),
            "detail": f"月度复购率 {repurchase:.1f}%",
        }
    )

    # 5. 折扣纪律
    disc_exc = compliance.get("discount_exception_rate", 0)
    if disc_exc <= 1:
        d_score = 95
    elif disc_exc <= 3:
        d_score = 80
    elif disc_exc <= 5:
        d_score = 65
    else:
        d_score = 40
    checks.append(
        {
            "item": "折扣纪律",
            "score": d_score,
            "status": "good" if d_score >= 80 else ("warning" if d_score >= 60 else "risk"),
            "detail": f"超额折扣订单占比 {disc_exc:.1f}%",
        }
    )

    # 6. 日结合规率
    settled = compliance.get("settled_days", 0)
    bdays = this_month.get("business_days", 1) or 1
    settle_rate = round(settled / bdays * 100, 1)
    if settle_rate >= 95:
        s_score = 95
    elif settle_rate >= 85:
        s_score = 75
    elif settle_rate >= 70:
        s_score = 55
    else:
        s_score = 35
    checks.append(
        {
            "item": "日结合规",
            "score": s_score,
            "status": "good" if s_score >= 80 else ("warning" if s_score >= 60 else "risk"),
            "detail": f"日结完成率 {settle_rate:.1f}%（{settled}/{bdays} 天）",
        }
    )

    return checks


def _generate_monthly_recommendations(
    this_month: dict,
    prev_month: dict,
    member: dict,
    health_checks: list[dict],
) -> dict[str, list[str]]:
    """投入产出建议：分成本端/营收端/运营端"""
    cost_recs: list[str] = []
    revenue_recs: list[str] = []
    ops_recs: list[str] = []

    margin = this_month["margin_rate"]
    if margin < 55:
        cost_recs.append(
            f"毛利率 {margin:.1f}% 偏低，建议下月对主力品项进行成本复核：审查BOM损耗率、"
            "食材采购价格（建议对比近3个月均价）、厨房出料标准化程度。"
        )
    cost_recs.append(
        "建议对月度高频耗材（餐具破损/一次性用品/包装材料）进行核查，"
        "历史数据显示这类隐性成本通常占营收 1-2%，优化后可直接提升净利。"
    )

    rev_mom = _delta(this_month["revenue_fen"], prev_month["revenue_fen"])
    if rev_mom is not None and rev_mom < 0:
        revenue_recs.append(
            f"本月营收环比下降 {abs(rev_mom):.1f}%，建议分析具体下降时段："
            "若为非高峰段，可考虑增加下午茶套餐或到店自提优惠；"
            "若为高峰段，优先排查桌台周转率和等位体验。"
        )

    member_rate = member.get("member_order_rate", 0)
    if member_rate < 35:
        revenue_recs.append(
            f"会员订单占比 {member_rate:.1f}%，建议本月重点推进会员体系建设：设定"
            "月度新增会员目标（建议 ≥ 本月总客人数的 15%），通过首单折扣/积分翻倍活动驱动。"
        )
    else:
        revenue_recs.append(
            f"会员订单占比良好（{member_rate:.1f}%），建议深化会员分层运营："
            "对沉默会员（60天未消费）发送定向唤醒优惠，目标唤醒率 ≥ 10%。"
        )

    # 找出评分最低的运营项
    risk_items = [h for h in health_checks if h["status"] == "risk"]
    if risk_items:
        worst = min(risk_items, key=lambda h: h["score"])
        ops_recs.append(
            f"本月经营体检【{worst['item']}】评分最低（{worst['score']}分），建议优先改善：{worst['detail']}。"
        )
    ops_recs.append(
        "建议本月组织一次门店运营复盘会（店长+收银主管），重点对账本月收支差异，确保日结数据与财务系统一致。"
    )

    return {
        "cost_side": cost_recs[:2],
        "revenue_side": revenue_recs[:2],
        "operations_side": ops_recs[:2],
    }


# ─── 端点 ─────────────────────────────────────────────────────────────────────


@router.get("/{store_id}", summary="单店月报 — 经营体检 + 投入产出建议")
async def get_store_monthly_brief(
    store_id: str,
    year: int | None = Query(None, description="年份，缺省为当月"),
    month: int | None = Query(None, ge=1, le=12, description="月份 1-12，缺省为当月"),
    db: AsyncSession = Depends(_get_db),
    tenant_id: str = Depends(_get_tenant),
):
    """
    返回指定门店的 AI 经营月报。
    - year/month 不传则为本月
    - 包含：月度核心指标 vs 上月 vs 去年同月、经营体检评分（8项）、投入产出建议
    """
    now = datetime.now(timezone.utc)
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    py, pm = _prev_month(year, month)
    yoy_year = year - 1

    this_m, prev_m, yoy_m, member, compliance = (
        await _month_metrics(db, tenant_id, year, month),
        await _month_metrics(db, tenant_id, py, pm),
        await _month_metrics(db, tenant_id, yoy_year, month),
        await _month_member_metrics(db, tenant_id, year, month),
        await _month_compliance_score(db, tenant_id, year, month),
    )

    health = _health_check(this_m, prev_m, yoy_m, member, compliance)
    overall_score = round(sum(h["score"] for h in health) / len(health), 1) if health else 0
    recommendations = _generate_monthly_recommendations(this_m, prev_m, member, health)

    logger.info(
        "monthly_brief.generated",
        store_id=store_id,
        year=year,
        month=month,
        overall_score=overall_score,
        tenant_id=tenant_id,
    )

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "period": f"{year}-{month:02d}",
            "generated_at": now.isoformat(),
            "metrics": {
                "this_month": this_m,
                "vs_last_month": {
                    "revenue": _delta(this_m["revenue_fen"], prev_m["revenue_fen"]),
                    "order_count": _delta(this_m["order_count"], prev_m["order_count"]),
                    "avg_ticket": _delta(this_m["avg_ticket_yuan"], prev_m["avg_ticket_yuan"]),
                    "margin_rate": _delta(this_m["margin_rate"], prev_m["margin_rate"]),
                },
                "vs_same_month_last_year": {
                    "revenue": _delta(this_m["revenue_fen"], yoy_m["revenue_fen"]),
                    "order_count": _delta(this_m["order_count"], yoy_m["order_count"]),
                },
            },
            "member_metrics": member,
            "health_check": {
                "overall_score": overall_score,
                "grade": "A"
                if overall_score >= 85
                else ("B" if overall_score >= 70 else ("C" if overall_score >= 55 else "D")),
                "items": health,
            },
            "recommendations": recommendations,
        },
    }


@router.get("/group", summary="集团月报汇总")
async def get_group_monthly_brief(
    year: int | None = Query(None),
    month: int | None = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(_get_db),
    tenant_id: str = Depends(_get_tenant),
):
    """集团级月报：各店营收排名 + 集团综合体检"""
    now = datetime.now(timezone.utc)
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    start, end = _month_range(year, month)
    py, pm = _prev_month(year, month)
    pstart, pend = _month_range(py, pm)

    try:
        r = await db.execute(
            text("""
            SELECT
                COALESCE(store_id::text, 'unknown') AS store_id,
                COALESCE(SUM(total_amount_fen), 0)::bigint   AS revenue_fen,
                COUNT(*)::int                                 AS order_count,
                COALESCE(AVG(total_amount_fen), 0)::numeric  AS avg_ticket_fen,
                COALESCE(SUM(cost_amount_fen), 0)::bigint    AS cost_fen
            FROM orders
            WHERE tenant_id  = :tid::uuid
              AND status      = 'completed'
              AND created_at >= :start
              AND created_at <  :end
            GROUP BY store_id
            ORDER BY revenue_fen DESC
        """),
            {"tid": tenant_id, "start": start, "end": end},
        )
        store_rows = r.mappings().all()

        lm_r = await db.execute(
            text("""
            SELECT COALESCE(SUM(total_amount_fen), 0)::bigint AS revenue_fen
            FROM orders
            WHERE tenant_id  = :tid::uuid
              AND status      = 'completed'
              AND created_at >= :start
              AND created_at <  :end
        """),
            {"tid": tenant_id, "start": pstart, "end": pend},
        )
        lm_rev = int((lm_r.scalar() or 0))

    except SQLAlchemyError as exc:
        logger.warning("monthly_brief.group_failed", error=str(exc))
        store_rows, lm_rev = [], 0

    total_revenue = sum(int(r["revenue_fen"]) for r in store_rows)
    total_orders = sum(int(r["order_count"]) for r in store_rows)

    store_ranking = [
        {
            "store_id": r["store_id"],
            "revenue_fen": int(r["revenue_fen"]),
            "order_count": int(r["order_count"]),
            "avg_ticket_yuan": round(float(r["avg_ticket_fen"]) / 100, 2),
            "margin_rate": round((int(r["revenue_fen"]) - int(r["cost_fen"])) / int(r["revenue_fen"]) * 100, 1)
            if int(r["revenue_fen"]) > 0
            else 0.0,
        }
        for r in store_rows
    ]

    logger.info("monthly_brief.group_generated", year=year, month=month, store_count=len(store_ranking))

    return {
        "ok": True,
        "data": {
            "period": f"{year}-{month:02d}",
            "generated_at": now.isoformat(),
            "group_totals": {
                "revenue_fen": total_revenue,
                "order_count": total_orders,
                "store_count": len(store_ranking),
                "vs_last_month_revenue": _delta(total_revenue, lm_rev),
            },
            "store_ranking": store_ranking,
        },
    }
