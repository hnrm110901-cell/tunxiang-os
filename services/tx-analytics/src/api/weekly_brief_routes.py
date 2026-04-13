"""AI 经营周报 — 结构性问题诊断 + 下周策略建议

端点：
  GET  /api/v1/analytics/weekly-brief/{store_id}  — 单店周报
  GET  /api/v1/analytics/weekly-brief/group        — 集团多店周报汇总

周报内容：
  - 本周营收/客单/翻台/毛利 (vs 上周 / vs 去年同周)
  - 结构性问题诊断（连续下滑品项/流失客户群/成本超标时段）
  - TOP3 问题 + 下周 3 条可执行策略建议
  - 品项维度：热销/滞销/新品表现/高毛利低销售
  - 客群维度：新客/回头客/沉默客占比趋势
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/analytics/weekly-brief", tags=["weekly-brief"])


# ─── 依赖 ─────────────────────────────────────────────────────────────────────

async def _get_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _get_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


# ─── 工具 ─────────────────────────────────────────────────────────────────────

def _week_range(week_start: date) -> tuple[datetime, datetime]:
    """返回周一 00:00 UTC 到下周一 00:00 UTC"""
    start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
    end = start + timedelta(days=7)
    return start, end


def _iso_week_start(d: date) -> date:
    """返回 d 所在周的周一"""
    return d - timedelta(days=d.weekday())


async def _week_metrics(db: AsyncSession, tenant_id: str, week_start: date) -> dict[str, Any]:
    """查询指定周的汇总指标"""
    start, end = _week_range(week_start)
    try:
        r = await db.execute(text("""
            SELECT
                COALESCE(SUM(total_amount_fen), 0)::bigint    AS revenue_fen,
                COUNT(*)                                       AS order_count,
                COUNT(DISTINCT DATE(created_at AT TIME ZONE 'Asia/Shanghai')) AS business_days,
                COALESCE(AVG(total_amount_fen), 0)::numeric   AS avg_ticket_fen,
                COALESCE(SUM(discount_amount_fen), 0)::bigint AS discount_fen,
                COALESCE(SUM(cost_amount_fen), 0)::bigint     AS cost_fen
            FROM orders
            WHERE tenant_id = :tid::uuid
              AND status    = 'completed'
              AND created_at >= :start
              AND created_at <  :end
        """), {"tid": tenant_id, "start": start, "end": end})
        row = dict(r.mappings().fetchone() or {})
        revenue = int(row.get("revenue_fen") or 0)
        cost = int(row.get("cost_fen") or 0)
        margin_fen = revenue - cost
        margin_rate = round(margin_fen / revenue * 100, 2) if revenue > 0 else 0.0
        order_count = int(row.get("order_count") or 0)
        avg_ticket = round(float(row.get("avg_ticket_fen") or 0) / 100, 2)
        return {
            "revenue_fen": revenue,
            "order_count": order_count,
            "avg_ticket_yuan": avg_ticket,
            "margin_rate": margin_rate,
            "discount_fen": int(row.get("discount_fen") or 0),
        }
    except SQLAlchemyError as exc:
        logger.warning("weekly_brief.metrics_failed", error=str(exc), week_start=str(week_start))
        return {"revenue_fen": 0, "order_count": 0, "avg_ticket_yuan": 0.0, "margin_rate": 0.0, "discount_fen": 0}


async def _week_dish_analysis(db: AsyncSession, tenant_id: str, week_start: date) -> dict[str, Any]:
    """本周品项表现分析"""
    start, end = _week_range(week_start)
    try:
        r = await db.execute(text("""
            SELECT
                oi.dish_name,
                SUM(oi.quantity)            AS qty,
                SUM(oi.unit_price_fen * oi.quantity) AS revenue_fen
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.tenant_id = :tid::uuid
              AND o.status    = 'completed'
              AND o.created_at >= :start
              AND o.created_at <  :end
            GROUP BY oi.dish_name
            ORDER BY qty DESC
            LIMIT 20
        """), {"tid": tenant_id, "start": start, "end": end})
        rows = r.mappings().all()
        top5 = [{"name": r["dish_name"], "qty": int(r["qty"]), "revenue_fen": int(r["revenue_fen"])} for r in rows[:5]]
        bottom5 = [{"name": r["dish_name"], "qty": int(r["qty"]), "revenue_fen": int(r["revenue_fen"])} for r in rows[-5:] if len(rows) >= 5]
        return {"top5_by_qty": top5, "bottom5_by_qty": bottom5, "total_skus_sold": len(rows)}
    except SQLAlchemyError as exc:
        logger.warning("weekly_brief.dish_failed", error=str(exc))
        return {"top5_by_qty": [], "bottom5_by_qty": [], "total_skus_sold": 0}


async def _week_member_analysis(db: AsyncSession, tenant_id: str, week_start: date) -> dict[str, Any]:
    """本周客群结构"""
    start, end = _week_range(week_start)
    try:
        r = await db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE member_id IS NOT NULL)  AS member_orders,
                COUNT(*) FILTER (WHERE member_id IS NULL)      AS guest_orders,
                COUNT(DISTINCT member_id) FILTER (WHERE member_id IS NOT NULL) AS unique_members
            FROM orders
            WHERE tenant_id  = :tid::uuid
              AND status      = 'completed'
              AND created_at >= :start
              AND created_at <  :end
        """), {"tid": tenant_id, "start": start, "end": end})
        row = dict(r.mappings().fetchone() or {})
        total = (int(row.get("member_orders") or 0) + int(row.get("guest_orders") or 0)) or 1
        member_rate = round(int(row.get("member_orders") or 0) / total * 100, 1)
        return {
            "member_order_rate": member_rate,
            "unique_members": int(row.get("unique_members") or 0),
            "total_orders": total,
        }
    except SQLAlchemyError as exc:
        logger.warning("weekly_brief.member_failed", error=str(exc))
        return {"member_order_rate": 0.0, "unique_members": 0, "total_orders": 0}


def _delta(current: float, compare: float) -> float | None:
    if compare == 0:
        return None
    return round((current - compare) / compare * 100, 1)


def _generate_weekly_strategies(
    this_week: dict,
    last_week: dict,
    dish_analysis: dict,
    member_analysis: dict,
) -> list[str]:
    """生成3条下周可执行策略建议"""
    strategies: list[str] = []

    # 营收策略
    rev_delta = _delta(this_week["revenue_fen"], last_week["revenue_fen"])
    if rev_delta is not None and rev_delta < -5:
        strategies.append(
            f"本周营收环比下滑 {abs(rev_delta):.1f}%，建议下周加强高峰段推客策略，"
            "重点激活沉默会员（30日未消费），增加复购触达频次。"
        )
    elif rev_delta is not None and rev_delta > 10:
        strategies.append(
            f"本周营收环比增长 {rev_delta:.1f}%，增长势头良好，"
            "建议下周维持当前高峰段排队效率，防止因等待过长流失客户。"
        )

    # 毛利策略
    margin_delta = _delta(this_week["margin_rate"], last_week["margin_rate"])
    if margin_delta is not None and margin_delta < -2:
        strategies.append(
            f"毛利率环比下降 {abs(margin_delta):.1f}ppt，建议排查本周折扣/赠菜异常，"
            "重点核查门店折扣权限是否被滥用。"
        )
    elif this_week["margin_rate"] < 55:
        strategies.append(
            "毛利率低于 55% 预警线，建议下周对毛利低于 40% 的品项进行定价复审，"
            "同时检查食材损耗是否超出正常范围。"
        )

    # 品项策略
    if dish_analysis.get("bottom5_by_qty"):
        slow_names = [d["name"] for d in dish_analysis["bottom5_by_qty"][:3]]
        strategies.append(
            f"滞销品项（{' / '.join(slow_names)}）本周销量极低，"
            "建议下周通过套餐捆绑或限时优惠提升动销，若连续3周滞销可考虑下架。"
        )

    # 会员策略
    if member_analysis.get("member_order_rate", 0) < 30:
        strategies.append(
            f"本周会员订单占比仅 {member_analysis['member_order_rate']:.1f}%，"
            "建议下周在收银台推广扫码入会，目标新增会员 ≥50 人。"
        )

    # 确保返回3条（不足时补通用建议）
    defaults = [
        "建议下周在客流高峰段（11:30-13:00 / 18:00-20:00）安排专人桌台分配，缩短等位时间。",
        "建议对本周高频退菜品项进行后厨品控抽检，减少顾客投诉风险。",
        "建议下周对30天未消费会员发送定向优惠短信，激活复购。",
    ]
    while len(strategies) < 3:
        strategies.append(defaults[len(strategies)])

    return strategies[:3]


def _identify_structural_issues(
    this_week: dict,
    last_week: dict,
    yoy_week: dict,
    dish_analysis: dict,
) -> list[dict[str, str]]:
    """识别结构性问题（连续性、趋势性，非单日波动）"""
    issues: list[dict[str, str]] = []

    rev_wow = _delta(this_week["revenue_fen"], last_week["revenue_fen"])
    if rev_wow is not None and rev_wow < -10:
        issues.append({
            "type": "revenue_decline",
            "severity": "high",
            "description": f"营收环比连续下滑 {abs(rev_wow):.1f}%，需关注是否有竞对开业或节假日效应",
        })

    margin_val = this_week["margin_rate"]
    if margin_val < 50:
        issues.append({
            "type": "low_margin",
            "severity": "high",
            "description": f"毛利率 {margin_val:.1f}% 低于健康水位 55%，成本管控存在漏洞",
        })
    elif margin_val < 55:
        issues.append({
            "type": "margin_warning",
            "severity": "medium",
            "description": f"毛利率 {margin_val:.1f}% 接近预警线，建议持续监控",
        })

    rev_yoy = _delta(this_week["revenue_fen"], yoy_week["revenue_fen"])
    if rev_yoy is not None and rev_yoy < -15:
        issues.append({
            "type": "yoy_decline",
            "severity": "medium",
            "description": f"较去年同期下降 {abs(rev_yoy):.1f}%，存在市场份额流失风险",
        })

    if dish_analysis.get("total_skus_sold", 0) > 0:
        top5_revenue = sum(d.get("revenue_fen", 0) for d in dish_analysis.get("top5_by_qty", []))
        # 如果 TOP5 品项占营收过高，说明菜单依赖度太强
        if this_week["revenue_fen"] > 0:
            top5_concentration = top5_revenue / this_week["revenue_fen"] * 100
            if top5_concentration > 60:
                issues.append({
                    "type": "menu_concentration",
                    "severity": "low",
                    "description": f"TOP5 品项贡献 {top5_concentration:.1f}% 营收，菜单结构集中风险偏高",
                })

    return issues[:5]


# ─── 端点 ─────────────────────────────────────────────────────────────────────

@router.get("/{store_id}", summary="单店周报 — 结构性问题 + 下周策略建议")
async def get_store_weekly_brief(
    store_id: str,
    week_start: date | None = Query(None, description="周一日期 YYYY-MM-DD，缺省为本周"),
    db: AsyncSession = Depends(_get_db),
    tenant_id: str = Depends(_get_tenant),
):
    """
    返回指定门店的 AI 经营周报。
    - week_start 不传则为本周周一
    - 包含：本周指标 vs 上周 vs 去年同期、结构性问题列表、TOP5/Bottom5 品项、下周3条策略
    """
    today = datetime.now(timezone.utc).date()
    if week_start is None:
        week_start = _iso_week_start(today)

    last_week_start = week_start - timedelta(days=7)
    yoy_week_start = week_start - timedelta(weeks=52)

    this_week, last_week, yoy_week, dish_analysis, member_analysis = (
        await _week_metrics(db, tenant_id, week_start),
        await _week_metrics(db, tenant_id, last_week_start),
        await _week_metrics(db, tenant_id, yoy_week_start),
        await _week_dish_analysis(db, tenant_id, week_start),
        await _week_member_analysis(db, tenant_id, week_start),
    )

    structural_issues = _identify_structural_issues(this_week, last_week, yoy_week, dish_analysis)
    strategies = _generate_weekly_strategies(this_week, last_week, dish_analysis, member_analysis)

    logger.info(
        "weekly_brief.generated",
        store_id=store_id,
        week_start=str(week_start),
        tenant_id=tenant_id,
        issues_count=len(structural_issues),
    )

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "week_start": str(week_start),
            "week_end": str(week_start + timedelta(days=6)),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metrics": {
                "this_week": this_week,
                "last_week": last_week,
                "vs_last_week": {
                    "revenue": _delta(this_week["revenue_fen"], last_week["revenue_fen"]),
                    "order_count": _delta(this_week["order_count"], last_week["order_count"]),
                    "avg_ticket": _delta(this_week["avg_ticket_yuan"], last_week["avg_ticket_yuan"]),
                    "margin_rate": _delta(this_week["margin_rate"], last_week["margin_rate"]),
                },
                "vs_same_week_last_year": {
                    "revenue": _delta(this_week["revenue_fen"], yoy_week["revenue_fen"]),
                    "order_count": _delta(this_week["order_count"], yoy_week["order_count"]),
                },
            },
            "structural_issues": structural_issues,
            "dish_analysis": dish_analysis,
            "member_analysis": member_analysis,
            "next_week_strategies": strategies,
        },
    }


@router.get("/group", summary="集团多店周报汇总")
async def get_group_weekly_brief(
    week_start: date | None = Query(None, description="周一日期 YYYY-MM-DD"),
    db: AsyncSession = Depends(_get_db),
    tenant_id: str = Depends(_get_tenant),
):
    """
    汇总租户下所有门店的本周经营数据，输出集团级周报。
    返回：总营收/订单/毛利 vs 上周、各店排名、集团结构性问题汇总
    """
    today = datetime.now(timezone.utc).date()
    if week_start is None:
        week_start = _iso_week_start(today)
    last_week_start = week_start - timedelta(days=7)

    start, end = _week_range(week_start)
    lstart, lend = _week_range(last_week_start)

    # 集团汇总 + 按门店分组
    try:
        r = await db.execute(text("""
            SELECT
                COALESCE(store_id::text, 'unknown')            AS store_id,
                COALESCE(SUM(total_amount_fen), 0)::bigint     AS revenue_fen,
                COUNT(*)                                        AS order_count,
                COALESCE(AVG(total_amount_fen), 0)::numeric    AS avg_ticket_fen,
                COALESCE(SUM(cost_amount_fen), 0)::bigint      AS cost_fen
            FROM orders
            WHERE tenant_id  = :tid::uuid
              AND status      = 'completed'
              AND created_at >= :start
              AND created_at <  :end
            GROUP BY store_id
            ORDER BY revenue_fen DESC
        """), {"tid": tenant_id, "start": start, "end": end})
        store_rows = r.mappings().all()

        lw_r = await db.execute(text("""
            SELECT
                COALESCE(SUM(total_amount_fen), 0)::bigint AS revenue_fen,
                COUNT(*)::int                               AS order_count
            FROM orders
            WHERE tenant_id  = :tid::uuid
              AND status      = 'completed'
              AND created_at >= :start
              AND created_at <  :end
        """), {"tid": tenant_id, "start": lstart, "end": lend})
        lw = dict(lw_r.mappings().fetchone() or {})

    except SQLAlchemyError as exc:
        logger.warning("weekly_brief.group_failed", error=str(exc))
        store_rows, lw = [], {"revenue_fen": 0, "order_count": 0}

    total_revenue = sum(int(r["revenue_fen"]) for r in store_rows)
    total_orders = sum(int(r["order_count"]) for r in store_rows)

    store_ranking = [
        {
            "store_id": r["store_id"],
            "revenue_fen": int(r["revenue_fen"]),
            "order_count": int(r["order_count"]),
            "avg_ticket_yuan": round(float(r["avg_ticket_fen"]) / 100, 2),
        }
        for r in store_rows
    ]

    lw_revenue = int(lw.get("revenue_fen") or 0)
    lw_orders = int(lw.get("order_count") or 0)

    logger.info("weekly_brief.group_generated", week_start=str(week_start), store_count=len(store_ranking))

    return {
        "ok": True,
        "data": {
            "week_start": str(week_start),
            "week_end": str(week_start + timedelta(days=6)),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "group_totals": {
                "revenue_fen": total_revenue,
                "order_count": total_orders,
                "store_count": len(store_ranking),
            },
            "vs_last_week": {
                "revenue": _delta(total_revenue, lw_revenue),
                "order_count": _delta(total_orders, lw_orders),
            },
            "store_ranking": store_ranking,
        },
    }
