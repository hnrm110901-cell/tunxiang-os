"""conflict_resolver.py — 统一同步冲突解决器（LWW + 终态保护 + POS 交易保护 + 云端权威覆盖）

本模块是屯象OS唯一的同步冲突解决实现。所有 sync-engine（本地PG ↔ 云端PG）
和 mac-station 必须引用本模块，不得再分散实现冲突解决逻辑。

冲突策略优先级：
1. 云端权威覆盖（authoritative=true） — 云端标记为权威时直接覆盖
2. POS 交易保护                    — 本地 source='pos' 且 status in ('pending','paid') 时保留本地
3. 终端保护                        — 本地处于终态时不被远端非终态覆盖
4. LWW（Last-Writer-Wins）         — 其余情况比较 updated_at，较新者优先

重要
----
本实现是 **LWW + 终态保护** 的启发式策略，并非真正的 CRDT（Conflict-free Replicated Data Type）。
真正的 CRDT 需要每个实体的 Operation 级合并语义（如共享版本文档树），
而本系统基于记录级 updated_at 时间戳比较，不满足 CRDT 的数学定义。

各文件职责：
- conflict_resolver.py（本文件）：resolve() 核心逻辑 —— 所有消费者通过此入口
- sync_engine.py：             sync-engine 主循环 —— 调用 resolve() 处理冲突
- sync_conflict_resolver.py：  mac-station 订单推送冲突检测 —— 调用 resolve() 后包装策略元数据
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger()

# 终态集合：处于这些状态的本地记录不被远端非终态覆盖
TERMINAL_STATUSES: frozenset[str] = frozenset({
    "done", "served", "completed", "cancelled", "refunded", "closed",
})

# POS 交易保护状态集合：活跃交易不被云端覆盖
POS_PROTECTED_STATUSES: frozenset[str] = frozenset({"pending", "paid"})


def _parse_ts(value: Any) -> datetime:
    """将 updated_at 字段解析为带时区的 datetime（解析失败返回 epoch）"""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        value = value.strip()
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f+00:00",
            "%Y-%m-%dT%H:%M:%S+00:00",
            "%Y-%m-%d %H:%M:%S.%f+00:00",
            "%Y-%m-%d %H:%M:%S+00:00",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                dt = datetime.strptime(value, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
    # 无法解析，视为 epoch
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


class ConflictResolver:
    """同步冲突解决器：LWW + 终态保护 + POS 交易保护 + 云端权威覆盖

    本实现不是 CRDT。详见模块 docstring。

    Usage::

        resolved = ConflictResolver.resolve(local_record, remote_record)
        # resolved 是应使用的最终版本（dict）
    """

    @staticmethod
    def resolve(
        local_record: dict[str, Any],
        remote_record: dict[str, Any],
    ) -> dict[str, Any]:
        """解决单条记录的同步冲突

        策略优先级（从高到低）：
          1. 云端权威覆盖（remote.authoritative == True）
          2. POS 交易保护（local.source='pos' 且 status in ('pending','paid')）
          3. 终端保护（local.status 在终态集合中，remote.status 不在）
          4. LWW：比较 updated_at，较新者优先

        Args:
            local_record:  本地 PG 中的当前版本
            remote_record: 云端拉取的版本

        Returns:
            应写入目标数据库的最终版本
        """
        # ── 规则 1：云端权威覆盖 ──────────────────────────────────────────
        if remote_record.get("authoritative") is True:
            logger.debug(
                "conflict_resolver.cloud_authoritative",
                reason="云端标记为 authoritative=true，直接覆盖",
            )
            return remote_record

        local_status = str(local_record.get("status", ""))
        remote_status = str(remote_record.get("status", ""))
        local_source = str(local_record.get("source", ""))

        # ── 规则 2：POS 交易保护 ──────────────────────────────────────────
        if local_source == "pos" and local_status in POS_PROTECTED_STATUSES:
            logger.debug(
                "conflict_resolver.pos_transaction_protection",
                local_status=local_status,
                reason="POS 活跃交易保护，保留本地",
            )
            return local_record

        local_ts = _parse_ts(local_record.get("updated_at"))
        remote_ts = _parse_ts(remote_record.get("updated_at"))

        # ── 规则 3：终态保护 ────────────────────────────────────────────
        # 情形 3a：本地比远端更新 且 本地是终态 → 保留本地（不被旧远端回滚）
        if local_ts > remote_ts and local_status in TERMINAL_STATUSES:
            logger.debug(
                "conflict_resolver.keep_local_terminal_newer",
                local_status=local_status,
                remote_status=remote_status,
                local_ts=local_ts.isoformat(),
                remote_ts=remote_ts.isoformat(),
            )
            return local_record

        # 情形 3b：本地是终态 且 远端是非终态（无论时间戳）→ 保留本地终态
        if local_status in TERMINAL_STATUSES and remote_status not in TERMINAL_STATUSES:
            logger.debug(
                "conflict_resolver.keep_local_terminal_status",
                local_status=local_status,
                remote_status=remote_status,
            )
            return local_record

        # ── 规则 4：LWW（Last-Writer-Wins） ─────────────────────────────
        if local_ts > remote_ts:
            logger.debug(
                "conflict_resolver.local_wins",
                local_ts=local_ts.isoformat(),
                remote_ts=remote_ts.isoformat(),
                local_status=local_status,
                remote_status=remote_status,
            )
            return local_record

        # 默认：云端优先（remote updated_at >= local updated_at）
        logger.debug(
            "conflict_resolver.remote_wins",
            local_ts=local_ts.isoformat(),
            remote_ts=remote_ts.isoformat(),
            local_status=local_status,
            remote_status=remote_status,
        )
        return remote_record
