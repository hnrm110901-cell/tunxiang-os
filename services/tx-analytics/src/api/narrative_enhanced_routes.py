"""
经营叙事引擎增强 — 对比叙事 + 异常叙事
P3-02: 差异化护城河

端点：
  GET  /api/v1/analytics/narrative/comparison    — 对比叙事（昨日/上周/上月）
  GET  /api/v1/analytics/narrative/anomaly       — 异常叙事（偏差检测）
  POST /api/v1/analytics/narrative/daily-report  — 完整日报（企微推送格式）
"""
import structlog
from fastapi import APIRouter, Query, Header
from pydantic import BaseModel
from typing import Optional
from datetime import date, timedelta

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/analytics/narrative", tags=["narrative-enhanced"])

# ─── Mock 历史基线数据（用于对比和异常检测） ─────────────────────────────────────

MOCK_HISTORICAL_METRICS = {
    "revenue_fen": {"avg_7d": 2_520_000, "avg_30d": 2_480_000, "std": 185_000},
    "discount_rate": {"avg_7d": 0.092, "avg_30d": 0.089, "std": 0.012},
    "void_order_rate": {"avg_7d": 0.011, "avg_30d": 0.012, "std": 0.004},
    "customer_count": {"avg_7d": 142, "avg_30d": 138, "std": 18},
    "avg_order_value_fen": {"avg_7d": 17_747, "avg_30d": 17_971, "std": 1_200},
}

# ─── Mock 今日数据（按 store_id 做轻微浮动） ─────────────────────────────────────

def _mock_today_metrics(store_id: Optional[str], analysis_date: date) -> dict:
    """基于 store_id 哈希生成稳定的今日模拟数据"""
    seed = abs(hash(str(store_id or "default") + str(analysis_date))) % 100
    # 利用 seed 在合理范围内浮动
    rev_delta = (seed - 50) * 8_000          # ±400_000 fen
    customer_delta = (seed - 50) // 5        # ±10
    discount_seed = seed % 3                 # 0=正常, 1=偏高, 2=严重偏高
    void_seed = seed % 4                     # 0=正常, 1=偏高, 2=严重偏高, 3=正常

    discount_rate = 0.092 + [0.003, 0.095, 0.018][discount_seed]   # 正常/高/严重
    void_rate = 0.011 + [0.002, 0.032, 0.001, 0.000][void_seed]

    return {
        "revenue_fen": 2_856_000 + rev_delta,
        "customer_count": 153 + customer_delta,
        "avg_order_value_fen": 18_700,
        "discount_rate": discount_rate,
        "void_order_rate": void_rate,
        "cost_rate": 0.381,
        "dinner_traffic_growth": 0.18,
        "lunch_traffic_change": -0.05,
    }

def _mock_compare_value(metric: str, dimension: str) -> float:
    """获取对比基准值"""
    hist = MOCK_HISTORICAL_METRICS.get(metric, {})
    if dimension in ("yesterday",):
        # 昨日：基于7日均值加小扰动
        base = hist.get("avg_7d", 0)
        return base * 0.97  # 昨日略低
    if dimension == "last_week":
        return hist.get("avg_7d", 0)
    if dimension == "last_month":
        return hist.get("avg_30d", 0)
    return hist.get("avg_7d", 0)


# ─── 叙事生成函数 ────────────────────────────────────────────────────────────────

def _change_label(rate: float) -> str:
    """根据变化率生成定性描述"""
    if rate > 0.10:
        return "强劲增长"
    if rate > 0.05:
        return "稳健提升"
    if rate > 0.00:
        return "小幅改善"
    if rate > -0.05:
        return "略有回落"
    return "需关注"


def _trend_direction(rate: float) -> str:
    if rate > 0:
        return "up"
    if rate < 0:
        return "down"
    return "flat"


def _format_fen(fen: int) -> str:
    """分转元，带千分符"""
    return f"¥{fen / 100:,.0f}"


def _build_comparison_detail(
    dimension: str,
    label: str,
    current_value: float,
    compare_value: float,
    metric_label: str,
    unit: str = "",
) -> dict:
    """构建单个对比维度的叙事块"""
    if compare_value == 0:
        change_rate = 0.0
    else:
        change_rate = (current_value - compare_value) / abs(compare_value)

    pct_str = f"{change_rate:+.1%}"
    trend = _trend_direction(change_rate)
    quality = _change_label(change_rate)

    if unit == "fen":
        curr_str = _format_fen(int(current_value))
        comp_str = _format_fen(int(compare_value))
        delta_str = _format_fen(int(current_value - compare_value))
        narrative = f"较{label}{pct_str}（{delta_str}），{quality}。"
        if dimension == "yesterday" and change_rate > 0.05:
            narrative += "晚市客流量+18%，人均消费提升至¥187。"
        elif dimension == "yesterday" and change_rate < -0.05:
            narrative += "午市客流有所回落，建议核查营业时段分布。"
    else:
        curr_str = f"{current_value:.1f}{unit}"
        comp_str = f"{compare_value:.1f}{unit}"
        delta_str = f"{current_value - compare_value:+.1f}{unit}"
        narrative = f"较{label}{pct_str}（{delta_str}），{quality}。"

    return {
        "dimension": dimension,
        "label": label,
        "current_value": current_value,
        "compare_value": compare_value,
        "change_rate": round(change_rate, 4),
        "trend": trend,
        "narrative": narrative,
        "current_display": curr_str,
        "compare_display": comp_str,
    }


def _extract_key_drivers(today: dict, comparisons: list[dict]) -> list[str]:
    """自动提取正向驱动因素（最多3个）"""
    drivers = []
    if today.get("dinner_traffic_growth", 0) > 0.10:
        drivers.append("晚市客流提升")
    # 营业额增长
    rev_comp = next((c for c in comparisons if c["dimension"] == "yesterday"), None)
    if rev_comp and rev_comp["change_rate"] > 0.08:
        drivers.append("营业额环比增长")
    if today.get("avg_order_value_fen", 0) > 18_000:
        drivers.append("客单价高于均值")
    if today.get("discount_rate", 1) < 0.10:
        drivers.append("折扣管控良好")
    # 保底
    if not drivers:
        drivers.append("稳定经营")
    return drivers[:3]


def _extract_concerns(today: dict) -> list[str]:
    """自动提取关注点（下滑或异常指标）"""
    concerns = []
    if today.get("lunch_traffic_change", 0) < -0.03:
        concerns.append(f"午市客流同比{today['lunch_traffic_change']:.0%}")
    if today.get("cost_rate", 0) > 0.36:
        concerns.append(f"食材成本率升至{today['cost_rate']:.0%}")
    if today.get("void_order_rate", 0) > 0.02:
        concerns.append(f"废单率{today['void_order_rate']:.1%}偏高")
    if today.get("discount_rate", 0) > 0.15:
        concerns.append(f"折扣率{today['discount_rate']:.1%}偏高")
    return concerns[:3]


# ─── Pydantic 模型 ────────────────────────────────────────────────────────────────

class DailyReportRequest(BaseModel):
    store_id: Optional[str] = None
    date: Optional[date] = None
    include_comparison: bool = True
    include_anomaly: bool = True
    template_id: Optional[str] = None


# ─── 端点1：对比叙事 ─────────────────────────────────────────────────────────────

@router.get("/comparison", summary="对比叙事（昨日/上周同期/上月同期）")
async def get_comparison_narrative(
    store_id: Optional[str] = Query(None, description="门店ID，不传则全店"),
    analysis_date: Optional[date] = Query(None, alias="date", description="分析日期，默认昨日"),
    compare_with: list[str] = Query(
        default=["yesterday", "last_week", "last_month"],
        description="对比维度：yesterday/last_week/last_month",
    ),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """
    对比叙事引擎：将今日核心经营指标与历史基准对比，生成差异化叙事文本。

    叙事质量规则：
    - 增长 >10%  → "强劲增长"
    - 增长 5-10% → "稳健提升"
    - 增长 0-5%  → "小幅改善"
    - 下降 0-5%  → "略有回落"
    - 下降 >10%  → "需关注"
    """
    target_date = analysis_date or (date.today() - timedelta(days=1))
    log = logger.bind(
        tenant=x_tenant_id,
        store_id=store_id,
        date=str(target_date),
        compare_with=compare_with,
    )

    today = _mock_today_metrics(store_id, target_date)
    revenue_fen = today["revenue_fen"]

    # 构建各维度对比
    dim_label_map = {
        "yesterday": "昨日",
        "last_week": "上周同期",
        "last_month": "上月同期",
    }
    valid_dims = [d for d in compare_with if d in dim_label_map]

    comparisons: list[dict] = []
    for dim in valid_dims:
        label = dim_label_map[dim]
        compare_rev = _mock_compare_value("revenue_fen", dim)
        comp = _build_comparison_detail(
            dimension=dim,
            label=label,
            current_value=revenue_fen,
            compare_value=compare_rev,
            metric_label="营业额",
            unit="fen",
        )
        comparisons.append(comp)

    # 主标题（以昨日为主，其余维度补充）
    primary = next((c for c in comparisons if c["dimension"] == "yesterday"), None)
    if primary:
        rate_str = f"{primary['change_rate']:+.1%}"
        headline = f"今日营业额{_format_fen(int(revenue_fen))}，较昨日{rate_str}"
        if len(comparisons) > 1:
            week_comp = next((c for c in comparisons if c["dimension"] == "last_week"), None)
            if week_comp:
                headline += f"，超上周同期{week_comp['change_rate']:+.1%}"
    else:
        headline = f"今日营业额{_format_fen(int(revenue_fen))}"

    key_drivers = _extract_key_drivers(today, comparisons)
    concerns = _extract_concerns(today)

    # 完整叙事段落
    date_str = target_date.strftime("%m月%d日")
    comp_summary = "；".join(c["narrative"] for c in comparisons)
    full_narrative = (
        f"【经营日报·{date_str}】今日全店营业额{_format_fen(int(revenue_fen))}，"
        f"接待顾客{today['customer_count']}人，人均消费"
        f"{_format_fen(today['avg_order_value_fen'])}。\n"
        f"{comp_summary}\n"
        f"▸ 亮点：{'、'.join(key_drivers)}\n"
        f"▸ 关注：{'、'.join(concerns) if concerns else '暂无异常'}"
    )

    log.info("narrative.comparison.ok", headline=headline, dims=len(comparisons))

    return {
        "ok": True,
        "data": {
            "date": target_date.isoformat(),
            "store_id": store_id or "all",
            "headline": headline,
            "revenue_fen": revenue_fen,
            "customer_count": today["customer_count"],
            "avg_order_value_fen": today["avg_order_value_fen"],
            "comparisons": comparisons,
            "key_drivers": key_drivers,
            "concerns": concerns,
            "full_narrative": full_narrative,
        },
        "error": None,
    }


# ─── 端点2：异常叙事 ─────────────────────────────────────────────────────────────

@router.get("/anomaly", summary="异常叙事（指标偏差检测）")
async def get_anomaly_narrative(
    store_id: Optional[str] = Query(None, description="门店ID"),
    analysis_date: Optional[date] = Query(None, alias="date", description="分析日期，默认今日"),
    threshold: float = Query(2.0, ge=1.0, le=5.0, description="标准差倍数阈值，超过即为异常"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """
    异常叙事引擎：检测今日指标与历史均值的标准差偏离，定位异常并生成说明文本。

    severity 规则：
    - deviation >= 3.0  → critical
    - deviation >= 2.0  → high
    - deviation >= 1.5  → medium
    """
    target_date = analysis_date or date.today()
    log = logger.bind(
        tenant=x_tenant_id,
        store_id=store_id,
        date=str(target_date),
        threshold=threshold,
    )

    today = _mock_today_metrics(store_id, target_date)

    # 需要检测的指标列表
    check_metrics = [
        {
            "metric": "discount_rate",
            "label": "折扣率",
            "current": today["discount_rate"],
            "hist_key": "discount_rate",
            "format": "pct",
            "related_agent": "discount_guard",
            "anomaly_hint": "折扣",
        },
        {
            "metric": "void_order_rate",
            "label": "废单率",
            "current": today["void_order_rate"],
            "hist_key": "void_order_rate",
            "format": "pct",
            "related_agent": "anomaly_detector",
            "anomaly_hint": "废单",
        },
        {
            "metric": "revenue_fen",
            "label": "营业额",
            "current": today["revenue_fen"],
            "hist_key": "revenue_fen",
            "format": "fen",
            "related_agent": "revenue_monitor",
            "anomaly_hint": "营业额",
        },
        {
            "metric": "customer_count",
            "label": "客流量",
            "current": today["customer_count"],
            "hist_key": "customer_count",
            "format": "int",
            "related_agent": "traffic_monitor",
            "anomaly_hint": "客流",
        },
    ]

    def _severity(deviation: float) -> str:
        if deviation >= 3.0:
            return "critical"
        if deviation >= 2.0:
            return "high"
        return "medium"

    def _format_value(val: float, fmt: str) -> str:
        if fmt == "pct":
            return f"{val:.1%}"
        if fmt == "fen":
            return _format_fen(int(val))
        return f"{val:.0f}"

    anomalies: list[dict] = []
    for item in check_metrics:
        hist = MOCK_HISTORICAL_METRICS.get(item["hist_key"], {})
        avg = hist.get("avg_7d", 0)
        std = hist.get("std", 1)
        if std == 0:
            continue
        current = item["current"]
        deviation = abs(current - avg) / std

        if deviation < threshold:
            continue

        sev = _severity(deviation)
        curr_display = _format_value(current, item["format"])
        avg_display = _format_value(avg, item["format"])

        # 构建叙事文本
        direction = "偏高" if current > avg else "偏低"
        if item["format"] == "pct":
            narrative = (
                f"今日{item['label']}{curr_display}，是历史均值{avg_display}的"
                f"{current / avg:.2f}倍（{direction}）。"
            )
        else:
            narrative = (
                f"今日{item['label']}{curr_display}，较历史均值{avg_display}"
                f"偏差{deviation:.1f}σ（{direction}）。"
            )

        # 补充 Agent 建议
        if item["metric"] == "discount_rate" and current > avg:
            narrative += "建议检查：是否有异常折扣操作，折扣守护Agent已标记3笔可疑记录。"
        elif item["metric"] == "void_order_rate" and current > avg:
            narrative += "最大拖累因素：14:30-15:30区间发生7笔废单，涉及员工赵**，建议核查。"
        elif item["metric"] == "revenue_fen" and current < avg:
            narrative += "建议检查营业时段覆盖是否完整，对比同期外卖/堂食占比变化。"

        anomalies.append({
            "metric": item["metric"],
            "label": item["label"],
            "current_value": current,
            "historical_avg": avg,
            "deviation": round(deviation, 2),
            "severity": sev,
            "direction": direction,
            "narrative": narrative,
            "related_agent": item["related_agent"],
        })

    # 按 deviation 降序排序
    anomalies.sort(key=lambda x: x["deviation"], reverse=True)
    has_anomaly = len(anomalies) > 0

    # 最大拖累因素
    biggest_drag = None
    if anomalies:
        worst = anomalies[0]
        if worst["direction"] == "偏高" and worst["metric"] in ("void_order_rate", "discount_rate"):
            # 估算影响金额（简化：超出均值部分 × 日营业额）
            rev = today["revenue_fen"]
            est_impact = int(rev * (worst["current_value"] - worst["historical_avg"]))
            biggest_drag = f"{worst['label']}异常（-{_format_fen(abs(est_impact))}估算影响）"
        else:
            biggest_drag = f"{worst['label']}异常（偏差{worst['deviation']:.1f}σ）"

    # 完整异常播报
    date_str = target_date.strftime("%m月%d日")
    if has_anomaly:
        anomaly_lines = "\n".join(
            f"  {'🔴' if a['severity'] == 'critical' else '⚠️'} {a['label']}：{a['narrative']}"
            for a in anomalies
        )
        full_narrative = (
            f"【异常播报·{date_str}】今日发现{len(anomalies)}项经营异常：\n"
            f"{anomaly_lines}\n"
            f"▸ 最大拖累：{biggest_drag or '暂无'}"
        )
    else:
        full_narrative = f"【异常播报·{date_str}】今日各项指标均在正常范围内，无重大异常。"

    log.info(
        "narrative.anomaly.ok",
        has_anomaly=has_anomaly,
        anomaly_count=len(anomalies),
        threshold=threshold,
    )

    return {
        "ok": True,
        "data": {
            "date": target_date.isoformat(),
            "store_id": store_id or "all",
            "threshold": threshold,
            "has_anomaly": has_anomaly,
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
            "biggest_drag": biggest_drag,
            "full_narrative": full_narrative,
        },
        "error": None,
    }


# ─── 端点3：日报完整版 ───────────────────────────────────────────────────────────

@router.post("/daily-report", summary="完整日报（企微推送格式）")
async def generate_daily_report(
    req: DailyReportRequest,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """
    完整日报生成器：合并对比叙事 + 异常叙事 + 基础叙事，输出企微推送格式文本。

    模板适配：
    - template_id=None / "default"   → 标准日报
    - template_id="compact"          → 精简版（仅关键指标）
    - template_id="boss"             → Boss版（一句话总结 + 最重要数据）
    """
    target_date = req.date or (date.today() - timedelta(days=1))
    store_id = req.store_id
    log = logger.bind(
        tenant=x_tenant_id,
        store_id=store_id,
        date=str(target_date),
        template_id=req.template_id,
    )

    today = _mock_today_metrics(store_id, target_date)
    revenue_fen = today["revenue_fen"]
    customer_count = today["customer_count"]
    avg_order = today["avg_order_value_fen"]

    # 收集对比数据
    rev_yesterday = _mock_compare_value("revenue_fen", "yesterday")
    rev_change = (revenue_fen - rev_yesterday) / rev_yesterday if rev_yesterday else 0

    # 收集异常摘要
    anomaly_summary_parts: list[str] = []
    if req.include_anomaly:
        hist_discount = MOCK_HISTORICAL_METRICS["discount_rate"]["avg_7d"]
        hist_void = MOCK_HISTORICAL_METRICS["void_order_rate"]["avg_7d"]
        std_discount = MOCK_HISTORICAL_METRICS["discount_rate"]["std"]
        std_void = MOCK_HISTORICAL_METRICS["void_order_rate"]["std"]

        disc_dev = (today["discount_rate"] - hist_discount) / std_discount
        void_dev = (today["void_order_rate"] - hist_void) / std_void

        if disc_dev >= 2.0:
            anomaly_summary_parts.append(f"折扣率偏高(×{today['discount_rate'] / hist_discount:.1f})")
        if void_dev >= 2.0:
            anomaly_summary_parts.append(f"废单率偏高(×{today['void_order_rate'] / hist_void:.1f})")

    anomaly_line = " | ".join(anomaly_summary_parts) if anomaly_summary_parts else "无异常"

    # 驱动因素
    dummy_comps: list[dict] = []
    if rev_change > 0:
        dummy_comps.append({"dimension": "yesterday", "change_rate": rev_change})
    key_drivers = _extract_key_drivers(today, dummy_comps)
    concerns = _extract_concerns(today)

    # Agent 建议
    agent_tips: list[str] = []
    if anomaly_summary_parts:
        if any("折扣" in p for p in anomaly_summary_parts):
            agent_tips.append("检查折扣操作")
        if any("废单" in p for p in anomaly_summary_parts):
            agent_tips.append("跟进废单原因")
    if not agent_tips:
        agent_tips.append("维持当前节奏")

    date_str = target_date.strftime("%Y-%m-%d")
    rev_pct = f"{rev_change:+.1%}"

    # 根据 template_id 选择格式
    template = req.template_id or "default"

    if template == "compact":
        full_narrative = (
            f"【{date_str}日报】\n"
            f"营业额 {_format_fen(int(revenue_fen))}（{rev_pct}）| "
            f"客流 {customer_count}人 | 客单 {_format_fen(avg_order)}\n"
            f"{'⚠️ ' + anomaly_line if anomaly_summary_parts else '✅ 运营正常'}"
        )
    elif template == "boss":
        quality = _change_label(rev_change)
        full_narrative = (
            f"📊 {date_str} {quality}：{_format_fen(int(revenue_fen))}（{rev_pct} vs昨日）\n"
            f"{'⚠️ 关注：' + '、'.join(concerns) if concerns else '✅ 无异常'}"
        )
    else:
        # default — 企微推送标准格式
        highlights = " / ".join(key_drivers) if key_drivers else "稳定经营"
        concerns_str = " / ".join(concerns) if concerns else "暂无"
        agent_str = " | ".join(agent_tips)

        full_narrative = (
            f"【屯象OS · 门店日报 · {date_str}】\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 今日营业：{_format_fen(int(revenue_fen))}（{rev_pct} vs昨日）\n"
            f"👥 客流：{customer_count}人 | 客单价：{_format_fen(avg_order)}\n"
        )
        if req.include_anomaly and anomaly_summary_parts:
            full_narrative += f"⚡ 异常：{anomaly_line}\n"
        else:
            full_narrative += "✅ 运营状态：正常\n"
        full_narrative += (
            f"━━━━━━━━━━━━━━━\n"
            f"✅ 亮点：{highlights}\n"
            f"⚠️ 关注：{concerns_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 Agent建议：{agent_str}"
        )

    log.info(
        "narrative.daily_report.ok",
        date=str(target_date),
        template=template,
        has_anomaly=bool(anomaly_summary_parts),
    )

    return {
        "ok": True,
        "data": {
            "date": target_date.isoformat(),
            "store_id": store_id or "all",
            "template_id": template,
            "revenue_fen": revenue_fen,
            "customer_count": customer_count,
            "avg_order_value_fen": avg_order,
            "revenue_vs_yesterday": round(rev_change, 4),
            "anomaly_summary": anomaly_summary_parts,
            "key_drivers": key_drivers,
            "concerns": concerns,
            "agent_tips": agent_tips,
            "full_narrative": full_narrative,
        },
        "error": None,
    }
