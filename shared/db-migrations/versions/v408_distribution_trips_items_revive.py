"""v408: distribution_trips / distribution_items revive

PR #357 ORM↔migration drift 检测捕获 distribution_items + distribution_trips
两张 ORM 无 CREATE TABLE。本 PR revive 接入 main chain。

历史背景：原 v069_distribution_tables 在 PR #128 chain rescue (a566102d) 中
被改名 v069b 并 disabled。后续 v096_distribution_db.py（enabled）部分覆盖 ——
**仅创建 distribution_warehouses + distribution_plans**（且 column 结构与 v069
原稿 / 现行 ORM 都不一致）—— 但未创建 distribution_trips / distribution_items。
此 PR surgical 范围：**仅 revive 两张缺失的表**。

──────── 本 PR 范围（drift 直击） ────────
新增表（columns 与 services/tx-supply/src/models/distribution.py ORM 完全对齐）：
  distribution_trips    — 配送行程（plan_id FK distribution_plans.id）
  distribution_items    — 配送明细（trip_id FK distribution_trips.id）

──────── 不在本 PR 范围（待单独审视） ────────
distribution_warehouses + distribution_plans 已被 v096_distribution_db.py 创建，
但 schema 与 ORM 严重漂移（column-level，drift 检测目前不覆盖）：
  - warehouses: v096 多 warehouse_id (NOT NULL UNIQUE) + lat/lng NUMERIC; ORM 无
                warehouse_id + lat/lng Float + 多 contact_name/phone/is_deleted
  - plans:      v096 用 route+store_deliveries(NOT NULL); ORM 用 route_json +
                多 driver_name/vehicle_no/is_deleted + 无 store_deliveries
  → ORM INSERT/UPDATE 这两张表 runtime 必坏（NOT NULL 缺供 / column 不存在）。
  → 单独 audit issue 跟进 + ORM 列重写 OR ALTER TABLE 补齐。

──────── 修复 v069 原文件 SECURITY bug (Class F2) ────────
原 _apply_rls helper 4 个 action 全用 USING；PG 不接受 INSERT POLICY USING。
按 PR #361 retail_mall revive 同模式修：
  SELECT/DELETE: USING only
  INSERT:        WITH CHECK only
  UPDATE:        USING + WITH CHECK (PG.7 防 tenant_id 行漂移)

Revision ID: v408_distribution_trips_items_revive
Revises: v407_retail_mall_revive
Create Date: 2026-05-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v408_distribution_trips_items_revive"
down_revision: Union[str, Sequence[str], None] = "v407_retail_mall_revive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TENANT_PREDICATE = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)

_NEW_TABLES = ["distribution_trips", "distribution_items"]


def _apply_rls(table_name: str) -> None:
    """ENABLE+FORCE RLS + 4 条 RESTRICTIVE 策略（INSERT WITH CHECK / UPDATE 双子句）。"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;")

    op.execute(f"""
        CREATE POLICY {table_name}_select_tenant ON {table_name}
        AS RESTRICTIVE FOR SELECT
        USING ({_TENANT_PREDICATE});
    """)
    op.execute(f"""
        CREATE POLICY {table_name}_insert_tenant ON {table_name}
        AS RESTRICTIVE FOR INSERT
        WITH CHECK ({_TENANT_PREDICATE});
    """)
    op.execute(f"""
        CREATE POLICY {table_name}_update_tenant ON {table_name}
        AS RESTRICTIVE FOR UPDATE
        USING ({_TENANT_PREDICATE})
        WITH CHECK ({_TENANT_PREDICATE});
    """)
    op.execute(f"""
        CREATE POLICY {table_name}_delete_tenant ON {table_name}
        AS RESTRICTIVE FOR DELETE
        USING ({_TENANT_PREDICATE});
    """)


def upgrade() -> None:
    # ── distribution_trips (FK→distribution_plans.id 由 v096 创建) ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS distribution_trips (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            plan_id         UUID        NOT NULL REFERENCES distribution_plans(id),
            store_id        UUID        NOT NULL,
            sequence        INT         NOT NULL DEFAULT 0,
            status          VARCHAR(20) NOT NULL DEFAULT 'pending',
            scheduled_at    TIMESTAMPTZ,
            delivered_at    TIMESTAMPTZ,
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    # ── distribution_items ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS distribution_items (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            trip_id             UUID        NOT NULL REFERENCES distribution_trips(id),
            item_id             VARCHAR(200) NOT NULL,
            item_name           VARCHAR(200) NOT NULL DEFAULT '',
            quantity            NUMERIC(10,3) NOT NULL DEFAULT 0,
            unit                VARCHAR(20)  NOT NULL DEFAULT '',
            received_quantity   NUMERIC(10,3),
            status              VARCHAR(20)  NOT NULL DEFAULT 'pending',
            notes               TEXT,
            is_deleted          BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """)

    # ── RLS (仅本 PR 新建的 2 张表；warehouses/plans 由 v096 已配置) ──
    for table in _NEW_TABLES:
        _apply_rls(table)

    # ── 索引 (仅本 PR 新建表) ──
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dist_trips_plan
            ON distribution_trips (tenant_id, plan_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dist_trips_store
            ON distribution_trips (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dist_items_trip
            ON distribution_items (tenant_id, trip_id);
    """)


def downgrade() -> None:
    # 顺序倒序：items 引用 trips
    op.execute("DROP TABLE IF EXISTS distribution_items CASCADE;")
    op.execute("DROP TABLE IF EXISTS distribution_trips CASCADE;")
