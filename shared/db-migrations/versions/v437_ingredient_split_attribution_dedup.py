"""v437 — IndexSplitProjector 幂等键 + 死信表 (PRD-11 sub-B.2 / Phase 2 W11 闭环 / Tier 1 第 30 例)

业务背景：
  PRD-11 sub-A (v434 share_split_rules) 配置层 ✅ ship
  PRD-11 sub-B (v436 OrderItem.share_count + ITEMS_SETTLED emit) Tier 1 第 29 例 ✅ ship
  本 PR (sub-B.2) — tx-supply 内 IndexSplitProjector 消费 ITEMS_SETTLED, 调
  auto_deduction.deduct_for_order(share_split=...) 物理扣料 + emit
  inventory.split_attributed event. 闭环 PRD-11 数据流.

设计要点（D1-D4 创始人 5/15 锁定）：
  - F2 P0 防重复扣料 (projector crash 重放) — ingredient_transactions ADD
    source_event_id UUID NULLABLE + UNIQUE 部分索引 (tenant_id, source_event_id)
    WHERE source_event_id IS NOT NULL. NULLABLE 保 backward compat (非 projector 路径
    INSERT 不强制提供; sub-B.2 路径必须提供, 由 projector 拿 event.event_id 作 dedup 键)
  - F4 死信表 dlq_split_attribution_failed — share_split_rule 禁用/超上限/无规则等
    apply_split ValueError 时 projector skip + 写本表; sub-C 死信看板从本表读
  - RLS 四联标准模式 (ENABLE + FORCE + POLICY + WITH CHECK), 与 v434/v435 一致
  - inspector-and-skip 模式 (与 v421+ 一致)

幂等语义（race-safe）：
  - projector handle() 在 SQLAlchemy SAVEPOINT 内调 deduct_for_order
  - source_event_id UNIQUE 在 INSERT 时触 IntegrityError → projector catch + rollback
    savepoint + log "dedup_skip" + 推进 checkpoint (视为消费成功)
  - 同 event_id 重放任意次数 ingredient_transactions row count 不变

Revision ID: v437_ingredient_split_attribution_dedup
Revises: v436_order_item_share_count
Create Date: 2026-05-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v437_ingredient_split_attribution_dedup"
down_revision: Union[str, Sequence[str], None] = "v436_order_item_share_count"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ── (1) ingredient_transactions.source_event_id UUID NULLABLE + UNIQUE 部分索引
    if "ingredient_transactions" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("ingredient_transactions")}
        if "source_event_id" not in existing_cols:
            op.execute(
                "ALTER TABLE ingredient_transactions ADD COLUMN source_event_id UUID"
            )
        existing_indexes = {ix["name"] for ix in inspector.get_indexes("ingredient_transactions")}
        if "uq_ingredient_transactions_tenant_source_event" not in existing_indexes:
            # PG14+ partial UNIQUE index — NULL 不参与唯一性, 非 projector 路径不冲突.
            # projector 必须传 source_event_id, 同 event_id 重放第二条 INSERT 触
            # IntegrityError (asyncpg.exceptions.UniqueViolationError).
            op.execute(
                """
                CREATE UNIQUE INDEX uq_ingredient_transactions_tenant_source_event
                ON ingredient_transactions (tenant_id, source_event_id)
                WHERE source_event_id IS NOT NULL
                """
            )

    # ── (2) dlq_split_attribution_failed 死信表 + RLS 四联
    if "dlq_split_attribution_failed" not in existing_tables:
        op.execute(
            """
            CREATE TABLE dlq_split_attribution_failed (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id       UUID NOT NULL,
                event_id        UUID NOT NULL,
                event_type      VARCHAR(80) NOT NULL,
                order_id        UUID,
                order_item_id   UUID,
                dish_id         UUID,
                error_class     VARCHAR(80) NOT NULL,
                error_msg       TEXT NOT NULL,
                payload         JSONB NOT NULL,
                occurred_at     TIMESTAMPTZ NOT NULL,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                acknowledged_at TIMESTAMPTZ,
                acknowledged_by UUID,
                ack_notes       TEXT
            )
            """
        )
        op.execute("ALTER TABLE dlq_split_attribution_failed ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE dlq_split_attribution_failed FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY dlq_split_attribution_failed_tenant_isolation
            ON dlq_split_attribution_failed
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        # 主查询入口: 未确认死信 (sub-C 看板按 tenant 倒序展示)
        op.execute(
            """
            CREATE INDEX idx_dlq_split_attribution_failed_tenant_unack
            ON dlq_split_attribution_failed (tenant_id, occurred_at DESC)
            WHERE acknowledged_at IS NULL
            """
        )
        # event_id 反查 (排查 / 防同 event 二次入死信)
        op.execute(
            """
            CREATE INDEX idx_dlq_split_attribution_failed_tenant_event
            ON dlq_split_attribution_failed (tenant_id, event_id)
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "dlq_split_attribution_failed" in existing_tables:
        op.execute("DROP TABLE dlq_split_attribution_failed CASCADE")

    if "ingredient_transactions" in existing_tables:
        existing_indexes = {ix["name"] for ix in inspector.get_indexes("ingredient_transactions")}
        if "uq_ingredient_transactions_tenant_source_event" in existing_indexes:
            op.execute("DROP INDEX uq_ingredient_transactions_tenant_source_event")
        existing_cols = {c["name"] for c in inspector.get_columns("ingredient_transactions")}
        if "source_event_id" in existing_cols:
            op.drop_column("ingredient_transactions", "source_event_id")
