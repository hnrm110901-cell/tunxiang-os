"""v114 — 徐记海鲜：宴席菜单多档次 + 渠道菜单管理

Revision ID: v114
Revises: v113
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v114"
down_revision = "v113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════
    # 一、宴席菜单体系
    # ═══════════════════════════════════════════════════════════════

    # ── 1. banquet_menus — 宴席菜单档次主表 ────────────────────────
    op.create_table(
        "banquet_menus",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True, comment="NULL=集团通用模板 / 有值=门店专属"),
        sa.Column("menu_code", sa.String(50), nullable=False, comment="菜单编码，如：BQ-288"),
        sa.Column("menu_name", sa.String(100), nullable=False, comment="如：精品宴288元/位"),
        sa.Column("tier", sa.String(20), nullable=False,
                  comment="standard=标准/premium=精品/luxury=豪华/custom=定制"),
        sa.Column("per_person_fen", sa.Integer, nullable=False, comment="人均价格（分）"),
        sa.Column("min_persons", sa.Integer, nullable=False, server_default="20",
                  comment="最少人数"),
        sa.Column("min_tables", sa.Integer, nullable=False, server_default="2",
                  comment="最少桌数"),
        sa.Column("description", sa.Text, nullable=True, comment="菜单简介"),
        sa.Column("highlights", JSONB, nullable=True, comment="亮点列表，如：[\"时令活鲜\",\"私厨服务\"]"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("valid_from", sa.Date, nullable=True, comment="有效期开始（季节性菜单）"),
        sa.Column("valid_until", sa.Date, nullable=True, comment="有效期截止"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )

    # ── 2. banquet_menu_sections — 宴席菜单分节（凉菜/热菜/海鲜/汤...）
    op.create_table(
        "banquet_menu_sections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("menu_id", UUID(as_uuid=True), nullable=False),
        sa.Column("section_name", sa.String(50), nullable=False,
                  comment="节名：凉菜/热菜/海鲜/汤/主食/甜品/水果"),
        sa.Column("serve_sequence", sa.Integer, nullable=False,
                  comment="出品顺序序号（凉菜=1最先，主食=最后）"),
        sa.Column("serve_delay_minutes", sa.Integer, nullable=False, server_default="0",
                  comment="相对开席时间的延迟分钟数（热菜=10分钟后出）"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("notes", sa.String(200), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # ── 3. banquet_menu_items — 宴席菜单明细（每节的菜品）
    op.create_table(
        "banquet_menu_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("section_id", UUID(as_uuid=True), nullable=False),
        sa.Column("menu_id", UUID(as_uuid=True), nullable=False, comment="冗余，便于直接查询"),
        sa.Column("dish_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dish_name", sa.String(100), nullable=False, comment="快照名称"),
        sa.Column("quantity_per_table", sa.Integer, nullable=False, server_default="1",
                  comment="每桌份数"),
        sa.Column("is_mandatory", sa.Boolean, nullable=False, server_default="true",
                  comment="True=固定菜，False=可替换/可选菜"),
        sa.Column("alternative_dish_ids", JSONB, nullable=True,
                  comment="可替换的其他菜品ID列表（换菜选项）"),
        sa.Column("extra_price_fen", sa.Integer, nullable=False, server_default="0",
                  comment="选此菜额外加价（针对高档替换菜）"),
        sa.Column("note", sa.String(200), nullable=True, comment="厨打单备注，如：少辣/不放葱"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # ── 4. banquet_sessions — 宴席场次（合同执行层）
    op.create_table(
        "banquet_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", UUID(as_uuid=True), nullable=True, comment="关联宴席合同"),
        sa.Column("banquet_menu_id", UUID(as_uuid=True), nullable=False, comment="使用的菜单"),
        sa.Column("session_name", sa.String(100), nullable=True, comment="场次名，如：刘先生婚宴"),
        sa.Column("scheduled_at", sa.TIMESTAMP(timezone=True), nullable=False, comment="计划开席时间"),
        sa.Column("actual_open_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("guest_count", sa.Integer, nullable=False),
        sa.Column("table_count", sa.Integer, nullable=False),
        sa.Column("table_ids", JSONB, nullable=True, comment="本次使用桌台UUID列表"),
        sa.Column("order_ids", JSONB, nullable=True, comment="生成的订单UUID列表（每桌一单）"),
        sa.Column("status", sa.String(20), nullable=False, server_default="scheduled",
                  comment="scheduled=已排期/preparing=备餐中/ready=就绪/serving=上菜中/completed=已结束/cancelled=取消"),
        sa.Column("current_section_id", UUID(as_uuid=True), nullable=True,
                  comment="当前正在出品的节ID"),
        sa.Column("next_section_at", sa.TIMESTAMP(timezone=True), nullable=True,
                  comment="下一节出品触发时间"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )

    # ═══════════════════════════════════════════════════════════════
    # 二、渠道菜单管理
    # ═══════════════════════════════════════════════════════════════

    # ── 5. sales_channels — 销售渠道配置 ────────────────────────────
    op.create_table(
        "sales_channels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True, comment="NULL=集团级渠道"),
        sa.Column("channel_type", sa.String(30), nullable=False,
                  comment="dine_in/banquet/meituan/eleme/douyin/miniapp/self_order/retail"),
        sa.Column("channel_name", sa.String(50), nullable=False, comment="如：美团外卖-徐记总店"),
        sa.Column("external_id", sa.String(100), nullable=True, comment="第三方平台店铺ID"),
        sa.Column("price_adjustment_pct", sa.Integer, nullable=False, server_default="0",
                  comment="整体价格调整百分比，正数=溢价，负数=折扣（如外卖+15%则填15）"),
        sa.Column("allow_live_seafood", sa.Boolean, nullable=False, server_default="false",
                  comment="是否允许上架活鲜（外卖渠道通常不允许）"),
        sa.Column("auto_sync_enabled", sa.Boolean, nullable=False, server_default="false",
                  comment="是否开启自动同步菜单到第三方平台"),
        sa.Column("last_sync_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("sync_status", sa.String(20), nullable=True,
                  comment="idle/syncing/success/failed"),
        sa.Column("config", JSONB, nullable=True, comment="渠道特殊配置，如美团的appKey/token等"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )

    # ── 6. channel_dish_configs — 渠道菜品个性化配置 ─────────────────
    op.create_table(
        "channel_dish_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dish_id", UUID(as_uuid=True), nullable=False),
        # 渠道专属价格
        sa.Column("channel_price_fen", sa.Integer, nullable=True,
                  comment="渠道专属价格（覆盖全局调整比例），NULL=使用全局调整"),
        # 渠道专属展示
        sa.Column("channel_name", sa.String(100), nullable=True, comment="渠道展示名（外卖平台名可能不同）"),
        sa.Column("channel_image_url", sa.String(512), nullable=True),
        sa.Column("channel_description", sa.Text, nullable=True),
        # 渠道可见性
        sa.Column("is_available", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_featured", sa.Boolean, nullable=False, server_default="false",
                  comment="是否在渠道置顶推荐"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        # 唯一约束：每个渠道每个菜品只有一条配置
        sa.UniqueConstraint("channel_id", "dish_id", name="uq_channel_dish"),
    )

    # ── 7. 索引 ──────────────────────────────────────────────────────
    op.create_index("ix_banquet_menus_tier", "banquet_menus", ["tier", "tenant_id"])
    op.create_index("ix_banquet_menu_sections_menu_id", "banquet_menu_sections", ["menu_id"])
    op.create_index("ix_banquet_menu_items_section_id", "banquet_menu_items", ["section_id"])
    op.create_index("ix_banquet_menu_items_menu_id", "banquet_menu_items", ["menu_id"])
    op.create_index("ix_banquet_sessions_store_id", "banquet_sessions", ["store_id", "status"])
    op.create_index("ix_banquet_sessions_scheduled_at", "banquet_sessions", ["scheduled_at"])
    op.create_index("ix_sales_channels_type", "sales_channels", ["channel_type", "tenant_id"])
    op.create_index("ix_channel_dish_configs_channel", "channel_dish_configs", ["channel_id"])
    op.create_index("ix_channel_dish_configs_dish", "channel_dish_configs", ["dish_id"])

    # ── 8. RLS ────────────────────────────────────────────────────────
    rls_tables = [
        "banquet_menus", "banquet_menu_sections", "banquet_menu_items",
        "banquet_sessions", "sales_channels", "channel_dish_configs",
    ]
    for table in rls_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
        """)

    # ── 9. updated_at 触发器 ──────────────────────────────────────────
    trigger_tables = [
        "banquet_menus", "banquet_sessions", "sales_channels", "channel_dish_configs",
    ]
    for table in trigger_tables:
        op.execute(f"""
            DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();
        """)


def downgrade() -> None:
    for table in [
        "channel_dish_configs", "sales_channels",
        "banquet_sessions", "banquet_menu_items",
        "banquet_menu_sections", "banquet_menus",
    ]:
        op.drop_table(table)
