"""屯象OS Skill Router — 事件→Skill 确定性路由引擎"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .registry import SkillRegistry
from .schemas import EventTrigger, SkillManifest

logger = logging.getLogger(__name__)


@dataclass
class SkillMatch:
    """路由命中结果"""

    skill: SkillManifest
    trigger: EventTrigger
    priority: int
    degraded: bool = False
    degraded_reason: str = ""


class SkillRouter:
    """
    事件→Skill 确定性路由引擎。

    对标 Claude 的语义匹配，但屯象用确定性路由（事件类型 + 条件表达式）。
    condition 是字符串表达式，支持：
      - "always"                       → 总是匹配
      - ""                             → 视为 "always"
      - "payload.xxx == 'value'"       → payload 中某字段等于字符串值
      - "payload.xxx == true/false"    → payload 中某字段为布尔值
      - "payload.xxx != null"          → payload 中某字段不为 null
      - "payload.xxx == null"          → payload 中某字段为 null
      - "payload.xxx in ['a','b']"     → 枚举匹配
    不支持复杂表达式，未能解析的 condition 视为 "always"（宽松策略）。
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def route(
        self,
        event_type: str,
        payload: dict,
        tenant_id: str = "",
        store_id: str = "",
    ) -> list[SkillMatch]:
        """
        给定事件类型和 payload，返回应处理该事件的 Skill 列表（按 priority 降序）。

        Args:
            event_type:  具体事件类型，如 "order.paid"
            payload:     事件 payload dict
            tenant_id:   租户 ID（预留，暂未参与路由判断）
            store_id:    门店 ID（预留，暂未参与路由判断）

        Returns:
            命中的 SkillMatch 列表，按 priority 降序排列
        """
        candidates = self.registry.find_by_event_type(event_type)
        matches: list[SkillMatch] = []

        for manifest, trigger in candidates:
            if self._eval_condition(trigger.condition, payload):
                matches.append(
                    SkillMatch(
                        skill=manifest,
                        trigger=trigger,
                        priority=trigger.priority,
                    )
                )

        # 按 priority 降序（find_by_event_type 已排序，这里再排保证稳定性）
        matches.sort(key=lambda m: m.priority, reverse=True)
        return matches

    # ─────────────────────────────────────────
    # 条件表达式解析（不使用 eval，安全解析）
    # ─────────────────────────────────────────

    def _eval_condition(self, condition: str, payload: dict) -> bool:
        """
        安全地评估简单条件表达式。

        Args:
            condition: 条件字符串
            payload:   事件 payload

        Returns:
            True 表示条件满足
        """
        condition = condition.strip()

        if not condition or condition == "always":
            return True

        # payload.xxx != null
        if "!= null" in condition:
            field_path = condition.split("!=")[0].strip()
            value = self._get_payload_value(field_path, payload)
            return value is not None

        # payload.xxx == null
        if "== null" in condition:
            field_path = condition.split("==")[0].strip()
            value = self._get_payload_value(field_path, payload)
            return value is None

        # payload.xxx in ['a', 'b', ...]
        if " in [" in condition or " in ['" in condition:
            return self._eval_in_condition(condition, payload)

        # payload.xxx == 'value' / true / false / 数字
        if "==" in condition:
            return self._eval_eq_condition(condition, payload)

        # 未能识别的表达式，宽松策略视为 always
        logger.debug("condition_unparsed_fallback_to_always: %r", condition)
        return True

    @staticmethod
    def _get_payload_value(field_path: str, payload: dict) -> object:
        """
        从 payload 中按点号路径取值。

        Args:
            field_path: 如 "payload.customer_id" 或 "payload.action"
            payload:    事件 payload dict

        Returns:
            字段值，找不到返回 None
        """
        parts = field_path.strip().split(".")
        # 去掉开头的 "payload"
        if parts and parts[0] == "payload":
            parts = parts[1:]

        current: object = payload
        for part in parts:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _eval_eq_condition(self, condition: str, payload: dict) -> bool:
        """解析 payload.xxx == value 形式的条件。"""
        parts = condition.split("==", 1)
        if len(parts) != 2:
            return True

        field_path = parts[0].strip()
        raw_expected = parts[1].strip()
        actual = self._get_payload_value(field_path, payload)

        # 布尔值
        if raw_expected == "true":
            return actual is True or actual == "true"
        if raw_expected == "false":
            return actual is False or actual == "false"

        # 字符串值（带引号）
        if (raw_expected.startswith("'") and raw_expected.endswith("'")) or (
            raw_expected.startswith('"') and raw_expected.endswith('"')
        ):
            expected_str = raw_expected[1:-1]
            return str(actual) == expected_str

        # 数字
        try:
            expected_num = float(raw_expected)
            return float(actual) == expected_num  # type: ignore[arg-type]
        except (ValueError, TypeError):
            pass

        # 回退：字符串比较
        return str(actual) == raw_expected

    def _eval_in_condition(self, condition: str, payload: dict) -> bool:
        """解析 payload.xxx in ['a', 'b'] 形式的条件。"""
        try:
            in_idx = condition.index(" in ")
            field_path = condition[:in_idx].strip()
            list_str = condition[in_idx + 4 :].strip()

            actual = self._get_payload_value(field_path, payload)

            # 简单解析方括号内逗号分隔的字符串列表
            list_str = list_str.strip("[]")
            items: list[str] = []
            for raw_item in list_str.split(","):
                item = raw_item.strip().strip("'\"")
                items.append(item)

            return str(actual) in items
        except (ValueError, IndexError):
            logger.debug("in_condition_parse_failed_fallback_to_always: %r", condition)
            return True
