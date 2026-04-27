"""v265 — Ontology 事件总线 Outbox Relay 配套表 (T5.1.4)

为 FCT Agent 2.0 的 Ontology 事件总线 (shared/events/bus/) 提供:

1. event_outbox_cursor
   - 基础设施单例表 (无 tenant_id, 不启用 RLS)
   - 记录 EventRelay 从 events 表扫描到的最新 sequence
   - 每个 relay 实例一行 (by relay_name)
   - Relay 自身以 RLS bypass 角色运行, 不走租户隔离

2. processed_events
   - Subscriber 消费侧幂等去重表
   - 按 (consumer_group, event_id) 去重, 避免同一事件被同组多实例重复处理
   - 含 tenant_id + RLS (与 projector_checkpoints 模式一致)
   - 金税四期 7 年留痕窗口由 events 主表承担, 此表只用于短期去重

Revision: v265
Revises: v263 (避开 v261 重复版本问题, v264 预留给 Phase 1 差分)
Create Date: 2026-04-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v265"
down_revision = "v263"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ── event_outbox_cursor — Relay 游标 (单例基础设施) ──────────────
    if "event_outbox_cursor" not in existing:
        op.create_table(
            "event_outbox_cursor",
            sa.Column("relay_name", sa.Text, primary_key=True,
                      comment="Relay 实例名, 如 ontology_relay_default"),
            sa.Column("last_event_id", UUID(as_uuid=True), nullable=False,
                      comment="最近一次转发成功的事件 ID"),
            sa.Column("last_sequence", sa.BigInteger, nullable=False,
                      server_default="0",
                      comment="最近一次转发成功的 events.sequence_num"),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            comment="Ontology 事件总线 Outbox Relay 游标表; 无 tenant_id (基础设施单例)",
        )
        # 不启用 RLS — 基础设施表, Relay 以管理员角色访问

    # ── processed_events — 消费侧去重表 ──────────────────────────────
    if "processed_events" not in existing:
        op.create_table(
            "processed_events",
            sa.Column("consumer_group", sa.Text, nullable=False,
                      comment="消费组名, 如 cashflow_alert"),
            sa.Column("event_id", UUID(as_uuid=True), nullable=False,
                      comment="被处理的事件 ID (与 events.event_id 对应)"),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("processed_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("consumer_group", "event_id",
                                    name="pk_processed_events"),
            comment="Subscriber 消费幂等去重表; 配 (consumer_group, event_id) 避免重复处理",
        )
        op.create_index(
            "idx_processed_events_tenant_time",
            "processed_events",
            ["tenant_id", "processed_at"],
            postgresql_using="btree",
        )

        # 启用 RLS (与 projector_checkpoints 模式一致)
        op.execute("ALTER TABLE processed_events ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE processed_events FORCE ROW LEVEL SECURITY;")
        op.execute(
            "DROP POLICY IF EXISTS processed_events_tenant ON processed_events;"
        )
        op.execute("""
            CREATE POLICY processed_events_tenant ON processed_events
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid);
        """)


def downgrade() -> None:
    # 反序删除 (先 RLS, 再索引, 再表)
    op.execute("DROP POLICY IF EXISTS processed_events_tenant ON processed_events;")
    op.execute("DROP INDEX IF EXISTS idx_processed_events_tenant_time;")
    op.execute("DROP TABLE IF EXISTS processed_events;")
    op.execute("DROP TABLE IF EXISTS event_outbox_cursor;")
