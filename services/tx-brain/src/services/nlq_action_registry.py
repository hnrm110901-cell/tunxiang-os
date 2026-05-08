"""NLQ actionId 白名单防火墙 — S4-03 Issue #290 / Tier 1。

零容忍：未在白名单内的 action_id 一律拒绝。

ALLOWED_ACTIONS 从 nlq_action_types.ActionId Literal 派生（typing.get_args），
保证白名单与类型定义单一来源。

类比 S4-02 nlq_keyword_firewall — 都是 Tier 1 安全前置纯函数。
"""

from __future__ import annotations

from typing import get_args

from .nlq_action_types import ActionId

# 从 Literal 单一来源派生 — 任何 ActionId 扩展都会自动同步
ALLOWED_ACTIONS: frozenset[str] = frozenset(get_args(ActionId))


class UnknownActionError(ValueError):
    """action_id 不在白名单内 — payload 篡改 / LLM 输出非法 actionId 都触发此异常。"""

    def __init__(self, action_id: str) -> None:
        super().__init__(
            f"action_id={action_id!r} 不在白名单（合法值: {sorted(ALLOWED_ACTIONS)}）"
        )
        self.action_id = action_id


def assert_action_id_allowed(action_id: str) -> None:
    """白名单 firewall。

    Raises:
        UnknownActionError: action_id 未在 ALLOWED_ACTIONS 中。
    """
    if action_id not in ALLOWED_ACTIONS:
        raise UnknownActionError(action_id)
