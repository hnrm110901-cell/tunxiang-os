"""v111: 会员等级运营体系 — 等级配置/升降级记录/积分规则

新增三张表：
  - member_level_configs    等级定义（普通/银卡/金卡/黑金）
  - member_level_history    升降级历史记录
  - member_points_rules     积分获取规则

RLS 策略沿用 NULLIF(current_setting('app.tenant_id', true), '')::uuid 模式。

Revision ID: v111
Revises: v110
Create Date: 2026-04-02
"""

import sqlalchemy as sa
from alembic import op

revision = "v111"
down_revision = "v110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. member_level_configs ──────────────────────────────────────────────
    op.create_table(
        "member_level_configs",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()"), comment="主键"),
        sa.Column("tenant_id", sa.UUID(), nullable=False, comment="租户ID"),
        sa.Column("level_code", sa.VARCHAR(20), nullable=False, comment="等级编码: normal|silver|gold|diamond"),
        sa.Column("level_name", sa.VARCHAR(20), nullable=False, comment="等级名称，如：普通会员"),
        sa.Column("min_points", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="升级所需最低积分"),
        sa.Column(
            "min_annual_spend_fen",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="年消费门槛（分）",
        ),
        sa.Column(
            "discount_rate",
            sa.Numeric(4, 2),
            nullable=False,
            server_default=sa.text("1.00"),
            comment="折扣率，0.95=95折",
        ),
        sa.Column(
            "birthday_bonus_multiplier",
            sa.Numeric(4, 2),
            nullable=False,
            server_default=sa.text("1.0"),
            comment="生日积分倍率",
        ),
        sa.Column(
            "priority_queue", sa.Boolean(), nullable=False, server_default=sa.text("FALSE"), comment="是否享有等位优先"
        ),
        sa.Column(
            "free_delivery", sa.Boolean(), nullable=False, server_default=sa.text("FALSE"), comment="是否免外卖费"
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="显示顺序"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "level_code", name="uq_member_level_configs_tenant_code"),
    )
    op.create_index("ix_member_level_configs_tenant_id", "member_level_configs", ["tenant_id"])

    # RLS
    op.execute("ALTER TABLE member_level_configs ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY tenant_isolation ON member_level_configs
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        );
    """)

    # ── 2. member_level_history ──────────────────────────────────────────────
    op.create_table(
        "member_level_history",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()"), comment="主键"),
        sa.Column("tenant_id", sa.UUID(), nullable=False, comment="租户ID"),
        sa.Column("member_id", sa.UUID(), nullable=False, comment="会员ID"),
        sa.Column("from_level", sa.VARCHAR(20), nullable=True, comment="变更前等级编码"),
        sa.Column("to_level", sa.VARCHAR(20), nullable=False, comment="变更后等级编码"),
        sa.Column(
            "trigger_type",
            sa.VARCHAR(30),
            nullable=False,
            comment="触发类型: points_upgrade|spend_upgrade|manual|expiry_downgrade",
        ),
        sa.Column("trigger_value", sa.Integer(), nullable=True, comment="触发时的积分/消费值"),
        sa.Column("note", sa.Text(), nullable=True, comment="备注"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_member_level_history_tenant_id", "member_level_history", ["tenant_id"])
    op.create_index("ix_member_level_history_member_id", "member_level_history", ["member_id"])

    # RLS
    op.execute("ALTER TABLE member_level_history ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY tenant_isolation ON member_level_history
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        );
    """)

    # ── 3. member_points_rules ───────────────────────────────────────────────
    op.create_table(
        "member_points_rules",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()"), comment="主键"),
        sa.Column("tenant_id", sa.UUID(), nullable=False, comment="租户ID"),
        sa.Column("store_id", sa.UUID(), nullable=True, comment="门店ID，NULL=全品牌"),
        sa.Column("rule_name", sa.VARCHAR(50), nullable=False, comment="规则名称"),
        sa.Column(
            "earn_type",
            sa.VARCHAR(20),
            nullable=False,
            comment="积分类型: consumption|birthday|signup|referral|checkin",
        ),
        sa.Column(
            "points_per_100fen",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="每消费100分得X积分（consumption用）",
        ),
        sa.Column(
            "fixed_points",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="固定积分（birthday/signup用）",
        ),
        sa.Column(
            "multiplier",
            sa.Numeric(4, 2),
            nullable=False,
            server_default=sa.text("1.0"),
            comment="积分倍率（如双倍积分活动）",
        ),
        sa.Column("valid_from", sa.Date(), nullable=True, comment="活动开始日期，NULL=永久"),
        sa.Column("valid_to", sa.Date(), nullable=True, comment="活动结束日期，NULL=永久"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_member_points_rules_tenant_id", "member_points_rules", ["tenant_id"])

    # RLS
    op.execute("ALTER TABLE member_points_rules ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY tenant_isolation ON member_points_rules
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        );
    """)

    # ── 4. 初始化默认4个等级数据（给所有已存在租户插入，实际生产中应通过API初始化）──
    # 此处仅创建表结构，等级数据通过应用层初始化API写入


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS member_points_rules CASCADE;")
    op.execute("DROP TABLE IF EXISTS member_level_history CASCADE;")
    op.execute("DROP TABLE IF EXISTS member_level_configs CASCADE;")
