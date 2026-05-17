"""v441 — GL 内核会计期表骨架（W3 P0 #756 第 1/4 / Tier1 邻接）

业务背景：
  屯象OS 进入 W3 战略路线图 GL 内核建设阶段。会计期是 GL 双分录入账的时间维度锚点：
  - 每个租户按 year_month（"2026-05"）建立会计期，控制凭证可入账的时间窗口
  - status: open（可入账）→ closed（已结账，禁止新增凭证）→ locked（已锁定，禁止任何变更）
  - W4 起 settle_order 接入 GL 时必须先取所属会计期，否则拒绝入账
  本表为 GL 4 表骨架第一张，**仅 schema 不接入业务路径**（W4 起接入）。

设计要点：
  - 单租户隔离：(tenant_id, year_month) partial UNIQUE INDEX → 防同期重复建立
  - 状态机：open / closed / locked 三态 + **双向 CHECK** 强制状态/时间戳一致性
    （round-1 §19 P1-5 修：单向 CHECK 允许 status='open' AND closed_at=NOW() 反例）
  - 复合 UNIQUE (tenant_id, id) → 让 journal_entry composite FK 同租户引用成立
    （round-1 §19 P0-1 security 修：单 id PK 允许跨租户 posting_period 被引用）
  - period_type 灵活粒度：'monthly'（默认）/ 'daily'（T+3 业态用）/ 'special'（年终调整）
    （round-1 §19 critic P1-3 修：原仅月级不支持创始人提及的"日级/特殊期"业务诉求）
  - RLS 四联（ENABLE + FORCE + POLICY + WITH CHECK）— 改 v139 NULLIF::uuid 模式
    （round-1 §19 critic P1-1 / security P1-2 修：tenant_id::text = current_setting
    在 SET 未生效时返回 NULL=NULL 行为不一致，NULLIF::uuid 模式与 v139 / v147 对齐）
  - inspector-and-skip 幂等模式（与 v421+ 一致）

Migration 链：
  v440_certificate_types → v441_posting_period (本 PR 1/4)
                        → v442_chart_of_accounts (本 PR 2/4)
                        → v443_journal_entry (本 PR 3/4, FK posting_period)
                        → v444_journal_line (本 PR 4/4, FK journal_entry + chart_of_accounts)
                        → v445_cost_center_dictionary (本 PR 5/5, round-1 §19 critic P1-2 新增)

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
                id                  UUID NOT NULL DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                year_month          CHAR(7) NOT NULL,
                period_type         VARCHAR(16) NOT NULL DEFAULT 'monthly',
                period_date         DATE,
                status              VARCHAR(16) NOT NULL DEFAULT 'open',
                opened_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                closed_at           TIMESTAMPTZ,
                locked_at           TIMESTAMPTZ,
                closed_by           UUID,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT pk_posting_period
                    PRIMARY KEY (id),
                CONSTRAINT uq_posting_period_tenant_id
                    UNIQUE (tenant_id, id),
                CONSTRAINT chk_posting_period_status
                    CHECK (status IN ('open', 'closed', 'locked')),
                CONSTRAINT chk_posting_period_period_type
                    CHECK (period_type IN ('monthly', 'daily', 'special')),
                CONSTRAINT chk_posting_period_year_month
                    CHECK (year_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
                CONSTRAINT chk_pp_status_consistency CHECK (
                    (status = 'open' AND closed_at IS NULL AND locked_at IS NULL)
                    OR (status = 'closed' AND closed_at IS NOT NULL AND locked_at IS NULL)
                    OR (status = 'locked' AND closed_at IS NOT NULL AND locked_at IS NOT NULL)
                ),
                CONSTRAINT chk_pp_period_type_consistency CHECK (
                    (period_type = 'monthly' AND period_date IS NULL)
                    OR (period_type = 'daily' AND period_date IS NOT NULL)
                    OR (period_type = 'special' AND period_date IS NULL)
                )
            )
            """
        )
        op.execute("ALTER TABLE posting_period ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE posting_period FORCE ROW LEVEL SECURITY")
        # v139 NULLIF::uuid 模式：未 SET LOCAL app.tenant_id 时返回空串 → NULLIF → NULL
        # → tenant_id = NULL 永假 → 返回 0 行（符合 fail-closed 安全语义）
        op.execute(
            """
            CREATE POLICY posting_period_tenant_isolation
            ON posting_period
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )
        # 单租户同期唯一（partial unique 软删除后允许新建同期）
        # monthly + special 按 (tenant, year_month) 唯一；daily 按 (tenant, period_date) 唯一
        op.execute(
            """
            CREATE UNIQUE INDEX uq_posting_period_tenant_year_month
            ON posting_period (tenant_id, year_month)
            WHERE period_type IN ('monthly', 'special') AND is_deleted = FALSE
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX uq_posting_period_tenant_period_date
            ON posting_period (tenant_id, period_date)
            WHERE period_type = 'daily' AND is_deleted = FALSE
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

    # journal_entry FK 依赖 posting_period.(tenant_id, id)，CASCADE 在 downgrade 链顺序保护
    if "posting_period" in existing:
        op.execute("DROP TABLE posting_period CASCADE")
