"""v108: 打印机配置与路由规则表

新建 2 张表：
  printers        — 门店打印机注册信息（名称/类型/连接方式/地址/纸宽）
  printer_routes  — 菜品类别→打印机路由规则（支持精确类别/标签/兜底）

设计要点：
  - printers.type CHECK: receipt/kitchen/label
  - printers.connection_type CHECK: usb/network/bluetooth
  - printers.paper_width CHECK: 58/80
  - printer_routes 支持 category_id 精确匹配、dish_tag 标签匹配、is_default 兜底
  - RLS: NULLIF(current_setting('app.tenant_id', true), '')::uuid 防 NULL 绕过
  - 索引覆盖 tenant_id / store_id / category_id / is_default

Revision ID: v108
Revises: v107
Create Date: 2026-04-02
"""

from alembic import op

revision = "v108"
down_revision = "v107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. 打印机表 ────────────────────────────────────────────────────
    op.execute("""
CREATE TABLE IF NOT EXISTS printers (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL,
    store_id         UUID NOT NULL,
    name             VARCHAR(50) NOT NULL,
    type             VARCHAR(20) NOT NULL DEFAULT 'receipt'
                         CHECK (type IN ('receipt', 'kitchen', 'label')),
    connection_type  VARCHAR(20) NOT NULL DEFAULT 'network'
                         CHECK (connection_type IN ('usb', 'network', 'bluetooth')),
    address          VARCHAR(100),
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    paper_width      INT NOT NULL DEFAULT 80
                         CHECK (paper_width IN (58, 80)),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""")

    # 索引
    op.execute("CREATE INDEX IF NOT EXISTS idx_printers_tenant_store ON printers(tenant_id, store_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_printers_store_active ON printers(store_id, is_active);")

    # updated_at 自动更新触发器
    op.execute("""
CREATE OR REPLACE FUNCTION update_printers_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;
""")
    op.execute("""
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_printers_updated_at'
  ) THEN
    CREATE TRIGGER trg_printers_updated_at
    BEFORE UPDATE ON printers
    FOR EACH ROW EXECUTE FUNCTION update_printers_updated_at();
  END IF;
END;
$$;
""")

    # RLS
    op.execute("ALTER TABLE printers ENABLE ROW LEVEL SECURITY;")
    op.execute("""
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'printers' AND policyname = 'tenant_isolation'
  ) THEN
    CREATE POLICY tenant_isolation ON printers
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
  END IF;
END;
$$;
""")

    # ── 2. 打印路由规则表 ──────────────────────────────────────────────
    op.execute("""
CREATE TABLE IF NOT EXISTS printer_routes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    store_id        UUID NOT NULL,
    printer_id      UUID NOT NULL REFERENCES printers(id) ON DELETE CASCADE,
    category_id     UUID,
    category_name   VARCHAR(50),
    dish_tag        VARCHAR(50),
    priority        INT NOT NULL DEFAULT 0,
    is_default      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""")

    # 索引
    op.execute("CREATE INDEX IF NOT EXISTS idx_printer_routes_tenant_store ON printer_routes(tenant_id, store_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_printer_routes_store_category ON printer_routes(store_id, category_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_printer_routes_is_default ON printer_routes(store_id, is_default) WHERE is_default = TRUE;")

    # updated_at 触发器
    op.execute("""
CREATE OR REPLACE FUNCTION update_printer_routes_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;
""")
    op.execute("""
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_printer_routes_updated_at'
  ) THEN
    CREATE TRIGGER trg_printer_routes_updated_at
    BEFORE UPDATE ON printer_routes
    FOR EACH ROW EXECUTE FUNCTION update_printer_routes_updated_at();
  END IF;
END;
$$;
""")

    # RLS
    op.execute("ALTER TABLE printer_routes ENABLE ROW LEVEL SECURITY;")
    op.execute("""
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'printer_routes' AND policyname = 'tenant_isolation'
  ) THEN
    CREATE POLICY tenant_isolation ON printer_routes
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
  END IF;
END;
$$;
""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS printer_routes;")
    op.execute("DROP TABLE IF EXISTS printers;")
    op.execute("DROP FUNCTION IF EXISTS update_printers_updated_at();")
    op.execute("DROP FUNCTION IF EXISTS update_printer_routes_updated_at();")
