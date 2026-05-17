"""v443 — GL 内核凭证主表骨架（W3 P0 #756 第 3/4 / Tier1 邻接）

业务背景：
  凭证（journal entry）是 GL 双分录的载体。每个业务事件（订单结算/退款/储值充值）
  生成一张凭证，凭证下含 N 条 journal_line（借贷必须平衡）。
  - status 状态机：draft（草稿）→ posted（已过账）→ reversed（已冲销）
  - business_event_id + business_event_occurred_at 复合 FK 到 v147 events
    （round-1 §19 critic P0-3 Q1=A 修：原 business_event_id 是孤儿列无 FK，
    随 events 软删/重建会有孤儿。events 是 PARTITION BY RANGE (occurred_at) 分区表，
    PG 12+ 支持 composite FK 到分区表 PK = (event_id, occurred_at)；DEFERRABLE
    INITIALLY DEFERRED 让 W4 settle_order 可在同事务内先写 events 再写 journal_entry）
  - reverse_of_entry_id 自引用 composite FK 形成冲销链（红字凭证），ON DELETE SET NULL
    （round-1 §19 security P0-2 修：原 single-col 自引用 FK 允许跨租户被冲销）
  - entry_no 凭证号在期内唯一（per posting_period），按租户隔离

设计要点：
  - 复合 UNIQUE (tenant_id, id) → 让 reverse_of 自引用 + journal_line composite FK
    都能"同租户引用"（round-1 §19 security P0-2 / P1-1 修）
  - FK posting_period 改 composite (tenant_id, posting_period_id) → posting_period
    (tenant_id, id)，PG 原生防跨租户引用（round-1 §19 security P0-1 修）
  - FK reverse_of_entry_id 改 composite (tenant_id, reverse_of_entry_id) → self
    (tenant_id, id)，ON DELETE SET NULL（round-1 §19 security P0-2 修）
  - FK business_event 复合 (business_event_id, business_event_occurred_at) → events
    (event_id, occurred_at)，ON DELETE RESTRICT + DEFERRABLE INITIALLY DEFERRED
    （round-1 §19 critic P0-3 Q1=A 修，W4 settle_order 同事务先 emit_event 再写 je）
  - status 三态 CHECK + **双向 CHECK**：posted_at 与 status='posted' / reversed_of_entry_id
    与 status='reversed' 一致性（round-1 §19 P1-5 security #17 修）
  - status='reversed' ⇔ reverse_of_entry_id NOT NULL CHECK（round-1 §19 security #17）
  - source_service 标注来源（tx-trade/tx-finance/etc）便于审计
  - RLS 四联（ENABLE + FORCE + POLICY + WITH CHECK）— v139 NULLIF::uuid 模式
    （round-1 §19 critic P1-1 修）
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
                id                          UUID NOT NULL DEFAULT gen_random_uuid(),
                tenant_id                   UUID NOT NULL,
                posting_period_id           UUID NOT NULL,
                business_event_id           UUID,
                business_event_occurred_at  TIMESTAMPTZ,
                entry_no                    VARCHAR(32) NOT NULL,
                status                      VARCHAR(16) NOT NULL DEFAULT 'draft',
                posted_at                   TIMESTAMPTZ,
                source_service              VARCHAR(32) NOT NULL,
                operator_id                 UUID,
                reverse_of_entry_id         UUID,
                memo                        TEXT,
                created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT pk_journal_entry
                    PRIMARY KEY (id),
                CONSTRAINT uq_journal_entry_tenant_id
                    UNIQUE (tenant_id, id),
                CONSTRAINT chk_je_status
                    CHECK (status IN ('draft', 'posted', 'reversed')),
                CONSTRAINT chk_je_status_consistency CHECK (
                    (status = 'draft' AND posted_at IS NULL)
                    OR (status = 'posted' AND posted_at IS NOT NULL)
                    OR (status = 'reversed' AND posted_at IS NOT NULL
                        AND reverse_of_entry_id IS NOT NULL)
                ),
                CONSTRAINT chk_je_reverse_consistency
                    CHECK (status != 'reversed' OR reverse_of_entry_id IS NOT NULL),
                CONSTRAINT chk_je_business_event_pair
                    CHECK (
                        (business_event_id IS NULL AND business_event_occurred_at IS NULL)
                        OR (business_event_id IS NOT NULL AND business_event_occurred_at IS NOT NULL)
                    ),
                CONSTRAINT fk_je_posting_period
                    FOREIGN KEY (tenant_id, posting_period_id)
                    REFERENCES posting_period (tenant_id, id)
                    ON DELETE RESTRICT,
                CONSTRAINT fk_je_reverse_of
                    FOREIGN KEY (tenant_id, reverse_of_entry_id)
                    REFERENCES journal_entry (tenant_id, id)
                    ON DELETE SET NULL,
                CONSTRAINT fk_je_business_event
                    FOREIGN KEY (business_event_id, business_event_occurred_at)
                    REFERENCES events (event_id, occurred_at)
                    ON DELETE RESTRICT
                    DEFERRABLE INITIALLY DEFERRED
            )
            """
        )
        op.execute("ALTER TABLE journal_entry ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE journal_entry FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY journal_entry_tenant_isolation
            ON journal_entry
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
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

    # journal_line FK 依赖 journal_entry.(tenant_id, id)，CASCADE 保护
    if "journal_entry" in existing:
        op.execute("DROP TABLE journal_entry CASCADE")
