"""conflict_resolver.py — 同步冲突解决策略

策略：云端优先（remote wins）
例外：本地记录处于终态（done/served/completed/cancelled）时不被远端非终态覆盖。

这样保证：
- 门店在断网期间完成的订单状态不会被云端旧状态回滚
- 其余字段（金额、菜品、时间戳等）以云端为准，避免本地脏数据污染全局
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger()

# 终态集合：处于这些状态的本地记录不被远端非终态覆盖
TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "served", "completed", "cancelled", "refunded", "closed"})


def _parse_ts(value: Any) -> datetime:
    """将 updated_at 字段解析为带时区的 datetime（解析失败返回 epoch）"""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        # 去掉末尾 +00:00 前可能出现的空格
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
    """冲突解决器：云端优先，保留本地终态"""

    @staticmethod
    def resolve(local_record: dict, remote_record: dict) -> dict:
        """解决单条记录的同步冲突

        Args:
            local_record:  本地 PG 中的当前版本
            remote_record: 云端拉取的版本

        Returns:
            应写入本地 PG 的最终版本
        """
        local_ts = _parse_ts(local_record.get("updated_at"))
        remote_ts = _parse_ts(remote_record.get("updated_at"))

        local_status = local_record.get("status", "")
        remote_status = remote_record.get("status", "")

        # 情形 1：本地比远端更新 且 本地是终态 → 保留本地（不被旧远端回滚）
        if local_ts > remote_ts and local_status in TERMINAL_STATUSES:
            logger.debug(
                "conflict_resolver.keep_local_terminal",
                local_status=local_status,
                remote_status=remote_status,
                local_ts=local_ts.isoformat(),
                remote_ts=remote_ts.isoformat(),
            )
            return local_record

        # 情形 2：本地是终态 且 远端是非终态（无论时间戳）→ 保留本地终态
        if local_status in TERMINAL_STATUSES and remote_status not in TERMINAL_STATUSES:
            logger.debug(
                "conflict_resolver.keep_local_terminal_status",
                local_status=local_status,
                remote_status=remote_status,
            )
            return local_record

        # 默认：云端优先
        logger.debug(
            "conflict_resolver.remote_wins",
            local_ts=local_ts.isoformat(),
            remote_ts=remote_ts.isoformat(),
            local_status=local_status,
            remote_status=remote_status,
        )
        return remote_record
