"""决策推送服务 — 4时间点差异化推送

迁移自 tunxiang V2.x decision_push_service.py
纯函数部分（格式化），无 DB/企微依赖。

推送规则：建议动作 + ¥影响 + 置信度 — 纯信息不推。
"""

MAX_DESC_CHARS = 512


# ─── 晨推 08:00 格式 ───

def format_morning_card(decisions: list[dict]) -> str:
    """晨推卡片描述：Top3 决策，面向老板"""
    if not decisions:
        return "今日暂无决策建议。"
    lines = []
    for i, d in enumerate(decisions[:3], 1):
        title = d.get("title", "")
        action = d.get("action", "")[:40]
        saving = d.get("expected_saving_yuan", 0)
        conf = d.get("confidence", 0) * 100
        diff = d.get("difficulty", "medium")
        lines.append(f"{i}. 【{title}】")
        lines.append(f"   行动：{action}")
        lines.append(f"   💰¥{saving:.0f} | 置信度{conf:.0f}% | 难度:{diff}")
    text = "\n".join(lines)
    return text[:MAX_DESC_CHARS]


# ─── 午推 12:00 格式 ───

def format_noon_anomaly(waste_summary: dict, decisions: list[dict]) -> str:
    """午推异常推送：损耗+决策，面向店长"""
    lines = []
    rate = waste_summary.get("waste_rate_pct", 0)
    total = waste_summary.get("waste_cost_yuan", 0)
    status = waste_summary.get("waste_rate_status", "ok")
    emoji = "🔴" if status == "critical" else "⚠️" if status == "warning" else "✅"
    lines.append(f"{emoji} 损耗率 {rate:.1f}%（¥{total:.0f}），状态：{status}")

    # TOP1 损耗
    top5 = waste_summary.get("top5", [])
    if top5:
        t = top5[0]
        lines.append(f"  损耗第1：{t.get('item_name', '')} ¥{t.get('waste_cost_yuan', 0):.0f}，归因：{t.get('action', '')[:20]}")

    for d in decisions[:2]:
        saving = d.get("expected_saving_yuan", 0)
        conf = d.get("confidence", 0) * 100
        lines.append(f"• {d.get('title', '')}（¥{saving:.0f}，置信度{conf:.0f}%）")

    return "\n".join(lines)[:MAX_DESC_CHARS]


# ─── 战前 17:30 格式 ───

def format_prebattle(decisions: list[dict], store_name: str) -> str:
    """战前核查：库存+紧急决策，面向经理"""
    lines = [f"【{store_name}】晚高峰备战核查"]

    inventory = [d for d in decisions if d.get("source") == "inventory"]
    others = [d for d in decisions if d.get("source") != "inventory"]

    if inventory:
        lines.append("📦 库存决策：")
        for d in inventory[:3]:
            lines.append(f"  • {d.get('title', '')} — {d.get('action', '')[:40]}")

    if others:
        lines.append("📊 其他建议：")
        for d in others[:2]:
            saving = d.get("expected_saving_yuan", 0)
            lines.append(f"  • {d.get('title', '')}（¥{saving:.0f}）")

    if not inventory and not others:
        lines.append("✅ 库存与经营指标均正常")

    return "\n".join(lines)[:MAX_DESC_CHARS]


# ─── 晚推 20:30 格式 ───

def format_evening_recap(decisions: list[dict], pending_count: int) -> str:
    """晚推经营简报：回顾+待批，面向全员"""
    lines = []

    if pending_count > 0:
        lines.append(f"⏳ 还有 {pending_count} 条决策待审批")

    total_saving = sum(d.get("expected_saving_yuan", 0) for d in decisions)
    if total_saving > 0:
        lines.append(f"💰 今日决策预期节省合计：¥{total_saving:.0f}")

    for d in decisions[:3]:
        conf = d.get("confidence", 0) * 100
        lines.append(f"• {d.get('title', '')} — 置信度{conf:.0f}%")

    if not lines:
        lines.append("✅ 今日经营正常，无待处理决策")

    return "\n".join(lines)[:MAX_DESC_CHARS]


# ─── 推送决策逻辑 ───

def should_push_noon(waste_status: str, has_anomaly_decisions: bool) -> bool:
    """午推是否推送：仅 warning/critical 时"""
    return waste_status in ("warning", "critical") or has_anomaly_decisions


def should_push_prebattle(decisions: list[dict]) -> bool:
    """战前是否推送：有库存/紧急决策时"""
    return any(
        d.get("source") == "inventory" or d.get("urgency_hours", 999) < 4
        for d in decisions
    )


def should_push_evening(pending_count: int, has_decisions: bool) -> bool:
    """晚推是否推送：有待批或有决策时"""
    return pending_count > 0 or has_decisions
