"""run_checks — 三条硬约束的统一执行入口

按顺序执行 gross_margin / food_safety / customer_experience，
聚合为 ConstraintResult。任一 check 返回 None 时记入 result.skipped（透明记录，
不视为通过）。
"""

from __future__ import annotations

from typing import Any

from . import customer_experience, food_safety, gross_margin
from .base import ConstraintName, ConstraintResult, SkillContext


def _coerce_payload(decision: Any) -> dict:
    """从 Skill 决策对象抽出 payload（dict）。

    支持 3 种入参：
        1. dict —— 直接当 payload
        2. AgentResult —— 取 result.data（dict）
        3. 其他对象 —— 尝试 .payload / .data 属性

    无法识别的形态返回 {}（约束都将 skipped）。
    """
    if isinstance(decision, dict):
        return decision
    # AgentResult-like：result.data
    data = getattr(decision, "data", None)
    if isinstance(data, dict):
        return data
    payload = getattr(decision, "payload", None)
    if isinstance(payload, dict):
        return payload
    return {}


async def run_checks(decision: Any, context: SkillContext) -> ConstraintResult:
    """执行三条硬约束并聚合结果。

    Args:
        decision: Skill 决策对象（AgentResult / dict / 其他带 .data/.payload）
        context:  SkillContext（含阈值 + tenant_id + 可选 inventory_repository）

    Returns:
        ConstraintResult: passed=False 时业务决策应被拒绝。
    """
    payload = _coerce_payload(decision)
    result = ConstraintResult()

    # 1. 毛利底线（同步）
    margin_check = gross_margin.check(payload, context)
    if margin_check is None:
        result.skipped.append("gross_margin")
    else:
        result.checks.append(margin_check)
        if not margin_check.passed:
            result.passed = False
            result.blocking_failures.append(f"毛利底线：{margin_check.reason}")

    # 2. 食安合规（异步：可能调 repository）
    safety_check = await food_safety.check(payload, context)
    if safety_check is None:
        result.skipped.append("food_safety")
    else:
        result.checks.append(safety_check)
        if not safety_check.passed:
            result.passed = False
            result.blocking_failures.append(f"食安合规：{safety_check.reason}")

    # 3. 客户体验（同步）
    exp_check = customer_experience.check(payload, context)
    if exp_check is None:
        result.skipped.append("customer_experience")
    else:
        result.checks.append(exp_check)
        if not exp_check.passed:
            result.passed = False
            result.blocking_failures.append(f"客户体验：{exp_check.reason}")

    return result


__all__ = ["ConstraintName", "run_checks"]
