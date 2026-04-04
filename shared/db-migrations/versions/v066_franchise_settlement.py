"""加盟商财务结算表

新增表：
  franchise_settlements      — 月结算单主表（draft/sent/confirmed/paid 状态机）
  franchise_settlement_items — 结算单费用明细条目

状态机（单向不可逆）：
  draft → sent → confirmed → paid

RLS 策略：
  全部使用 v006+ 标准安全模式（NULLIF + 4操作 + FORCE ROW LEVEL SECURITY）

Revision ID: v066
Revises: v065
Create Date: 2026-03-31
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v066"
down_revision: Union[str, None] = "v065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 标准 NULLIF NULL guard 条件（v006+ 安全标准）
_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"

_SETTLEMENT_TABLES = [
    "franchise_settlement_items",
    "franchise_settlements",
]


def _apply_safe_rls(table: str) -> None:
    """创建标准安全 RLS：四操作 PERMISSIVE + NULLIF NULL guard + FORCE。"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_select ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_select ON {table} "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_insert ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_insert ON {table} "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_update ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_update ON {table} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_delete ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_delete ON {table} "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. franchise_settlements — 月结算单主表
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS franchise_settlements (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            franchisee_id       UUID NOT NULL REFERENCES franchisees(id),
            year                SMALLINT NOT NULL CHECK (year >= 2020 AND year <= 2099),
            month               SMALLINT NOT NULL CHECK (month >= 1 AND month <= 12),

            -- 金额字段（单位：分，避免浮点精度问题）
            revenue_fen         BIGINT NOT NULL DEFAULT 0
                                    CHECK (revenue_fen >= 0),
            royalty_amount_fen  BIGINT NOT NULL DEFAULT 0
                                    CHECK (royalty_amount_fen >= 0),
            mgmt_fee_fen        BIGINT NOT NULL DEFAULT 0
                                    CHECK (mgmt_fee_fen >= 0),
            total_amount_fen    BIGINT NOT NULL DEFAULT 0
                                    CHECK (total_amount_fen >= 0),

            -- 状态机（单向不可逆：draft→sent→confirmed→paid）
            status              VARCHAR(20) NOT NULL DEFAULT 'draft'
                                    CHECK (status IN ('draft','sent','confirmed','paid')),

            -- 付款信息
            due_date            DATE,
            paid_at             TIMESTAMPTZ,
            payment_ref         VARCHAR(200),

            -- 元数据
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            -- 同一加盟商同月只能有一张结算单（幂等保护）
            UNIQUE (tenant_id, franchisee_id, year, month)
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_franchise_settlements_tenant_franchisee "
        "ON franchise_settlements (tenant_id, franchisee_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_franchise_settlements_tenant_status "
        "ON franchise_settlements (tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_franchise_settlements_tenant_due_date "
        "ON franchise_settlements (tenant_id, due_date) "
        "WHERE status IN ('sent', 'confirmed')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_franchise_settlements_year_month "
        "ON franchise_settlements (tenant_id, year, month)"
    )

    _apply_safe_rls("franchise_settlements")

    # ─────────────────────────────────────────────────────────────────
    # 2. franchise_settlement_items — 结算单费用明细条目
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS franchise_settlement_items (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            settlement_id   UUID NOT NULL REFERENCES franchise_settlements(id) ON DELETE CASCADE,
            item_type       VARCHAR(50) NOT NULL
                                CHECK (item_type IN ('royalty','management_fee','training_fee','other')),
            description     VARCHAR(200) NOT NULL,
            amount_fen      BIGINT NOT NULL DEFAULT 0
                                CHECK (amount_fen >= 0),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_franchise_settlement_items_settlement "
        "ON franchise_settlement_items (settlement_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_franchise_settlement_items_tenant "
        "ON franchise_settlement_items (tenant_id)"
    )

    _apply_safe_rls("franchise_settlement_items")

    # ─────────────────────────────────────────────────────────────────
    # 3. 触发器：franchise_settlements.updated_at 自动更新
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_franchise_settlements_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        CREATE TRIGGER trg_franchise_settlements_updated_at
        BEFORE UPDATE ON franchise_settlements
        FOR EACH ROW
        EXECUTE FUNCTION update_franchise_settlements_updated_at()
    """)


def downgrade() -> None:
    # 删除触发器和函数
    op.execute(
        "DROP TRIGGER IF EXISTS trg_franchise_settlements_updated_at "
        "ON franchise_settlements"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS update_franchise_settlements_updated_at()"
    )

    # 删除 RLS 策略和表（逆序，先删明细表）
    for table in _SETTLEMENT_TABLES:
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
