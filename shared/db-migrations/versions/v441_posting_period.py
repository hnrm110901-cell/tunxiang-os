"""v441 — GL 内核会计期表骨架（W3 P0 #756 第 1/4 / Tier1 邻接）

业务背景：
  屯象OS 进入 W3 战略路线图 GL 内核建设阶段。会计期是 GL 双分录入账的时间维度锚点：
  - 每个租户按 year_month（"2026-05"）建立会计期，控制凭证可入账的时间窗口
  - status: open（可入账）→ closed（已结账，禁止新增凭证）→ locked（已锁定，禁止任何变更）
  - W4 起 settle_order 接入 GL 时必须先取所属会计期，否则拒绝入账
  本表为 GL 4 表骨架第一张，**仅 schema 不接入业务路径**（W4 起接入）。

设计要点：
  - 单租户隔离：(tenant_id, year_month) 唯一约束 → 防同期重复建立
  - 状态机：open / closed / locked 三态 + CHECK 约束 closed_at 与 status 一致性
  - 时间戳：opened_at / closed_at / locked_at 分别记录三态转移时刻
  - closed_by UUID 留痕操作员，审计用
  - RLS 四联（ENABLE + FORCE + POLICY + WITH CHECK），与 v440/v435/v432 同模式
  - inspector-and-skip 幂等模式（与 v421+ 一致）

Migration 链：
  v440_certificate_types → v441_posting_period (本 PR 1/4)
                        → v442_chart_of_accounts (本 PR 2/4)
                        → v443_journal_entry (本 PR 3/4, FK posting_period)
                        → v444_journal_line (本 PR 4/4, FK journal_entry + chart_of_accounts)

Revision ID: v441_posting_period
Revises: v440_certificate_types
Create Date: 2026-05-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v441_posting_period"
down_revision: Union[str, Sequence[str], None] = "v440_certificate_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ─────────────────────────────────────────────────────────────────────────
    # GL 4/4 之 1: posting_period 会计期表
    # ─────────────────────────────────────────────────────────────────────────
    if "posting_period" not in existing:
        op.execute(
            """
            CREATE TABLE posting_period (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                year_month          CHAR(7) NOT NULL,
                status              VARCHAR(16) NOT NULL DEFAULT 'open',
                opened_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                closed_at           TIMESTAMPTZ,
                locked_at           TIMESTAMPTZ,
                closed_by           UUID,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_posting_period_status
                    CHECK (status IN ('open', 'closed', 'locked')),
                CONSTRAINT chk_posting_period_year_month
                    CHECK (year_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
                CONSTRAINT chk_posting_period_closed_at_consistency
                    CHECK (status = 'open' OR closed_at IS NOT NULL),
                CONSTRAINT chk_posting_period_locked_at_consistency
                    CHECK (status != 'locked' OR locked_at IS NOT NULL)
            )
            """
        )
        op.execute("ALTER TABLE posting_period ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE posting_period FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY posting_period_tenant_isolation
            ON posting_period
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        # 单租户同期唯一（软删除后允许新建同期）
        op.execute(
            """
            CREATE UNIQUE INDEX uq_posting_period_tenant_year_month
            ON posting_period (tenant_id, year_month)
            WHERE is_deleted = FALSE
            """
        )
        # 主查询入口：按租户 + 状态筛选可入账会计期
        op.execute(
            """
            CREATE INDEX idx_posting_period_tenant_status
            ON posting_period (tenant_id, status)
            WHERE is_deleted = FALSE
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # journal_entry FK 依赖 posting_period.id，CASCADE 在 downgrade 链顺序保护
    if "posting_period" in existing:
        op.execute("DROP TABLE posting_period CASCADE")
