"""
规则引擎降级基类 — 当 CoreML 不可用时使用

折扣风险检测（规则版）：
- 折扣率 > 0.5 → high risk
- 折扣率 0.3-0.5 → medium risk
- 折扣率 < 0.3 → low risk
- 高峰期 + 折扣 > 0.4 → risk_score += 20
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_PEAK_HOURS = frozenset(range(11, 14)) | frozenset(range(17, 21))


# ─── 基类 ────────────────────────────────────────────────────────────────────


class RuleBasedPredictor:
    """规则推理基类 — 所有规则引擎继承此类"""

    @property
    def method(self) -> str:
        return "rule_fallback"

    def evaluate(self, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


# ─── 折扣风险检测（规则版） ──────────────────────────────────────────────────


@dataclass
class DiscountRiskInput:
    discount_rate: float       # 折扣率 0.0-1.0（0.0=无折扣, 1.0=全免）
    hour_of_day: int           # 当前小时 0-23
    order_amount_fen: int      # 订单金额（分）
    employee_id: str = ""      # 操作员 ID（用于异常检测）
    table_id: str = ""         # 桌台 ID


@dataclass
class DiscountRiskResult:
    risk_level: str            # "low" | "medium" | "high"
    risk_score: int            # 0-100
    method: str                # "rule_fallback"
    reasons: list[str]
    should_alert: bool


class RuleBasedDiscountRisk(RuleBasedPredictor):
    """折扣风险规则引擎

    三级风险判定：
    - high:   折扣率 > 0.5，或 risk_score >= 70
    - medium: 折扣率 0.3-0.5，或 risk_score 40-70
    - low:    折扣率 < 0.3 且 risk_score < 40
    """

    @property
    def method(self) -> str:
        return "rule_fallback"

    def evaluate(self, context: dict[str, Any]) -> dict[str, Any]:
        """通用字典接口（兼容基类）"""
        inp = DiscountRiskInput(
            discount_rate=float(context.get("discount_rate", 0.0)),
            hour_of_day=int(context.get("hour_of_day", 12)),
            order_amount_fen=int(context.get("order_amount_fen", 0)),
            employee_id=str(context.get("employee_id", "")),
            table_id=str(context.get("table_id", "")),
        )
        result = self.evaluate_discount(inp)
        return {
            "risk_level": result.risk_level,
            "risk_score": result.risk_score,
            "method": result.method,
            "reasons": result.reasons,
            "should_alert": result.should_alert,
        }

    def evaluate_discount(self, inp: DiscountRiskInput) -> DiscountRiskResult:
        """强类型入参版折扣风险评估"""
        risk_score = 0
        reasons: list[str] = []

        # 基础折扣率分档
        if inp.discount_rate > 0.5:
            risk_score += 60
            reasons.append(f"折扣率 {inp.discount_rate:.0%} 超过50%阈值")
        elif inp.discount_rate >= 0.3:
            risk_score += 35
            reasons.append(f"折扣率 {inp.discount_rate:.0%} 处于中等风险区间")
        elif inp.discount_rate > 0.0:
            risk_score += 10

        # 高峰期 + 折扣 > 0.4 → 额外风险
        if inp.hour_of_day in _PEAK_HOURS and inp.discount_rate > 0.4:
            risk_score += 20
            reasons.append(f"高峰时段（{inp.hour_of_day}时）叠加高折扣，异常概率上升")

        # 大金额订单折扣
        if inp.order_amount_fen >= 100_00 and inp.discount_rate >= 0.3:  # 100元以上
            risk_score += 10
            reasons.append(f"大额订单（{inp.order_amount_fen / 100:.0f}元）高折扣，需审批")

        risk_score = min(risk_score, 100)

        if risk_score >= 70 or inp.discount_rate > 0.5:
            risk_level = "high"
        elif risk_score >= 40 or inp.discount_rate >= 0.3:
            risk_level = "medium"
        else:
            risk_level = "low"

        should_alert = risk_level in ("high", "medium")

        log.info(
            "discount_risk_evaluated",
            discount_rate=inp.discount_rate,
            risk_level=risk_level,
            risk_score=risk_score,
            method="rule_fallback",
        )

        return DiscountRiskResult(
            risk_level=risk_level,
            risk_score=risk_score,
            method="rule_fallback",
            reasons=reasons,
            should_alert=should_alert,
        )


# ─── 客流量预测（规则版） ────────────────────────────────────────────────────


@dataclass
class TrafficPredictInput:
    hour_of_day: int           # 预测时段（0-23）
    day_of_week: int           # 星期几（0=周一, 6=周日）
    seats_total: int           # 门店总座位数
    weather_score: float = 1.0  # 天气系数（0.5=极端天气, 1.0=正常, 1.2=节假日）


@dataclass
class TrafficPredictResult:
    expected_covers: int       # 预计就餐人数
    turnover_rate: float       # 预计翻台率
    confidence: float          # 置信度
    method: str                # "rule_fallback"
    peak_label: str            # "lunch_peak" | "dinner_peak" | "off_peak"


_HOURLY_LOAD: dict[int, float] = {
    # 早市
    7: 0.15, 8: 0.20, 9: 0.10,
    # 午市
    11: 0.55, 12: 0.90, 13: 0.75, 14: 0.35,
    # 下午茶
    15: 0.15, 16: 0.10,
    # 晚市
    17: 0.50, 18: 0.85, 19: 0.95, 20: 0.80, 21: 0.45,
    22: 0.20,
}

_WEEKEND_BOOST = 1.25  # 周末客流提升系数


class RuleBasedTrafficPredict(RuleBasedPredictor):
    """客流量预测规则引擎

    基于时段负载系数 × 座位数 × 天气系数 × 周末加成
    """

    @property
    def method(self) -> str:
        return "rule_fallback"

    def evaluate(self, context: dict[str, Any]) -> dict[str, Any]:
        """通用字典接口（兼容基类）"""
        inp = TrafficPredictInput(
            hour_of_day=int(context.get("hour_of_day", 12)),
            day_of_week=int(context.get("day_of_week", 2)),
            seats_total=int(context.get("seats_total", 80)),
            weather_score=float(context.get("weather_score", 1.0)),
        )
        result = self.predict_traffic(inp)
        return {
            "expected_covers": result.expected_covers,
            "turnover_rate": result.turnover_rate,
            "confidence": result.confidence,
            "method": result.method,
            "peak_label": result.peak_label,
        }

    def predict_traffic(self, inp: TrafficPredictInput) -> TrafficPredictResult:
        """强类型入参版客流量预测"""
        load_factor = _HOURLY_LOAD.get(inp.hour_of_day, 0.05)

        # 周末加成
        if inp.day_of_week >= 5:  # 5=周六, 6=周日
            load_factor *= _WEEKEND_BOOST

        # 天气系数
        load_factor *= inp.weather_score

        # 预计就餐人数（按人均1.5个座位估算翻台）
        avg_party_size = 3.0
        expected_covers = int(inp.seats_total * load_factor * avg_party_size / avg_party_size)
        expected_covers = max(0, expected_covers)

        turnover_rate = round(load_factor * 2.5, 2)  # 高峰期翻台率约2.5

        if inp.hour_of_day in range(11, 14):
            peak_label = "lunch_peak"
        elif inp.hour_of_day in range(17, 22):
            peak_label = "dinner_peak"
        else:
            peak_label = "off_peak"

        # 规则引擎置信度：高峰期较稳定，非高峰期波动大
        confidence = 0.80 if peak_label != "off_peak" else 0.65

        return TrafficPredictResult(
            expected_covers=expected_covers,
            turnover_rate=turnover_rate,
            confidence=confidence,
            method="rule_fallback",
            peak_label=peak_label,
        )
