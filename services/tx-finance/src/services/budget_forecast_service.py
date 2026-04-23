"""Sprint D4c — 预算预测服务（Sonnet 4.7 + Prompt Cache）

设计原则（复用 D4a/D4b CachedPromptBuilder 模式）：
  · 第 1 段 STABLE_SYSTEM：预算预测输出 JSON schema（跨租户稳定，~1.5KB）
  · 第 2 段 PNL_BENCHMARKS：5 业态 P&L 行业 benchmark（~2KB），cacheable
  · 用户消息：历史 12 月 P&L 快照 + 预测窗口（每次独立）

多店/多品牌/多季度分析共享前两段 cache → 稳态命中率目标 ≥ 75%。

输出 schema：
  {
    "predicted_line_items": [
      {"line_item": "revenue|food_cost|labor_cost|rent|utility|other|net",
       "predicted_fen": int, "ratio_of_revenue": float,
       "confidence_low": int, "confidence_high": int}
    ],
    "variance_risks": [
      {"line_item", "risk_type": "cost_overrun|revenue_drop|margin_compression|compliance_breach",
       "severity": "critical|high|medium|low", "delta_fen": int,
       "evidence": "...", "legal_flag": bool}
    ],
    "preventive_actions": [
      {"action", "owner_role": "store_manager|chef|hr|cfo",
       "deadline_days": int, "expected_saving_fen": int}
    ],
    "analysis": "..."
  }

Service 层硬编码 model_id=claude-sonnet-4-7 覆盖 ModelRouter 默认值，
走 Anthropic Prompt Cache beta。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────

SONNET_CACHED_MODEL = "claude-sonnet-4-7"

# 法规/行业硬阈值（用于 fallback + 严重度判定）
LABOR_COST_RED_LINE_PCT = 0.30  # 人工占营收 30% 红线（正餐）
FOOD_COST_RED_LINE_PCT = 0.45  # 食材占营收 45% 红线（正餐）
NEGATIVE_MARGIN_THRESHOLD_PCT = 0.0  # 净利率 < 0 即 critical
MARGIN_COMPRESSION_THRESHOLD_PCT = 0.03  # 净利率环比下跌 >3pp 即预警
COST_OVERRUN_THRESHOLD_PCT = 0.10  # 单项成本环比涨幅 >10% 即预警

ALLOWED_BUSINESS_TYPES = {
    "full_service",
    "quick_service",
    "tea_beverage",
    "buffet",
    "hot_pot",
}
ALLOWED_SCOPES = {
    "monthly_brand",
    "monthly_store",
    "quarterly_brand",
    "adhoc",
}
LINE_ITEMS = ("revenue", "food_cost", "labor_cost", "rent", "utility", "other", "net")


# ─────────────────────────────────────────────────────────────
# 数据类
# ─────────────────────────────────────────────────────────────


@dataclass
class MonthlyPnL:
    """单月 P&L 快照（单位：分）"""

    month: date  # YYYY-MM-01
    revenue_fen: int
    food_cost_fen: int
    labor_cost_fen: int
    rent_fen: int
    utility_fen: int
    other_fen: int

    @property
    def total_cost_fen(self) -> int:
        return (
            self.food_cost_fen
            + self.labor_cost_fen
            + self.rent_fen
            + self.utility_fen
            + self.other_fen
        )

    @property
    def net_fen(self) -> int:
        return self.revenue_fen - self.total_cost_fen

    @property
    def margin_pct(self) -> float:
        if self.revenue_fen <= 0:
            return 0.0
        return round(self.net_fen / self.revenue_fen, 4)

    def to_dict(self) -> dict:
        return {
            "month": self.month.isoformat(),
            "revenue_fen": self.revenue_fen,
            "food_cost_fen": self.food_cost_fen,
            "labor_cost_fen": self.labor_cost_fen,
            "rent_fen": self.rent_fen,
            "utility_fen": self.utility_fen,
            "other_fen": self.other_fen,
            "net_fen": self.net_fen,
            "margin_pct": self.margin_pct,
        }


@dataclass
class BudgetSignalBundle:
    """预测入参：租户 + 预测窗口 + 历史 P&L"""

    tenant_id: str
    forecast_month: date  # 预测期首日 YYYY-MM-01
    forecast_scope: str  # monthly_brand|monthly_store|quarterly_brand|adhoc
    business_type: str  # full_service|quick_service|tea_beverage|buffet|hot_pot
    history: list[MonthlyPnL]
    brand_id: Optional[str] = None
    store_id: Optional[str] = None
    brand_name: Optional[str] = None
    store_name: Optional[str] = None

    def __post_init__(self) -> None:
        if self.forecast_scope not in ALLOWED_SCOPES:
            raise ValueError(f"forecast_scope 非法：{self.forecast_scope!r}")
        if self.business_type not in ALLOWED_BUSINESS_TYPES:
            raise ValueError(f"business_type 非法：{self.business_type!r}")
        if not self.history:
            raise ValueError("history 至少需要 1 个月数据")

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "brand_id": self.brand_id,
            "store_id": self.store_id,
            "brand_name": self.brand_name,
            "store_name": self.store_name,
            "forecast_month": self.forecast_month.isoformat(),
            "forecast_scope": self.forecast_scope,
            "business_type": self.business_type,
            "history": [m.to_dict() for m in self.history],
            "history_months": len(self.history),
        }


@dataclass
class PredictedLineItem:
    line_item: str
    predicted_fen: int
    ratio_of_revenue: float
    confidence_low: int
    confidence_high: int

    def to_dict(self) -> dict:
        return {
            "line_item": self.line_item,
            "predicted_fen": self.predicted_fen,
            "ratio_of_revenue": self.ratio_of_revenue,
            "confidence_low": self.confidence_low,
            "confidence_high": self.confidence_high,
        }


@dataclass
class VarianceRisk:
    line_item: str
    risk_type: str  # cost_overrun|revenue_drop|margin_compression|compliance_breach
    severity: str  # critical|high|medium|low
    delta_fen: int
    evidence: str
    legal_flag: bool = False

    def to_dict(self) -> dict:
        return {
            "line_item": self.line_item,
            "risk_type": self.risk_type,
            "severity": self.severity,
            "delta_fen": self.delta_fen,
            "evidence": self.evidence,
            "legal_flag": self.legal_flag,
        }


@dataclass
class PreventiveAction:
    action: str
    owner_role: str  # store_manager|chef|hr|cfo
    deadline_days: int
    expected_saving_fen: int

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "owner_role": self.owner_role,
            "deadline_days": self.deadline_days,
            "expected_saving_fen": self.expected_saving_fen,
        }


@dataclass
class BudgetForecastResult:
    predicted_line_items: list[PredictedLineItem] = field(default_factory=list)
    variance_risks: list[VarianceRisk] = field(default_factory=list)
    preventive_actions: list[PreventiveAction] = field(default_factory=list)
    sonnet_analysis: str = ""
    model_id: str = SONNET_CACHED_MODEL
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def has_critical(self) -> bool:
        return any(r.severity == "critical" for r in self.variance_risks)

    @property
    def has_legal_flag(self) -> bool:
        return any(r.legal_flag for r in self.variance_risks)

    @property
    def cache_hit_rate(self) -> float:
        total = (
            self.cache_read_tokens
            + self.cache_creation_tokens
            + self.input_tokens
        )
        if total <= 0:
            return 0.0
        return round(self.cache_read_tokens / total, 4)

    @property
    def predicted_revenue_fen(self) -> int:
        for li in self.predicted_line_items:
            if li.line_item == "revenue":
                return li.predicted_fen
        return 0

    @property
    def predicted_net_fen(self) -> int:
        for li in self.predicted_line_items:
            if li.line_item == "net":
                return li.predicted_fen
        return 0

    @property
    def predicted_margin_pct(self) -> float:
        rev = self.predicted_revenue_fen
        if rev <= 0:
            return 0.0
        return round(self.predicted_net_fen / rev, 4)


# ─────────────────────────────────────────────────────────────
# CachedPromptBuilder — 共享 P&L 行业 benchmark
# ─────────────────────────────────────────────────────────────


class CachedPromptBuilder:
    """2 段 cacheable system + 1 段动态 user。

    · STABLE_SYSTEM：输出 JSON schema（跨租户稳定）
    · PNL_BENCHMARKS：5 业态 P&L 行业 benchmark（跨分析共享）
    · user：历史 P&L + 预测窗口（每次独立）
    """

    STABLE_SYSTEM = """你是屯象OS 预算预测 Agent，任务是基于历史 P&L 数据和行业 benchmark 预测下期成本结构，
并标注可能的 variance 风险。

输出严格 JSON：
{
  "predicted_line_items": [
    {"line_item": "revenue|food_cost|labor_cost|rent|utility|other|net",
     "predicted_fen": 整数（单位：分），
     "ratio_of_revenue": 0.00~1.00,
     "confidence_low": 整数（80% 置信区间下沿）,
     "confidence_high": 整数（80% 置信区间上沿）}
  ],
  "variance_risks": [
    {"line_item": "...",
     "risk_type": "cost_overrun|revenue_drop|margin_compression|compliance_breach",
     "severity": "critical|high|medium|low",
     "delta_fen": 整数（预测值 - 历史 12 月中位数）,
     "evidence": "简短因果链（≤80字）",
     "legal_flag": true|false}
  ],
  "preventive_actions": [
    {"action": "可执行建议",
     "owner_role": "store_manager|chef|hr|cfo",
     "deadline_days": 1~90,
     "expected_saving_fen": 整数}
  ],
  "analysis": "≤300字总结，先说结论再说理由"
}

规则：
· predicted_line_items 必须覆盖全部 7 项（revenue/food_cost/labor_cost/rent/utility/other/net）
· confidence_low ≤ predicted_fen ≤ confidence_high
· net 必须等于 revenue 减其他 5 项成本
· variance_risks 按 severity 和 delta_fen 绝对值降序排列
· 法规红线（人工占比 >30%、食材占比 >45%）自动 legal_flag=true
· 不使用 markdown 代码块，直接输出 JSON
"""

    # 5 业态 P&L 行业 benchmark（2025 版，来源：中国烹饪协会 + 行业研究报告）
    PNL_BENCHMARKS = """【P&L 行业基准表 — 2025 版】

## 正餐（full_service）
· 目标食材占比：35~42%（红线 45%）
· 目标人工占比：22~28%（红线 30%）
· 目标租金占比：8~12%（超 15% 即高成本区位）
· 目标能耗占比：2~4%
· 目标其他：4~6%（营销/耗材/维修）
· 目标净利率：15~22%
· 典型单店月营收：60~200 万元

## 快餐（quick_service）
· 目标食材占比：28~35%
· 目标人工占比：18~24%
· 目标租金占比：10~15%
· 目标能耗占比：3~5%
· 目标其他：5~7%
· 目标净利率：18~25%
· 典型单店月营收：30~80 万元

## 茶饮（tea_beverage）
· 目标食材占比：25~32%
· 目标人工占比：15~22%
· 目标租金占比：12~18%（多位于高流量商圈）
· 目标能耗占比：2~4%
· 目标其他：6~10%（杯具/营销占比高）
· 目标净利率：20~28%
· 典型单店月营收：15~40 万元

## 自助（buffet）
· 目标食材占比：40~48%（最接近红线，依赖客单量）
· 目标人工占比：18~24%
· 目标租金占比：8~12%
· 目标能耗占比：3~5%
· 目标其他：4~6%
· 目标净利率：12~18%
· 典型单店月营收：80~250 万元

## 火锅（hot_pot）
· 目标食材占比：38~45%
· 目标人工占比：20~26%
· 目标租金占比：8~12%
· 目标能耗占比：4~6%（电磁炉/排风）
· 目标其他：4~6%
· 目标净利率：15~22%
· 典型单店月营收：70~220 万元

【季节性调整系数】
· 春节月（农历 1 月）：营收 +30~50%，人工 +15%
· 夏季 7-8 月：茶饮 +40%，火锅 -20%
· 冬季 12-2 月：火锅 +30%，茶饮 -15%
· 雨季（华南 4-6 月、华东 6-7 月）：堂食 -10%

【合规红线】
· 人工成本占营收 > 30%（正餐/火锅）→ legal_flag=true（劳动合规风险）
· 食材成本占营收 > 45%（正餐/火锅/自助）→ legal_flag=true（可能亏损常态化）
· 净利率 < 0 → severity=critical + risk_type=margin_compression
· 单项成本环比涨幅 > 15% 且无季节性解释 → severity=high + risk_type=cost_overrun
"""

    @classmethod
    def build_messages(cls, bundle: BudgetSignalBundle) -> dict[str, Any]:
        """返回 Anthropic messages API 入参（含 cache_control）"""
        user_content = json.dumps(
            {
                "forecast_window": {
                    "forecast_month": bundle.forecast_month.isoformat(),
                    "forecast_scope": bundle.forecast_scope,
                    "business_type": bundle.business_type,
                    "brand_id": bundle.brand_id,
                    "store_id": bundle.store_id,
                    "brand_name": bundle.brand_name,
                    "store_name": bundle.store_name,
                },
                "history": [m.to_dict() for m in bundle.history],
            },
            ensure_ascii=False,
            indent=2,
        )

        return {
            "model": SONNET_CACHED_MODEL,
            "max_tokens": 2048,
            "system": [
                {
                    "type": "text",
                    "text": cls.STABLE_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": cls.PNL_BENCHMARKS,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            "messages": [
                {
                    "role": "user",
                    "content": f"请预测下列窗口的 P&L 结构：\n{user_content}",
                }
            ],
        }


# ─────────────────────────────────────────────────────────────
# 解析 Sonnet 输出
# ─────────────────────────────────────────────────────────────


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def parse_sonnet_response(raw: str) -> dict:
    """容错解析：剥离 code fence / 直接 json"""
    if not raw or not raw.strip():
        return {}
    stripped = raw.strip()
    m = _CODE_FENCE_RE.match(stripped)
    if m:
        stripped = m.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        logger.warning("budget_forecast_parse_failed", extra={"raw_preview": raw[:200]})
        return {}


# ─────────────────────────────────────────────────────────────
# Fallback 规则引擎（Sonnet 不可用时的兜底）
# ─────────────────────────────────────────────────────────────


def _median(values: list[int]) -> int:
    if not values:
        return 0
    sorted_v = sorted(values)
    n = len(sorted_v)
    mid = n // 2
    if n % 2 == 1:
        return sorted_v[mid]
    return (sorted_v[mid - 1] + sorted_v[mid]) // 2


def _recent_trend(values: list[int], window: int = 3) -> float:
    """近 `window` 月 vs 前 `window` 月的比值（>1 表示上升）"""
    if len(values) < 2 * window:
        return 1.0
    recent = sum(values[-window:])
    previous = sum(values[-2 * window : -window])
    if previous <= 0:
        return 1.0
    return recent / previous


def fallback_forecast(bundle: BudgetSignalBundle) -> BudgetForecastResult:
    """基于历史中位数 + 近期趋势做保守预测，标注超阈值风险"""
    history = bundle.history
    result = BudgetForecastResult(model_id="rule_engine_fallback")

    if not history:
        return result

    # 聚合历史指标
    revenues = [m.revenue_fen for m in history]
    food_costs = [m.food_cost_fen for m in history]
    labor_costs = [m.labor_cost_fen for m in history]
    rents = [m.rent_fen for m in history]
    utilities = [m.utility_fen for m in history]
    others = [m.other_fen for m in history]

    # 预测 = 中位数 × 趋势系数（限幅 0.8~1.2）
    def _predict(values: list[int]) -> tuple[int, int, int]:
        med = _median(values)
        trend = max(0.8, min(1.2, _recent_trend(values)))
        predicted = int(med * trend)
        low = int(predicted * 0.9)
        high = int(predicted * 1.15)
        return predicted, low, high

    rev_pred, rev_low, rev_high = _predict(revenues)
    food_pred, food_low, food_high = _predict(food_costs)
    labor_pred, labor_low, labor_high = _predict(labor_costs)
    rent_pred, rent_low, rent_high = _predict(rents)
    util_pred, util_low, util_high = _predict(utilities)
    other_pred, other_low, other_high = _predict(others)
    net_pred = rev_pred - food_pred - labor_pred - rent_pred - util_pred - other_pred
    net_low = rev_low - food_high - labor_high - rent_high - util_high - other_high
    net_high = rev_high - food_low - labor_low - rent_low - util_low - other_low

    def _ratio(n: int) -> float:
        if rev_pred <= 0:
            return 0.0
        return round(n / rev_pred, 4)

    result.predicted_line_items = [
        PredictedLineItem("revenue", rev_pred, 1.0, rev_low, rev_high),
        PredictedLineItem("food_cost", food_pred, _ratio(food_pred), food_low, food_high),
        PredictedLineItem("labor_cost", labor_pred, _ratio(labor_pred), labor_low, labor_high),
        PredictedLineItem("rent", rent_pred, _ratio(rent_pred), rent_low, rent_high),
        PredictedLineItem("utility", util_pred, _ratio(util_pred), util_low, util_high),
        PredictedLineItem("other", other_pred, _ratio(other_pred), other_low, other_high),
        PredictedLineItem("net", net_pred, _ratio(net_pred), net_low, net_high),
    ]

    # 风险检查
    risks: list[VarianceRisk] = []
    actions: list[PreventiveAction] = []

    food_ratio = _ratio(food_pred)
    labor_ratio = _ratio(labor_pred)
    margin = _ratio(net_pred)

    # 负利润（最严重）
    if net_pred < 0:
        risks.append(
            VarianceRisk(
                line_item="net",
                risk_type="margin_compression",
                severity="critical",
                delta_fen=net_pred - _median([m.net_fen for m in history]),
                evidence=f"预测净利为负（{net_pred}分），历史中位数 {_median([m.net_fen for m in history])}分",
                legal_flag=False,
            )
        )
        actions.append(
            PreventiveAction(
                action="CFO 牵头紧急成本复盘：冻结非必要开支 + 评估关店止损",
                owner_role="cfo",
                deadline_days=7,
                expected_saving_fen=abs(net_pred),
            )
        )

    # 人工红线（合规风险）
    if labor_ratio > LABOR_COST_RED_LINE_PCT:
        severity = "critical" if labor_ratio > 0.35 else "high"
        risks.append(
            VarianceRisk(
                line_item="labor_cost",
                risk_type="compliance_breach",
                severity=severity,
                delta_fen=labor_pred - _median(labor_costs),
                evidence=f"人工占营收 {labor_ratio*100:.1f}%，超法规红线 30%",
                legal_flag=True,
            )
        )
        actions.append(
            PreventiveAction(
                action="HR 复核排班：削减高峰外冗余班次 + 取消新增岗位",
                owner_role="hr",
                deadline_days=14,
                expected_saving_fen=int(labor_pred - rev_pred * LABOR_COST_RED_LINE_PCT),
            )
        )

    # 食材红线（亏损前兆）
    if food_ratio > FOOD_COST_RED_LINE_PCT:
        severity = "critical" if food_ratio > 0.50 else "high"
        risks.append(
            VarianceRisk(
                line_item="food_cost",
                risk_type="cost_overrun",
                severity=severity,
                delta_fen=food_pred - _median(food_costs),
                evidence=f"食材占营收 {food_ratio*100:.1f}%，超行业红线 45%",
                legal_flag=True,
            )
        )
        actions.append(
            PreventiveAction(
                action="供应链部门重议合同 + 行政总厨优化菜单",
                owner_role="chef",
                deadline_days=21,
                expected_saving_fen=int(food_pred - rev_pred * FOOD_COST_RED_LINE_PCT),
            )
        )

    # 毛利压缩
    hist_margins = [m.margin_pct for m in history]
    if hist_margins:
        hist_median = sorted(hist_margins)[len(hist_margins) // 2]
        if margin < hist_median - MARGIN_COMPRESSION_THRESHOLD_PCT:
            risks.append(
                VarianceRisk(
                    line_item="net",
                    risk_type="margin_compression",
                    severity="medium" if margin >= 0 else "critical",
                    delta_fen=net_pred - _median([m.net_fen for m in history]),
                    evidence=f"预测净利率 {margin*100:.1f}% 比历史中位数 {hist_median*100:.1f}% 低 {(hist_median-margin)*100:.1f}pp",
                    legal_flag=False,
                )
            )

    # 单项成本突增
    for item, current, series in [
        ("food_cost", food_pred, food_costs),
        ("labor_cost", labor_pred, labor_costs),
        ("utility", util_pred, utilities),
    ]:
        med = _median(series)
        if med > 0 and (current - med) / med > COST_OVERRUN_THRESHOLD_PCT:
            risks.append(
                VarianceRisk(
                    line_item=item,
                    risk_type="cost_overrun",
                    severity="medium",
                    delta_fen=current - med,
                    evidence=f"{item} 环比涨幅 {((current-med)/med)*100:.1f}%，超 {COST_OVERRUN_THRESHOLD_PCT*100:.0f}% 阈值",
                    legal_flag=False,
                )
            )

    # 风险排序：legal_flag desc → severity desc → delta_fen 绝对值 desc
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    risks.sort(
        key=lambda r: (
            not r.legal_flag,
            severity_order.get(r.severity, 4),
            -abs(r.delta_fen),
        )
    )

    result.variance_risks = risks
    result.preventive_actions = actions
    result.sonnet_analysis = (
        f"[规则引擎] 基于 {len(history)} 个月历史中位数 × 近期趋势系数预测。"
        f"预测营收 {rev_pred/100:.0f}元，净利 {net_pred/100:.0f}元（{margin*100:.1f}%）。"
        f"共识别 {len(risks)} 个 variance 风险。"
    )

    return result


# ─────────────────────────────────────────────────────────────
# 服务入口
# ─────────────────────────────────────────────────────────────

# invoker 协议：async (request: dict) → response: dict
InvokerType = Callable[[dict], Awaitable[dict]]


class BudgetForecastService:
    """预算预测主服务

    用法：
        svc = BudgetForecastService(invoker=my_anthropic_client)
        result = await svc.forecast(bundle)

    invoker 不传 → 规则引擎 fallback（开发 / 容灾）。
    """

    def __init__(self, invoker: Optional[InvokerType] = None) -> None:
        self._invoker = invoker

    async def forecast(self, bundle: BudgetSignalBundle) -> BudgetForecastResult:
        if self._invoker is None:
            logger.info("budget_forecast_fallback_rule_engine", extra={
                "forecast_month": bundle.forecast_month.isoformat(),
                "business_type": bundle.business_type,
            })
            return fallback_forecast(bundle)

        request = CachedPromptBuilder.build_messages(bundle)
        try:
            response = await self._invoker(request)
        except Exception as exc:  # Anthropic 客户端具体异常由上层捕获
            logger.exception("budget_forecast_invoker_failed")
            result = fallback_forecast(bundle)
            result.sonnet_analysis = f"[Sonnet 调用失败，降级规则引擎] {exc}"
            return result

        return self._parse_response(response, fallback_bundle=bundle)

    def _parse_response(
        self, response: dict, fallback_bundle: BudgetSignalBundle
    ) -> BudgetForecastResult:
        """从 Anthropic 响应中提取 JSON + usage"""
        result = BudgetForecastResult(model_id=SONNET_CACHED_MODEL)

        # usage
        usage = response.get("usage", {}) or {}
        result.cache_read_tokens = int(usage.get("cache_read_input_tokens", 0) or 0)
        result.cache_creation_tokens = int(
            usage.get("cache_creation_input_tokens", 0) or 0
        )
        result.input_tokens = int(usage.get("input_tokens", 0) or 0)
        result.output_tokens = int(usage.get("output_tokens", 0) or 0)

        # content blocks
        content = response.get("content", []) or []
        raw_text = ""
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    raw_text += block.get("text", "")
        elif isinstance(content, str):
            raw_text = content

        parsed = parse_sonnet_response(raw_text)
        if not parsed:
            logger.warning("budget_forecast_empty_parsed_response")
            fb = fallback_forecast(fallback_bundle)
            fb.cache_read_tokens = result.cache_read_tokens
            fb.cache_creation_tokens = result.cache_creation_tokens
            fb.input_tokens = result.input_tokens
            fb.output_tokens = result.output_tokens
            fb.sonnet_analysis = "[Sonnet 输出无法解析，降级规则引擎]"
            return fb

        # predicted_line_items
        for li in parsed.get("predicted_line_items", []) or []:
            try:
                result.predicted_line_items.append(
                    PredictedLineItem(
                        line_item=str(li.get("line_item", "")),
                        predicted_fen=int(li.get("predicted_fen", 0) or 0),
                        ratio_of_revenue=float(li.get("ratio_of_revenue", 0) or 0),
                        confidence_low=int(li.get("confidence_low", 0) or 0),
                        confidence_high=int(li.get("confidence_high", 0) or 0),
                    )
                )
            except (TypeError, ValueError):
                continue

        # variance_risks
        for r in parsed.get("variance_risks", []) or []:
            try:
                result.variance_risks.append(
                    VarianceRisk(
                        line_item=str(r.get("line_item", "")),
                        risk_type=str(r.get("risk_type", "cost_overrun")),
                        severity=str(r.get("severity", "medium")),
                        delta_fen=int(r.get("delta_fen", 0) or 0),
                        evidence=str(r.get("evidence", "")),
                        legal_flag=bool(r.get("legal_flag", False)),
                    )
                )
            except (TypeError, ValueError):
                continue

        # preventive_actions
        for a in parsed.get("preventive_actions", []) or []:
            try:
                result.preventive_actions.append(
                    PreventiveAction(
                        action=str(a.get("action", "")),
                        owner_role=str(a.get("owner_role", "cfo")),
                        deadline_days=int(a.get("deadline_days", 14) or 14),
                        expected_saving_fen=int(a.get("expected_saving_fen", 0) or 0),
                    )
                )
            except (TypeError, ValueError):
                continue

        result.sonnet_analysis = str(parsed.get("analysis", ""))

        # 一致性校验：如 Sonnet 没返回 7 项 line_item，补规则引擎
        predicted_items = {li.line_item for li in result.predicted_line_items}
        if not set(LINE_ITEMS).issubset(predicted_items):
            logger.warning("budget_forecast_incomplete_line_items", extra={
                "missing": list(set(LINE_ITEMS) - predicted_items),
            })
            fb = fallback_forecast(fallback_bundle)
            result.predicted_line_items = fb.predicted_line_items
            result.sonnet_analysis += "\n[行数不全，line_items 使用规则引擎补齐]"

        return result


# ─────────────────────────────────────────────────────────────
# DB 持久化
# ─────────────────────────────────────────────────────────────


async def save_forecast_to_db(
    db: AsyncSession,
    *,
    tenant_id: str,
    signal_bundle: BudgetSignalBundle,
    result: BudgetForecastResult,
) -> str:
    """写入 budget_forecast_analyses，返回 analysis_id。

    critical 或 legal_flag → 自动升级 status='escalated'；否则 'analyzed'。
    """
    status = "escalated" if (result.has_critical or result.has_legal_flag) else "analyzed"

    payload = {
        "tenant_id": tenant_id,
        "brand_id": signal_bundle.brand_id,
        "store_id": signal_bundle.store_id,
        "forecast_month": signal_bundle.forecast_month,
        "forecast_scope": signal_bundle.forecast_scope,
        "history_months": len(signal_bundle.history),
        "business_type": signal_bundle.business_type,
        "history_snapshot": json.dumps(
            {
                "history": [m.to_dict() for m in signal_bundle.history],
                "brand_name": signal_bundle.brand_name,
                "store_name": signal_bundle.store_name,
            },
            ensure_ascii=False,
        ),
        "predicted_line_items": json.dumps(
            [li.to_dict() for li in result.predicted_line_items], ensure_ascii=False
        ),
        "variance_risks": json.dumps(
            [r.to_dict() for r in result.variance_risks], ensure_ascii=False
        ),
        "preventive_actions": json.dumps(
            [a.to_dict() for a in result.preventive_actions], ensure_ascii=False
        ),
        "sonnet_analysis": result.sonnet_analysis,
        "predicted_revenue_fen": max(0, result.predicted_revenue_fen),
        "predicted_net_fen": result.predicted_net_fen,
        "predicted_margin_pct": result.predicted_margin_pct,
        "model_id": result.model_id,
        "cache_read_tokens": result.cache_read_tokens,
        "cache_creation_tokens": result.cache_creation_tokens,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "status": status,
    }

    row = await db.execute(
        text("""
            INSERT INTO budget_forecast_analyses (
                tenant_id, brand_id, store_id, forecast_month, forecast_scope,
                history_months, business_type, history_snapshot,
                predicted_line_items, variance_risks, preventive_actions,
                sonnet_analysis, predicted_revenue_fen, predicted_net_fen,
                predicted_margin_pct, model_id, cache_read_tokens,
                cache_creation_tokens, input_tokens, output_tokens, status
            ) VALUES (
                CAST(:tenant_id AS uuid),
                CAST(:brand_id AS uuid),
                CAST(:store_id AS uuid),
                :forecast_month, :forecast_scope, :history_months, :business_type,
                CAST(:history_snapshot AS jsonb),
                CAST(:predicted_line_items AS jsonb),
                CAST(:variance_risks AS jsonb),
                CAST(:preventive_actions AS jsonb),
                :sonnet_analysis, :predicted_revenue_fen, :predicted_net_fen,
                :predicted_margin_pct, :model_id, :cache_read_tokens,
                :cache_creation_tokens, :input_tokens, :output_tokens, :status
            )
            ON CONFLICT (
                tenant_id,
                COALESCE(brand_id, '00000000-0000-0000-0000-000000000000'::uuid),
                COALESCE(store_id, '00000000-0000-0000-0000-000000000000'::uuid),
                forecast_month,
                forecast_scope
            ) WHERE is_deleted = false
            DO UPDATE SET
                history_snapshot = EXCLUDED.history_snapshot,
                predicted_line_items = EXCLUDED.predicted_line_items,
                variance_risks = EXCLUDED.variance_risks,
                preventive_actions = EXCLUDED.preventive_actions,
                sonnet_analysis = EXCLUDED.sonnet_analysis,
                predicted_revenue_fen = EXCLUDED.predicted_revenue_fen,
                predicted_net_fen = EXCLUDED.predicted_net_fen,
                predicted_margin_pct = EXCLUDED.predicted_margin_pct,
                cache_read_tokens = EXCLUDED.cache_read_tokens,
                cache_creation_tokens = EXCLUDED.cache_creation_tokens,
                input_tokens = EXCLUDED.input_tokens,
                output_tokens = EXCLUDED.output_tokens,
                status = EXCLUDED.status,
                updated_at = NOW()
            RETURNING id
        """),
        payload,
    )
    analysis_id = row.scalar_one()
    await db.commit()
    return str(analysis_id)
