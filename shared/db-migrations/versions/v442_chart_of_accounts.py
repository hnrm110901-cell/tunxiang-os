"""v442 — GL 内核科目主表骨架（W3 P0 #756 第 2/4 / Tier1 邻接）

业务背景：
  科目主表是 GL 双分录的基础维度。每个租户维护自己的科目表（chart of accounts）：
  - account_code 是科目编码，如 "1001" 现金 / "6001" 主营业务成本
  - parent_code 自引用支持科目树（一级科目 / 二级明细）
  - allow_posting 区分末级科目（true，可入账）与汇总科目（false，不可入账）
  - account_type 五分类：asset / liability / equity / revenue / expense（SAP 视角）
  W3 P2 sub-issue 会 seed 标准科目数据（本 PR 不含 seed）。

设计要点：
  - 单租户隔离：(tenant_id, account_code) 唯一约束 → 科目编码租户内唯一
  - 自引用 parent_code：仅引用 account_code 字符串（同租户 RLS 保证隔离），
    不加 FK 约束（自引用 + tenant_id 组合 FK 在 alembic + asyncpg 测试场景复杂度高，
    业务层自行保证 parent_code 存在；W4 接入时配 service-level 校验）
  - UNIQUE CONSTRAINT (tenant_id, account_code) 而非 INDEX，让 v444 journal_line 可走
    composite FK (tenant_id, account_code) → chart_of_accounts (PG 要求 FK 目标必须是 UNIQUE 约束)
  - RLS 四联（ENABLE + FORCE + POLICY + WITH CHECK），与 v440/v441 同模式
  - inspector-and-skip 幂等模式

Migration 链：
  v441_posting_period → v442_chart_of_accounts (本 PR 2/4)

Revision ID: v442_chart_of_accounts
Revises: v441_posting_period
Create Date: 2026-05-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v442_chart_of_accounts"
down_revision: Union[str, Sequence[str], None] = "v441_posting_period"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ─────────────────────────────────────────────────────────────────────────
    # GL 4/4 之 2: chart_of_accounts 科目主表
    # ─────────────────────────────────────────────────────────────────────────
    if "chart_of_accounts" not in existing:
        op.execute(
            """
            CREATE TABLE chart_of_accounts (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                account_code        VARCHAR(32) NOT NULL,
                account_name        VARCHAR(128) NOT NULL,
                parent_code         VARCHAR(32),
                account_type        VARCHAR(16) NOT NULL,
                allow_posting       BOOLEAN NOT NULL DEFAULT TRUE,
                description         TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_coa_account_type
                    CHECK (account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')),
                CONSTRAINT uq_coa_tenant_account_code
                    UNIQUE (tenant_id, account_code)
            )
            """
        )
        op.execute("ALTER TABLE chart_of_accounts ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE chart_of_accounts FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY chart_of_accounts_tenant_isolation
            ON chart_of_accounts
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        # 树形遍历主查询：按租户 + parent_code 查子科目（软删除过滤）
        op.execute(
            """
            CREATE INDEX idx_coa_tenant_parent
            ON chart_of_accounts (tenant_id, parent_code)
            WHERE is_deleted = FALSE
            """
        )
        # 末级科目筛选索引：allow_posting=true 是 journal_line 入账校验的高频路径
        op.execute(
            """
            CREATE INDEX idx_coa_tenant_postable
            ON chart_of_accounts (tenant_id, account_type)
            WHERE allow_posting = TRUE AND is_deleted = FALSE
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # journal_line FK 依赖 chart_of_accounts (tenant_id, account_code)，CASCADE 保护
    if "chart_of_accounts" in existing:
        op.execute("DROP TABLE chart_of_accounts CASCADE")
