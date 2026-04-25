"""硬约束 #1：毛利底线

读 decision.payload 中的 (price_fen, cost_fen) 或别名 (final_amount_fen, food_cost_fen)
计算毛利率，与 SkillContext.min_margin_rate（缺省 15%）比对。

任何降级（包括折扣、赠送、套餐组合后的实际成交价）若使毛利率 < 阈值，即视为违反。
"""

from __future__ import annotations

from typing import Optional

from .base import ConstraintCheck, SkillContext

# 模块默认（store_config 未声明时使用）
MIN_MARGIN_RATE = 0.15


def _extract_price_cost(payload: dict) -> tuple[Optional[int], Optional[int]]:
    """提取 price_fen 与 cost_fen，兼容 final_amount_fen / food_cost_fen 别名。

    用 `if key in` 而非 `or`，避免 price=0 被 truthy 测试误判为缺失
    （price=0 是"零售价错误设为 0"的真实违规场景）。
    """
    price = payload.get("price_fen")
    if price is None:
        price = payload.get("final_amount_fen")
    cost = payload.get("cost_fen")
    if cost is None:
        cost = payload.get("food_cost_fen")
    return price, cost


def check(payload: dict, ctx: SkillContext) -> Optional[ConstraintCheck]:
    """毛利底线校验。

    Returns:
        ConstraintCheck —— 校验执行了（pass 或 fail）
        None            —— payload 中无 price/cost 字段，跳过（runner 标 skipped）
    """
    price_fen, cost_fen = _extract_price_cost(payload)
    if price_fen is None or cost_fen is None:
        return None

    threshold = ctx.min_margin_rate

    # price=0 视为违规（不能除以 0）
    if price_fen <= 0:
        return ConstraintCheck(
            name="gross_margin",
            passed=False,
            reason=f"售价为 {price_fen} 分，无法计算毛利",
            details={
                "price_fen": price_fen,
                "cost_fen": cost_fen,
                "actual_rate": 0.0,
                "threshold": threshold,
            },
        )

    margin_rate = (price_fen - cost_fen) / price_fen
    passed = margin_rate >= threshold

    return ConstraintCheck(
        name="gross_margin",
        passed=passed,
        reason=(
            f"毛利率 {margin_rate:.1%} >= 阈值 {threshold:.1%}"
            if passed
            else f"毛利率 {margin_rate:.1%} < 阈值 {threshold:.1%}"
        ),
        details={
            "price_fen": price_fen,
            "cost_fen": cost_fen,
            "actual_rate": round(margin_rate, 4),
            "threshold": threshold,
        },
    )
