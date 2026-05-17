"""IndexSplitProjector — PRD-11 多人合点成本分摊投影器 (sub-B.2, 2026-05-16)

消费事件:
  order.items_settled (OrderEventType.ITEMS_SETTLED, 由 cashier_engine.settle_order
  fire-and-forget emit, payload 携 items[] = [{order_item_id, dish_id, qty, share_count,
  subtotal_fen}])

业务侧动作:
  对 share_count > 1 的 OrderItem 构造 share_split={method:'even', count:share_count},
  调 auto_deduction.deduct_for_order(share_split=...) 让 sub-A 的 apply_split 真正生效:
    1. BOM 物理扣料 (与 share_count=1 等价, 物理消耗不变)
    2. cost attribution 切分到多 share
    3. emit inventory.split_attributed event (sub-C dashboard 消费)

幂等性 (F2 P0):
  - 每个 IngredientTransaction.source_event_id = uuid5(event_id, ingredient/line/dish/item)
  - v437 UNIQUE (tenant_id, source_event_id) WHERE NOT NULL 让重放命中 IntegrityError
  - SQLAlchemy session 内 SAVEPOINT (db.begin_nested) 捕获 IntegrityError, rollback
    savepoint, 整 event 视为消费成功 (推进 checkpoint)

死信 (F4):
  - share_split_rule 被禁用 / 超 max_share_count / 无规则 → apply_split raise ValueError
  - projector 不阻塞事件流: rollback business savepoint + INSERT
    dlq_split_attribution_failed 表 (sub-C 死信看板消费) + log warning + 推进 checkpoint

数据流隔离 (架构师 D1 ① 推荐):
  - tx-supply 内 service-local, **不**加入全局 ProjectorRegistry (避免污染 mv_* 投影器
    "只读" 心智), 由独立 daemon / lifespan hook 启动
  - 与 mv_inventory_bom 不共享同一事务循环 (业务写不污染视图维护)
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

import structlog
from sqlalchemy.exc import IntegrityError

from shared.events.src.event_types import OrderEventType
from shared.events.src.projector import ProjectorBase
from shared.ontology.src.database import async_session_factory

from ..metrics import record_silent_fallback

log = structlog.get_logger(__name__)

# v437 UNIQUE constraint 名 (constraint name 来自 migration 的 CREATE UNIQUE INDEX 语句)
_DEDUP_UNIQUE_INDEX = "uq_ingredient_transactions_tenant_source_event"


class IndexSplitProjector(ProjectorBase):
    """sub-B.2 投影器 — 消费 ITEMS_SETTLED 触发 share_split BOM 扣料."""

    name = "inventory_split_attribution"
    event_types = {OrderEventType.ITEMS_SETTLED.value}

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        """处理单条 ITEMS_SETTLED 事件.

        Args:
            event: events 表 row dict, 含 event_id/event_type/payload/store_id/occurred_at
            conn:  asyncpg.Connection — projector_base 已 set tenant context. 本投影器
                   只用 conn 写 dlq_split_attribution_failed (业务写另起 SQLAlchemy session)
        """
        event_type = event.get("event_type")
        if event_type != OrderEventType.ITEMS_SETTLED.value:
            # event_types 过滤已生效, 防御性额外校验
            return

        event_id_raw = event.get("event_id")
        if not event_id_raw:
            # 注意: structlog 保留 'event' 关键字, 不可作为 kwarg — 用 raw_event
            log.warning("index_split_event_missing_id", raw_event=event)
            return
        event_id: uuid.UUID = (
            event_id_raw if isinstance(event_id_raw, uuid.UUID) else uuid.UUID(str(event_id_raw))
        )

        payload = event.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                log.warning(
                    "index_split_payload_malformed",
                    event_id=str(event_id),
                    payload_type=type(payload).__name__,
                )
                return

        items_raw = payload.get("items") or []
        if not isinstance(items_raw, list) or not items_raw:
            # 空 items[] = 无 OrderItem (空单 settle), 静默推进 checkpoint
            log.info("index_split_no_items", event_id=str(event_id))
            return

        # §19 round-1 P0 fix — cashier_engine.settle_order emit ITEMS_SETTLED payload
        # 字段名为 "order_no" (订单号字符串), order_id 由 emit_event 的 stream_id 参数
        # 传入 events 表 stream_id 列. projector_base._fetch_next_batch SELECT 出来
        # event 字典含 stream_id. 用 stream_id 作 order_id 来源 (payload.order_id 兜底
        # 兼容未来 cashier 显式补字段).
        order_id = payload.get("order_id") or event.get("stream_id")
        store_id = payload.get("store_id") or event.get("store_id")
        if not order_id or not store_id:
            log.warning(
                "index_split_missing_order_or_store",
                event_id=str(event_id),
                order_id=order_id,
                store_id=store_id,
            )
            return

        # 过滤 share_count > 1 的 OrderItem (share_count == 1 单人独享, 无需 attribution)
        share_items: list[dict[str, Any]] = []
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            share_count = it.get("share_count") or 1
            try:
                share_count_int = int(share_count)
            except (TypeError, ValueError):
                continue
            if share_count_int <= 1:
                continue
            dish_id = it.get("dish_id")
            if not dish_id:
                continue
            share_items.append(
                {
                    "dish_id": str(dish_id),
                    "quantity": int(it.get("qty") or 1),
                    "order_item_id": str(it["order_item_id"]) if it.get("order_item_id") else None,
                    "share_split": {
                        "method": "even",
                        "count": share_count_int,
                    },
                }
            )

        if not share_items:
            # 全单 share_count=1 — 无 attribution 需要触发, 推进 checkpoint
            log.info("index_split_no_share_items", event_id=str(event_id))
            return

        # 业务写: 独立 SQLAlchemy session (与 projector_base 的 asyncpg conn 分离),
        # SAVEPOINT 内调 deduct_for_order, IntegrityError 捕获 (F2 dedup) / ValueError
        # 捕获 (F4 dlq).
        # Lazy import 避免 module-load cycle (auto_deduction imports tx-supply models).
        from ..services.auto_deduction import deduct_for_order

        tenant_id_str = str(self.tenant_id)
        async with async_session_factory() as db:
            try:
                async with db.begin():
                    await deduct_for_order(
                        order_id=str(order_id),
                        order_items=share_items,
                        store_id=str(store_id),
                        tenant_id=tenant_id_str,
                        db=db,
                        source_event_id=event_id,
                    )
            except IntegrityError as ie:
                # F2 P0 — UNIQUE (tenant_id, source_event_id) 命中 = 重放
                if _is_dedup_violation(ie):
                    log.info(
                        "index_split_dedup_skip",
                        event_id=str(event_id),
                        tenant_id=tenant_id_str,
                        order_id=str(order_id),
                    )
                    return
                # 其他 IntegrityError (FK / NOT NULL / 不相关 UNIQUE) 走死信
                await _dlq_insert(
                    conn=conn,
                    tenant_id=self.tenant_id,
                    event_id=event_id,
                    event=event,
                    error_class=type(ie).__name__,
                    error_msg=str(ie.orig) if getattr(ie, "orig", None) else str(ie),
                )
                log.warning(
                    "index_split_dlq_integrity",
                    event_id=str(event_id),
                    constraint=getattr(getattr(ie, "orig", None), "constraint_name", None),
                )
                return
            except ValueError as ve:
                # F4 — share_split_rule 禁用/超上限/无规则: skip + dlq
                await _dlq_insert(
                    conn=conn,
                    tenant_id=self.tenant_id,
                    event_id=event_id,
                    event=event,
                    error_class="ValueError",
                    error_msg=str(ve),
                )
                log.warning(
                    "index_split_dlq_rule_violation",
                    event_id=str(event_id),
                    error=str(ve),
                )
                return

        log.info(
            "index_split_attributed",
            event_id=str(event_id),
            tenant_id=tenant_id_str,
            order_id=str(order_id),
            share_item_count=len(share_items),
        )


def _is_dedup_violation(ie: IntegrityError) -> bool:
    """检测 IntegrityError 是否由 v437 source_event_id UNIQUE 触发.

    asyncpg UniqueViolationError 暴露 constraint_name (来自 PG SQLSTATE 23505 metadata).
    SQLAlchemy 在 ie.orig 上保留 asyncpg 原异常.
    """
    orig = getattr(ie, "orig", None)
    if orig is None:
        return False
    constraint = getattr(orig, "constraint_name", None)
    if constraint == _DEDUP_UNIQUE_INDEX:
        return True
    # 防御: 部分驱动包路径不暴露 constraint_name, 退化用 detail 字符串匹配
    detail = getattr(orig, "detail", "") or ""
    return _DEDUP_UNIQUE_INDEX in str(detail) or _DEDUP_UNIQUE_INDEX in str(ie)


async def _dlq_insert(
    conn: object,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    event: dict[str, Any],
    error_class: str,
    error_msg: str,
) -> None:
    """写 dlq_split_attribution_failed 死信表 (F4 错误处理 D3 ①).

    用 projector_base 的 asyncpg conn 直接 INSERT (RLS context 已由 _process_backlog
    SELECT set_config('app.tenant_id', ...) 设置, 本表 RLS 策略 WITH CHECK 通过).
    """
    payload = event.get("payload") or {}
    if isinstance(payload, (dict, list)):
        payload_json = json.dumps(payload, default=str)
    else:
        payload_json = json.dumps(str(payload))
    # §19 round-2 P2 follow-up: order_id 与 handle() 主路径对齐取 stream_id 兜底
    # (cashier_engine payload 只有 order_no, 真 order_id 在 stream_id 列). 避免 DLQ
    # 行 order_id 永远 NULL 导致 sub-C 看板无法直接 JOIN orders.
    order_id = (
        (payload.get("order_id") if isinstance(payload, dict) else None)
        or event.get("stream_id")
    )
    items = payload.get("items") if isinstance(payload, dict) else None
    first_item = items[0] if isinstance(items, list) and items else {}
    order_item_id = first_item.get("order_item_id") if isinstance(first_item, dict) else None
    dish_id = first_item.get("dish_id") if isinstance(first_item, dict) else None

    occurred_at = event.get("occurred_at")
    # §19 round-1 P1 fix — projector_base._process_backlog 先 set_config(...TRUE)
    # 是 autocommit 模式下的语句级事务, 提交后 transaction-local 设置即失效;
    # 进入随后的 conn.transaction() 时 app.tenant_id 已为空, dlq 表 FORCE RLS WITH CHECK
    # NULL=NULL false → INSERT 被拒. 此处显式补设 tenant context (FALSE = session-level
    # 在 conn.transaction() 内仍有效) 让 RLS WITH CHECK 通过.
    await conn.execute(  # type: ignore[attr-defined]
        "SELECT set_config('app.tenant_id', $1, FALSE)",
        str(tenant_id),
    )
    await conn.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO dlq_split_attribution_failed
            (tenant_id, event_id, event_type, order_id, order_item_id, dish_id,
             error_class, error_msg, payload, occurred_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
        """,
        tenant_id,
        event_id,
        str(event.get("event_type") or ""),
        _safe_uuid(order_id),
        _safe_uuid(order_item_id),
        _safe_uuid(dish_id),
        error_class[:80],
        error_msg[:4000],
        payload_json,
        occurred_at,
    )


def _safe_uuid(val: Optional[Any]) -> Optional[uuid.UUID]:
    if not val:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError) as exc:
        log.warning(
            "index_split_event_parse_malformed_uuid",
            raw_value=str(val)[:200],
            error=str(exc),
        )
        record_silent_fallback("index_split.event_parse")
        return None
