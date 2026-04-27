"""TxEvent -- 屯象OS 统一事件基础数据类

所有跨服务事件的标准化载体。无论通过 Redis Streams 还是 PG NOTIFY 传输，
事件格式统一为 TxEvent。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class TxEvent:
    """屯象OS 标准事件

    Attributes:
        event_type:  点分事件类型，如 "order.created", "inventory.low_stock"
        tenant_id:   租户 ID（RLS 隔离）
        payload:     业务数据字典
        source:      发送方服务名，如 "tx-trade", "tx-supply"
        store_id:    门店 ID（品牌级事件可为 None）
        event_id:    唯一事件 ID（UUID4 字符串）
        timestamp:   事件发生时刻（UTC）
        version:     事件格式版本号
    """

    event_type: str
    tenant_id: str
    payload: dict[str, Any]
    source: str
    store_id: str | None = None
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: str = "1.0"

    # ------------------------------------------------------------------
    # 序列化 / 反序列化
    # ------------------------------------------------------------------

    def to_stream_fields(self) -> dict[str, str]:
        """序列化为 Redis Stream fields（全部 str 值）。"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id or "",
            "payload": json.dumps(self.payload, ensure_ascii=False, default=str),
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_stream_fields(cls, fields: dict[str, str]) -> TxEvent:
        """从 Redis Stream fields 反序列化。

        Raises:
            KeyError: 必填字段缺失
            json.JSONDecodeError: payload 不是合法 JSON
            ValueError: timestamp 格式错误
        """
        ts_raw = fields.get("timestamp", "")
        if ts_raw:
            timestamp = datetime.fromisoformat(ts_raw)
        else:
            timestamp = datetime.now(timezone.utc)

        return cls(
            event_type=fields["event_type"],
            tenant_id=fields["tenant_id"],
            store_id=fields.get("store_id") or None,
            payload=json.loads(fields.get("payload", "{}")),
            source=fields.get("source", "unknown"),
            event_id=fields.get("event_id", str(uuid4())),
            timestamp=timestamp,
            version=fields.get("version", "1.0"),
        )

    def to_json(self) -> str:
        """序列化为 JSON 字符串（用于 PG NOTIFY payload 等场景）。"""
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return json.dumps(d, ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, raw: str) -> TxEvent:
        """从 JSON 字符串反序列化。

        Raises:
            json.JSONDecodeError: JSON 格式错误
            KeyError: 必填字段缺失
        """
        d = json.loads(raw)
        ts_raw = d.get("timestamp", "")
        if ts_raw:
            d["timestamp"] = datetime.fromisoformat(ts_raw)
        else:
            d["timestamp"] = datetime.now(timezone.utc)
        return cls(**d)
