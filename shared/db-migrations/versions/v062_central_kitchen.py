"""中央厨房基础框架 — 生产计划/半成品BOM/配送调度

新增表：
  central_kitchen_profiles       — 中央厨房档案（名称/地址/产能/负责人）
  production_plans               — 生产计划（日期/状态/菜品需求JSONB）
  production_orders              — 生产工单（菜品/数量/执行状态）
  distribution_orders            — 配送单（中央厨房→门店）
  store_receiving_confirmations  — 门店收货确认（实收数量/差异记录）

RLS 策略：
  全部使用 v056+ 标准安全模式（NULLIF + 4操作 + FORCE ROW LEVEL SECURITY）

Revision ID: v062
Revises: v047
Create Date: 2026-03-31

并行分支说明：
  此迁移与 v056/v057/v058/v059/v060/v061 并行，均以 v047 为基础。
  合并后请确认 alembic heads 状态正常。
"""
from typing import Sequence, Union

from alembic import op

revision = "v062"
down_revision= "v047"
branch_labels= None
depends_on= None

# 标准 NULLIF NULL guard 条件（与 v056+ 保持一致）
_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"

_CK_TABLES = [
    "central_kitchen_profiles",
    "production_plans",
    "production_orders",
    "distribution_orders",
    "store_receiving_confirmations",
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
    # 1. central_kitchen_profiles — 中央厨房档案
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS central_kitchen_profiles (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID NOT NULL,
            name             VARCHAR(100) NOT NULL,
            address          VARCHAR(255),
            capacity_daily   NUMERIC(10, 2) NOT NULL DEFAULT 0
                                 CHECK (capacity_daily >= 0),
            manager_id       UUID,
            contact_phone    VARCHAR(20),
            is_active        BOOLEAN NOT NULL DEFAULT TRUE,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ck_profiles_tenant_active "
        "ON central_kitchen_profiles (tenant_id, is_active)"
    )
    _apply_safe_rls("central_kitchen_profiles")

    # ─────────────────────────────────────────────────────────────────
    # 2. production_plans — 生产计划
    #    items JSONB 结构：
    #    [{dish_id, dish_name, quantity, unit, target_stores: [store_id, ...]}]
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS production_plans (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    UUID NOT NULL,
            kitchen_id   UUID NOT NULL,
            plan_date    DATE NOT NULL,
            status       VARCHAR(20) NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft','confirmed','in_progress','completed')),
            items        JSONB NOT NULL DEFAULT '[]',
            created_by   UUID,
            confirmed_at TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE production_plans ADD COLUMN IF NOT EXISTS kitchen_id UUID")
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name='production_plans' AND column_name IN ('tenant_id', 'kitchen_id', 'plan_date')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_production_plans_tenant_kitchen_date ON production_plans (tenant_id, kitchen_id, plan_date DESC)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name='production_plans' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_production_plans_tenant_status ON production_plans (tenant_id, status)';
            END IF;
        END $$;
    """)
    _apply_safe_rls("production_plans")

    # ─────────────────────────────────────────────────────────────────
    # 3. production_orders — 生产工单（每个菜品一张工单）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS production_orders (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    UUID NOT NULL,
            kitchen_id   UUID NOT NULL,
            plan_id      UUID NOT NULL REFERENCES production_plans(id),
            dish_id      UUID NOT NULL,
            quantity     NUMERIC(10, 3) NOT NULL CHECK (quantity > 0),
            unit         VARCHAR(20) NOT NULL DEFAULT '份',
            status       VARCHAR(20) NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending','in_progress','completed','cancelled')),
            started_at   TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            operator_id  UUID,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE production_orders ADD COLUMN IF NOT EXISTS kitchen_id UUID")
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name='production_orders' AND column_name IN ('tenant_id', 'plan_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_production_orders_tenant_plan ON production_orders (tenant_id, plan_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name='production_orders' AND column_name IN ('tenant_id', 'kitchen_id', 'status')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_production_orders_tenant_kitchen_status ON production_orders (tenant_id, kitchen_id, status)';
            END IF;
        END $$;
    """)
    _apply_safe_rls("production_orders")

    # ─────────────────────────────────────────────────────────────────
    # 4. distribution_orders — 配送单（中央厨房→门店）
    #    items JSONB 结构：
    #    [{dish_id, dish_name, quantity, unit}]
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS distribution_orders (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            kitchen_id      UUID NOT NULL,
            target_store_id UUID NOT NULL,
            scheduled_at    TIMESTAMPTZ NOT NULL,
            delivered_at    TIMESTAMPTZ,
            status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','dispatched','delivered','confirmed')),
            items           JSONB NOT NULL DEFAULT '[]',
            driver_name     VARCHAR(50),
            driver_phone    VARCHAR(20),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE distribution_orders ADD COLUMN IF NOT EXISTS kitchen_id UUID")
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name='distribution_orders' AND column_name IN ('tenant_id', 'kitchen_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_distribution_orders_tenant_kitchen ON distribution_orders (tenant_id, kitchen_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name='distribution_orders' AND column_name IN ('tenant_id', 'target_store_id', 'scheduled_at')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_distribution_orders_tenant_store_scheduled ON distribution_orders (tenant_id, target_store_id, scheduled_at DESC)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name='distribution_orders' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_distribution_orders_tenant_status ON distribution_orders (tenant_id, status)';
            END IF;
        END $$;
    """)
    _apply_safe_rls("distribution_orders")

    # ─────────────────────────────────────────────────────────────────
    # 5. store_receiving_confirmations — 门店收货确认
    #    items JSONB 结构：
    #    [{dish_id, dish_name, expected_qty, received_qty, unit, variance_notes}]
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS store_receiving_confirmations (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id             UUID NOT NULL,
            distribution_order_id UUID NOT NULL REFERENCES distribution_orders(id),
            store_id              UUID NOT NULL,
            confirmed_by          UUID NOT NULL,
            confirmed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            items                 JSONB NOT NULL DEFAULT '[]',
            notes                 TEXT,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_store_receiving_tenant_distribution "
        "ON store_receiving_confirmations (tenant_id, distribution_order_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_store_receiving_tenant_store "
        "ON store_receiving_confirmations (tenant_id, store_id, confirmed_at DESC)"
    )
    _apply_safe_rls("store_receiving_confirmations")


def downgrade() -> None:
    for table in reversed(_CK_TABLES):
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
