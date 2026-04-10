"""
同步冲突解决器

mac-station sync-engine 在将本地离线订单推送云端时，若发现云端已存在
相同 idempotency_key 的记录，则触发冲突解决逻辑。

策略（ConflictStrategy）：
1. cloud_wins  — 云端优先（默认）：云端有记录则本地标记 conflict，不推送
2. local_wins  — 本地优先（危险）：本地记录推送覆盖云端，需人工确认
3. newer_wins  — 时间戳优先：比较 created_at，取更新的一条

ResolutionResult 字段：
  strategy               — 使用的策略名称
  winner                 — "cloud" / "local" / "manual_review"
  reason                 — 决策理由（可读文字，供日志/审计）
  requires_manual_review — True 时 sync-engine 应暂停该订单，推送到人工队列
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog

log = structlog.get_logger(__name__)


# ─── 策略枚举 ─────────────────────────────────────────────────────────────────

class ConflictStrategy(str, Enum):
    CLOUD_WINS = "cloud_wins"
    LOCAL_WINS = "local_wins"
    NEWER_WINS = "newer_wins"


# ─── 结果模型 ─────────────────────────────────────────────────────────────────

@dataclass
class ResolutionResult:
    """冲突解决结果。

    Attributes:
        strategy: 使用的策略
        winner: "cloud" | "local" | "manual_review"
        reason: 人类可读的决策理由（用于审计日志）
        requires_manual_review: True 时 sync-engine 应暂停并推送到人工队列
        local_order_id: 本地订单 ID（方便 caller 更新 sync_status）
        cloud_order_id: 云端订单 ID（若存在）
        metadata: 附加调试信息
    """
    strategy: ConflictStrategy
    winner: str                              # "cloud" | "local" | "manual_review"
    reason: str
    requires_manual_review: bool
    local_order_id: str = ""
    cloud_order_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ─── 解析器 ───────────────────────────────────────────────────────────────────

class ConflictResolver:
    """离线订单同步冲突解决器。

    Usage::

        resolver = ConflictResolver(strategy=ConflictStrategy.CLOUD_WINS)
        result = resolver.resolve(local_order, cloud_order)
        if result.requires_manual_review:
            await push_to_manual_queue(result)
        elif result.winner == "local":
            await push_to_cloud(local_order)

    Args:
        strategy: 冲突解决策略，默认 CLOUD_WINS（最安全）。
    """

    def __init__(self, strategy: ConflictStrategy = ConflictStrategy.CLOUD_WINS) -> None:
        self.strategy = strategy

    def resolve(
        self,
        local_order: dict[str, Any],
        cloud_order: dict[str, Any],
    ) -> ResolutionResult:
        """解决一对冲突订单，返回处置建议。

        Args:
            local_order: 本地 PG 中的订单字典，必须包含 id、created_at、
                         idempotency_key、total_amount_fen 等字段。
            cloud_order: 云端 API 返回的订单字典，格式同上。

        Returns:
            ResolutionResult 实例，caller 根据 winner 和 requires_manual_review
            决定后续动作。

        Raises:
            ValueError: 若 local_order 或 cloud_order 缺少必要字段。
        """
        self._validate_order(local_order, "local")
        self._validate_order(cloud_order, "cloud")

        local_id = str(local_order.get("id", local_order.get("order_id", "")))
        cloud_id = str(cloud_order.get("id", cloud_order.get("order_id", "")))
        ikey = local_order.get("idempotency_key", "")

        log.info(
            "conflict_resolution_started",
            strategy=self.strategy,
            local_order_id=local_id,
            cloud_order_id=cloud_id,
            idempotency_key=ikey,
        )

        result: ResolutionResult

        if self.strategy == ConflictStrategy.CLOUD_WINS:
            result = self._resolve_cloud_wins(local_id, cloud_id, ikey)
        elif self.strategy == ConflictStrategy.LOCAL_WINS:
            result = self._resolve_local_wins(local_id, cloud_id, ikey)
        elif self.strategy == ConflictStrategy.NEWER_WINS:
            result = self._resolve_newer_wins(local_order, cloud_order, local_id, cloud_id, ikey)
        else:
            # 不可能走到此分支（Enum 已穷举），防御性处理
            raise ValueError(f"未知冲突策略: {self.strategy}")

        log.info(
            "conflict_resolution_done",
            strategy=self.strategy,
            local_order_id=local_id,
            cloud_order_id=cloud_id,
            winner=result.winner,
            requires_manual_review=result.requires_manual_review,
            reason=result.reason,
        )
        return result

    # ── 策略实现 ──────────────────────────────────────────────────────────────

    def _resolve_cloud_wins(
        self, local_id: str, cloud_id: str, ikey: str
    ) -> ResolutionResult:
        """云端优先：本地记录标记 conflict，不推送。"""
        return ResolutionResult(
            strategy=self.strategy,
            winner="cloud",
            reason=(
                f"云端优先策略：云端已存在 idempotency_key={ikey!r} 的订单 "
                f"(cloud_id={cloud_id})，本地订单 {local_id} 标记为 conflict，跳过推送。"
            ),
            requires_manual_review=False,
            local_order_id=local_id,
            cloud_order_id=cloud_id,
            metadata={"idempotency_key": ikey},
        )

    def _resolve_local_wins(
        self, local_id: str, cloud_id: str, ikey: str
    ) -> ResolutionResult:
        """本地优先：推送本地记录覆盖云端，但标记需人工确认（高风险）。"""
        return ResolutionResult(
            strategy=self.strategy,
            winner="local",
            reason=(
                f"本地优先策略：将用本地订单 {local_id} 覆盖云端订单 {cloud_id} "
                f"(idempotency_key={ikey!r})。此操作不可撤销，已触发人工确认流程。"
            ),
            requires_manual_review=True,
            local_order_id=local_id,
            cloud_order_id=cloud_id,
            metadata={"idempotency_key": ikey, "warning": "destructive_overwrite"},
        )

    def _resolve_newer_wins(
        self,
        local_order: dict[str, Any],
        cloud_order: dict[str, Any],
        local_id: str,
        cloud_id: str,
        ikey: str,
    ) -> ResolutionResult:
        """时间戳优先：比较 created_at，取更新的一条。

        若时间戳相差 < 1 秒（浮点精度问题），降级到 cloud_wins 并需人工确认。
        """
        local_ts = self._parse_ts(local_order.get("created_at"))
        cloud_ts = self._parse_ts(cloud_order.get("created_at"))

        if local_ts is None or cloud_ts is None:
            return ResolutionResult(
                strategy=self.strategy,
                winner="manual_review",
                reason=(
                    f"时间戳优先策略：无法解析时间戳 "
                    f"(local_created_at={local_order.get('created_at')!r}, "
                    f"cloud_created_at={cloud_order.get('created_at')!r})，"
                    f"降级为人工审核。"
                ),
                requires_manual_review=True,
                local_order_id=local_id,
                cloud_order_id=cloud_id,
                metadata={"idempotency_key": ikey, "reason": "unparseable_timestamp"},
            )

        diff_secs = abs((local_ts - cloud_ts).total_seconds())
        if diff_secs < 1.0:
            # 时间差极小，很可能是同一次事务的双写，不确定谁新，人工处理
            return ResolutionResult(
                strategy=self.strategy,
                winner="manual_review",
                reason=(
                    f"时间戳优先策略：本地 ({local_ts.isoformat()}) 与云端 "
                    f"({cloud_ts.isoformat()}) 时间差 < 1s，无法确定哪条更新，"
                    f"降级为人工审核。"
                ),
                requires_manual_review=True,
                local_order_id=local_id,
                cloud_order_id=cloud_id,
                metadata={
                    "idempotency_key": ikey,
                    "local_ts": local_ts.isoformat(),
                    "cloud_ts": cloud_ts.isoformat(),
                    "diff_secs": diff_secs,
                },
            )

        if local_ts > cloud_ts:
            return ResolutionResult(
                strategy=self.strategy,
                winner="local",
                reason=(
                    f"时间戳优先策略：本地订单更新 ({local_ts.isoformat()} > "
                    f"{cloud_ts.isoformat()})，推送本地记录，需人工确认后执行覆盖。"
                ),
                requires_manual_review=True,
                local_order_id=local_id,
                cloud_order_id=cloud_id,
                metadata={
                    "idempotency_key": ikey,
                    "local_ts": local_ts.isoformat(),
                    "cloud_ts": cloud_ts.isoformat(),
                },
            )
        else:
            return ResolutionResult(
                strategy=self.strategy,
                winner="cloud",
                reason=(
                    f"时间戳优先策略：云端订单更新 ({cloud_ts.isoformat()} >= "
                    f"{local_ts.isoformat()})，本地订单 {local_id} 标记 conflict，跳过推送。"
                ),
                requires_manual_review=False,
                local_order_id=local_id,
                cloud_order_id=cloud_id,
                metadata={
                    "idempotency_key": ikey,
                    "local_ts": local_ts.isoformat(),
                    "cloud_ts": cloud_ts.isoformat(),
                },
            )

    # ── 辅助方法 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_order(order: dict[str, Any], label: str) -> None:
        """校验订单字典必要字段，缺失时抛出 ValueError。"""
        if not isinstance(order, dict):
            raise ValueError(f"{label}_order 必须是 dict，收到: {type(order).__name__}")
        # 允许 id 或 order_id 二选一
        if not order.get("id") and not order.get("order_id"):
            raise ValueError(f"{label}_order 缺少 id / order_id 字段")

    @staticmethod
    def _parse_ts(ts_value: Any) -> datetime | None:
        """解析 created_at 字段为 datetime（支持 ISO 字符串和 datetime 对象）。"""
        if ts_value is None:
            return None
        if isinstance(ts_value, datetime):
            return ts_value if ts_value.tzinfo else ts_value.replace(tzinfo=timezone.utc)
        if isinstance(ts_value, str):
            try:
                dt = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        return None
