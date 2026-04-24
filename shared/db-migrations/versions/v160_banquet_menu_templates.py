"""v160 — 宴席套餐模板引擎

新增两张表：
  banquet_menu_templates   — 宴席套餐模板主表
  banquet_template_items   — 套餐模板菜品明细

RLS 策略：NULLIF(current_setting('app.tenant_id', true), '')::uuid 标准安全模式。

Revision ID: v160
Revises: v159
Create Date: 2026-04-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v160"
down_revision = "v159"
branch_labels = None
depends_on = None

_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _apply_rls(table_name: str) -> None:
    """标准三段式 RLS：ENABLE → FORCE → 四条策略"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table_name}_rls_select ON {table_name} FOR SELECT USING ({_SAFE_CONDITION})")
    op.execute(f"CREATE POLICY {table_name}_rls_insert ON {table_name} FOR INSERT WITH CHECK ({_SAFE_CONDITION})")
    op.execute(
        f"CREATE POLICY {table_name}_rls_update ON {table_name} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"CREATE POLICY {table_name}_rls_delete ON {table_name} FOR DELETE USING ({_SAFE_CONDITION})")


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── banquet_menu_templates 宴席套餐模板主表 ───────────────────────────
    if "banquet_menu_templates" not in _existing:
        op.create_table(
            "banquet_menu_templates",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "store_id",
                UUID(as_uuid=True),
                nullable=True,
                comment="NULL=集团通用，非NULL=门店专属",
            ),
            sa.Column(
                "name",
                sa.String(200),
                nullable=False,
                comment="套餐名称，如：婚宴标准套餐88桌",
            ),
            sa.Column(
                "category",
                sa.String(50),
                nullable=False,
                comment="套餐分类：wedding/business/birthday/festival/other",
            ),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column(
                "guest_count_min",
                sa.Integer,
                nullable=False,
                server_default="1",
                comment="适用最小人数",
            ),
            sa.Column(
                "guest_count_max",
                sa.Integer,
                nullable=False,
                server_default="999",
                comment="适用最大人数",
            ),
            sa.Column(
                "price_per_table_fen",
                sa.BigInteger,
                nullable=False,
                comment="每桌价格（分）",
            ),
            sa.Column(
                "price_per_person_fen",
                sa.BigInteger,
                nullable=True,
                comment="每位价格（分，可选）",
            ),
            sa.Column(
                "min_table_count",
                sa.Integer,
                nullable=False,
                server_default="1",
                comment="最低桌数",
            ),
            sa.Column(
                "deposit_rate",
                sa.Numeric(5, 4),
                nullable=False,
                server_default="0.3",
                comment="定金比例",
            ),
            sa.Column(
                "is_active",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("TRUE"),
            ),
            sa.Column(
                "sort_order",
                sa.Integer,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "is_deleted",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("FALSE"),
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_bmt_tenant ON banquet_menu_templates (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_bmt_tenant_category ON banquet_menu_templates (tenant_id, category)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_bmt_tenant_store ON banquet_menu_templates (tenant_id, store_id)")
    _apply_rls("banquet_menu_templates")

    # ── banquet_template_items 套餐模板菜品明细 ──────────────────────────
    if "banquet_template_items" not in _existing:
        op.create_table(
            "banquet_template_items",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "template_id",
                UUID(as_uuid=True),
                sa.ForeignKey("banquet_menu_templates.id"),
                nullable=False,
            ),
            sa.Column(
                "dish_name",
                sa.String(200),
                nullable=False,
            ),
            sa.Column(
                "dish_category",
                sa.String(50),
                nullable=True,
                comment="菜品分类：cold/hot/soup/staple/dessert/drink",
            ),
            sa.Column(
                "quantity",
                sa.Numeric(10, 2),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "unit",
                sa.String(20),
                nullable=False,
                server_default="'道'",
            ),
            sa.Column(
                "is_signature",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("FALSE"),
                comment="是否主打菜",
            ),
            sa.Column(
                "is_optional",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("FALSE"),
                comment="是否可替换",
            ),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column(
                "sort_order",
                sa.Integer,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "is_deleted",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("FALSE"),
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_bti_tenant ON banquet_template_items (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_bti_template ON banquet_template_items (template_id)")
    _apply_rls("banquet_template_items")


def downgrade() -> None:
    for table in [
        "banquet_template_items",
        "banquet_menu_templates",
    ]:
        for policy in ["rls_delete", "rls_update", "rls_insert", "rls_select"]:
            op.execute(f"DROP POLICY IF EXISTS {table}_{policy} ON {table}")
        op.drop_table(table)
