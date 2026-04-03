"""D8 周度复盘 — 从日复盘汇聚周数据，生成周度经营报告

聚合一周内的日复盘数据，生成周度趋势分析、问题汇总、改进措施。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  周度复盘
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def generate_weekly_review(
    store_id: str,
    week_start: date,
    tenant_id: str,
    db: Any,
    *,
    daily_reviews: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """生成周度复盘报告。

    聚合本周 7 天日复盘数据，与上周对比，提炼问题及改进方向。

    Args:
        store_id: 门店 ID
        week_start: 周一日期
        tenant_id: 租户 ID
        db: 数据库会话
        daily_reviews: 本周日复盘列表（测试注入用）

    Returns:
        {"review_id", "week_summary", "vs_last_week", "top_issues",
         "improvement_actions", "highlights"}
    """
    review_id = f"weekly_{store_id}_{week_start.isoformat()}_{uuid.uuid4().hex[:8]}"
    week_end = week_start + timedelta(days=6)

    reviews = daily_reviews or []
    week_summary = aggregate_weekly_from_daily(store_id, reviews)

    # 上周数据占位（实际从 db 查询）
    last_week_summary = await _fetch_last_week_summary(store_id, week_start, tenant_id, db)
    vs_last_week = _calc_week_comparison(week_summary, last_week_summary)

    # 提炼本周 TOP 问题
    top_issues = _extract_top_issues(reviews)

    # 生成改进行动建议
    improvement_actions = _generate_improvement_actions(week_summary, top_issues)

    # 亮点提炼
    highlights = _extract_highlights(week_summary, reviews)

    result = {
        "review_id": review_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "week_summary": week_summary,
        "vs_last_week": vs_last_week,
        "top_issues": top_issues,
        "improvement_actions": improvement_actions,
        "highlights": highlights,
        "status": "draft",
        "created_at": datetime.utcnow().isoformat(),
    }

    log.info(
        "weekly_review_generated",
        store_id=store_id,
        tenant_id=tenant_id,
        review_id=review_id,
        issue_count=len(top_issues),
    )
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  日复盘聚合
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def aggregate_weekly_from_daily(
    store_id: str,
    daily_reviews: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """从日复盘列表汇聚周数据。

    Args:
        store_id: 门店 ID
        daily_reviews: 本周日复盘列表

    Returns:
        {"total_revenue_fen", "total_orders", "avg_margin_pct",
         "total_waste_fen", "day_count", "daily_trend"}
    """
    total_revenue = 0
    total_orders = 0
    total_cost = 0
    total_waste = 0
    daily_trend: List[Dict[str, Any]] = []

    for review in daily_reviews:
        rev = review.get("revenue_summary", {})
        cost = review.get("cost_summary", {})
        day_rev = rev.get("total_revenue_fen", 0)
        day_orders = rev.get("order_count", 0)
        day_cost = cost.get("total_cost_fen", 0)
        day_waste = cost.get("waste_cost_fen", 0)

        total_revenue += day_rev
        total_orders += day_orders
        total_cost += day_cost
        total_waste += day_waste

        daily_trend.append({
            "date": review.get("date", ""),
            "revenue_fen": day_rev,
            "orders": day_orders,
            "margin_pct": review.get("margin_summary", {}).get("gross_margin_pct", 0.0),
        })

    day_count = len(daily_reviews)
    gross_profit = total_revenue - total_cost
    avg_margin_pct = round(gross_profit / total_revenue * 100, 2) if total_revenue > 0 else 0.0

    return {
        "store_id": store_id,
        "total_revenue_fen": total_revenue,
        "total_orders": total_orders,
        "avg_margin_pct": avg_margin_pct,
        "total_waste_fen": total_waste,
        "total_cost_fen": total_cost,
        "gross_profit_fen": gross_profit,
        "day_count": day_count,
        "daily_trend": daily_trend,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _fetch_last_week_summary(
    store_id: str,
    current_week_start: date,
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """获取上周周汇总（实际从 DB 查询，此处返回骨架）。"""
    return {
        "total_revenue_fen": 0,
        "total_orders": 0,
        "avg_margin_pct": 0.0,
        "total_waste_fen": 0,
    }


def _calc_week_comparison(
    current: Dict[str, Any],
    last: Dict[str, Any],
) -> Dict[str, Any]:
    """计算本周 vs 上周对比。"""
    def _delta_pct(cur: int | float, prev: int | float) -> float:
        if prev == 0:
            return 0.0
        return round((cur - prev) / prev * 100, 2)

    return {
        "revenue_delta_pct": _delta_pct(
            current.get("total_revenue_fen", 0),
            last.get("total_revenue_fen", 0),
        ),
        "orders_delta_pct": _delta_pct(
            current.get("total_orders", 0),
            last.get("total_orders", 0),
        ),
        "margin_delta_pp": round(
            current.get("avg_margin_pct", 0.0) - last.get("avg_margin_pct", 0.0), 2,
        ),
        "waste_delta_pct": _delta_pct(
            current.get("total_waste_fen", 0),
            last.get("total_waste_fen", 0),
        ),
    }


def _extract_top_issues(daily_reviews: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从日复盘中提炼本周 TOP 问题。"""
    issue_counter: Dict[str, Dict[str, Any]] = {}

    for review in daily_reviews:
        for exc in review.get("exception_list", []):
            etype = exc.get("type", "unknown")
            if etype not in issue_counter:
                issue_counter[etype] = {
                    "type": etype,
                    "count": 0,
                    "total_impact_fen": 0,
                    "examples": [],
                }
            issue_counter[etype]["count"] += 1
            issue_counter[etype]["total_impact_fen"] += exc.get("impact_fen", 0)
            if len(issue_counter[etype]["examples"]) < 3:
                issue_counter[etype]["examples"].append(exc.get("summary", ""))

        for action in review.get("action_items", []):
            if action.get("priority") == "high":
                atype = action.get("type", "unknown")
                if atype not in issue_counter:
                    issue_counter[atype] = {
                        "type": atype,
                        "count": 0,
                        "total_impact_fen": 0,
                        "examples": [],
                    }
                issue_counter[atype]["count"] += 1

    issues = sorted(issue_counter.values(), key=lambda x: x["count"], reverse=True)
    return issues[:5]


def _generate_improvement_actions(
    week_summary: Dict[str, Any],
    top_issues: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """根据周汇总和 TOP 问题生成改进建议。"""
    actions: List[Dict[str, Any]] = []

    if week_summary.get("avg_margin_pct", 100) < 50:
        actions.append({
            "type": "margin",
            "priority": "high",
            "title": f"本周平均毛利率 {week_summary['avg_margin_pct']}%，低于50%",
            "suggestion": "核查高成本菜品、损耗原因，优化采购和出品标准",
        })

    if week_summary.get("total_waste_fen", 0) > 0:
        waste_ratio = week_summary["total_waste_fen"] / max(week_summary.get("total_revenue_fen", 1), 1)
        if waste_ratio > 0.03:
            actions.append({
                "type": "waste",
                "priority": "high",
                "title": f"本周损耗占比 {round(waste_ratio * 100, 2)}%，超过3%警戒线",
                "suggestion": "分析损耗原因（过期/操作/退菜），针对性改进",
            })

    for issue in top_issues[:3]:
        if issue["count"] >= 3:
            actions.append({
                "type": issue["type"],
                "priority": "medium",
                "title": f"问题类型「{issue['type']}」本周出现 {issue['count']} 次",
                "suggestion": "需要制定专项整改方案，避免问题反复出现",
            })

    return actions


def _extract_highlights(
    week_summary: Dict[str, Any],
    daily_reviews: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """提炼本周经营亮点。"""
    highlights: List[Dict[str, Any]] = []

    if week_summary.get("avg_margin_pct", 0) >= 60:
        highlights.append({
            "type": "margin",
            "title": f"本周平均毛利率达 {week_summary['avg_margin_pct']}%，表现优秀",
        })

    # 查找营收最好的一天
    trend = week_summary.get("daily_trend", [])
    if trend:
        best_day = max(trend, key=lambda d: d.get("revenue_fen", 0))
        if best_day.get("revenue_fen", 0) > 0:
            highlights.append({
                "type": "revenue",
                "title": f"本周营收最高日 {best_day.get('date', '')}，"
                         f"营收 {best_day['revenue_fen']} 分",
            })

    return highlights
