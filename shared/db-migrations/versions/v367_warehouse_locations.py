"""库位/库区/温区编码 — TASK-2 仓储库存细化

新增表（4 张）：
  warehouse_zones                — 库区（含温区类型）
  warehouse_locations            — 库位（隶属库区，含 ABC 周转分级）
  ingredient_location_bindings   — 食材→默认库位绑定
  inventory_by_location          — 按库位粒度的实时库存

背景：
  tx-supply 现有库存粒度只到"门店"，无法支持中型仓储和冷链管理。
  本迁移新增库区/库位编码体系，支持：
    - 温区分类（常温/冷藏/冷冻/活鲜）
    - ABC 周转优先级（A=高频，B=中频，C=低频）
    - 库位级实时库存（按批次拆分）
    - 食材主库位绑定（入库自动定位）

兼容性：
  原有 ingredients.current_quantity 与 ingredient_transactions 路径不变；
  inventory_by_location 是细化视图，老 API 通过聚合保持兼容。

RLS 策略：
  全部使用 v056+ 标准安全模式
  （NULLIF + 四操作 PERMISSIVE + FORCE ROW LEVEL SECURITY）
  禁止使用 app.current_store_id / app.current_tenant 等错误变量名。

updated_at 自动维护：
  使用 trigger trg_set_updated_at_<table> 在 BEFORE UPDATE 时刷新。

Revision ID: v367
Revises: v365_forge_ecosystem_metrics
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v367"
down_revision: Union[str, None] = "v365_forge_ecosystem_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ─────────────────────────────────────────────────────────────────────────────
# 安全 RLS 条件 — NULLIF NULL-guard 防止空字符串绕过（v056+ 标准）
# ─────────────────────────────────────────────────────────────────────────────
_SAFE_CONDITION = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"
)

_TASK2_TABLES = [
    "warehouse_zones",
    "warehouse_locations",
    "ingredient_location_bindings",
    "inventory_by_location",
]


def _apply_safe_rls(table: str) -> None:
    """创建标准安全 RLS：四操作 PERMISSIVE + NULLIF NULL-guard + FORCE。"""
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


def _attach_updated_at_trigger(table: str) -> None:
    """为表挂上 updated_at 自动刷新 trigger。"""
    op.execute(f"""
        CREATE OR REPLACE FUNCTION trg_fn_{table}_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(f"DROP TRIGGER IF EXISTS trg_set_updated_at_{table} ON {table}")
    op.execute(f"""
        CREATE TRIGGER trg_set_updated_at_{table}
        BEFORE UPDATE ON {table}
        FOR EACH ROW
        EXECUTE FUNCTION trg_fn_{table}_updated_at()
    """)


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────────
    # 1. warehouse_zones — 库区（含温区类型）
    #    temperature_type:
    #      NORMAL          常温（米面油干货）
    #      REFRIGERATED    冷藏（0~10℃，肉禽蛋蔬菜）
    #      FROZEN          冷冻（-18℃以下，速冻品）
    #      LIVE_SEAFOOD    活鲜（鱼缸/海鲜池）
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS warehouse_zones (
            id                 UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          UUID         NOT NULL,
            store_id           UUID         NOT NULL,
            zone_code          VARCHAR(32)  NOT NULL,
            zone_name          VARCHAR(64)  NOT NULL,
            temperature_type   VARCHAR(24)  NOT NULL
                                  CHECK (temperature_type IN
                                         ('NORMAL', 'REFRIGERATED', 'FROZEN', 'LIVE_SEAFOOD')),
            min_temp_celsius   NUMERIC(5, 2),
            max_temp_celsius   NUMERIC(5, 2),
            description        TEXT,
            enabled            BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted         BOOLEAN      NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_warehouse_zones_tenant_store_code
                UNIQUE (tenant_id, store_id, zone_code)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_warehouse_zones_tenant_store "
        "ON warehouse_zones (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_warehouse_zones_tenant_temp "
        "ON warehouse_zones (tenant_id, temperature_type)"
    )
    _apply_safe_rls("warehouse_zones")
    _attach_updated_at_trigger("warehouse_zones")

    # ─────────────────────────────────────────────────────────────────────
    # 2. warehouse_locations — 库位（隶属库区）
    #    location_code: "A-01-03"（aisle-rack-shelf）
    #    abc_class:   A=高频 / B=中频 / C=低频（基于近30天动销）
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS warehouse_locations (
            id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID         NOT NULL,
            zone_id             UUID         NOT NULL REFERENCES warehouse_zones(id),
            store_id            UUID         NOT NULL,
            location_code       VARCHAR(48)  NOT NULL,
            aisle               VARCHAR(8),
            rack                VARCHAR(8),
            shelf               VARCHAR(8),
            abc_class           VARCHAR(2)   CHECK (abc_class IN ('A', 'B', 'C')),
            max_capacity_units  INTEGER,
            enabled             BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN      NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_warehouse_locations_tenant_store_code
                UNIQUE (tenant_id, store_id, location_code)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_warehouse_locations_tenant_zone "
        "ON warehouse_locations (tenant_id, zone_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_warehouse_locations_tenant_abc "
        "ON warehouse_locations (tenant_id, abc_class)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_warehouse_locations_tenant_store "
        "ON warehouse_locations (tenant_id, store_id)"
    )
    _apply_safe_rls("warehouse_locations")
    _attach_updated_at_trigger("warehouse_locations")

    # ─────────────────────────────────────────────────────────────────────
    # 3. ingredient_location_bindings — 食材→默认库位映射
    #    is_primary: 主库位（每个食材在每个租户内最多一个 is_primary=TRUE）
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS ingredient_location_bindings (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            ingredient_id   UUID         NOT NULL,
            location_id     UUID         NOT NULL REFERENCES warehouse_locations(id),
            is_primary      BOOLEAN      NOT NULL DEFAULT TRUE,
            bound_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            bound_by        UUID,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_ing_loc_bindings_tenant_ing_loc
                UNIQUE (tenant_id, ingredient_id, location_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ing_loc_bindings_tenant_ing "
        "ON ingredient_location_bindings (tenant_id, ingredient_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ing_loc_bindings_tenant_loc "
        "ON ingredient_location_bindings (tenant_id, location_id)"
    )
    # 同一食材在同一租户内最多一个主库位（部分唯一索引）
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ing_loc_bindings_primary "
        "ON ingredient_location_bindings (tenant_id, ingredient_id) "
        "WHERE is_primary = TRUE AND is_deleted = FALSE"
    )
    _apply_safe_rls("ingredient_location_bindings")
    _attach_updated_at_trigger("ingredient_location_bindings")

    # ─────────────────────────────────────────────────────────────────────
    # 4. inventory_by_location — 按库位粒度的实时库存
    #    quantity:           物理库存量（与单位一致）
    #    reserved_quantity:  已预留（订单/调拨锁定）
    #    可用 = quantity - reserved_quantity
    #    expiry_date 冗余：从 ingredient_batches 复制，方便临期查询
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS inventory_by_location (
            id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID            NOT NULL,
            store_id            UUID            NOT NULL,
            location_id         UUID            NOT NULL REFERENCES warehouse_locations(id),
            ingredient_id       UUID            NOT NULL,
            batch_no            VARCHAR(64)     NOT NULL DEFAULT '',
            quantity            NUMERIC(14, 3)  NOT NULL DEFAULT 0,
            reserved_quantity   NUMERIC(14, 3)  NOT NULL DEFAULT 0,
            last_in_at          TIMESTAMPTZ,
            last_out_at         TIMESTAMPTZ,
            expiry_date         DATE,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_inventory_by_location_tenant_loc_ing_batch
                UNIQUE (tenant_id, location_id, ingredient_id, batch_no)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_by_location_tenant_store_ing "
        "ON inventory_by_location (tenant_id, store_id, ingredient_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_by_location_tenant_expiry "
        "ON inventory_by_location (tenant_id, expiry_date) "
        "WHERE expiry_date IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_by_location_tenant_loc "
        "ON inventory_by_location (tenant_id, location_id)"
    )
    _apply_safe_rls("inventory_by_location")
    _attach_updated_at_trigger("inventory_by_location")


def downgrade() -> None:
    for table in reversed(_TASK2_TABLES):
        # 先删 trigger / function
        op.execute(f"DROP TRIGGER IF EXISTS trg_set_updated_at_{table} ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS trg_fn_{table}_updated_at()")
        # 再删 RLS policy
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}")
        # 最后删表
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
