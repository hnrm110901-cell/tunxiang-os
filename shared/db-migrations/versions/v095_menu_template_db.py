"""v095: 菜单模板中心 DB 化 — 将 menu_template.py 的内存存储迁移到 PostgreSQL

新建 6 张表：
  - menu_templates         — 菜单模板主表
  - menu_template_dishes   — 模板菜品明细
  - store_menu_publishes   — 门店已发布菜单（模板→门店的发布记录）
  - menu_channel_prices    — 菜品渠道差异价（全局，按 dish+channel）
  - store_seasonal_menus   — 门店季节菜单
  - store_room_menus       — 门店包厢专属菜单

所有表：
  - 含 tenant_id + RLS 策略（使用 NULLIF(app.tenant_id) 防 NULL 绕过）
  - 含 created_at / updated_at / is_deleted（基类字段）

Revision ID: v095
Revises: v094
Create Date: 2026-04-01
"""

from alembic import op

revision = "v095"
down_revision = "v094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. menu_templates — 菜单模板主表 ──────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS menu_templates (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            name        VARCHAR(200) NOT NULL,
            rules       JSONB       NOT NULL DEFAULT '{}',
            status      VARCHAR(20) NOT NULL DEFAULT 'draft',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted  BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("ALTER TABLE menu_templates ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY menu_templates_rls ON menu_templates
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_menu_templates_tenant
            ON menu_templates(tenant_id)
            WHERE is_deleted = false
    """)

    # ── 2. menu_template_dishes — 模板菜品明细 ────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS menu_template_dishes (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            template_id UUID        NOT NULL REFERENCES menu_templates(id) ON DELETE CASCADE,
            dish_id     UUID        NOT NULL,
            sort_order  INT         NOT NULL DEFAULT 0,
            dish_data   JSONB       NOT NULL DEFAULT '{}',
            UNIQUE (tenant_id, template_id, dish_id)
        )
    """)
    op.execute("ALTER TABLE menu_template_dishes ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY menu_template_dishes_rls ON menu_template_dishes
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_menu_template_dishes_template
            ON menu_template_dishes(tenant_id, template_id)
    """)

    # ── 3. store_menu_publishes — 门店已发布菜单 ──────────────────────────
    # 每个门店只有一条 active 记录（覆盖更新），记录哪个模板当前生效
    op.execute("""
        CREATE TABLE IF NOT EXISTS store_menu_publishes (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            store_id    UUID        NOT NULL,
            template_id UUID        NOT NULL REFERENCES menu_templates(id),
            published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            status      VARCHAR(20) NOT NULL DEFAULT 'active',
            UNIQUE (tenant_id, store_id)
        )
    """)
    op.execute("ALTER TABLE store_menu_publishes ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY store_menu_publishes_rls ON store_menu_publishes
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_menu_publishes_store
            ON store_menu_publishes(tenant_id, store_id)
    """)

    # ── 4. menu_channel_prices — 菜品渠道差异价 ───────────────────────────
    # 全局级（不绑 store），set_channel_price() 设置后 get_store_menu() 读取应用
    op.execute("""
        CREATE TABLE IF NOT EXISTS menu_channel_prices (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            dish_id     UUID        NOT NULL,
            channel     VARCHAR(30) NOT NULL,
            price_fen   INT         NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, dish_id, channel)
        )
    """)
    op.execute("ALTER TABLE menu_channel_prices ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY menu_channel_prices_rls ON menu_channel_prices
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_menu_channel_prices_dish
            ON menu_channel_prices(tenant_id, dish_id, channel)
    """)

    # ── 5. store_seasonal_menus — 门店季节菜单 ────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS store_seasonal_menus (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            store_id    UUID        NOT NULL,
            season      VARCHAR(20) NOT NULL,
            dishes      JSONB       NOT NULL DEFAULT '[]',
            dish_count  INT         NOT NULL DEFAULT 0,
            status      VARCHAR(20) NOT NULL DEFAULT 'active',
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id, season)
        )
    """)
    op.execute("ALTER TABLE store_seasonal_menus ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY store_seasonal_menus_rls ON store_seasonal_menus
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_seasonal_menus_store
            ON store_seasonal_menus(tenant_id, store_id, season)
    """)

    # ── 6. store_room_menus — 门店包厢专属菜单 ────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS store_room_menus (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            store_id    UUID        NOT NULL,
            room_type   VARCHAR(30) NOT NULL,
            dishes      JSONB       NOT NULL DEFAULT '[]',
            dish_count  INT         NOT NULL DEFAULT 0,
            status      VARCHAR(20) NOT NULL DEFAULT 'active',
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id, room_type)
        )
    """)
    op.execute("ALTER TABLE store_room_menus ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY store_room_menus_rls ON store_room_menus
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_room_menus_store
            ON store_room_menus(tenant_id, store_id, room_type)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS store_room_menus CASCADE")
    op.execute("DROP TABLE IF EXISTS store_seasonal_menus CASCADE")
    op.execute("DROP TABLE IF EXISTS menu_channel_prices CASCADE")
    op.execute("DROP TABLE IF EXISTS store_menu_publishes CASCADE")
    op.execute("DROP TABLE IF EXISTS menu_template_dishes CASCADE")
    op.execute("DROP TABLE IF EXISTS menu_templates CASCADE")
