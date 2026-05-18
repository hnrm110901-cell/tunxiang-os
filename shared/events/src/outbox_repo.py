"""trade_event_outbox 同事务 INSERT helper (W3 D1 PR-1 C 方案 helper-only).

战略 plan §4 举措 3 "真 Outbox" — 配合 v446 trade_event_outbox 单元 (PR #795 ship)
+ tx-event-relay shadow worker, 让业务事务在同一 PG 事务内 INSERT outbox 行,
relay worker (services/tx-event-relay :8020) 异步 polling 投递, 失败 backoff 重试不丢.

设计约束:
- 接受 caller 的 ``db: AsyncSession`` (不自建 session, 不自建 transaction).
  调用方必须 ``async with db.begin():`` 包裹 — 任何 raise 让整事务 rollback
  (业务表 + journal_entry + outbox 三表原子).
- RLS 必备: 调本 helper 前先 ``SELECT set_config('app.tenant_id', :tid, true)``;
  本 helper 自行调一次 (idempotent, set_config local=true 仅当前事务).
- composite tenant_id 字段必填 (per memory `feedback_multi_tenant_composite_fk_pattern`);
  v446 表已 ENABLE + FORCE RLS, tenant_id 不传或不一致直接 RLS reject.
- payload 强类型 ``dict[str, Any]`` 不接受 raw bytes (防 caller 误传二进制).
- 异常路径 raise ``OutboxInsertError`` (chained via ``__cause__``),
  caller 决定 rollback (本 helper 不主动 rollback 因事务在 caller 控制).

W4 #760 (settle_order GL+outbox 通账) / W5 #768 (refund/recharge) 真接入时,
caller 在自己业务事务内调本 helper.insert(...) 同事务写 outbox.

API signature 与 #760 issue body 描述的 ``TradeEventOutbox(...)`` ORM kwargs 对齐:
``tenant_id / event_type / stream_id / payload / source_service / store_id``
(+ v446 schema 的可选 ``metadata / causation_id / correlation_id``).

本 PR (helper-only) 0 接入业务路径 — 仅交付 helper + 5 单测.
W4 #760 真接入是单独 Tier 1 PR (创始人 explicit approval + §19 multi-round reviewer).
"""

from __future__ import annotations

import json
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class OutboxInsertError(Exception):
    """trade_event_outbox INSERT 失败 — caller 应整事务 rollback.

    原异常通过 ``__cause__`` 链可访问 (``raise ... from exc``).
    """


_SET_TENANT_SQL = text("SELECT set_config('app.tenant_id', :tid, true)")

_INSERT_OUTBOX_SQL = text(
    """
    INSERT INTO trade_event_outbox (
        tenant_id, event_type, stream_id, payload, metadata,
        source_service, store_id, causation_id, correlation_id,
        delivered, delivery_attempts
    ) VALUES (
        :tenant_id, :event_type, :stream_id,
        CAST(:payload AS jsonb), CAST(:metadata AS jsonb),
        :source_service, :store_id, :causation_id, :correlation_id,
        FALSE, 0
    )
    RETURNING id
    """
)


async def insert(
    *,
    db: AsyncSession,
    tenant_id: UUID | str,
    event_type: str,
    stream_id: str,
    payload: dict[str, Any],
    source_service: str,
    store_id: Optional[UUID | str] = None,
    causation_id: Optional[UUID | str] = None,
    correlation_id: Optional[UUID | str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> UUID:
    """同事务 INSERT trade_event_outbox, 返回新 row id.

    Args:
        db: caller 的 AsyncSession (本函数不调 commit/begin);
            调用方必须 ``async with db.begin():`` 包裹.
        tenant_id: 多租户隔离, 必填; 走 RLS ``set_config('app.tenant_id', :tid, true)``.
        event_type: 业务事件类型 (e.g., 'order.paid', 'order.refunded'), 不限 enum 由 caller 拍板;
            约定与 ``shared.events.src.event_types`` 中的枚举 .value 一致.
        stream_id: 业务实体 ID (e.g., ``str(order.id)``).
        payload: JSONB, ``dict[str, Any]``, 序列化为 PG jsonb;
            金额字段约定为分 (整数), 与 ``emit_event`` 同语义.
        source_service: 源服务名 (e.g., 'tx-trade').
        store_id: 门店 UUID (可选).
        causation_id: 触发本事件的父事件 ID (因果链追踪, 可选).
        correlation_id: 同一业务流程的相关 ID (可选).
        metadata: 元数据 (设备/操作员/渠道等, 可选).

    Returns:
        新 INSERT 的 outbox row id (UUID).

    Raises:
        OutboxInsertError: INSERT 失败 (PG / RLS / RETURNING 空 / 任何 SQLAlchemyError),
            caller 应整事务 rollback.
    """
    # 1. 设 RLS (idempotent within transaction, local=true 仅本事务)
    await db.execute(_SET_TENANT_SQL, {"tid": str(tenant_id)})

    # 2. INSERT + RETURNING id
    try:
        result = await db.execute(
            _INSERT_OUTBOX_SQL,
            {
                "tenant_id": str(tenant_id),
                "event_type": event_type,
                "stream_id": stream_id,
                "payload": json.dumps(payload),
                "metadata": json.dumps(metadata or {}),
                "source_service": source_service,
                "store_id": str(store_id) if store_id is not None else None,
                "causation_id": str(causation_id) if causation_id is not None else None,
                "correlation_id": str(correlation_id) if correlation_id is not None else None,
            },
        )
        row = result.fetchone()
        if row is None:
            # 理论上 INSERT ... RETURNING 必返回一行; 兜底防 driver 异常.
            raise OutboxInsertError(
                f"INSERT trade_event_outbox returned no row for stream_id={stream_id}"
            )
        return UUID(str(row[0]))
    except SQLAlchemyError as exc:
        logger.warning(
            "outbox_insert_failed",
            tenant_id=str(tenant_id),
            event_type=event_type,
            stream_id=stream_id,
            source_service=source_service,
            error=str(exc),
            exc_info=True,
        )
        raise OutboxInsertError(
            f"outbox INSERT failed: {exc}"
        ) from exc
