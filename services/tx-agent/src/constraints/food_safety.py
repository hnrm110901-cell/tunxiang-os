"""硬约束 #2：食安合规

支持两种数据来源（按优先级）：

  1. payload["ingredients"]: list[dict]
     直接传食材快照，每项需包含 {name, remaining_hours[, batch_id]}。
     适用于：决策已经查过库存的 Skill（如 inventory_alert.check_expiration）

  2. payload["ingredient_ids"]: list[str] + ctx.inventory_repository
     由约束层调用 repository.fetch_expiry_status(ids) 反查批次效期。
     适用于：决策只知 dish 没查库存的 Skill（如 menu_advisor / smart_menu）

任一食材 remaining_hours < expiry_buffer_hours（缺省 24h）即视为违反。
remaining_hours=None 视为非保质期敏感品（跳过该项）。
"""

from __future__ import annotations

from typing import Optional, Protocol

from .base import ConstraintCheck, SkillContext

# 模块默认（store_config 未声明时使用）
EXPIRY_BUFFER_HOURS = 24


class InventoryRepository(Protocol):
    """食安反查协议。

    Skill 决策只携带 ingredient_ids 时，由约束层用 ctx.inventory_repository.fetch_expiry_status
    取每条食材最近一批次的 remaining_hours。

    Returns:
        list of dict: [{"name": str, "remaining_hours": Optional[float], "batch_id": Optional[str]}]
    """

    async def fetch_expiry_status(self, tenant_id: str, ingredient_ids: list[str]) -> list[dict]:  # pragma: no cover
        ...


def _normalize_ingredients(raw: list) -> list[dict]:
    """统一食材清单格式。

    接受 list[dict] 或 list[ConstraintContext.IngredientSnapshot]（dataclass）；
    任何非 dict/dataclass 项被丢弃。
    """
    out: list[dict] = []
    for item in raw or []:
        if isinstance(item, dict):
            out.append(item)
            continue
        # 兼容 dataclass（如 agents.context.IngredientSnapshot）
        if hasattr(item, "name") and hasattr(item, "remaining_hours"):
            out.append(
                {
                    "name": getattr(item, "name", "unknown"),
                    "remaining_hours": getattr(item, "remaining_hours", None),
                    "batch_id": getattr(item, "batch_id", None),
                }
            )
    return out


async def check(payload: dict, ctx: SkillContext) -> Optional[ConstraintCheck]:
    """食安合规校验。

    Returns:
        ConstraintCheck —— 校验执行了
        None            —— payload 既无 ingredients 也无 ingredient_ids，跳过
    """
    raw_ings = payload.get("ingredients")
    ingredients = _normalize_ingredients(raw_ings) if isinstance(raw_ings, list) else []

    # 路径 2：从 repository 反查
    if not ingredients:
        ids = payload.get("ingredient_ids")
        if isinstance(ids, list) and ids and ctx.inventory_repository is not None:
            try:
                ingredients = list(await ctx.inventory_repository.fetch_expiry_status(ctx.tenant_id, ids))
            except Exception:  # noqa: BLE001 — repository 不可用时退回 skipped
                # repository 不可达不应直接通过：标 skipped 让上层决定（runner 会记入）
                return None

    if not ingredients:
        return None

    threshold = ctx.expiry_buffer_hours
    violations: list[dict] = []

    for ing in ingredients:
        remaining_hours = ing.get("remaining_hours")
        if remaining_hours is None:
            # 非保质期敏感品，跳过该项
            continue
        if remaining_hours < threshold:
            violations.append(
                {
                    "ingredient": ing.get("name", "unknown"),
                    "remaining_hours": remaining_hours,
                    "threshold_hours": threshold,
                    "batch_id": ing.get("batch_id"),
                }
            )

    if violations:
        names = ", ".join(v["ingredient"] for v in violations[:3])
        suffix = f" 等 {len(violations)} 项" if len(violations) > 3 else ""
        return ConstraintCheck(
            name="food_safety",
            passed=False,
            reason=f"临期/过期食材：{names}{suffix}",
            details={
                "violations": violations,
                "threshold_hours": threshold,
                "total_checked": len(ingredients),
            },
        )

    return ConstraintCheck(
        name="food_safety",
        passed=True,
        reason=f"全部 {len(ingredients)} 项食材剩余时间 >= {threshold}h",
        details={
            "violations": [],
            "threshold_hours": threshold,
            "total_checked": len(ingredients),
        },
    )
