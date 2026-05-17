"""SplitAttributionProjector — PRD-11 sub-C cost attribution 汇总投影器 (2026-05-16).

消费事件:
  inventory.split_attributed (InventoryEventType.SPLIT_ATTRIBUTED, 由
  tx-supply auto_deduction.deduct_for_dish 在 share_split 路径 fire-and-forget emit,
  payload 携 {order_id, order_item_id, dish_id, method, count, bom_cost_total_fen,
  shares: [{share_index, weight, attributed_cost_fen}, ...]})

业务侧动作:
  写入 cost_attribution_summary 表 (v438), sub-C dashboard 3 个 endpoint 直接读本表:
    - GET /cost-attribution/orders/{order_id}    单订单 share 切分明细
    - GET /cost-attribution/dishes/{dish_id}/summary  单菜 share_count 分布 + 平均
    - GET /cost-attribution/summary?from=&to=    时段总览

幂等性 (F2):
  - 每行 source_event_id = event.event_id, v438 UNIQUE (tenant_id, source_event_id)
  - asyncpg ON CONFLICT DO NOTHING 静默吞 dedup, 重放任意次数行数不变

错误处理 (F4):
  - payload 缺字段 / 类型错 → log warning + 静默跳过 (推进 checkpoint, 不阻塞事件流)
  - 不写 DLQ — sub-C 是 consumer 端汇总, 上游 sub-B.2 已在死信表落盘真正失败的事件;
    本投影器再写 DLQ 会重复且语义错位

数据流隔离:
  - tx-analytics 内 service-local, 不加入全局 ProjectorRegistry (mv_* 投影器是
    "只读"语义, 本投影器是 attribution 汇总 INSERT, 性质不同)
  - 与 mv_inventory_bom 不共享同一事务循环
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from shared.events.src.event_types import InventoryEventType
from shared.events.src.projector import ProjectorBase

log = structlog.get_logger(__name__)


class SplitAttributionProjector(ProjectorBase):
    """sub-C 投影器 — 消费 SPLIT_ATTRIBUTED 写入 cost_attribution_summary."""

    name = "cost_attribution_summary"
    event_types = {InventoryEventType.SPLIT_ATTRIBUTED.value}

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        """处理单条 SPLIT_ATTRIBUTED 事件.

        Args:
            event: events 表 row dict, 含 event_id/event_type/payload/store_id/occurred_at
            conn:  asyncpg.Connection — projector_base 已 set tenant context, 本投影器
                   只用 conn INSERT cost_attribution_summary
        """
        event_type = event.get("event_type")
        if event_type != InventoryEventType.SPLIT_ATTRIBUTED.value:
            # event_types 过滤已生效, 防御性额外校验
            return

        event_id_raw = event.get("event_id")
        if not event_id_raw:
            # 注意: structlog 保留 'event' 关键字, 不可作为 kwarg — 用 raw_event
            log.warning("split_attribution_event_missing_id", raw_event=event)
            return
        event_id: uuid.UUID = (
            event_id_raw
            if isinstance(event_id_raw, uuid.UUID)
            else uuid.UUID(str(event_id_raw))
        )

        payload = event.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                log.warning(
                    "split_attribution_payload_malformed",
                    event_id=str(event_id),
                    payload_type=type(payload).__name__,
                )
                return
        if not isinstance(payload, dict):
            log.warning(
                "split_attribution_payload_not_dict",
                event_id=str(event_id),
                payload_type=type(payload).__name__,
            )
            return

        method = payload.get("method")
        share_count_raw = payload.get("count")
        bom_cost_total_fen_raw = payload.get("bom_cost_total_fen")
        shares = payload.get("shares")

        if not method or share_count_raw is None or bom_cost_total_fen_raw is None:
            log.warning(
                "split_attribution_payload_missing_fields",
                event_id=str(event_id),
                method=method,
                share_count=share_count_raw,
                bom_cost_total_fen=bom_cost_total_fen_raw,
            )
            return

        try:
            share_count = int(share_count_raw)
            bom_cost_total_fen = int(bom_cost_total_fen_raw)
        except (TypeError, ValueError):
            log.warning(
                "split_attribution_payload_type_error",
                event_id=str(event_id),
            )
            return

        if not isinstance(shares, list):
            # 兜底: shares 不是数组 — 写空数组占位 (downstream dashboard 渲染能容错)
            shares = []

        order_id = payload.get("order_id") or event.get("stream_id")
        order_item_id = payload.get("order_item_id")
        dish_id = payload.get("dish_id")
        occurred_at = event.get("occurred_at")

        # shares 转 JSON 字符串 (asyncpg ::jsonb cast)
        shares_json = json.dumps(shares, default=str)

        # v438 RLS FORCE WITH CHECK — projector_base._process_backlog 用 TRUE
        # (transaction-local) set_config, 进入新事务后失效; 此处显式补 FALSE
        # session-level 让 INSERT 通过 WITH CHECK. 与 tx-supply IndexSplitProjector
        # _dlq_insert 同一对策 (sub-B.2 §19 round-1 P1 fix 同源教训).
        await conn.execute(  # type: ignore[attr-defined]
            "SELECT set_config('app.tenant_id', $1, FALSE)",
            str(self.tenant_id),
        )
        await conn.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO cost_attribution_summary
                (tenant_id, source_event_id, order_id, order_item_id, dish_id,
                 method, share_count, bom_cost_total_fen, shares, occurred_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
            ON CONFLICT (tenant_id, source_event_id) DO NOTHING
            """,
            self.tenant_id,
            event_id,
            _safe_uuid(order_id),
            _safe_uuid(order_item_id),
            _safe_uuid(dish_id),
            str(method)[:40],
            share_count,
            bom_cost_total_fen,
            shares_json,
            occurred_at,
        )

        log.info(
            "split_attribution_summary_written",
            event_id=str(event_id),
            tenant_id=str(self.tenant_id),
            order_id=str(order_id) if order_id else None,
            method=method,
            share_count=share_count,
            bom_cost_total_fen=bom_cost_total_fen,
        )


def _safe_uuid(val: Any) -> uuid.UUID | None:
    if not val:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError) as exc:
        # 畸形 UUID payload (PRD-11 sub-C event 字段 source_doc_id /
        # source_doc_line_id 偶有非 UUID 字符串). 沿用 tx-supply
        # IndexSplitProjector _safe_uuid 同模式 (PR #752 sub-D):
        # 保留 return None 让 caller 落 NULL 不阻塞 projector 推进,
        # warn level 给运维可观测.
        log.warning(
            "split_attribution_safe_uuid_invalid",
            raw_value=str(val)[:40],
            error=str(exc),
        )
        return None
