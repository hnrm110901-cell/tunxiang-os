"""多品牌管理DB统一 + 多区域主数据

Revision ID: v198
Revises: v197
Create Date: 2026-04-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v198"
down_revision = "v197"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 1. brands — 品牌主数据（内存双轨统一到DB） ──────────────────────────────
    op.create_table(
        "brands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.VARCHAR(100), nullable=False, comment="品牌名称"),
        sa.Column("brand_code", sa.VARCHAR(20), unique=True, nullable=False, comment="品牌编码：如 XJ/QQ/SG"),
        sa.Column("brand_type", sa.VARCHAR(30), nullable=True, comment="seafood/hotpot/canteen/quick_service/banquet"),
        sa.Column("logo_url", sa.TEXT(), nullable=True, comment="品牌Logo URL"),
        sa.Column(
            "primary_color", sa.VARCHAR(7), nullable=False, server_default="#FF6B35", comment="品牌主色调（Hex）"
        ),
        sa.Column("description", sa.TEXT(), nullable=True, comment="品牌描述"),
        sa.Column(
            "status", sa.VARCHAR(20), nullable=False, server_default="active", comment="active/inactive/archived"
        ),
        sa.Column("hq_store_id", postgresql.UUID(as_uuid=True), nullable=True, comment="总店/旗舰店ID"),
        sa.Column(
            "strategy_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="品牌策略配置（替代内存存储）：折扣阈值/菜谱策略/报表模板等",
        ),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("idx_brands_tenant", "brands", ["tenant_id"])
    op.create_index("idx_brands_code", "brands", ["brand_code"])

    # ─── 2. regions — 区域主数据（树形结构：大区→省→城市） ─────────────────────────
    op.create_table(
        "regions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True, comment="父区域ID（NULL=顶级大区）"),
        sa.Column("name", sa.VARCHAR(50), nullable=False, comment="区域名称"),
        sa.Column("region_code", sa.VARCHAR(20), nullable=True, comment="区域编码"),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1", comment="1=大区 2=省 3=城市"),
        sa.Column("brand_id", postgresql.UUID(as_uuid=True), nullable=True, comment="绑定品牌ID（可选）"),
        sa.Column("manager_id", postgresql.UUID(as_uuid=True), nullable=True, comment="区域负责人员工ID"),
        sa.Column(
            "tax_rate",
            sa.Numeric(5, 4),
            nullable=False,
            server_default="0.0600",
            comment="区域默认税率，影响该区域所有门店发票",
        ),
        sa.Column(
            "freight_template",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="运费模板配置",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )

    # regions 自引用外键
    op.create_foreign_key(
        "fk_regions_parent_id",
        "regions",
        "regions",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("idx_regions_tenant", "regions", ["tenant_id"])
    op.create_index("idx_regions_parent", "regions", ["tenant_id", "parent_id"])
    op.create_index("idx_regions_brand", "regions", ["tenant_id", "brand_id"])

    # ─── 3. RLS 策略（2张表） ────────────────────────────────────────────────────
    for table in ("brands", "regions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
        """)


def downgrade() -> None:
    # 删除 RLS 策略
    for table in ("brands", "regions"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    # 删除索引和表（regions 先删，因为有自引用FK）
    op.drop_constraint("fk_regions_parent_id", "regions", type_="foreignkey")
    op.drop_index("idx_regions_brand", table_name="regions")
    op.drop_index("idx_regions_parent", table_name="regions")
    op.drop_index("idx_regions_tenant", table_name="regions")
    op.drop_table("regions")

    op.drop_index("idx_brands_code", table_name="brands")
    op.drop_index("idx_brands_tenant", table_name="brands")
    op.drop_table("brands")
