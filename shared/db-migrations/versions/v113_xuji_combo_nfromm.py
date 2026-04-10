"""v113 — 徐记海鲜：套餐N选M分组支持

Revision ID: v113
Revises: v112
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v113"
down_revision = "v112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. dish_combos 表扩展（IF NOT EXISTS 保证幂等）──────────────
    op.execute("""
        ALTER TABLE dish_combos
            ADD COLUMN IF NOT EXISTS combo_type      VARCHAR(20)  NOT NULL DEFAULT 'fixed',
            ADD COLUMN IF NOT EXISTS description     TEXT,
            ADD COLUMN IF NOT EXISTS min_person      INTEGER,
            ADD COLUMN IF NOT EXISTS is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS available_from  TIME,
            ADD COLUMN IF NOT EXISTS available_until TIME,
            ADD COLUMN IF NOT EXISTS image_url       VARCHAR(512)
    """)

    # ── 2. combo_groups — N选M分组表 ─────────────────────────────
    op.create_table(
        "combo_groups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("combo_id", UUID(as_uuid=True), nullable=False, comment="关联套餐ID"),
        sa.Column("group_name", sa.String(100), nullable=False, comment="分组名，如：主菜（任选2款）"),
        sa.Column("min_select", sa.Integer, nullable=False, server_default="1", comment="最少选N款"),
        sa.Column("max_select", sa.Integer, nullable=False, server_default="1", comment="最多选M款"),
        sa.Column("is_required", sa.Boolean, nullable=False, server_default="true", comment="是否必选"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("notes", sa.String(200), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )

    # ── 3. combo_group_items — 分组内可选菜品 ────────────────────
    op.create_table(
        "combo_group_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", UUID(as_uuid=True), nullable=False, comment="关联分组ID"),
        sa.Column("dish_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dish_name", sa.String(100), nullable=False, comment="冗余，防止菜品更名后历史套餐显示异常"),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1", comment="该菜品在此分组内的份数"),
        sa.Column("extra_price_fen", sa.Integer, nullable=False, server_default="0",
                  comment="额外加价（高档替换菜）"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false",
                  comment="固定套餐兼容：is_default=True表示默认包含"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )

    # ── 4. order_item_combo_selections — 订单中套餐选择快照 ───────
    # 记录顾客实际选了哪几款，结账和厨打单使用
    op.create_table(
        "order_item_combo_selections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("order_item_id", UUID(as_uuid=True), nullable=False, comment="关联订单明细ID（套餐主项）"),
        sa.Column("combo_group_id", UUID(as_uuid=True), nullable=False),
        sa.Column("combo_group_item_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dish_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dish_name", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("extra_price_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # ── 5. 索引 ───────────────────────────────────────────────────
    op.create_index("ix_combo_groups_combo_id", "combo_groups", ["combo_id", "tenant_id"])
    op.create_index("ix_combo_group_items_group_id", "combo_group_items", ["group_id"])
    op.create_index("ix_combo_group_items_dish_id", "combo_group_items", ["dish_id"])
    op.create_index("ix_order_item_combo_sel_order_item", "order_item_combo_selections", ["order_item_id"])

    # ── 6. RLS ──────────────────────────────────────────────────
    for table in ["combo_groups", "combo_group_items", "order_item_combo_selections"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
        """)

    # ── 7. updated_at 触发器 ──────────────────────────────────────
    for table in ["combo_groups", "combo_group_items"]:
        op.execute(f"""
            DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();
        """)


def downgrade() -> None:
    op.drop_table("order_item_combo_selections")
    op.drop_table("combo_group_items")
    op.drop_table("combo_groups")
    for col in ["combo_type", "description", "min_person", "is_active",
                "available_from", "available_until", "image_url"]:
        op.drop_column("dish_combos", col)
