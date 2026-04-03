"""v076 — 品牌→门店菜品三级发布体系

Revision ID: v076
Revises: v075
Create Date: 2026-03-31

新增5张表支撑品牌→门店三级发布体系：
1. menu_publish_plans        — 发布方案（总部批量发布到门店）
2. menu_publish_plan_items   — 发布方案菜品明细（含可选覆盖价）
3. store_dish_overrides      — 门店对品牌菜品的本地微调
4. price_adjustment_rules    — 时段/渠道/日期范围调价规则
5. dish_price_adjustments    — 菜品与调价规则的多对多关联

同时对 dishes 表追加 is_brand_standard / brand_id 字段（如已有则跳过）。

RLS 策略遵循 v056+ 标准 NULLIF 模式：
  tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision: str = "v077"
down_revision: Union[str, None] = "v076"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 标准 NULLIF NULL guard 条件（v056+ 唯一正确模式）
_SAFE = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _rls(table: str) -> None:
    """标准三策略 RLS（SELECT/INSERT/UPDATE）"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON {table} "
        f"USING ({_SAFE})"
    )
    op.execute(
        f"CREATE POLICY tenant_insert_{table} ON {table} "
        f"FOR INSERT WITH CHECK ({_SAFE})"
    )
    op.execute(
        f"CREATE POLICY tenant_update_{table} ON {table} "
        f"FOR UPDATE USING ({_SAFE}) WITH CHECK ({_SAFE})"
    )


def _drop_rls(table: str) -> None:
    for suffix in ("isolation", "insert", "update"):
        op.execute(f"DROP POLICY IF EXISTS tenant_{suffix}_{table} ON {table}")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # ─── 1. dishes 表追加字段（幂等：使用 IF NOT EXISTS 等价方案）───
    # 注意：PostgreSQL 不支持 ADD COLUMN IF NOT EXISTS 在旧版本，用 DO $$ 块保护
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='dishes' AND column_name='is_brand_standard'
            ) THEN
                ALTER TABLE dishes ADD COLUMN is_brand_standard BOOLEAN NOT NULL DEFAULT FALSE;
            END IF;
        END
        $$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='dishes' AND column_name='brand_id'
            ) THEN
                ALTER TABLE dishes ADD COLUMN brand_id UUID;
                CREATE INDEX IF NOT EXISTS idx_dishes_brand_id ON dishes(brand_id);
            END IF;
        END
        $$;
    """)

    # ─── 2. menu_publish_plans — 发布方案 ───
    op.create_table(
        "menu_publish_plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("brand_id", UUID(as_uuid=True), nullable=True, index=True,
                  comment="所属品牌ID，NULL=全租户通用"),
        sa.Column("plan_name", sa.String(200), nullable=False),
        sa.Column(
            "target_type", sa.String(30), nullable=False,
            comment="all_stores | region | stores",
        ),
        sa.Column("target_ids", JSON, nullable=True,
                  comment="目标区域或门店ID列表，all_stores时为NULL"),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="draft",
            comment="draft | published | archived",
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        sa.CheckConstraint(
            "target_type IN ('all_stores', 'region', 'stores')",
            name="ck_publish_plans_target_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_publish_plans_status",
        ),
    )
    op.create_index("idx_publish_plans_tenant_status",
                    "menu_publish_plans", ["tenant_id", "status"])
    _rls("menu_publish_plans")

    # ─── 3. menu_publish_plan_items — 方案内菜品 ───
    op.create_table(
        "menu_publish_plan_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("plan_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("dish_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("override_price_fen", sa.Integer, nullable=True,
                  comment="可选覆盖价(分)，NULL=使用品牌标准价"),
        sa.Column("is_available", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "plan_id", "dish_id",
                            name="uq_publish_plan_items_plan_dish"),
    )
    op.create_index("idx_publish_plan_items_plan_id",
                    "menu_publish_plan_items", ["plan_id"])
    _rls("menu_publish_plan_items")

    # ─── 4. store_dish_overrides — 门店菜品本地微调 ───
    op.create_table(
        "store_dish_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("dish_id", UUID(as_uuid=True), nullable=False, index=True,
                  comment="引用 dishes.id（品牌菜品）"),
        sa.Column("local_price_fen", sa.Integer, nullable=True,
                  comment="门店售价(分)，NULL=使用品牌价"),
        sa.Column("local_name", sa.String(200), nullable=True,
                  comment="门店显示名，NULL=使用品牌名"),
        sa.Column("local_description", sa.Text, nullable=True),
        sa.Column("local_image_url", sa.String(500), nullable=True),
        sa.Column("is_available", sa.Boolean, nullable=False, server_default="true",
                  comment="门店是否销售此菜"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_by", UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "store_id", "dish_id",
                            name="uq_store_dish_overrides_store_dish"),
    )
    op.create_index("idx_store_dish_overrides_store_dish",
                    "store_dish_overrides", ["store_id", "dish_id"])
    _rls("store_dish_overrides")

    # ─── 5. price_adjustment_rules — 时段/渠道调价规则 ───
    op.create_table(
        "price_adjustment_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True, index=True,
                  comment="NULL=品牌级规则"),
        sa.Column("rule_name", sa.String(200), nullable=False),
        sa.Column(
            "rule_type", sa.String(30), nullable=False,
            comment="time_period | channel | date_range | holiday",
        ),
        sa.Column("channel", sa.String(30), nullable=True,
                  comment="dine_in|delivery|takeout|self_order，NULL=所有渠道"),
        sa.Column("time_start", sa.Time, nullable=True, comment="时段开始(时段规则)"),
        sa.Column("time_end", sa.Time, nullable=True, comment="时段结束(时段规则)"),
        sa.Column("date_start", sa.Date, nullable=True, comment="日期范围开始"),
        sa.Column("date_end", sa.Date, nullable=True, comment="日期范围结束"),
        sa.Column("weekdays", JSON, nullable=True,
                  comment="生效星期[1-7]，1=周一，7=周日"),
        sa.Column(
            "adjustment_type", sa.String(20), nullable=False,
            comment="percentage | fixed_add | fixed_price",
        ),
        sa.Column("adjustment_value", sa.Numeric(10, 2), nullable=False,
                  comment="百分比/固定加减金额(分)/固定价格(分)"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0",
                  comment="优先级，值越大越先命中"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "rule_type IN ('time_period', 'channel', 'date_range', 'holiday')",
            name="ck_price_adj_rules_rule_type",
        ),
        sa.CheckConstraint(
            "adjustment_type IN ('percentage', 'fixed_add', 'fixed_price')",
            name="ck_price_adj_rules_adj_type",
        ),
    )
    op.create_index("idx_price_adj_rules_tenant_store",
                    "price_adjustment_rules", ["tenant_id", "store_id"])
    op.create_index("idx_price_adj_rules_active",
                    "price_adjustment_rules", ["tenant_id", "store_id", "is_active", "priority"])
    _rls("price_adjustment_rules")

    # ─── 6. dish_price_adjustments — 菜品与调价规则关联 ───
    op.create_table(
        "dish_price_adjustments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("rule_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("dish_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "rule_id", "dish_id",
                            name="uq_dish_price_adjustments_rule_dish"),
    )
    op.create_index("idx_dish_price_adj_dish_id",
                    "dish_price_adjustments", ["dish_id"])
    _rls("dish_price_adjustments")


def downgrade() -> None:
    for table in (
        "dish_price_adjustments",
        "price_adjustment_rules",
        "store_dish_overrides",
        "menu_publish_plan_items",
        "menu_publish_plans",
    ):
        _drop_rls(table)
        op.drop_table(table)

    # dishes 字段降级（暂不删除，避免数据丢失）
    # 如需彻底回滚：
    # op.execute("ALTER TABLE dishes DROP COLUMN IF EXISTS is_brand_standard")
    # op.execute("ALTER TABLE dishes DROP COLUMN IF EXISTS brand_id")
