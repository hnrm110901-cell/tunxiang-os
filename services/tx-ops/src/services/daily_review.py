"""E7 店长复盘 — 日度经营复盘、行动项提交、历史查询、店长签发

聚合当日经营数据，生成复盘报告，支持行动项管理。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import structlog

from shared.events import OpsEventType, UniversalPublisher

log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  日度复盘
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def generate_daily_review(
    store_id: str,
    date_: date,
    tenant_id: str,
    db: Any,
    *,
    revenue_data: Optional[Dict[str, Any]] = None,
    cost_data: Optional[Dict[str, Any]] = None,
    exceptions: Optional[List[Dict[str, Any]]] = None,
    dish_sales: Optional[List[Dict[str, Any]]] = None,
    staff_data: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """生成日度复盘报告。

    聚合收入、成本、毛利、异常、菜品表现、员工表现。

    Args:
        store_id: 门店 ID
        date_: 日期
        tenant_id: 租户 ID
        db: 数据库会话
        revenue_data: 营收数据（测试注入用）
        cost_data: 成本数据
        exceptions: 当日异常列表
        dish_sales: 菜品销售数据
        staff_data: 员工数据

    Returns:
        {"review_id": str, "revenue_summary": {...}, "cost_summary": {...},
         "margin_summary": {...}, "exception_list": [...],
         "dish_performance": [...], "staff_performance": [...],
         "action_items": [...]}
    """
    review_id = f"review_{store_id}_{date_.isoformat()}_{uuid.uuid4().hex[:8]}"

    # 营收汇总
    rev = revenue_data or {}
    revenue_summary = {
        "total_revenue_fen": rev.get("total_revenue_fen", 0),
        "target_revenue_fen": rev.get("target_revenue_fen", 0),
        "achievement_pct": _calc_pct(
            rev.get("total_revenue_fen", 0),
            rev.get("target_revenue_fen", 0),
        ),
        "order_count": rev.get("order_count", 0),
        "avg_ticket_fen": (
            rev.get("total_revenue_fen", 0) // rev.get("order_count", 1) if rev.get("order_count", 0) > 0 else 0
        ),
        "table_turnover": rev.get("table_turnover", 0.0),
        "channel_breakdown": rev.get("channel_breakdown", {}),
    }

    # 成本汇总
    c = cost_data or {}
    total_cost_fen = c.get("total_cost_fen", 0)
    cost_summary = {
        "total_cost_fen": total_cost_fen,
        "food_cost_fen": c.get("food_cost_fen", 0),
        "labor_cost_fen": c.get("labor_cost_fen", 0),
        "other_cost_fen": c.get("other_cost_fen", 0),
        "waste_cost_fen": c.get("waste_cost_fen", 0),
    }

    # 毛利汇总
    total_rev = revenue_summary["total_revenue_fen"]
    gross_profit = total_rev - total_cost_fen
    margin_summary = {
        "gross_profit_fen": gross_profit,
        "gross_margin_pct": _calc_pct(gross_profit, total_rev) if total_rev > 0 else 0.0,
        "food_cost_ratio_pct": _calc_pct(c.get("food_cost_fen", 0), total_rev) if total_rev > 0 else 0.0,
    }

    # 异常列表
    exception_list = []
    for exc in exceptions or []:
        exception_list.append(
            {
                "exception_id": exc.get("exception_id", ""),
                "type": exc.get("type", ""),
                "summary": exc.get("summary", ""),
                "status": exc.get("status", ""),
                "impact_fen": exc.get("impact_fen", 0),
            }
        )

    # 菜品表现
    dish_performance = _build_dish_performance(dish_sales or [])

    # 员工表现
    staff_performance = _build_staff_performance(staff_data or [])

    # 自动生成行动项建议
    action_items = _generate_action_suggestions(
        revenue_summary,
        cost_summary,
        margin_summary,
        exception_list,
        dish_performance,
    )

    review = {
        "review_id": review_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "date": date_.isoformat(),
        "revenue_summary": revenue_summary,
        "cost_summary": cost_summary,
        "margin_summary": margin_summary,
        "exception_list": exception_list,
        "dish_performance": dish_performance,
        "staff_performance": staff_performance,
        "action_items": action_items,
        "status": "draft",
        "created_at": datetime.utcnow().isoformat(),
    }

    log.info(
        "daily_review_generated",
        store_id=store_id,
        tenant_id=tenant_id,
        review_id=review_id,
        action_item_count=len(action_items),
    )
    return review


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  行动项管理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def submit_action_items(
    store_id: str,
    items: List[Dict[str, Any]],
    manager_id: str,
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """提交次日行动项。

    Args:
        store_id: 门店 ID
        items: 行动项列表, 每项包含:
            {"title": str, "assignee_id": str, "priority": str, "due_date": str}
        manager_id: 提交人(店长) ID
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"submitted_count": int, "items": [...], "submitted_by": str}
    """
    enriched = []
    for idx, item in enumerate(items):
        enriched.append(
            {
                "action_id": f"act_{store_id}_{uuid.uuid4().hex[:8]}",
                "seq": idx,
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "assignee_id": item.get("assignee_id", ""),
                "priority": item.get("priority", "medium"),
                "due_date": item.get("due_date", ""),
                "status": "pending",
                "created_by": manager_id,
                "created_at": datetime.utcnow().isoformat(),
            }
        )

    log.info(
        "action_items_submitted",
        store_id=store_id,
        tenant_id=tenant_id,
        manager_id=manager_id,
        count=len(enriched),
    )

    return {
        "submitted_count": len(enriched),
        "items": enriched,
        "submitted_by": manager_id,
        "submitted_at": datetime.utcnow().isoformat(),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  历史复盘
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_review_history(
    store_id: str,
    days: int,
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """获取历史复盘列表。

    Args:
        store_id: 门店 ID
        days: 查询天数
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"store_id": str, "days": int, "reviews": [...], "total": int}
    """
    # 实际从 db 查询; 返回结构骨架
    log.info(
        "review_history_queried",
        store_id=store_id,
        tenant_id=tenant_id,
        days=days,
    )
    return {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "days": days,
        "reviews": [],
        "total": 0,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  店长签发
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def sign_off_review(
    store_id: str,
    date_: date,
    manager_id: str,
    tenant_id: str,
    db: Any,
    *,
    review: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """店长签发复盘报告。

    Args:
        store_id: 门店 ID
        date_: 日期
        manager_id: 店长 ID
        tenant_id: 租户 ID
        db: 数据库会话
        review: 已加载的复盘报告

    Returns:
        {"signed_off": bool, "signed_by": str, "signed_at": str}
    """
    if review is not None:
        if review.get("status") == "signed_off":
            raise ValueError("Review already signed off")
        review["status"] = "signed_off"
        review["signed_by"] = manager_id
        review["signed_at"] = datetime.utcnow().isoformat()

    log.info(
        "review_signed_off",
        store_id=store_id,
        tenant_id=tenant_id,
        manager_id=manager_id,
        date=date_.isoformat(),
    )

    total_revenue_fen = (review or {}).get("revenue_summary", {}).get("total_revenue_fen", 0)
    asyncio.create_task(
        UniversalPublisher.publish(
            event_type=OpsEventType.DAILY_E7_SETTLEMENT_DONE,
            tenant_id=uuid.UUID(tenant_id),
            store_id=uuid.UUID(store_id),
            entity_id=None,
            event_data={"store_id": store_id, "total_revenue_fen": total_revenue_fen},
            source_service="tx-ops",
        )
    )

    return {
        "signed_off": True,
        "signed_by": manager_id,
        "signed_at": datetime.utcnow().isoformat(),
        "store_id": store_id,
        "date": date_.isoformat(),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _calc_pct(part: int | float, whole: int | float) -> float:
    """安全计算百分比。"""
    if whole == 0:
        return 0.0
    return round(part / whole * 100, 2)


def _build_dish_performance(dish_sales: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """构建菜品表现排行。"""
    result = []
    for dish in dish_sales:
        result.append(
            {
                "dish_id": dish.get("dish_id", ""),
                "dish_name": dish.get("dish_name", ""),
                "qty_sold": dish.get("qty_sold", 0),
                "revenue_fen": dish.get("revenue_fen", 0),
                "gross_margin_pct": dish.get("gross_margin_pct", 0.0),
                "return_rate_pct": dish.get("return_rate_pct", 0.0),
            }
        )
    result.sort(key=lambda d: d["revenue_fen"], reverse=True)
    return result


def _build_staff_performance(staff_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """构建员工表现汇总。"""
    result = []
    for s in staff_data:
        result.append(
            {
                "staff_id": s.get("staff_id", ""),
                "name": s.get("name", ""),
                "role": s.get("role", ""),
                "orders_served": s.get("orders_served", 0),
                "revenue_fen": s.get("revenue_fen", 0),
                "complaints": s.get("complaints", 0),
                "tips_fen": s.get("tips_fen", 0),
            }
        )
    return result


def _generate_action_suggestions(
    revenue_summary: Dict,
    cost_summary: Dict,
    margin_summary: Dict,
    exception_list: List[Dict],
    dish_performance: List[Dict],
) -> List[Dict[str, Any]]:
    """根据经营数据自动生成行动项建议。"""
    suggestions: List[Dict[str, Any]] = []

    # 营收达成率低于 80%
    achievement = revenue_summary.get("achievement_pct", 100)
    if achievement < 80:
        suggestions.append(
            {
                "type": "revenue",
                "priority": "high",
                "title": f"营收达成率仅 {achievement}%，需制定提升方案",
                "description": "分析客流和客单价，制定次日促销或引流措施",
            }
        )

    # 食材成本率超 40%
    food_ratio = margin_summary.get("food_cost_ratio_pct", 0)
    if food_ratio > 40:
        suggestions.append(
            {
                "type": "cost",
                "priority": "high",
                "title": f"食材成本率 {food_ratio}%，超出40%警戒线",
                "description": "核查高成本菜品用量，检查损耗和采购价格",
            }
        )

    # 异常数量超 3 个
    if len(exception_list) > 3:
        suggestions.append(
            {
                "type": "exception",
                "priority": "medium",
                "title": f"今日 {len(exception_list)} 个异常事件，需重点关注",
                "description": "逐个复盘异常根因，制定预防措施",
            }
        )

    # 退菜率高的菜品
    for dish in dish_performance:
        if dish.get("return_rate_pct", 0) > 5:
            suggestions.append(
                {
                    "type": "dish_quality",
                    "priority": "medium",
                    "title": f"菜品「{dish['dish_name']}」退菜率 {dish['return_rate_pct']}%",
                    "description": "与厨师长沟通出品质量，必要时调整配方或暂停售卖",
                }
            )
            break  # 只取第一个高退菜率菜品

    return suggestions
