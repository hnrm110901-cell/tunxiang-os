"""硬约束 #3：客户体验

读 payload["estimated_serve_time_seconds"] 或 payload["estimated_serve_minutes"]，
与 SkillContext.max_serve_minutes（缺省 30 分钟）比对。

任一决策预计出餐 > 上限即视为违反客户体验底线。
"""

from __future__ import annotations

from typing import Optional

from .base import ConstraintCheck, SkillContext

# 模块默认（store_config 未声明时使用）
MAX_SERVE_MINUTES = 30


def _extract_minutes(payload: dict) -> Optional[float]:
    """提取出餐时长（分钟），同时兼容秒为单位的 payload 字段。"""
    minutes = payload.get("estimated_serve_minutes")
    if minutes is not None:
        try:
            return float(minutes)
        except (TypeError, ValueError):
            return None

    seconds = payload.get("estimated_serve_time_seconds")
    if seconds is not None:
        try:
            return float(seconds) / 60.0
        except (TypeError, ValueError):
            return None
    return None


def check(payload: dict, ctx: SkillContext) -> Optional[ConstraintCheck]:
    """客户体验校验。

    Returns:
        ConstraintCheck —— 校验执行了
        None            —— payload 既无 estimated_serve_minutes 也无 estimated_serve_time_seconds，跳过
    """
    minutes = _extract_minutes(payload)
    if minutes is None:
        return None

    threshold = ctx.max_serve_minutes
    passed = minutes <= threshold

    return ConstraintCheck(
        name="customer_experience",
        passed=passed,
        reason=(
            f"预计出餐 {minutes:.1f} 分钟 <= 上限 {threshold} 分钟"
            if passed
            else f"预计出餐 {minutes:.1f} 分钟 > 上限 {threshold} 分钟"
        ),
        details={
            "actual_minutes": round(minutes, 2),
            "threshold_minutes": threshold,
        },
    )
