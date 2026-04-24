"""预算管理系统：预算主表 + 科目分配 + 调整记录 + 月末快照
Tables: budgets, budget_allocations, budget_adjustments, budget_snapshots
Sprint: P2-S1（预算管理系统）

设计原则：
  - 预算分年度/月度两个维度：budget_month=NULL 表示年度预算，有值表示月度预算
  - 支持集团级（store_id=NULL）和门店级预算
  - used_amount 原子更新，避免并发冲突
  - 月末快照保存完整历史，支持趋势分析

Revision ID: v242
Revises: v241
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v242"
down_revision = "v241"
branch_labels = None
depends_on = None

# 标准安全 RLS 条件（NULLIF 保护，与 v241 规范一致）
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    # ------------------------------------------------------------------
    # 表1：budgets（预算主表）
    # ------------------------------------------------------------------

    if "budgets" not in existing:
        op.create_table(
            "budgets",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), nullable=False
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("budget_name", sa.String(200), nullable=False, comment="预算名称"),
            sa.Column("budget_year", sa.Integer(), nullable=False, comment="预算年份，如 2026"),
            sa.Column("budget_month", sa.Integer(), nullable=True, comment="预算月份（NULL=年度预算，1-12=月度预算）"),
            sa.Column(
                "budget_type",
                sa.String(32),
                nullable=True,
                server_default="expense",
                comment="预算类型：expense/travel/procurement",
            ),
            sa.Column("store_id", UUID(as_uuid=True), nullable=True, comment="关联门店ID（NULL=集团预算）"),
            sa.Column("department", sa.String(100), nullable=True, comment="部门"),
            sa.Column("total_amount", sa.BigInteger(), nullable=False, comment="预算总额（分），展示时除以100转元"),
            sa.Column(
                "used_amount", sa.BigInteger(), nullable=False, server_default="0", comment="已使用金额（分），原子更新"
            ),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="active",
                comment="预算状态：draft/active/locked/expired",
            ),
            sa.Column("approved_by", UUID(as_uuid=True), nullable=True, comment="审批人员工ID"),
            sa.Column("notes", sa.Text(), nullable=True, comment="备注"),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True, comment="创建人员工ID"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), nullable=True, server_default="false"),
        )

        # 唯一约束：同一租户/年/月/类型/门店不重复
        op.execute(
            """
            CREATE UNIQUE INDEX budgets_unique_period
            ON budgets(
                tenant_id,
                budget_year,
                COALESCE(budget_month, 0),
                budget_type,
                COALESCE(store_id, '00000000-0000-0000-0000-000000000000'::UUID)
            )
            WHERE is_deleted = false
            """
        )

        # 索引
        op.create_index(
            "ix_budgets_tenant_year_month",
            "budgets",
            ["tenant_id", "budget_year", "budget_month"],
        )
        op.create_index(
            "ix_budgets_tenant_status",
            "budgets",
            ["tenant_id", "status"],
            postgresql_where=sa.text("is_deleted = false"),
        )
        op.create_index(
            "ix_budgets_tenant_store_id",
            "budgets",
            ["tenant_id", "store_id"],
        )
        op.create_index(
            "ix_budgets_tenant_type",
            "budgets",
            ["tenant_id", "budget_type"],
        )

        # RLS
        op.execute("ALTER TABLE budgets ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY budgets_tenant_isolation
            ON budgets
            USING ({_RLS_COND})
            """
        )

        # ------------------------------------------------------------------
        # 表2：budget_allocations（预算科目分配）
        # ------------------------------------------------------------------

    if "budget_allocations" not in existing:
        op.create_table(
            "budget_allocations",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), nullable=False
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("budget_id", UUID(as_uuid=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["budget_id"],
                ["budgets.id"],
                name="fk_budget_allocations_budget_id",
                ondelete="CASCADE",
            ),
            sa.Column(
                "category_code", sa.String(64), nullable=True, comment="费用科目代码（对应 ExpenseCategoryCode）"
            ),
            sa.Column("allocated_amount", sa.BigInteger(), nullable=False, comment="分配金额（分）"),
            sa.Column("used_amount", sa.BigInteger(), nullable=False, server_default="0", comment="已使用金额（分）"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
        )

        # 索引
        op.create_index(
            "ix_budget_allocations_tenant_budget",
            "budget_allocations",
            ["tenant_id", "budget_id"],
        )
        op.create_index(
            "ix_budget_allocations_tenant_category",
            "budget_allocations",
            ["tenant_id", "category_code"],
        )

        # RLS
        op.execute("ALTER TABLE budget_allocations ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY budget_allocations_tenant_isolation
            ON budget_allocations
            USING ({_RLS_COND})
            """
        )

        # ------------------------------------------------------------------
        # 表3：budget_adjustments（预算调整记录）
        # ------------------------------------------------------------------

    if "budget_adjustments" not in existing:
        op.create_table(
            "budget_adjustments",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), nullable=False
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("budget_id", UUID(as_uuid=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["budget_id"],
                ["budgets.id"],
                name="fk_budget_adjustments_budget_id",
                ondelete="CASCADE",
            ),
            sa.Column(
                "adjustment_type", sa.String(32), nullable=True, comment="调整类型：increase/decrease/reallocate"
            ),
            sa.Column("amount", sa.BigInteger(), nullable=False, comment="调整金额（分，正增负减）"),
            sa.Column("reason", sa.Text(), nullable=True, comment="调整原因"),
            sa.Column("approved_by", UUID(as_uuid=True), nullable=True, comment="审批人员工ID"),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True, comment="创建人员工ID"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
        )

        # 索引
        op.create_index(
            "ix_budget_adjustments_tenant_budget",
            "budget_adjustments",
            ["tenant_id", "budget_id"],
        )
        op.create_index(
            "ix_budget_adjustments_tenant_created_at",
            "budget_adjustments",
            ["tenant_id", "created_at"],
        )

        # RLS
        op.execute("ALTER TABLE budget_adjustments ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY budget_adjustments_tenant_isolation
            ON budget_adjustments
            USING ({_RLS_COND})
            """
        )

        # ------------------------------------------------------------------
        # 表4：budget_snapshots（月末快照）
        # ------------------------------------------------------------------

    if "budget_snapshots" not in existing:
        op.create_table(
            "budget_snapshots",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), nullable=False
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("budget_id", UUID(as_uuid=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["budget_id"],
                ["budgets.id"],
                name="fk_budget_snapshots_budget_id",
                ondelete="CASCADE",
            ),
            sa.Column("snapshot_date", sa.Date(), nullable=False, comment="快照日期"),
            sa.Column("total_amount", sa.BigInteger(), nullable=True, comment="快照时预算总额（分）"),
            sa.Column("used_amount", sa.BigInteger(), nullable=True, comment="快照时已使用金额（分）"),
            sa.Column("execution_rate", sa.Numeric(7, 4), nullable=True, comment="执行率，如 0.8567"),
            sa.Column("snapshot_data", JSONB, nullable=True, comment="完整快照 JSON（含分配明细等）"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
        )

        # 索引
        op.create_index(
            "ix_budget_snapshots_tenant_budget",
            "budget_snapshots",
            ["tenant_id", "budget_id"],
        )
        op.create_index(
            "ix_budget_snapshots_tenant_date",
            "budget_snapshots",
            ["tenant_id", "snapshot_date"],
        )

        # RLS
        op.execute("ALTER TABLE budget_snapshots ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY budget_snapshots_tenant_isolation
            ON budget_snapshots
            USING ({_RLS_COND})
            """
        )


def downgrade() -> None:
    # 按依赖反向删除

    # budget_snapshots
    op.execute("DROP POLICY IF EXISTS budget_snapshots_tenant_isolation ON budget_snapshots")
    op.drop_table("budget_snapshots")

    # budget_adjustments
    op.execute("DROP POLICY IF EXISTS budget_adjustments_tenant_isolation ON budget_adjustments")
    op.drop_table("budget_adjustments")

    # budget_allocations
    op.execute("DROP POLICY IF EXISTS budget_allocations_tenant_isolation ON budget_allocations")
    op.drop_table("budget_allocations")

    # budgets
    op.execute("DROP INDEX IF EXISTS budgets_unique_period")
    op.execute("DROP POLICY IF EXISTS budgets_tenant_isolation ON budgets")
    op.drop_table("budgets")
