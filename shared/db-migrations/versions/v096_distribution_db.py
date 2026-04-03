"""v096: 配送管理 DB 化 — 将 distribution.py 的内存存储迁移到 PostgreSQL

新建 4 张表：
  - distribution_warehouses  — 仓库信息（含地理坐标）
  - distribution_store_geos  — 门店地理信息（供路线优化使用）
  - distribution_drivers     — 司机信息
  - distribution_plans       — 配送计划主表（store_deliveries/route 存为 JSONB）

设计要点：
  - store_deliveries 存 JSONB：每个门店的配送项列表，状态随业务流转更新
  - route 存 JSONB：贪心算法计算结果，路线优化后写入
  - 仓库/门店地理/司机表均做 UPSERT（inject_* 接口），幂等安全
  - 全部表 RLS：NULLIF(app.tenant_id) 防 NULL 绕过

Revision ID: v096
Revises: v095
Create Date: 2026-04-01
"""

from alembic import op

revision = "v096"
down_revision = "v095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. distribution_warehouses — 仓库信息 ────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS distribution_warehouses (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            warehouse_id    UUID         NOT NULL,
            warehouse_name  VARCHAR(200) NOT NULL,
            lat             NUMERIC(10,7) NOT NULL DEFAULT 0,
            lng             NUMERIC(10,7) NOT NULL DEFAULT 0,
            address         TEXT,
            capacity_kg     NUMERIC(10,2),
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, warehouse_id)
        )
    """)
    op.execute("ALTER TABLE distribution_warehouses ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY distribution_warehouses_rls ON distribution_warehouses
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # ── 2. distribution_store_geos — 门店地理信息 ─────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS distribution_store_geos (
            id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID         NOT NULL,
            store_id    UUID         NOT NULL,
            store_name  VARCHAR(200) NOT NULL DEFAULT '',
            lat         NUMERIC(10,7) NOT NULL DEFAULT 0,
            lng         NUMERIC(10,7) NOT NULL DEFAULT 0,
            address     TEXT,
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id)
        )
    """)
    op.execute("ALTER TABLE distribution_store_geos ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY distribution_store_geos_rls ON distribution_store_geos
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # ── 3. distribution_drivers — 司机信息 ───────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS distribution_drivers (
            id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID        NOT NULL,
            driver_id     UUID        NOT NULL,
            driver_name   VARCHAR(100) NOT NULL,
            phone         VARCHAR(20),
            vehicle_no    VARCHAR(20),
            vehicle_type  VARCHAR(30),
            capacity_kg   NUMERIC(10,2),
            is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, driver_id)
        )
    """)
    op.execute("ALTER TABLE distribution_drivers ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY distribution_drivers_rls ON distribution_drivers
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # ── 4. distribution_plans — 配送计划主表 ─────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS distribution_plans (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL,
            warehouse_id      UUID        NOT NULL,
            status            VARCHAR(20) NOT NULL DEFAULT 'planned',
            store_count       INT         NOT NULL DEFAULT 0,
            total_items       INT         NOT NULL DEFAULT 0,
            driver_id         UUID,
            route             JSONB,
            store_deliveries  JSONB       NOT NULL DEFAULT '[]',
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            dispatched_at     TIMESTAMPTZ,
            completed_at      TIMESTAMPTZ
        )
    """)
    op.execute("ALTER TABLE distribution_plans ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY distribution_plans_rls ON distribution_plans
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_distribution_plans_warehouse
            ON distribution_plans(tenant_id, warehouse_id, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_distribution_plans_status
            ON distribution_plans(tenant_id, status, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS distribution_plans CASCADE")
    op.execute("DROP TABLE IF EXISTS distribution_drivers CASCADE")
    op.execute("DROP TABLE IF EXISTS distribution_store_geos CASCADE")
    op.execute("DROP TABLE IF EXISTS distribution_warehouses CASCADE")
