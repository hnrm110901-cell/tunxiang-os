"""D8 月度复盘 — 月度经营报告、趋势分析、区域汇总

生成门店月度经营复盘与区域维度汇总。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  月度复盘
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def generate_monthly_review(
    store_id: str,
    month: str,
    tenant_id: str,
    db: Any,
    *,
    weekly_reviews: Optional[List[Dict[str, Any]]] = None,
    targets: Optional[Dict[str, Any]] = None,
    staff_data: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """生成月度复盘报告。

    Args:
        store_id: 门店 ID
        month: 月份 (YYYY-MM)
        tenant_id: 租户 ID
        db: 数据库会话
        weekly_reviews: 本月周复盘列表（测试注入用）
        targets: 月度目标数据
        staff_data: 员工绩效数据

    Returns:
        {"review_id", "month_summary", "trend_analysis", "target_achievement",
         "cost_analysis", "staff_performance", "action_plan"}
    """
    review_id = f"monthly_{store_id}_{month}_{uuid.uuid4().hex[:8]}"

    weeks = weekly_reviews or []
    month_summary = _build_month_summary(store_id, month, weeks)
    trend_analysis = _build_trend_analysis(weeks)
    target_achievement = _calc_target_achievement(month_summary, targets or {})
    cost_analysis = _build_cost_analysis(month_summary)
    staff_performance = _build_monthly_staff_performance(staff_data or [])
    action_plan = _generate_monthly_action_plan(
        month_summary, trend_analysis, target_achievement, cost_analysis,
    )

    result = {
        "review_id": review_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "month": month,
        "month_summary": month_summary,
        "trend_analysis": trend_analysis,
        "target_achievement": target_achievement,
        "cost_analysis": cost_analysis,
        "staff_performance": staff_performance,
        "action_plan": action_plan,
        "status": "draft",
        "created_at": datetime.utcnow().isoformat(),
    }

    log.info(
        "monthly_review_generated",
        store_id=store_id,
        tenant_id=tenant_id,
        review_id=review_id,
        month=month,
    )
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  区域汇总
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def generate_regional_review(
    region_id: str,
    month: str,
    tenant_id: str,
    db: Any,
    *,
    store_reviews: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """生成区域月度汇总报告。

    汇聚区域内所有门店的月度复盘数据。

    Args:
        region_id: 区域 ID
        month: 月份 (YYYY-MM)
        tenant_id: 租户 ID
        db: 数据库会话
        store_reviews: 区域内各门店月复盘列表（测试注入用）

    Returns:
        {"review_id", "region_summary", "store_ranking", "common_issues",
         "best_practices", "regional_action_plan"}
    """
    review_id = f"regional_{region_id}_{month}_{uuid.uuid4().hex[:8]}"
    reviews = store_reviews or []

    region_summary = _build_region_summary(region_id, month, reviews)
    store_ranking = _rank_stores(reviews)
    common_issues = _find_common_issues(reviews)
    best_practices = _find_best_practices(reviews)
    regional_action_plan = _generate_regional_action_plan(
        region_summary, common_issues,
    )

    result = {
        "review_id": review_id,
        "region_id": region_id,
        "tenant_id": tenant_id,
        "month": month,
        "region_summary": region_summary,
        "store_ranking": store_ranking,
        "common_issues": common_issues,
        "best_practices": best_practices,
        "regional_action_plan": regional_action_plan,
        "status": "draft",
        "created_at": datetime.utcnow().isoformat(),
    }

    log.info(
        "regional_review_generated",
        region_id=region_id,
        tenant_id=tenant_id,
        review_id=review_id,
        month=month,
        store_count=len(reviews),
    )
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部辅助 — 月度
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _build_month_summary(
    store_id: str,
    month: str,
    weekly_reviews: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """从周复盘汇聚月度汇总。"""
    total_revenue = 0
    total_orders = 0
    total_cost = 0
    total_waste = 0

    for week in weekly_reviews:
        ws = week.get("week_summary", {})
        total_revenue += ws.get("total_revenue_fen", 0)
        total_orders += ws.get("total_orders", 0)
        total_cost += ws.get("total_cost_fen", 0)
        total_waste += ws.get("total_waste_fen", 0)

    gross_profit = total_revenue - total_cost
    margin_pct = round(gross_profit / total_revenue * 100, 2) if total_revenue > 0 else 0.0

    return {
        "store_id": store_id,
        "month": month,
        "total_revenue_fen": total_revenue,
        "total_orders": total_orders,
        "total_cost_fen": total_cost,
        "gross_profit_fen": gross_profit,
        "gross_margin_pct": margin_pct,
        "total_waste_fen": total_waste,
        "week_count": len(weekly_reviews),
    }


def _build_trend_analysis(
    weekly_reviews: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """生成月内周趋势分析。"""
    weekly_trend: List[Dict[str, Any]] = []
    for week in weekly_reviews:
        ws = week.get("week_summary", {})
        weekly_trend.append({
            "week_start": week.get("week_start", ""),
            "revenue_fen": ws.get("total_revenue_fen", 0),
            "orders": ws.get("total_orders", 0),
            "margin_pct": ws.get("avg_margin_pct", 0.0),
        })

    revenue_values = [w["revenue_fen"] for w in weekly_trend]
    trend_direction = "stable"
    if len(revenue_values) >= 2:
        if revenue_values[-1] > revenue_values[0] * 1.05:
            trend_direction = "up"
        elif revenue_values[-1] < revenue_values[0] * 0.95:
            trend_direction = "down"

    return {
        "weekly_trend": weekly_trend,
        "revenue_trend": trend_direction,
    }


def _calc_target_achievement(
    month_summary: Dict[str, Any],
    targets: Dict[str, Any],
) -> Dict[str, Any]:
    """计算月度目标达成情况。"""
    def _pct(actual: int | float, target: int | float) -> float:
        if target == 0:
            return 0.0
        return round(actual / target * 100, 2)

    revenue_target = targets.get("revenue_target_fen", 0)
    orders_target = targets.get("orders_target", 0)
    margin_target = targets.get("margin_target_pct", 0.0)

    return {
        "revenue_achievement_pct": _pct(
            month_summary.get("total_revenue_fen", 0), revenue_target,
        ),
        "orders_achievement_pct": _pct(
            month_summary.get("total_orders", 0), orders_target,
        ),
        "margin_vs_target_pp": round(
            month_summary.get("gross_margin_pct", 0.0) - margin_target, 2,
        ),
        "targets": targets,
    }


def _build_cost_analysis(month_summary: Dict[str, Any]) -> Dict[str, Any]:
    """成本结构分析。"""
    total_rev = month_summary.get("total_revenue_fen", 0) or 1
    total_cost = month_summary.get("total_cost_fen", 0)
    waste = month_summary.get("total_waste_fen", 0)

    return {
        "cost_ratio_pct": round(total_cost / total_rev * 100, 2),
        "waste_ratio_pct": round(waste / total_rev * 100, 2),
        "total_cost_fen": total_cost,
        "total_waste_fen": waste,
    }


def _build_monthly_staff_performance(
    staff_data: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """构建月度员工绩效汇总。"""
    result: List[Dict[str, Any]] = []
    for s in staff_data:
        result.append({
            "staff_id": s.get("staff_id", ""),
            "name": s.get("name", ""),
            "role": s.get("role", ""),
            "total_orders_served": s.get("total_orders_served", 0),
            "total_revenue_fen": s.get("total_revenue_fen", 0),
            "complaint_count": s.get("complaint_count", 0),
            "attendance_days": s.get("attendance_days", 0),
            "rating": s.get("rating", 0.0),
        })
    result.sort(key=lambda x: x["total_revenue_fen"], reverse=True)
    return result


def _generate_monthly_action_plan(
    month_summary: Dict[str, Any],
    trend_analysis: Dict[str, Any],
    target_achievement: Dict[str, Any],
    cost_analysis: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """生成月度行动计划。"""
    plan: List[Dict[str, Any]] = []

    rev_ach = target_achievement.get("revenue_achievement_pct", 100)
    if 0 < rev_ach < 90:
        plan.append({
            "type": "revenue",
            "priority": "high",
            "title": f"营收达成率 {rev_ach}%，低于90%目标线",
            "actions": ["分析客流量变化", "评估促销策略效果", "制定下月引流方案"],
        })

    if trend_analysis.get("revenue_trend") == "down":
        plan.append({
            "type": "trend",
            "priority": "high",
            "title": "月内营收呈下降趋势",
            "actions": ["分析下降原因（竞品/季节/口碑）", "制定止损方案"],
        })

    waste_ratio = cost_analysis.get("waste_ratio_pct", 0)
    if waste_ratio > 3:
        plan.append({
            "type": "waste",
            "priority": "medium",
            "title": f"月损耗率 {waste_ratio}%，需改善",
            "actions": ["按品类分析损耗原因", "优化备料标准", "加强库存管理"],
        })

    return plan


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部辅助 — 区域
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _build_region_summary(
    region_id: str,
    month: str,
    store_reviews: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """区域维度汇总。"""
    total_revenue = 0
    total_orders = 0
    total_cost = 0

    for review in store_reviews:
        ms = review.get("month_summary", {})
        total_revenue += ms.get("total_revenue_fen", 0)
        total_orders += ms.get("total_orders", 0)
        total_cost += ms.get("total_cost_fen", 0)

    gross_profit = total_revenue - total_cost
    margin_pct = round(gross_profit / total_revenue * 100, 2) if total_revenue > 0 else 0.0

    return {
        "region_id": region_id,
        "month": month,
        "store_count": len(store_reviews),
        "total_revenue_fen": total_revenue,
        "total_orders": total_orders,
        "total_cost_fen": total_cost,
        "gross_profit_fen": gross_profit,
        "avg_margin_pct": margin_pct,
    }


def _rank_stores(store_reviews: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """门店排名。"""
    ranking: List[Dict[str, Any]] = []
    for review in store_reviews:
        ms = review.get("month_summary", {})
        ranking.append({
            "store_id": ms.get("store_id", review.get("store_id", "")),
            "revenue_fen": ms.get("total_revenue_fen", 0),
            "margin_pct": ms.get("gross_margin_pct", 0.0),
            "orders": ms.get("total_orders", 0),
        })
    ranking.sort(key=lambda x: x["revenue_fen"], reverse=True)
    for i, r in enumerate(ranking):
        r["rank"] = i + 1
    return ranking


def _find_common_issues(store_reviews: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """识别区域内共性问题。"""
    issue_map: Dict[str, int] = {}
    for review in store_reviews:
        ap = review.get("action_plan", [])
        for action in ap:
            atype = action.get("type", "unknown")
            issue_map[atype] = issue_map.get(atype, 0) + 1

    common = [
        {"type": k, "store_count": v}
        for k, v in sorted(issue_map.items(), key=lambda x: x[1], reverse=True)
        if v >= 2
    ]
    return common[:5]


def _find_best_practices(store_reviews: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从表现好的门店提炼最佳实践。"""
    practices: List[Dict[str, Any]] = []
    for review in store_reviews:
        ms = review.get("month_summary", {})
        margin = ms.get("gross_margin_pct", 0.0)
        if margin >= 60:
            practices.append({
                "store_id": ms.get("store_id", ""),
                "metric": "gross_margin_pct",
                "value": margin,
                "note": "毛利率优秀，可作为标杆门店",
            })
    return practices


def _generate_regional_action_plan(
    region_summary: Dict[str, Any],
    common_issues: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """区域级整改计划。"""
    plan: List[Dict[str, Any]] = []
    for issue in common_issues:
        plan.append({
            "type": issue["type"],
            "scope": "regional",
            "title": f"区域共性问题「{issue['type']}」涉及 {issue['store_count']} 家门店",
            "actions": ["制定统一整改方案", "组织区域培训", "跟踪整改效果"],
        })
    return plan
