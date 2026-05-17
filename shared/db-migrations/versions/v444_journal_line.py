"""v444 — GL 内核凭证明细骨架（W3 P0 #756 第 4/4 / Tier1 邻接）

业务背景：
  凭证明细（journal line）承载具体的借贷金额。每条 line 必须指向一个末级科目，
  且借方/贷方有且只有一方为正（不允许双零空行，不允许双边都有金额）。
  - debit_fen / credit_fen 单位为分（BIGINT），与 v147 事件总线金额规范一致
  - cost_center 标注业态/门店/部门维度，便于 P&L 切片（W5 接入 cost_center_dictionary）
  - account_code 通过 composite FK (tenant_id, account_code) 引用 chart_of_accounts，
    PG 原生防跨租户引用（feedback 5 项：composite FK 更稳）
  - entry_id 通过 composite FK (tenant_id, entry_id) 引用 journal_entry，
    PG 原生防跨租户 line 挂到他租户 entry（round-1 §19 security P1-1 修）
  - tenant_id 显式列方便 RLS policy 直接判定，不依赖 entry_id JOIN

设计要点：
  - FK entry_id 改 composite (tenant_id, entry_id) → journal_entry (tenant_id, id),
    ON DELETE RESTRICT 防误删凭证后明细悬空（round-1 §19 security P1-1 修）
  - Composite FK (tenant_id, account_code) → chart_of_accounts (tenant_id, account_code)
    ON DELETE RESTRICT — PG 强制同租户，无需 trigger
  - CHECK (debit_fen >= 0 AND credit_fen >= 0) — 借贷不可负
  - CHECK 借贷互斥：要么 debit > 0 credit = 0，要么 debit = 0 credit > 0（不允许双零/双正）
  - UNIQUE (entry_id, line_no) — 凭证内行号唯一
  - RLS 四联（ENABLE + FORCE + POLICY + WITH CHECK）— v139 NULLIF::uuid 模式
    （round-1 §19 critic P1-1 修：与 v441/v442/v443 对齐）
  - inspector-and-skip 幂等模式

Migration 链：
  v443_journal_entry → v444_journal_line (本 PR 4/4, GL 4 表骨架收官)
                    → v445_cost_center_dictionary (本 PR 5/5, round-1 §19 critic P1-2 新增)

Revision ID: v444_journal_line
Revises: v443_journal_entry
Create Date: 2026-05-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v444_journal_line"
down_revision: Union[str, Sequence[str], None] = "v443_journal_entry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ─────────────────────────────────────────────────────────────────────────
    # GL 4/4 之 4: journal_line 凭证明细
    # ─────────────────────────────────────────────────────────────────────────
    if "journal_line" not in existing:
        op.execute(
            """
            CREATE TABLE journal_line (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                entry_id            UUID NOT NULL,
                line_no             INTEGER NOT NULL,
                account_code        VARCHAR(32) NOT NULL,
                debit_fen           BIGINT NOT NULL DEFAULT 0,
                credit_fen          BIGINT NOT NULL DEFAULT 0,
                currency            VARCHAR(8) NOT NULL DEFAULT 'CNY',
                cost_center         VARCHAR(64),
                memo                VARCHAR(256),
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_jl_amounts_nonneg
                    CHECK (debit_fen >= 0 AND credit_fen >= 0),
                CONSTRAINT chk_jl_amounts_exclusive
                    CHECK (
                        (debit_fen > 0 AND credit_fen = 0)
                        OR (debit_fen = 0 AND credit_fen > 0)
                    ),
                CONSTRAINT chk_jl_line_no_positive
                    CHECK (line_no > 0),
                CONSTRAINT fk_jl_entry
                    FOREIGN KEY (tenant_id, entry_id)
                    REFERENCES journal_entry (tenant_id, id)
                    ON DELETE RESTRICT,
                CONSTRAINT fk_jl_coa
                    FOREIGN KEY (tenant_id, account_code)
                    REFERENCES chart_of_accounts (tenant_id, account_code)
                    ON DELETE RESTRICT,
                CONSTRAINT uq_jl_entry_line_no
                    UNIQUE (entry_id, line_no)
            )
            """
        )
        op.execute("ALTER TABLE journal_line ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE journal_line FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY journal_line_tenant_isolation
            ON journal_line
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )
        # 凭证内明细遍历主路径：按 entry_id 拿全部 line 算借贷平衡
        op.execute(
            """
            CREATE INDEX idx_jl_tenant_entry
            ON journal_line (tenant_id, entry_id)
            WHERE is_deleted = FALSE
            """
        )
        # 科目维度聚合：按租户 + 科目算余额（W5 财务报表高频路径）
        op.execute(
            """
            CREATE INDEX idx_jl_tenant_account
            ON journal_line (tenant_id, account_code)
            WHERE is_deleted = FALSE
            """
        )
        # 成本中心切片：按业态/门店/部门聚合 P&L
        op.execute(
            """
            CREATE INDEX idx_jl_tenant_cost_center
            ON journal_line (tenant_id, cost_center)
            WHERE cost_center IS NOT NULL AND is_deleted = FALSE
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "journal_line" in existing:
        op.execute("DROP TABLE journal_line CASCADE")
