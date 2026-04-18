"""三条硬约束校验 — 所有 Agent 决策必须通过

1. 毛利底线 — 折扣/赠送不可使单笔毛利低于阈值
2. 食安合规 — 临期/过期食材不可用于出品
3. 客户体验 — 出餐时间不可超过门店设定上限

无例外。违反任何一条，决策被拦截。

Sprint D1 / PR G 扩展：
  - `check_all(ctx_or_data, scope=...)` 双入参接口：
      ctx_or_data=ConstraintContext → 走结构化校验
      ctx_or_data=dict              → 从 data 组装 context 后走同一路径（迁移兼容）
  - `scope` 参数控制仅校验 {margin, safety, experience} 子集；None 时校验全部
  - 结果附带 `scope` 字段（"margin" / "safety" / "experience" / "n/a" / "waived"），
    下游可按 scope 维度做 Grafana 覆盖率统计
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

import structlog

from .context import ConstraintContext

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
    # Sprint D1 新增：覆盖率统计字段
    scopes_checked: list[str] = field(default_factory=list)
    scopes_skipped: list[str] = field(default_factory=list)
    scope: str = "unknown"  # "margin" | "safety" | "experience" | "mixed" | "n/a" | "waived"

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violations": self.violations,
            "margin_check": self.margin_check,
            "food_safety_check": self.food_safety_check,
            "experience_check": self.experience_check,
            "scopes_checked": self.scopes_checked,
            "scopes_skipped": self.scopes_skipped,
            "scope": self.scope,
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

    def check_all(
        self,
        ctx_or_data: Union[ConstraintContext, dict],
        scope: Optional[set[str]] = None,
    ) -> ConstraintResult:
        """执行三条约束校验（支持结构化 context + scope 过滤）。

        Args:
            ctx_or_data: ConstraintContext 实例（推荐）或旧版 data 字典（迁移兼容）
            scope:       需要校验的约束子集 {'margin','safety','experience'}；
                         None 或未指定 → 校验全部；空 set → 跳过所有（视为豁免）

        Returns:
            ConstraintResult，附带 scopes_checked / scopes_skipped 字段供 Grafana 统计
        """
        if isinstance(ctx_or_data, dict):
            ctx = ConstraintContext.from_data(ctx_or_data)
        elif isinstance(ctx_or_data, ConstraintContext):
            ctx = ctx_or_data
        else:
            raise TypeError(
                f"check_all 只接受 ConstraintContext 或 dict，收到 {type(ctx_or_data).__name__}"
            )

        # scope 默认取 ctx.constraint_scope；显式 scope 参数优先（便于 base.py 强制覆盖）
        effective_scope: set[str] = scope if scope is not None else set(ctx.constraint_scope)

        result = ConstraintResult()
        result.scopes_checked = []
        result.scopes_skipped = []

        # 1. 毛利底线
        if "margin" in effective_scope:
            margin_result = self._check_margin(ctx)
            result.margin_check = margin_result
            if margin_result is None:
                result.scopes_skipped.append("margin")
            else:
                result.scopes_checked.append("margin")
                if not margin_result.get("passed", True):
                    result.passed = False
                    result.violations.append(
                        f"毛利底线违规: 毛利率 {margin_result.get('actual_rate', 0):.1%} "
                        f"< 阈值 {self.min_margin_rate:.1%}"
                    )

        # 2. 食安合规
        if "safety" in effective_scope:
            safety_result = self._check_food_safety(ctx)
            result.food_safety_check = safety_result
            if safety_result is None:
                result.scopes_skipped.append("safety")
            else:
                result.scopes_checked.append("safety")
                if not safety_result.get("passed", True):
                    result.passed = False
                    result.violations.append(
                        f"食安合规违规: {safety_result.get('reason', '临期/过期食材')}"
                    )

        # 3. 客户体验
        if "experience" in effective_scope:
            experience_result = self._check_experience(ctx)
            result.experience_check = experience_result
            if experience_result is None:
                result.scopes_skipped.append("experience")
            else:
                result.scopes_checked.append("experience")
                if not experience_result.get("passed", True):
                    result.passed = False
                    result.violations.append(
                        f"客户体验违规: 预计出餐 {experience_result.get('actual_minutes', 0)} 分钟 "
                        f"> 上限 {self.max_serve_minutes} 分钟"
                    )

        return result

    # ──────────────────────────────────────────────────────────────────
    # 新的结构化实现（私有，对外仅保留 check_all）
    # 保留原 check_margin/check_food_safety/check_experience 为旧版 dict API 兼容入口
    # ──────────────────────────────────────────────────────────────────

    def _check_margin(self, ctx: ConstraintContext) -> dict | None:
        if ctx.price_fen is None or ctx.cost_fen is None:
            return None
        if ctx.price_fen <= 0:
            return {"passed": False, "actual_rate": 0, "threshold": self.min_margin_rate}

        margin_rate = (ctx.price_fen - ctx.cost_fen) / ctx.price_fen
        return {
            "passed": margin_rate >= self.min_margin_rate,
            "actual_rate": round(margin_rate, 4),
            "threshold": self.min_margin_rate,
            "price_fen": ctx.price_fen,
            "cost_fen": ctx.cost_fen,
        }

    def _check_food_safety(self, ctx: ConstraintContext) -> dict | None:
        if not ctx.ingredients:
            return None

        violations: list[dict] = []
        for ing in ctx.ingredients:
            if ing.remaining_hours is None:
                continue
            if ing.remaining_hours < self.expiry_buffer_hours:
                violations.append({
                    "ingredient": ing.name,
                    "remaining_hours": ing.remaining_hours,
                    "threshold_hours": self.expiry_buffer_hours,
                })

        if violations:
            return {"passed": False, "reason": "临期食材", "items": violations}
        return {"passed": True}

    def _check_experience(self, ctx: ConstraintContext) -> dict | None:
        if ctx.estimated_serve_minutes is None:
            return None
        return {
            "passed": ctx.estimated_serve_minutes <= self.max_serve_minutes,
            "actual_minutes": ctx.estimated_serve_minutes,
            "threshold_minutes": self.max_serve_minutes,
        }

    # ── 旧 dict API（仅为向后兼容保留） ───────────────────────────────
    def check_margin(self, data: dict) -> dict | None:
        """@deprecated: 改用 check_all(ctx) 或 _check_margin(ctx)"""
        return self._check_margin(ConstraintContext.from_data(data))

    def check_food_safety(self, data: dict) -> dict | None:
        """@deprecated: 改用 check_all(ctx) 或 _check_food_safety(ctx)"""
        return self._check_food_safety(ConstraintContext.from_data(data))

    def check_experience(self, data: dict) -> dict | None:
        """@deprecated: 改用 check_all(ctx) 或 _check_experience(ctx)"""
        return self._check_experience(ConstraintContext.from_data(data))
