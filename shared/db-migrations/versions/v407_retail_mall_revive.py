"""v407: 零售商城表 revive — retail_products_v2 / retail_orders_v2 / retail_order_items_v2

历史背景：原 v073_retail_mall_tables 在 PR #128 chain rescue (a566102d) 中
被改名 v073b 并 disabled（.py.disabled 后缀），但 main.py 已 wired
retail_mall_routes — 这部分 API 实际访问会撞 "relation does not exist"。
PR #357 ORM↔migration drift 检测捕获 (3 张 ORM 无 CREATE TABLE)。

本 revive 修两处历史 bug 后并入 main chain：
  1. revision/down_revision 改写为 v407 / v406_nlq_reports_views_p3 (current head)
  2. _apply_rls helper 修 Class F bug — INSERT 用 WITH CHECK 而非 USING，
     UPDATE 用 USING+WITH CHECK (PG.7 防 tenant_id 行漂移)

新增表（columns 与 services/tx-trade/src/models/retail_mall.py ORM 完全对齐）：
  retail_products_v2    — 零售商品
  retail_orders_v2      — 零售订单
  retail_order_items_v2 — 零售订单明细

RLS 策略（修正版）：
  ENABLE + FORCE ROW LEVEL SECURITY
  SELECT/DELETE: USING (tenant_id check)
  INSERT:        WITH CHECK (tenant_id check)
  UPDATE:        USING + WITH CHECK (PG.7 防跨租户行漂移)

Revision ID: v407_retail_mall_revive
Revises: v406_nlq_reports_views_p3
Create Date: 2026-05-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v407_retail_mall_revive"
down_revision: Union[str, Sequence[str], None] = "v406_nlq_reports_views_p3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TENANT_PREDICATE = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def _apply_rls(table_name: str) -> None:
    """ENABLE+FORCE RLS + 4 条 RESTRICTIVE 策略（INSERT WITH CHECK / UPDATE 双子句）。"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;")

    # SELECT — USING only
    op.execute(f"""
        CREATE POLICY {table_name}_select_tenant ON {table_name}
        AS RESTRICTIVE FOR SELECT
        USING ({_TENANT_PREDICATE});
    """)

    # INSERT — WITH CHECK only (PG: USING invalid for INSERT)
    op.execute(f"""
        CREATE POLICY {table_name}_insert_tenant ON {table_name}
        AS RESTRICTIVE FOR INSERT
        WITH CHECK ({_TENANT_PREDICATE});
    """)

    # UPDATE — USING + WITH CHECK (PG.7 防 tenant_id 行漂移)
    op.execute(f"""
        CREATE POLICY {table_name}_update_tenant ON {table_name}
        AS RESTRICTIVE FOR UPDATE
        USING ({_TENANT_PREDICATE})
        WITH CHECK ({_TENANT_PREDICATE});
    """)

    # DELETE — USING only
    op.execute(f"""
        CREATE POLICY {table_name}_delete_tenant ON {table_name}
        AS RESTRICTIVE FOR DELETE
        USING ({_TENANT_PREDICATE});
    """)


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # retail_products_v2 — 零售商品
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS retail_products_v2 (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            store_id        UUID         NOT NULL,
            name            VARCHAR(200) NOT NULL,
            sku             VARCHAR(100) NOT NULL,
            category        VARCHAR(50)  NOT NULL DEFAULT 'merchandise',
            price_fen       INTEGER      NOT NULL,
            cost_fen        INTEGER      NOT NULL DEFAULT 0,
            stock_qty       INTEGER      NOT NULL DEFAULT 0,
            min_stock       INTEGER      NOT NULL DEFAULT 0,
            image_url       TEXT,
            status          VARCHAR(20)  NOT NULL DEFAULT 'active',
            is_weighable    BOOLEAN      NOT NULL DEFAULT FALSE,
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """)

    _apply_rls("retail_products_v2")

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_retail_products_v2_tenant
            ON retail_products_v2 (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_retail_products_v2_store_status
            ON retail_products_v2 (store_id, status);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_retail_products_v2_tenant_category
            ON retail_products_v2 (tenant_id, category);
    """)

    # ─────────────────────────────────────────────────────────────────
    # retail_orders_v2 — 零售订单
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS retail_orders_v2 (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            store_id        UUID         NOT NULL,
            order_no        VARCHAR(50)  NOT NULL UNIQUE,
            customer_id     UUID,
            total_fen       INTEGER      NOT NULL DEFAULT 0,
            discount_fen    INTEGER      NOT NULL DEFAULT 0,
            final_fen       INTEGER      NOT NULL DEFAULT 0,
            payment_method  VARCHAR(30),
            status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
            paid_at         TIMESTAMPTZ,
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """)

    _apply_rls("retail_orders_v2")

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_retail_orders_v2_tenant
            ON retail_orders_v2 (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_retail_orders_v2_store_status
            ON retail_orders_v2 (store_id, status);
    """)

    # ─────────────────────────────────────────────────────────────────
    # retail_order_items_v2 — 零售订单明细
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS retail_order_items_v2 (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            order_id        UUID         NOT NULL REFERENCES retail_orders_v2(id),
            product_id      UUID         NOT NULL REFERENCES retail_products_v2(id),
            product_name    VARCHAR(200) NOT NULL,
            quantity        INTEGER      NOT NULL,
            unit_price_fen  INTEGER      NOT NULL,
            subtotal_fen    INTEGER      NOT NULL,
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """)

    _apply_rls("retail_order_items_v2")

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_retail_order_items_v2_tenant
            ON retail_order_items_v2 (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_retail_order_items_v2_order
            ON retail_order_items_v2 (order_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_retail_order_items_v2_product
            ON retail_order_items_v2 (product_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS retail_order_items_v2 CASCADE;")
    op.execute("DROP TABLE IF EXISTS retail_orders_v2 CASCADE;")
    op.execute("DROP TABLE IF EXISTS retail_products_v2 CASCADE;")
