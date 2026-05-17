"""v443 — GL 内核凭证主表骨架（W3 P0 #756 第 3/4 / Tier1 邻接）

业务背景：
  凭证（journal entry）是 GL 双分录的载体。每个业务事件（订单结算/退款/储值充值）
  生成一张凭证，凭证下含 N 条 journal_line（借贷必须平衡）。
  - status 状态机：draft（草稿）→ posted（已过账）→ reversed（已冲销）
  - business_event_id 关联 v147+ 统一事件总线（W3 真 Outbox #757 上线后改 NOT NULL）
  - reverse_of_entry_id 自引用 FK 形成冲销链（红字凭证），ON DELETE SET NULL 保护链路
  - entry_no 凭证号在期内唯一（per posting_period），按租户隔离

设计要点：
  - FK posting_period_id → v441 posting_period.id，ON DELETE RESTRICT 防止结清后误删
  - 自引用 reverse_of_entry_id → journal_entry.id，ON DELETE SET NULL（被冲销原票被删时
    新凭证退化为无冲销链元数据，不级联爆炸）
  - UNIQUE (tenant_id, posting_period_id, entry_no) 防同期同号
  - status 三态 CHECK + posted_at 与 status='posted' 一致性 CHECK
  - source_service 标注来源（tx-trade/tx-finance/etc）便于审计
  - RLS 四联（ENABLE + FORCE + POLICY + WITH CHECK）
  - inspector-and-skip 幂等模式

Migration 链：
  v442_chart_of_accounts → v443_journal_entry (本 PR 3/4)

Revision ID: v443_journal_entry
Revises: v442_chart_of_accounts
Create Date: 2026-05-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v443_journal_entry"
down_revision: Union[str, Sequence[str], None] = "v442_chart_of_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ─────────────────────────────────────────────────────────────────────────
    # GL 4/4 之 3: journal_entry 凭证主表
    # ─────────────────────────────────────────────────────────────────────────
    if "journal_entry" not in existing:
        op.execute(
            """
            CREATE TABLE journal_entry (
                id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id               UUID NOT NULL,
                posting_period_id       UUID NOT NULL,
                business_event_id       UUID,
                entry_no                VARCHAR(32) NOT NULL,
                status                  VARCHAR(16) NOT NULL DEFAULT 'draft',
                posted_at               TIMESTAMPTZ,
                source_service          VARCHAR(32) NOT NULL,
                operator_id             UUID,
                reverse_of_entry_id     UUID,
                memo                    TEXT,
                created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_je_status
                    CHECK (status IN ('draft', 'posted', 'reversed')),
                CONSTRAINT chk_je_posted_at_consistency
                    CHECK (status != 'posted' OR posted_at IS NOT NULL),
                CONSTRAINT fk_je_posting_period
                    FOREIGN KEY (posting_period_id)
                    REFERENCES posting_period (id)
                    ON DELETE RESTRICT,
                CONSTRAINT fk_je_reverse_of
                    FOREIGN KEY (reverse_of_entry_id)
                    REFERENCES journal_entry (id)
                    ON DELETE SET NULL
            )
            """
        )
        op.execute("ALTER TABLE journal_entry ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE journal_entry FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY journal_entry_tenant_isolation
            ON journal_entry
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        # 期内凭证号唯一（软删除后允许复用同号）
        op.execute(
            """
            CREATE UNIQUE INDEX uq_je_tenant_period_entry_no
            ON journal_entry (tenant_id, posting_period_id, entry_no)
            WHERE is_deleted = FALSE
            """
        )
        # 主查询入口：按租户 + 期 + 状态筛选已过账凭证
        op.execute(
            """
            CREATE INDEX idx_je_tenant_period_status
            ON journal_entry (tenant_id, posting_period_id, status)
            WHERE is_deleted = FALSE
            """
        )
        # 业务事件反查：通过 business_event_id 追溯凭证（W4 settle_order 接入后高频）
        op.execute(
            """
            CREATE INDEX idx_je_business_event
            ON journal_entry (tenant_id, business_event_id)
            WHERE business_event_id IS NOT NULL AND is_deleted = FALSE
            """
        )
        # 冲销链反查：找一张凭证的所有冲销票
        op.execute(
            """
            CREATE INDEX idx_je_reverse_of
            ON journal_entry (tenant_id, reverse_of_entry_id)
            WHERE reverse_of_entry_id IS NOT NULL AND is_deleted = FALSE
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # journal_line FK 依赖 journal_entry.id，CASCADE 保护
    if "journal_entry" in existing:
        op.execute("DROP TABLE journal_entry CASCADE")
