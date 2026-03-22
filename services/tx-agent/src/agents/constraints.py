"""三条硬约束校验 — 所有 Agent 决策必须通过

1. 毛利底线 — 折扣/赠送不可使单笔毛利低于阈值
2. 食安合规 — 临期/过期食材不可用于出品
3. 客户体验 — 出餐时间不可超过门店设定上限

无例外。违反任何一条，决策被拦截。
"""
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger()

# 默认阈值（可通过门店配置覆盖）
DEFAULT_MIN_MARGIN_RATE = 0.15       # 毛利率不低于 15%
DEFAULT_EXPIRY_BUFFER_HOURS = 24     # 食材距过期不少于 24 小时
DEFAULT_MAX_SERVE_MINUTES = 30       # 出餐不超过 30 分钟


@dataclass
class ConstraintResult:
    """约束校验结果"""
    passed: bool = True
    violations: list[str] = field(default_factory=list)
    margin_check: Optional[dict] = None
    food_safety_check: Optional[dict] = None
    experience_check: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violations": self.violations,
            "margin_check": self.margin_check,
            "food_safety_check": self.food_safety_check,
            "experience_check": self.experience_check,
        }


class ConstraintChecker:
    """三条硬约束校验器"""

    def __init__(
        self,
        min_margin_rate: float = DEFAULT_MIN_MARGIN_RATE,
        expiry_buffer_hours: int = DEFAULT_EXPIRY_BUFFER_HOURS,
        max_serve_minutes: int = DEFAULT_MAX_SERVE_MINUTES,
    ):
        self.min_margin_rate = min_margin_rate
        self.expiry_buffer_hours = expiry_buffer_hours
        self.max_serve_minutes = max_serve_minutes

    def check_all(self, decision_data: dict) -> ConstraintResult:
        """执行全部三条约束校验"""
        result = ConstraintResult()

        # 1. 毛利底线
        margin_result = self.check_margin(decision_data)
        result.margin_check = margin_result
        if margin_result and not margin_result.get("passed", True):
            result.passed = False
            result.violations.append(
                f"毛利底线违规: 毛利率 {margin_result.get('actual_rate', 0):.1%} "
                f"< 阈值 {self.min_margin_rate:.1%}"
            )

        # 2. 食安合规
        safety_result = self.check_food_safety(decision_data)
        result.food_safety_check = safety_result
        if safety_result and not safety_result.get("passed", True):
            result.passed = False
            result.violations.append(
                f"食安合规违规: {safety_result.get('reason', '临期/过期食材')}"
            )

        # 3. 客户体验
        experience_result = self.check_experience(decision_data)
        result.experience_check = experience_result
        if experience_result and not experience_result.get("passed", True):
            result.passed = False
            result.violations.append(
                f"客户体验违规: 预计出餐 {experience_result.get('actual_minutes', 0)} 分钟 "
                f"> 上限 {self.max_serve_minutes} 分钟"
            )

        return result

    def check_margin(self, data: dict) -> dict | None:
        """约束1: 毛利底线"""
        price_fen = data.get("price_fen") or data.get("final_amount_fen")
        cost_fen = data.get("cost_fen") or data.get("food_cost_fen")

        if price_fen is None or cost_fen is None:
            return None  # 无价格/成本数据，跳过

        if price_fen <= 0:
            return {"passed": False, "actual_rate": 0, "threshold": self.min_margin_rate}

        margin_rate = (price_fen - cost_fen) / price_fen
        passed = margin_rate >= self.min_margin_rate

        return {
            "passed": passed,
            "actual_rate": round(margin_rate, 4),
            "threshold": self.min_margin_rate,
            "price_fen": price_fen,
            "cost_fen": cost_fen,
        }

    def check_food_safety(self, data: dict) -> dict | None:
        """约束2: 食安合规 — 临期/过期食材不可用于出品"""
        ingredients = data.get("ingredients", [])
        if not ingredients:
            return None

        violations = []
        for ing in ingredients:
            remaining_hours = ing.get("remaining_hours")
            if remaining_hours is not None and remaining_hours < self.expiry_buffer_hours:
                violations.append({
                    "ingredient": ing.get("name", "unknown"),
                    "remaining_hours": remaining_hours,
                    "threshold_hours": self.expiry_buffer_hours,
                })

        if violations:
            return {"passed": False, "reason": "临期食材", "items": violations}
        return {"passed": True}

    def check_experience(self, data: dict) -> dict | None:
        """约束3: 客户体验 — 出餐时间不超过上限"""
        estimated_minutes = data.get("estimated_serve_minutes")
        if estimated_minutes is None:
            return None

        passed = estimated_minutes <= self.max_serve_minutes
        return {
            "passed": passed,
            "actual_minutes": estimated_minutes,
            "threshold_minutes": self.max_serve_minutes,
        }
