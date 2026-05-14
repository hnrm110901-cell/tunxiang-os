"""v432 — RequisitionTemplate 3 表 + purchase_orders 3 表 (#589 闭环)（PRD-07 / Phase 2 W10 / T2）

业务背景：
  徐记海鲜门店每天上传申购单，80% SKU 重复。每次手工录 30+ 行 = 15 分钟/店 × 200 店
  = 50 工时/天。**操作低效 → 店长抵触 → 替换失败**。
  本表族为总部预设 RequisitionTemplate（按品类：海鲜/蔬菜/调料/酒水），仓库（大店 /
  小店 / 中央厨房）可绑定不同模板，一键发起申购自动填充 SKU + AI 推荐量。
  长期资产：门店申购行为画像 → AI 补货模型输入。

设计要点：
  PRD-07 三表：
  1. requisition_templates — 模板主表 (tenant_id, name, category, is_active, created_by)
  2. requisition_template_items — 模板明细 (template_id FK CASCADE, ingredient_id,
                                  default_qty NULL=AI, qty_method enum)
  3. warehouse_requisition_template_bindings — 仓库绑定 (warehouse_id, template_id FK,
                                                auto_trigger_cron None=手动)

  #589 三表（pre-existing baseline bug — purchase_order_routes.py docstring 描述但仓库无 migration）：
  4. purchase_orders — 采购单 (含 PRD-03 doc_number VARCHAR(64) + po_number 兼容字段)
  5. purchase_order_items — 采购明细 (FK CASCADE)
  6. ingredient_batches — 批次表 (FK 可空 — 也可独立入库)

设计沿用：
  - RLS 标准模式：tenant_id::text = current_setting('app.tenant_id', true)
  - ENABLE + FORCE + POLICY + WITH CHECK 四联 inline（v428/v429/v430/v431 一致）
  - inspector-and-skip 模式（与 v421+ 一致）

Revision ID: v432_requisition_template_and_purchase_orders
Revises: v431_rfq_schema
Create Date: 2026-05-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v432_requisition_template_and_purchase_orders"
down_revision: Union[str, Sequence[str], None] = "v431_rfq_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ───── PRD-07 1/3: requisition_templates 模板主表 ─────────────────────────
    if "requisition_templates" not in existing:
        op.execute(
            """
            CREATE TABLE requisition_templates (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                name                VARCHAR(120) NOT NULL,
                category            VARCHAR(32) NOT NULL,
                is_active           BOOLEAN NOT NULL DEFAULT TRUE,
                notes               TEXT,
                created_by          UUID NOT NULL,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_req_tpl_category
                    CHECK (category IN ('seafood','meat','vegetable','seasoning','beverage','dry_goods','frozen','other'))
            )
            """
        )
        op.execute("ALTER TABLE requisition_templates ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE requisition_templates FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY requisition_templates_tenant_isolation
            ON requisition_templates
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        op.execute(
            """
            CREATE INDEX idx_req_tpl_tenant_active
            ON requisition_templates (tenant_id, is_active, category)
            WHERE is_deleted = FALSE
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX uq_req_tpl_tenant_name
            ON requisition_templates (tenant_id, name)
            WHERE is_deleted = FALSE
            """
        )

    # ───── PRD-07 2/3: requisition_template_items 模板明细 ───────────────────
    if "requisition_template_items" not in existing:
        op.execute(
            """
            CREATE TABLE requisition_template_items (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                template_id         UUID NOT NULL,
                ingredient_id       UUID NOT NULL,
                default_qty         NUMERIC(14,4),
                qty_method          VARCHAR(20) NOT NULL DEFAULT 'fixed',
                qty_unit            VARCHAR(16),
                sort_order          INTEGER NOT NULL DEFAULT 0,
                notes               TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_req_tpl_item_qty_method
                    CHECK (qty_method IN ('fixed','ai_predicted','last_order','par_level')),
                CONSTRAINT chk_req_tpl_item_fixed_has_qty
                    CHECK (qty_method != 'fixed' OR default_qty IS NOT NULL),
                CONSTRAINT chk_req_tpl_item_qty_positive
                    CHECK (default_qty IS NULL OR default_qty > 0),
                CONSTRAINT fk_req_tpl_item_template
                    FOREIGN KEY (template_id) REFERENCES requisition_templates(id) ON DELETE CASCADE
            )
            """
        )
        op.execute("ALTER TABLE requisition_template_items ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE requisition_template_items FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY requisition_template_items_tenant_isolation
            ON requisition_template_items
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        op.execute(
            """
            CREATE INDEX idx_req_tpl_item_template
            ON requisition_template_items (tenant_id, template_id, sort_order)
            WHERE is_deleted = FALSE
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX uq_req_tpl_item_template_ingredient
            ON requisition_template_items (tenant_id, template_id, ingredient_id)
            WHERE is_deleted = FALSE
            """
        )

    # ───── PRD-07 3/3: warehouse_requisition_template_bindings 仓库绑定 ──────
    if "warehouse_requisition_template_bindings" not in existing:
        op.execute(
            """
            CREATE TABLE warehouse_requisition_template_bindings (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                warehouse_id        UUID NOT NULL,
                template_id         UUID NOT NULL,
                auto_trigger_cron   VARCHAR(64),
                priority            INTEGER NOT NULL DEFAULT 0,
                created_by          UUID NOT NULL,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT fk_wh_req_tpl_binding_template
                    FOREIGN KEY (template_id) REFERENCES requisition_templates(id) ON DELETE CASCADE
            )
            """
        )
        op.execute("ALTER TABLE warehouse_requisition_template_bindings ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE warehouse_requisition_template_bindings FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY warehouse_requisition_template_bindings_tenant_isolation
            ON warehouse_requisition_template_bindings
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        op.execute(
            """
            CREATE INDEX idx_wh_req_tpl_warehouse
            ON warehouse_requisition_template_bindings (tenant_id, warehouse_id, priority)
            WHERE is_deleted = FALSE
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX uq_wh_req_tpl_binding
            ON warehouse_requisition_template_bindings (tenant_id, warehouse_id, template_id)
            WHERE is_deleted = FALSE
            """
        )

    # ───── #589 闭环 1/3: purchase_orders 采购单主表 ──────────────────────────
    # #589 ask 含 PRD-03 doc_number VARCHAR(64) 字段（避免后续二次 ALTER）+ po_number 兼容字段
    # 索引 (tenant_id, store_id, status) + (tenant_id, supplier_id)（per #589 文中提议）
    if "purchase_orders" not in existing:
        op.execute(
            """
            CREATE TABLE purchase_orders (
                id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id               UUID NOT NULL,
                store_id                UUID NOT NULL,
                supplier_id             UUID,
                po_number               VARCHAR(64) NOT NULL,
                doc_number              VARCHAR(64),
                status                  VARCHAR(20) NOT NULL DEFAULT 'draft',
                total_amount_fen        BIGINT NOT NULL DEFAULT 0,
                expected_delivery_date  DATE,
                actual_delivery_date    DATE,
                approved_by             UUID,
                approved_at             TIMESTAMPTZ,
                received_at             TIMESTAMPTZ,
                requisition_id          UUID,
                notes                   TEXT,
                created_by              UUID,
                created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_po_status
                    CHECK (status IN ('draft','pending_approval','approved','received','cancelled')),
                CONSTRAINT chk_po_total_nonneg
                    CHECK (total_amount_fen >= 0)
            )
            """
        )
        op.execute("ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE purchase_orders FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY purchase_orders_tenant_isolation
            ON purchase_orders
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        # #589 提议的两个主查询索引
        op.execute(
            """
            CREATE INDEX idx_po_tenant_store_status
            ON purchase_orders (tenant_id, store_id, status)
            WHERE is_deleted = FALSE
            """
        )
        op.execute(
            """
            CREATE INDEX idx_po_tenant_supplier
            ON purchase_orders (tenant_id, supplier_id)
            WHERE is_deleted = FALSE
            """
        )
        # PRD-03 doc_number 唯一性（per tenant，已规则化）
        op.execute(
            """
            CREATE UNIQUE INDEX uq_po_tenant_po_number
            ON purchase_orders (tenant_id, po_number)
            WHERE is_deleted = FALSE
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX uq_po_tenant_doc_number
            ON purchase_orders (tenant_id, doc_number)
            WHERE doc_number IS NOT NULL AND is_deleted = FALSE
            """
        )

    # ───── #589 闭环 2/3: purchase_order_items 采购明细 ───────────────────────
    if "purchase_order_items" not in existing:
        op.execute(
            """
            CREATE TABLE purchase_order_items (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                po_id               UUID NOT NULL,
                ingredient_id       UUID NOT NULL,
                ingredient_name     VARCHAR(200) NOT NULL DEFAULT '',
                quantity            NUMERIC(14,4) NOT NULL,
                unit                VARCHAR(16) NOT NULL DEFAULT '',
                unit_price_fen      BIGINT NOT NULL DEFAULT 0,
                subtotal_fen        BIGINT NOT NULL DEFAULT 0,
                received_quantity   NUMERIC(14,4) NOT NULL DEFAULT 0,
                notes               TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_poi_quantity_pos
                    CHECK (quantity > 0),
                CONSTRAINT chk_poi_received_nonneg
                    CHECK (received_quantity >= 0),
                CONSTRAINT fk_poi_po
                    FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE CASCADE
            )
            """
        )
        op.execute("ALTER TABLE purchase_order_items ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE purchase_order_items FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY purchase_order_items_tenant_isolation
            ON purchase_order_items
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        op.execute(
            """
            CREATE INDEX idx_poi_po
            ON purchase_order_items (tenant_id, po_id)
            WHERE is_deleted = FALSE
            """
        )
        op.execute(
            """
            CREATE INDEX idx_poi_ingredient
            ON purchase_order_items (tenant_id, ingredient_id)
            WHERE is_deleted = FALSE
            """
        )

    # ───── #589 闭环 3/3: ingredient_batches 批次表 ───────────────────────────
    if "ingredient_batches" not in existing:
        op.execute(
            """
            CREATE TABLE ingredient_batches (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                ingredient_id       UUID NOT NULL,
                store_id            UUID NOT NULL,
                po_id               UUID,
                batch_no            VARCHAR(64),
                quantity            NUMERIC(14,4) NOT NULL,
                unit_price_fen      BIGINT NOT NULL DEFAULT 0,
                expiry_date         DATE,
                received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                notes               TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_ib_quantity_pos
                    CHECK (quantity > 0),
                CONSTRAINT fk_ib_po
                    FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE SET NULL
            )
            """
        )
        op.execute("ALTER TABLE ingredient_batches ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE ingredient_batches FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY ingredient_batches_tenant_isolation
            ON ingredient_batches
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        op.execute(
            """
            CREATE INDEX idx_ib_tenant_store_ingredient
            ON ingredient_batches (tenant_id, store_id, ingredient_id)
            WHERE is_deleted = FALSE
            """
        )
        op.execute(
            """
            CREATE INDEX idx_ib_expiry
            ON ingredient_batches (tenant_id, expiry_date)
            WHERE expiry_date IS NOT NULL AND is_deleted = FALSE
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # FK 依赖序：ingredient_batches → purchase_order_items → purchase_orders
    # PRD-07: warehouse_requisition_template_bindings + requisition_template_items → requisition_templates
    if "ingredient_batches" in existing:
        op.execute("DROP TABLE ingredient_batches CASCADE")
    if "purchase_order_items" in existing:
        op.execute("DROP TABLE purchase_order_items CASCADE")
    if "purchase_orders" in existing:
        op.execute("DROP TABLE purchase_orders CASCADE")
    if "warehouse_requisition_template_bindings" in existing:
        op.execute("DROP TABLE warehouse_requisition_template_bindings CASCADE")
    if "requisition_template_items" in existing:
        op.execute("DROP TABLE requisition_template_items CASCADE")
    if "requisition_templates" in existing:
        op.execute("DROP TABLE requisition_templates CASCADE")
