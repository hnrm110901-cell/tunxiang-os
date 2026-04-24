"""加盟管理系统 — 加盟商/门店/费用/分润结算/巡店审计

新增表：
  franchisees            — 加盟商档案（名称/合同/费率/状态）
  franchisee_stores      — 加盟商门店关联（join_date/initial_fee）
  royalty_bills          — 月度特许权费用账单（营收/分润/管理费/到期/状态）
  franchise_audits       — 巡店审计记录（分数/发现项/审计人）

RLS 策略：
  全部使用 v006+ 标准安全模式（NULLIF + 4操作 + FORCE ROW LEVEL SECURITY）

Revision ID: v060
Revises: v047
Create Date: 2026-03-31

并行分支说明：
  此迁移与 v056/v057/v058 并行，均以 v047 为基础。
  合并后请确认 alembic heads 状态正常。
"""

from alembic import op

revision = "v060"
down_revision = "v047"
branch_labels = None
depends_on = None

# 标准 NULLIF NULL guard 条件
_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"

_FRANCHISE_TABLES = [
    "franchisees",
    "franchisee_stores",
    "royalty_bills",
    "franchise_audits",
]


def _apply_safe_rls(table: str) -> None:
    """创建标准安全 RLS：四操作 PERMISSIVE + NULLIF NULL guard + FORCE。"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_select ON {table}")
    op.execute(f"CREATE POLICY {table}_rls_select ON {table} FOR SELECT USING ({_SAFE_CONDITION})")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_insert ON {table}")
    op.execute(f"CREATE POLICY {table}_rls_insert ON {table} FOR INSERT WITH CHECK ({_SAFE_CONDITION})")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_update ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_update ON {table} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_delete ON {table}")
    op.execute(f"CREATE POLICY {table}_rls_delete ON {table} FOR DELETE USING ({_SAFE_CONDITION})")


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. franchisees — 加盟商档案
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS franchisees (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            name                VARCHAR(100) NOT NULL,
            contact_name        VARCHAR(50),
            contact_phone       VARCHAR(20),
            contact_email       VARCHAR(100),
            region              VARCHAR(50),
            status              VARCHAR(20) NOT NULL DEFAULT 'active'
                                    CHECK (status IN ('active','suspended','terminated')),
            contract_start      DATE,
            contract_end        DATE,
            royalty_rate        NUMERIC(5,4) NOT NULL DEFAULT 0.05,
            royalty_tiers       JSONB NOT NULL DEFAULT '[]',
            management_fee_fen  BIGINT NOT NULL DEFAULT 0,
            brand_usage_fee_fen BIGINT NOT NULL DEFAULT 0,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_franchisees_tenant_status ON franchisees (tenant_id, status)")
    _apply_safe_rls("franchisees")

    # ─────────────────────────────────────────────────────────────────
    # 2. franchisee_stores — 加盟商门店关联
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS franchisee_stores (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID NOT NULL,
            franchisee_id    UUID NOT NULL REFERENCES franchisees(id),
            store_id         UUID NOT NULL,
            join_date        DATE NOT NULL DEFAULT CURRENT_DATE,
            initial_fee_fen  BIGINT NOT NULL DEFAULT 0,
            status           VARCHAR(20) NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active','closed')),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_franchisee_stores_tenant_franchisee "
        "ON franchisee_stores (tenant_id, franchisee_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_franchisee_stores_store ON franchisee_stores (tenant_id, store_id)")
    _apply_safe_rls("franchisee_stores")

    # ─────────────────────────────────────────────────────────────────
    # 3. royalty_bills — 月度特许权费用账单
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS royalty_bills (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID NOT NULL,
            franchisee_id        UUID NOT NULL REFERENCES franchisees(id),
            store_id             UUID,
            period_start         DATE NOT NULL,
            period_end           DATE NOT NULL,
            revenue_fen          BIGINT NOT NULL DEFAULT 0,
            royalty_rate         NUMERIC(5,4) NOT NULL,
            royalty_amount_fen   BIGINT NOT NULL DEFAULT 0,
            management_fee_fen   BIGINT NOT NULL DEFAULT 0,
            total_due_fen        BIGINT NOT NULL DEFAULT 0,
            status               VARCHAR(20) NOT NULL DEFAULT 'pending'
                                     CHECK (status IN ('pending','paid','overdue')),
            due_date             DATE,
            paid_at              TIMESTAMPTZ,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE royalty_bills ADD COLUMN IF NOT EXISTS franchisee_id UUID")
    op.execute("ALTER TABLE royalty_bills ADD COLUMN IF NOT EXISTS period_start DATE")
    op.execute("ALTER TABLE royalty_bills ADD COLUMN IF NOT EXISTS period_end DATE")
    op.execute("ALTER TABLE royalty_bills ADD COLUMN IF NOT EXISTS revenue_fen BIGINT DEFAULT 0")
    op.execute("ALTER TABLE royalty_bills ADD COLUMN IF NOT EXISTS royalty_rate NUMERIC(5,4)")
    op.execute("ALTER TABLE royalty_bills ADD COLUMN IF NOT EXISTS royalty_amount_fen BIGINT DEFAULT 0")
    op.execute("ALTER TABLE royalty_bills ADD COLUMN IF NOT EXISTS management_fee_fen BIGINT DEFAULT 0")
    op.execute("ALTER TABLE royalty_bills ADD COLUMN IF NOT EXISTS total_due_fen BIGINT DEFAULT 0")
    op.execute("ALTER TABLE royalty_bills ADD COLUMN IF NOT EXISTS due_date DATE")
    op.execute("ALTER TABLE royalty_bills ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ")
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name='royalty_bills' AND column_name IN ('tenant_id', 'franchisee_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_royalty_bills_tenant_franchisee ON royalty_bills (tenant_id, franchisee_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name='royalty_bills' AND column_name IN ('tenant_id', 'period_start', 'period_end')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_royalty_bills_tenant_period ON royalty_bills (tenant_id, period_start, period_end)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name='royalty_bills' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_royalty_bills_status ON royalty_bills (tenant_id, status)';
            END IF;
        END $$;
    """)
    _apply_safe_rls("royalty_bills")

    # ─────────────────────────────────────────────────────────────────
    # 4. franchise_audits — 巡店审计记录
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS franchise_audits (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID NOT NULL,
            franchisee_id UUID NOT NULL REFERENCES franchisees(id),
            store_id      UUID NOT NULL,
            audit_date    DATE NOT NULL,
            score         NUMERIC(5,2),
            findings      JSONB NOT NULL DEFAULT '{}',
            auditor_id    UUID,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_franchise_audits_tenant_franchisee "
        "ON franchise_audits (tenant_id, franchisee_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_franchise_audits_store_date "
        "ON franchise_audits (tenant_id, store_id, audit_date DESC)"
    )
    _apply_safe_rls("franchise_audits")


def downgrade() -> None:
    for table in reversed(_FRANCHISE_TABLES):
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
