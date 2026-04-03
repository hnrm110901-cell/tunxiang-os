"""损耗监控服务 — 帮老板每年多赚30万的核心

迁移自 tunxiang V2.x waste_guard_service.py
纯函数部分（根因映射 + 行动建议），Service 类依赖 DB。

核心指标：每降低 1% 食材损耗 = 直接利润提升。
"""
from typing import Optional

# ─── 根因 → 行动建议映射表 ───

ROOT_CAUSE_ACTIONS: dict[str, str] = {
    "staff_error": "建议针对相关岗位开展操作规范培训（1周内）",
    "food_quality": "建议检查供应商批次质量",
    "over_prep": "建议根据近7天客流调整备餐量（系数1.15）",
    "spoilage": "建议缩短采购周期或改为每日采购",
    "bom_deviation": "建议更新BOM配方",
    "transfer_loss": "建议优化称重/分拣流程",
    "drop_damage": "建议高损耗时段加强备货区巡查",
    "unknown": "建议开启损耗事件追踪",
}


# ─── 纯函数 ───

def action_for_causes(root_causes: list[dict]) -> str:
    """根据根因列表返回最优先的行动建议"""
    if not root_causes:
        return ROOT_CAUSE_ACTIONS["unknown"]
    top_cause = root_causes[0].get("root_cause") or root_causes[0].get("event_type", "unknown")
    return ROOT_CAUSE_ACTIONS.get(top_cause, ROOT_CAUSE_ACTIONS["unknown"])


def compute_waste_rate(waste_fen: int, revenue_fen: int) -> Optional[float]:
    """计算损耗率（%）"""
    if revenue_fen <= 0:
        return None
    return round(waste_fen / revenue_fen * 100, 2)


def classify_waste_status(waste_rate_pct: Optional[float]) -> str:
    """损耗率分级（行业标准：< 3% 正常）

    Returns:
        ok / warning / critical
    """
    if waste_rate_pct is None:
        return "ok"
    if waste_rate_pct >= 5.0:
        return "critical"
    if waste_rate_pct >= 3.0:
        return "warning"
    return "ok"


def compute_waste_change(
    current_fen: int,
    previous_fen: int,
) -> dict:
    """计算损耗环比变化"""
    change_fen = current_fen - previous_fen
    change_pct = None
    if previous_fen > 0:
        change_pct = round(change_fen / previous_fen * 100, 2)

    return {
        "change_fen": change_fen,
        "change_yuan": round(change_fen / 100, 2),
        "change_pct": change_pct,
        "direction": "up" if change_fen > 0 else "down" if change_fen < 0 else "flat",
    }


def build_top5_item(
    rank: int,
    item_name: str,
    waste_cost_fen: int,
    waste_qty: float,
    total_waste_fen: int,
    root_causes: list[dict],
) -> dict:
    """构建 TOP5 损耗单项"""
    cost_share_pct = 0.0
    if total_waste_fen > 0:
        cost_share_pct = round(waste_cost_fen / total_waste_fen * 100, 1)

    return {
        "rank": rank,
        "item_name": item_name,
        "waste_cost_yuan": round(waste_cost_fen / 100, 2),
        "waste_cost_fen": waste_cost_fen,
        "waste_qty": waste_qty,
        "cost_share_pct": cost_share_pct,
        "root_causes": root_causes,
        "action": action_for_causes(root_causes),
    }


def build_waste_rate_summary(
    waste_fen: int,
    revenue_fen: int,
    prev_waste_fen: int,
    start_date: str,
    end_date: str,
) -> dict:
    """构建损耗率摘要"""
    waste_rate = compute_waste_rate(waste_fen, revenue_fen)
    status = classify_waste_status(waste_rate)
    change = compute_waste_change(waste_fen, prev_waste_fen)

    return {
        "waste_rate_pct": waste_rate,
        "waste_rate_status": status,
        "waste_cost_yuan": round(waste_fen / 100, 2),
        "revenue_yuan": round(revenue_fen / 100, 2),
        "period": {"start": start_date, "end": end_date},
        "vs_previous": change,
    }
