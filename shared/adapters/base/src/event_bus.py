"""emit_adapter_event / AdapterEventMixin —— 14 适配器统一事件总线接入面（Sprint F1 / PR F）

背景
----
14 个旧系统适配器（品智 / 奥琦玮 / 天财 / 美团 / 饿了么 / 抖音 / 微信 / 物流 /
科脉 / 微生活 / 宜鼎 / 诺诺 / 小红书 / ERP）是屯象 OS 与外部系统之间的
"数据边界层"。历史上这些适配器只打 structlog，出问题时要翻日志才能定位：

  - 同步多久一次？多久没跑了？
  - 为什么昨晚漏抓了 128 单？
  - Token 过期没人知道，直到收银员报"外卖单不见了"

PR F 的目标是把这一层的关键动作也打进 v147 事件总线，让：

  - Grafana `mv_adapter_health` 能按 adapter_name + scope 看同步频次和失败率
  - Agent 订阅 `tx_adapter_events` 流，RECONNECTED/CREDENTIAL_EXPIRED 直接触发告警
  - 历史回溯（events 表）可按 adapter 粒度重放某天的同步流程，支持事故复盘

设计
----
两种用法：

1. **函数式**（推荐给已有适配器轻量接入）

   ```python
   from shared.adapters.base.src.event_bus import emit_adapter_event
   from shared.events.src.event_types import AdapterEventType

   asyncio.create_task(emit_adapter_event(
       adapter_name="pinzhi",
       event_type=AdapterEventType.SYNC_STARTED,
       tenant_id=tenant_id,
       scope="orders",
       payload={"since": since.isoformat(), "store_id": store_id},
   ))
   ```

2. **Mixin 继承**（推荐给新适配器或大改的适配器）

   ```python
   from shared.adapters.base.src.event_bus import AdapterEventMixin

   class PinzhiPOSAdapter(AdapterEventMixin):
       adapter_name = "pinzhi"

       async def sync_orders(self, since, tenant_id):
           async with self.track_sync(tenant_id=tenant_id, scope="orders") as track:
               raw = await self._order_sync.fetch_orders(...)
               track.ingested = len(raw)
               return raw
   ```

`track_sync` 是一个 async context manager，自动发 SYNC_STARTED、
成功时发 SYNC_FINISHED、异常时发 SYNC_FAILED，调用方只需要维护 `ingested`
计数。适合把"旁路埋点"降到 3 行侵入。

不做的事
-------
- **不捕获异常**：`track_sync` 记录失败事件后继续抛出，业务层保持原行为
- **不保证投递**：`emit_adapter_event` 内部已 `create_task` 不阻塞主业务，
  Redis/PG 任一失败会降级到 warning 日志（emitter.py 既有约定）
- **不替代 structlog**：事件总线记录"业务语义"，日志仍然是问题排查首选
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, ClassVar, Optional
from uuid import UUID

import structlog

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import AdapterEventType

logger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────
# 函数式接口
# ──────────────────────────────────────────────────────────────────────


async def emit_adapter_event(
    *,
    adapter_name: str,
    event_type: AdapterEventType,
    tenant_id: UUID | str,
    scope: Optional[str] = None,
    stream_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    store_id: Optional[UUID | str] = None,
    metadata: Optional[dict[str, Any]] = None,
    correlation_id: Optional[UUID | str] = None,
) -> Optional[str]:
    """发射适配器事件到 tx_adapter_events 流。

    Args:
        adapter_name:   适配器标识（pinzhi / meituan / eleme / ...，长度 ≤32）
        event_type:     AdapterEventType 枚举值
        tenant_id:      租户 UUID
        scope:          同步范围（orders/menu/members/inventory/status_push）。
                        与 adapter_name 一起进 stream_id，便于按 adapter+scope 聚合
        stream_id:      自定义聚合根 ID。None 时自动生成 `{adapter_name}:{scope or 'default'}`
        payload:        业务数据。约定字段：
                          ingested_count / pushed_count / duration_ms / error_code /
                          error_message / source_id（三方业务 ID）
        store_id:       门店 UUID（可选）
        metadata:       元数据
        correlation_id: 同一批次的相关 ID（便于关联 SYNC_STARTED/FINISHED）

    Returns:
        PG events 表的 event_id（失败为 None，不抛）
    """
    if not adapter_name:
        raise ValueError("adapter_name 不能为空")
    if len(adapter_name) > 32:
        raise ValueError(f"adapter_name 过长（最多 32 字符，当前 {len(adapter_name)}）")

    sid = stream_id or f"{adapter_name}:{scope or 'default'}"

    merged_payload: dict[str, Any] = {
        "adapter_name": adapter_name,
        "scope": scope,
        **(payload or {}),
    }

    merged_metadata: dict[str, Any] = {
        "adapter_name": adapter_name,
        **(metadata or {}),
    }

    return await emit_event(
        event_type=event_type,
        tenant_id=tenant_id,
        stream_id=sid,
        payload=merged_payload,
        store_id=store_id,
        source_service=f"adapter:{adapter_name}",
        metadata=merged_metadata,
        correlation_id=correlation_id,
    )


# ──────────────────────────────────────────────────────────────────────
# Mixin 接口
# ──────────────────────────────────────────────────────────────────────


@dataclass
class SyncTrack:
    """track_sync 上下文对象 —— 子类在块内赋值 `ingested` / `pushed` / `extra` 即可。"""

    ingested: int = 0
    pushed: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class AdapterEventMixin:
    """为 BaseAdapter 子类提供"同步过程自动打点"。

    子类只需：
      1. 设置 `adapter_name` class var
      2. 用 `async with self.track_sync(tenant_id=..., scope="orders") as track:`
         包裹同步逻辑
      3. 在块内把计数赋给 `track.ingested` / `track.pushed`

    失败路径会发 SYNC_FAILED 并原样抛出，业务层无感知。
    """

    adapter_name: ClassVar[str] = "unknown"

    async def emit_reconnected(
        self,
        *,
        tenant_id: UUID | str,
        downtime_seconds: float,
        scope: Optional[str] = None,
    ) -> None:
        """长时故障后首次恢复 —— 触发 Agent 重算 / SRE P0 告警。"""
        await emit_adapter_event(
            adapter_name=self.adapter_name,
            event_type=AdapterEventType.RECONNECTED,
            tenant_id=tenant_id,
            scope=scope,
            payload={"downtime_seconds": round(downtime_seconds, 1)},
        )

    async def emit_credential_expired(
        self,
        *,
        tenant_id: UUID | str,
        expires_at: Optional[str] = None,
    ) -> None:
        """Token / AccessKey 过期 —— 触发运维续签流程。"""
        await emit_adapter_event(
            adapter_name=self.adapter_name,
            event_type=AdapterEventType.CREDENTIAL_EXPIRED,
            tenant_id=tenant_id,
            payload={"expires_at": expires_at},
        )

    async def emit_webhook_received(
        self,
        *,
        tenant_id: UUID | str,
        webhook_type: str,
        source_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        """三方 webhook 回调（退单/异议/票据回执）。"""
        await emit_adapter_event(
            adapter_name=self.adapter_name,
            event_type=AdapterEventType.WEBHOOK_RECEIVED,
            tenant_id=tenant_id,
            stream_id=f"{self.adapter_name}:webhook:{source_id}",
            payload={
                "webhook_type": webhook_type,
                "source_id": source_id,
                **(payload or {}),
            },
        )

    @asynccontextmanager
    async def track_sync(
        self,
        *,
        tenant_id: UUID | str,
        scope: str,
        store_id: Optional[UUID | str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[SyncTrack]:
        """自动在 try 前后发 SYNC_STARTED / FINISHED / FAILED 三元事件。

        Yields:
            SyncTrack 对象，业务代码在块内更新其 ingested / pushed / extra 字段。
        """
        correlation_id = os.urandom(8).hex()
        start_ts = time.perf_counter()
        track = SyncTrack()

        # SYNC_STARTED（fire-and-forget）
        asyncio.create_task(
            emit_adapter_event(
                adapter_name=self.adapter_name,
                event_type=AdapterEventType.SYNC_STARTED,
                tenant_id=tenant_id,
                scope=scope,
                store_id=store_id,
                correlation_id=correlation_id,
                metadata=metadata,
            )
        )

        try:
            yield track
        except Exception as exc:  # noqa: BLE001 — 跟踪器必须兜底全部异常然后重抛
            duration_ms = int((time.perf_counter() - start_ts) * 1000)
            # SYNC_FAILED（await，确保失败事件在异常传播前落库）
            try:
                await emit_adapter_event(
                    adapter_name=self.adapter_name,
                    event_type=AdapterEventType.SYNC_FAILED,
                    tenant_id=tenant_id,
                    scope=scope,
                    store_id=store_id,
                    correlation_id=correlation_id,
                    payload={
                        "duration_ms": duration_ms,
                        "error_code": type(exc).__name__,
                        "error_message": str(exc)[:500],
                        "ingested_count": track.ingested,
                    },
                    metadata=metadata,
                )
            except Exception as emit_exc:  # noqa: BLE001
                logger.warning(
                    "adapter_emit_sync_failed_noop",
                    adapter_name=self.adapter_name,
                    scope=scope,
                    error=str(emit_exc),
                )
            raise

        duration_ms = int((time.perf_counter() - start_ts) * 1000)
        # SYNC_FINISHED（fire-and-forget）
        asyncio.create_task(
            emit_adapter_event(
                adapter_name=self.adapter_name,
                event_type=AdapterEventType.SYNC_FINISHED,
                tenant_id=tenant_id,
                scope=scope,
                store_id=store_id,
                correlation_id=correlation_id,
                payload={
                    "duration_ms": duration_ms,
                    "ingested_count": track.ingested,
                    "pushed_count": track.pushed,
                    **track.extra,
                },
                metadata=metadata,
            )
        )


__all__ = [
    "emit_adapter_event",
    "AdapterEventMixin",
    "SyncTrack",
]
