"""档口路由规则表 dispatch_rules

支持多品牌/多渠道/时段的档口路由规则配置，替代固定的 DishDeptMapping 硬映射。

Revision ID: 20260330_dispatch_rules
Revises:
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "v020"
down_revision = "v019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 创建 dispatch_rules 表 ──
    op.create_table(
        "dispatch_rules",
        # 基础字段（对应 TenantBase）
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),

        # 规则元信息
        sa.Column("name", sa.String(100), nullable=False, comment="规则名称（管理用途）"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0",
                  comment="优先级，越大越先匹配"),

        # 匹配条件（全部可为NULL，NULL=通配）
        sa.Column("match_dish_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="按菜品ID精确匹配"),
        sa.Column("match_dish_category", sa.String(50), nullable=True,
                  comment="按菜品分类匹配"),
        sa.Column("match_brand_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="按品牌ID匹配（多品牌共用厨房场景）"),
        sa.Column("match_channel", sa.String(30), nullable=True,
                  comment="按渠道匹配：dine_in/takeaway/delivery/reservation"),
        sa.Column("match_time_start", sa.Time(), nullable=True,
                  comment="时段开始时间（含），如 11:00"),
        sa.Column("match_time_end", sa.Time(), nullable=True,
                  comment="时段结束时间（含），如 14:00"),
        sa.Column("match_day_type", sa.String(20), nullable=True,
                  comment="工作日类型：weekday/weekend/holiday"),

        # 路由目标
        sa.Column("target_dept_id", postgresql.UUID(as_uuid=True), nullable=False,
                  comment="路由目标档口ID"),
        sa.Column("target_printer_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="可选覆盖打印机ID"),

        # 作用域
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true",
                  comment="规则是否启用"),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False,
                  comment="规则所属门店"),

        # 外键约束
        sa.ForeignKeyConstraint(["target_dept_id"], ["production_depts.id"],
                                name="fk_dispatch_rules_target_dept"),
    )

    # ── 索引 ──
    # 主查询索引：租户+门店+优先级+启用状态（规则引擎核心查询路径）
    op.create_index(
        "ix_dispatch_rules_tenant_store_priority",
        "dispatch_rules",
        ["tenant_id", "store_id", sa.text("priority DESC"), "is_active"],
        postgresql_where=sa.text("is_deleted = false"),
    )
    # 租户ID单列索引（RLS基础）
    op.create_index(
        "ix_dispatch_rules_tenant_id",
        "dispatch_rules",
        ["tenant_id"],
    )
    # 门店ID索引（缓存失效时按门店查询）
    op.create_index(
        "ix_dispatch_rules_store_id",
        "dispatch_rules",
        ["store_id"],
    )
    # 菜品匹配索引
    op.create_index(
        "ix_dispatch_rules_match_dish_id",
        "dispatch_rules",
        ["match_dish_id"],
        postgresql_where=sa.text("match_dish_id IS NOT NULL AND is_deleted = false"),
    )
    # 品牌匹配索引
    op.create_index(
        "ix_dispatch_rules_match_brand_id",
        "dispatch_rules",
        ["match_brand_id"],
        postgresql_where=sa.text("match_brand_id IS NOT NULL AND is_deleted = false"),
    )

    # ── RLS 策略（使用 app.tenant_id，与 v006/v014/v017 安全模式一致） ──
    op.execute("""
        ALTER TABLE dispatch_rules ENABLE ROW LEVEL SECURITY;
    """)

    op.execute("""
        CREATE POLICY dispatch_rules_select ON dispatch_rules FOR SELECT
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        CREATE POLICY dispatch_rules_insert ON dispatch_rules FOR INSERT
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        CREATE POLICY dispatch_rules_update ON dispatch_rules FOR UPDATE
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        CREATE POLICY dispatch_rules_delete ON dispatch_rules FOR DELETE
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        ALTER TABLE dispatch_rules FORCE ROW LEVEL SECURITY;
    """)

    op.execute("""
        COMMENT ON TABLE dispatch_rules IS
        '档口路由规则表：支持按品牌/渠道/时段/菜品多维度路由，优先级越高越先匹配。';
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS dispatch_rules_select ON dispatch_rules;")
    op.execute("DROP POLICY IF EXISTS dispatch_rules_insert ON dispatch_rules;")
    op.execute("DROP POLICY IF EXISTS dispatch_rules_update ON dispatch_rules;")
    op.execute("DROP POLICY IF EXISTS dispatch_rules_delete ON dispatch_rules;")
    op.execute("ALTER TABLE dispatch_rules DISABLE ROW LEVEL SECURITY;")
    op.drop_index("ix_dispatch_rules_match_brand_id", table_name="dispatch_rules")
    op.drop_index("ix_dispatch_rules_match_dish_id", table_name="dispatch_rules")
    op.drop_index("ix_dispatch_rules_store_id", table_name="dispatch_rules")
    op.drop_index("ix_dispatch_rules_tenant_id", table_name="dispatch_rules")
    op.drop_index("ix_dispatch_rules_tenant_store_priority", table_name="dispatch_rules")
    op.drop_table("dispatch_rules")
