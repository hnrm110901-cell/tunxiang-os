"""v446 — 真 Outbox 表 trade_event_outbox（W3 P0 issue #757 / Tier1 邻接）

业务背景:
  战略 plan §4 举措 3 "真 Outbox" — 现行 emit_event fire-and-forget 走 Redis Stream +
  PG events 表双写, 推送失败 silent (PG 失败返 None, Redis create_task 不等待),
  Tier 1 资金/状态机/库存事件丢失风险 P0.

  本表为 trade-side 业务事务的 outbox 单元: 业务写入路径在同事务内 INSERT outbox
  (与业务表同事务原子保证), 由独立 worker (services/tx-event-relay, port 8020)
  异步 polling 投递到 events 表 + Redis Stream, 失败 backoff 重试不丢.

设计要点 (创始人 explicit-ask 4 问决议):
  - Q1 = A: 推送成功后 INSERT events + UPDATE outbox.delivered=true 同事务 +
    delivered_event_id 回填 + 30d GC. 故 schema 含 delivered_event_id UUID NULL
    + chk_outbox_delivered_consistency CHECK 约束防不一致状态.
  - Q2 = 8020: tx-event-relay 服务端口 (base.yml 8000-8019 全占).
  - Q3 = 30d GC: shadow 期间 outbox 不真投递; W11 follow-up 立 cron DELETE WHERE
    delivered=true AND delivered_at < NOW() - INTERVAL '30 days'.
  - Q4 = T3 default off: Helm chart PDB/NetPol/ConfigMap 全 disabled, W11 切真路径
    follow-up issue 评估升 T2/T1.

  - 非分区表: shadow 期间预期 0 行, W4-W5 接入业务后单表可承载 < 100w 行/月,
    GC 周期足以避免无限增长 (vs v147 events 表 PARTITION BY RANGE 永存语义不同).
  - 不加 FK to events 表: outbox 是 write-buffer (业务事务同写) / events 是
    read-model (投递成功后才填), 写入时 events 表里 stream_id 对应 event 还不存在;
    delivered_event_id 字段为 NULL → events.event_id 回填, 设计 A 下仅作回查不作
    约束. W4 follow-up issue 评估是否补 composite FK (本 PR 不引入).
  - RLS 四联 (ENABLE + FORCE + POLICY + WITH CHECK), NULLIF::UUID 模式严格对齐
    v147 events 标准 (不用 ::text 弱比对, #756 round-1 P1-1 教训).
  - inspector-and-skip 幂等模式 (与 v444 / v445 一致).
  - 3 个 partial index 按职责 (relay polling 主路径 / 单聚合根回放 / 监控积压).

Migration 链:
  v445_cost_center_dictionary → v446_create_trade_event_outbox (本 PR W3 #757)

Revision ID: v446_create_trade_event_outbox
Revises: v445_cost_center_dictionary
Create Date: 2026-05-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v446_create_trade_event_outbox"
down_revision: Union[str, Sequence[str], None] = "v445_cost_center_dictionary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ─────────────────────────────────────────────────────────────────────────
    # trade_event_outbox 真 Outbox 单元
    # ─────────────────────────────────────────────────────────────────────────
    if "trade_event_outbox" not in existing:
        op.execute(
            """
            CREATE TABLE trade_event_outbox (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                -- 业务字段 (与 v147 events 表对齐)
                event_type          VARCHAR(128) NOT NULL,
                stream_id           VARCHAR(255) NOT NULL,
                payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
                metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
                source_service      VARCHAR(64) NOT NULL DEFAULT 'unknown',
                store_id            UUID,
                -- 因果链字段 (与 emit_event signature 对齐, W4 接入 settle_order 复用)
                causation_id        UUID,
                correlation_id      UUID,
                -- Outbox 调度字段
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                delivered           BOOLEAN NOT NULL DEFAULT FALSE,
                delivered_at        TIMESTAMPTZ,
                delivery_attempts   INTEGER NOT NULL DEFAULT 0,
                last_attempt_at     TIMESTAMPTZ,
                last_error          TEXT,
                -- 设计 A: delivered → events.event_id 回填 (NULL 直到投递成功)
                delivered_event_id  UUID,
                CONSTRAINT chk_outbox_attempts_nonneg
                    CHECK (delivery_attempts >= 0),
                CONSTRAINT chk_outbox_delivered_consistency
                    CHECK (
                        (delivered = FALSE AND delivered_at IS NULL AND delivered_event_id IS NULL)
                        OR (delivered = TRUE AND delivered_at IS NOT NULL)
                    )
            )
            """
        )
        op.execute("ALTER TABLE trade_event_outbox ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE trade_event_outbox FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY trade_event_outbox_tenant_isolation
            ON trade_event_outbox
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )
        # relay polling 主路径: 找未投递事件按创建时间升序
        op.execute(
            """
            CREATE INDEX idx_outbox_pending
            ON trade_event_outbox (created_at)
            WHERE delivered = FALSE
            """
        )
        # 单聚合根回放 / 调试: 按租户+stream查事件链
        op.execute(
            """
            CREATE INDEX idx_outbox_tenant_stream
            ON trade_event_outbox (tenant_id, stream_id, created_at DESC)
            """
        )
        # 监控: 按租户统计积压数
        op.execute(
            """
            CREATE INDEX idx_outbox_tenant_pending
            ON trade_event_outbox (tenant_id)
            WHERE delivered = FALSE
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "trade_event_outbox" in existing:
        op.execute("DROP TABLE trade_event_outbox CASCADE")
