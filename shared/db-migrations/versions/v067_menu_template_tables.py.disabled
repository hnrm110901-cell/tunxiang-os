"""v067: 菜单模板持久化 — 模板 / 门店发布 / 渠道差异价 / 季节菜单 / 包间菜单

将 menu_template 服务从内存存储迁移到 PostgreSQL。

新增表：
  menu_templates         — 菜单模板主表
  store_menu_publishes   — 门店发布记录
  channel_prices         — 渠道差异价
  seasonal_menus         — 季节菜单
  room_menus             — 包间菜单

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v067
Revises: v046
Create Date: 2026-03-31
"""

from alembic import op

revision = "v067"
down_revision = "v046"
branch_labels = None
depends_on = None

_TABLES = [
    "menu_templates",
    "store_menu_publishes",
    "channel_prices",
    "seasonal_menus",
    "room_menus",
]


def _apply_rls(table_name: str) -> None:
    """为表启用 RLS 并创建 4 操作安全策略"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY {table_name}_{action.lower()}_tenant ON {table_name}
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. menu_templates — 菜单模板主表
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS menu_templates (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL,
            name              VARCHAR(200) NOT NULL,
            dishes            JSONB       NOT NULL DEFAULT '[]',
            rules             JSONB       NOT NULL DEFAULT '{}',
            status            VARCHAR(20) NOT NULL DEFAULT 'draft',
            published_stores  JSONB       NOT NULL DEFAULT '[]',
            package_price_fen INT,
            guest_count       INT,
            description       VARCHAR(500),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted        BOOLEAN     NOT NULL DEFAULT FALSE
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_menu_templates_tenant
            ON menu_templates (tenant_id);
    """)
    _apply_rls("menu_templates")

    # ─────────────────────────────────────────────────────────────────
    # 2. store_menu_publishes — 门店发布记录
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS store_menu_publishes (
            id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID        NOT NULL,
            store_id       UUID        NOT NULL,
            template_id    UUID        NOT NULL,
            template_name  VARCHAR(200) NOT NULL,
            dishes         JSONB       NOT NULL DEFAULT '[]',
            status         VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted     BOOLEAN     NOT NULL DEFAULT FALSE
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_store_menu_publishes_tenant
            ON store_menu_publishes (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_store_menu_publishes_store
            ON store_menu_publishes (tenant_id, store_id);
    """)
    _apply_rls("store_menu_publishes")

    # ─────────────────────────────────────────────────────────────────
    # 3. channel_prices — 渠道差异价
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS channel_prices (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            dish_id     UUID        NOT NULL,
            channel     VARCHAR(20) NOT NULL,
            price_fen   INT         NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted  BOOLEAN     NOT NULL DEFAULT FALSE,
            UNIQUE(tenant_id, dish_id, channel)
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_channel_prices_tenant
            ON channel_prices (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_channel_prices_dish
            ON channel_prices (tenant_id, dish_id);
    """)
    _apply_rls("channel_prices")

    # ─────────────────────────────────────────────────────────────────
    # 4. seasonal_menus — 季节菜单
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS seasonal_menus (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            store_id    UUID        NOT NULL,
            season      VARCHAR(20) NOT NULL,
            dishes      JSONB       NOT NULL DEFAULT '[]',
            dish_count  INT         NOT NULL DEFAULT 0,
            status      VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted  BOOLEAN     NOT NULL DEFAULT FALSE,
            UNIQUE(tenant_id, store_id, season)
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_seasonal_menus_tenant
            ON seasonal_menus (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_seasonal_menus_store
            ON seasonal_menus (tenant_id, store_id);
    """)
    _apply_rls("seasonal_menus")

    # ─────────────────────────────────────────────────────────────────
    # 5. room_menus — 包间菜单
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS room_menus (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            store_id    UUID        NOT NULL,
            room_type   VARCHAR(20) NOT NULL,
            dishes      JSONB       NOT NULL DEFAULT '[]',
            dish_count  INT         NOT NULL DEFAULT 0,
            status      VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted  BOOLEAN     NOT NULL DEFAULT FALSE,
            UNIQUE(tenant_id, store_id, room_type)
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_room_menus_tenant
            ON room_menus (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_room_menus_store
            ON room_menus (tenant_id, store_id);
    """)
    _apply_rls("room_menus")


def downgrade() -> None:
    for table_name in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
