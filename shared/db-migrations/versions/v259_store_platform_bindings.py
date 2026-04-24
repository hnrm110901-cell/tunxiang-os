"""v259 — 平台门店绑定表：store_platform_bindings

新建：
  store_platform_bindings — 平台门店 ID -> 内部 store_id 映射

支持平台：meituan_booking / dianping_booking / wechat_booking
所有表含 tenant_id + RLS（app.tenant_id）。

Revision ID: v259
Revises: v258
Create Date: 2026-04-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v259"
down_revision = "v258"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ── store_platform_bindings ───────────────────────────────────────────────
    if "store_platform_bindings" not in existing:
        op.create_table(
            "store_platform_bindings",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, comment="关联 stores.id"),
            sa.Column(
                "platform", sa.String(50), nullable=False, comment="meituan_booking / dianping_booking / wechat_booking"
            ),
            sa.Column(
                "platform_shop_id", sa.Text, nullable=False, comment="平台侧门店 ID（美团 shop_id / 点评 poi_id 等）"
            ),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
        op.create_index(
            "ix_store_platform_bindings_tenant_platform_shop",
            "store_platform_bindings",
            ["tenant_id", "platform", "platform_shop_id"],
        )
        op.create_index(
            "ix_store_platform_bindings_store_id",
            "store_platform_bindings",
            ["store_id"],
        )

    op.execute("ALTER TABLE store_platform_bindings ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS store_platform_bindings_tenant ON store_platform_bindings;")
    op.execute("""
        CREATE POLICY store_platform_bindings_tenant ON store_platform_bindings
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.drop_table("store_platform_bindings")
