"""经营故事叙述器 — 老板30秒读懂今天生意

迁移自 tunxiang V2.x narrative_engine.py
全纯函数，无 DB 依赖。总字数硬约束 ≤ 200 字。
"""

from typing import Optional

BRIEF_MAX_CHARS = 200


# ─── 纯函数1：经营概览 ───


def build_overview(
    store_label: str,
    cost_metrics: dict,
    decision_summary: dict,
) -> str:
    """经营概览句（1句话）

    Args:
        store_label: 门店标签（如"芙蓉路店"）
        cost_metrics: {"revenue_yuan": 8560, "actual_cost_pct": 32.5, "cost_rate_label": "正常"}
        decision_summary: {"approved": 2, "total": 3}
    """
    revenue = cost_metrics.get("revenue_yuan", 0)
    cost_pct = cost_metrics.get("actual_cost_pct", 0)
    status_label = cost_metrics.get("cost_rate_label", "未知")

    text = f"{store_label}今日营收¥{revenue:,.0f}，成本率{cost_pct:.1f}%（{status_label}）"

    total = decision_summary.get("total", 0)
    approved = decision_summary.get("approved", 0)
    if total > 0:
        text += f"，决策采纳{approved}/{total}"

    return text


# ─── 纯函数2：异常检测 ───


def detect_anomalies(
    cost_metrics: dict,
    waste_top5: list,
    pending_count: int = 0,
    top_decisions: Optional[list] = None,
) -> list[str]:
    """检测异常，最多返回 3 条，按优先级排序

    Returns:
        异常描述列表（带 emoji 前缀）
    """
    anomalies: list[tuple[int, str]] = []  # (priority, text)

    # 成本异常
    cost_status = cost_metrics.get("cost_rate_status")
    cost_pct = cost_metrics.get("actual_cost_pct", 0)
    if cost_status == "critical":
        anomalies.append((0, f"🔴 食材成本严重超标：{cost_pct:.1f}%，需立即干预"))
    elif cost_status == "warning":
        anomalies.append((1, f"⚠️ 食材成本偏高：{cost_pct:.1f}%，关注趋势"))

    # 损耗 TOP1
    if waste_top5:
        top = waste_top5[0]
        item_name = top.get("item_name", top.get("ingredient_name", "未知"))
        waste_yuan = top.get("waste_cost_yuan", 0)
        action = top.get("action", "")[:18]
        priority = 1 if cost_status == "critical" else 2
        anomalies.append((priority, f"⚠️ {item_name}损耗¥{waste_yuan:.0f}居首，{action}"))

    # 待审批决策
    if pending_count > 0:
        saving = _sum_saving(top_decisions or [])
        anomalies.append((2, f"⏳ {pending_count}条决策待审批，预期节省¥{saving:.0f}"))

    anomalies.sort(key=lambda x: x[0])
    return [text for _, text in anomalies[:3]]


def _sum_saving(decisions: list) -> float:
    """汇总决策预期节省"""
    total = 0.0
    for d in decisions:
        total += d.get("expected_saving_yuan", 0) or d.get("net_benefit_yuan", 0)
    return total


# ─── 纯函数3：行动建议 ───


def build_action(
    top_decisions: list,
    cost_metrics: dict,
) -> str:
    """生成行动建议（1句话）"""
    if top_decisions and top_decisions[0].get("action"):
        action = top_decisions[0]["action"][:46]
        return f"✅ 明日建议：{action}"

    cost_status = cost_metrics.get("cost_rate_status")
    if cost_status == "critical":
        return "✅ 明日建议：重点核查超标食材，与厨师长核对BOM用量"
    if cost_status == "warning":
        return "✅ 明日建议：关注成本率变化，确认备料量是否合理"
    return "✅ 明日建议：维持当前节奏，关注明日天气和客流预测"


# ─── 纯函数4：组装简报 ───


def compose_brief(
    store_label: str,
    cost_metrics: dict,
    decision_summary: dict,
    waste_top5: list,
    pending_count: int = 0,
    top_decisions: Optional[list] = None,
) -> str:
    """组装完整经营简报（≤200字）

    Returns:
        多行文本，不超过 200 字符
    """
    overview = build_overview(store_label, cost_metrics, decision_summary)
    anomalies = detect_anomalies(cost_metrics, waste_top5, pending_count, top_decisions)
    action = build_action(top_decisions or [], cost_metrics)

    parts = [overview] + anomalies + [action]
    brief = "\n".join(parts)

    if len(brief) > BRIEF_MAX_CHARS:
        brief = brief[: BRIEF_MAX_CHARS - 1] + "…"

    return brief
