"""v166 — 菜谱方案与门店菜谱管理

新增三张表：
  menu_schemes         — 集团菜谱方案（模板，含多条目）
  menu_scheme_items    — 方案内菜品配置（价格/状态/排序覆盖）
  store_menu_overrides — 门店对方案的微调（价格/状态个性化）

RLS 策略：NULLIF(current_setting('app.tenant_id', true), '')::uuid 标准安全模式。

Revision ID: v166
Revises: v165
Create Date: 2026-04-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v166"
down_revision = "v165"
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

    # ── menu_schemes 集团菜谱方案 ─────────────────────────────────────────
    if "menu_schemes" not in _existing:
        op.create_table(
            "menu_schemes",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "brand_id",
                UUID(as_uuid=True),
                nullable=True,
                comment="所属品牌，NULL 表示集团级方案",
            ),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'draft'"),
                comment="draft | published | archived",
            ),
            sa.Column(
                "published_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
            ),
            sa.Column("created_by", sa.String(200), nullable=True),
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
            sa.CheckConstraint(
                "status IN ('draft', 'published', 'archived')",
                name="ck_menu_schemes_status",
            ),
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_menu_schemes_tenant ON menu_schemes (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_menu_schemes_tenant_brand ON menu_schemes (tenant_id, brand_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_menu_schemes_tenant_status ON menu_schemes (tenant_id, status)")
    _apply_rls("menu_schemes")

    # ── menu_scheme_items 方案内菜品配置 ──────────────────────────────────
    if "menu_scheme_items" not in _existing:
        op.create_table(
            "menu_scheme_items",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "scheme_id",
                UUID(as_uuid=True),
                sa.ForeignKey("menu_schemes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("dish_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "price_fen",
                sa.Integer,
                nullable=True,
                comment="方案定价（分），NULL 表示沿用菜品默认价",
            ),
            sa.Column(
                "is_available",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("TRUE"),
            ),
            sa.Column(
                "sort_order",
                sa.Integer,
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("notes", sa.Text, nullable=True),
            sa.UniqueConstraint(
                "scheme_id",
                "dish_id",
                name="uq_menu_scheme_items_scheme_dish",
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_menu_scheme_items_tenant_scheme ON menu_scheme_items (tenant_id, scheme_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_menu_scheme_items_tenant_dish ON menu_scheme_items (tenant_id, dish_id)")
    _apply_rls("menu_scheme_items")

    # ── store_menu_overrides 门店菜谱微调 ─────────────────────────────────
    if "store_menu_overrides" not in _existing:
        op.create_table(
            "store_menu_overrides",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("dish_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "scheme_id",
                UUID(as_uuid=True),
                sa.ForeignKey("menu_schemes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "override_price_fen",
                sa.Integer,
                nullable=True,
                comment="门店覆盖价格（分），NULL 表示沿用方案价",
            ),
            sa.Column(
                "override_available",
                sa.Boolean,
                nullable=True,
                comment="门店覆盖可售状态，NULL 表示沿用方案状态",
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "store_id",
                "dish_id",
                "scheme_id",
                name="uq_store_menu_overrides_store_dish_scheme",
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_store_menu_overrides_tenant_store ON store_menu_overrides (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_store_menu_overrides_tenant_scheme "
        "ON store_menu_overrides (tenant_id, scheme_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_store_menu_overrides_store_scheme ON store_menu_overrides (store_id, scheme_id)"
    )
    _apply_rls("store_menu_overrides")

    # ── store_scheme_assignments 门店当前使用的方案（下发记录）──────────────
    if "store_scheme_assignments" not in _existing:
        op.create_table(
            "store_scheme_assignments",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "scheme_id",
                UUID(as_uuid=True),
                sa.ForeignKey("menu_schemes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "distributed_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("distributed_by", sa.String(200), nullable=True),
            sa.UniqueConstraint(
                "store_id",
                "scheme_id",
                name="uq_store_scheme_assignments_store_scheme",
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_store_scheme_assignments_tenant_store "
        "ON store_scheme_assignments (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_store_scheme_assignments_tenant_scheme "
        "ON store_scheme_assignments (tenant_id, scheme_id)"
    )
    _apply_rls("store_scheme_assignments")


def downgrade() -> None:
    for table in [
        "store_scheme_assignments",
        "store_menu_overrides",
        "menu_scheme_items",
        "menu_schemes",
    ]:
        for policy in ["rls_delete", "rls_update", "rls_insert", "rls_select"]:
            op.execute(f"DROP POLICY IF EXISTS {table}_{policy} ON {table}")
        op.drop_table(table)
