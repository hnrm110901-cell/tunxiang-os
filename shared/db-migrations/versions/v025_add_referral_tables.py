"""v025: 添加裂变拉新表（邀请有礼）

新增两张表：
  referral_campaigns  — 裂变活动配置（活动规则、奖励配置、防刷开关）
  referral_records    — 邀请记录（每条对应一个邀请链接/邀请码）

索引：
  - invite_code UNIQUE（全局唯一，供小程序快速查询）
  - (campaign_id, referrer_customer_id) 复合索引（查某人在某活动的邀请数）
  - (invitee_device_id, campaign_id) 复合索引（防刷设备查重）
  - (invitee_customer_id, campaign_id) 复合索引（首单触发查询）

RLS 策略：
  使用 v006+ 标准安全模式（4 操作 + NULL 值 guard + FORCE ROW LEVEL SECURITY）
  current_setting('app.tenant_id', TRUE) IS NOT NULL
  AND current_setting('app.tenant_id', TRUE) <> ''
  AND tenant_id = current_setting('app.tenant_id')::UUID

Revision ID: v025
Revises: v024
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v025"
down_revision = "v024"
branch_labels = None
depends_on = None

# RLS 条件（v006+ 标准模式）
_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def upgrade() -> None:
    # ----------------------------------------------------------------
    # 1. referral_campaigns
    # ----------------------------------------------------------------
    op.create_table(
        "referral_campaigns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),

        # 基本信息
        sa.Column("name", sa.String(100), nullable=False, comment="活动名称"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft",
                  comment="draft|active|paused|ended"),

        # 邀请方奖励
        sa.Column("referrer_reward_type", sa.String(20), nullable=False, server_default="coupon",
                  comment="coupon|points|stored_value"),
        sa.Column("referrer_reward_value", sa.Integer(), nullable=False, server_default="0",
                  comment="优惠券ID/积分数/储值分"),
        sa.Column("referrer_reward_condition", sa.String(20), nullable=False, server_default="first_order",
                  comment="new_register|first_order"),

        # 被邀请方奖励
        sa.Column("invitee_reward_type", sa.String(20), nullable=False, server_default="coupon"),
        sa.Column("invitee_reward_value", sa.Integer(), nullable=False, server_default="0"),

        # 限制条件
        sa.Column("max_referrals_per_user", sa.Integer(), nullable=False, server_default="0",
                  comment="每人最多邀请N人，0=不限"),
        sa.Column("min_order_amount_fen", sa.Integer(), nullable=False, server_default="0",
                  comment="新人首单最低金额(分)，0=不限"),
        sa.Column("valid_days", sa.Integer(), nullable=False, server_default="30",
                  comment="邀请链接有效天数"),

        # 防刷开关
        sa.Column("anti_fraud_same_device", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("anti_fraud_same_ip", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("anti_fraud_same_phone_prefix", sa.Boolean(), nullable=False, server_default="true"),

        # 时效
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),

        comment="裂变活动配置表",
    )

    op.create_index(
        "idx_referral_campaigns_tenant_id",
        "referral_campaigns",
        ["tenant_id"],
    )
    op.create_index(
        "idx_referral_campaigns_tenant_status",
        "referral_campaigns",
        ["tenant_id", "status"],
    )

    # ----------------------------------------------------------------
    # 2. referral_records
    # ----------------------------------------------------------------
    op.create_table(
        "referral_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),

        # 关联
        sa.Column("campaign_id", UUID(as_uuid=True),
                  sa.ForeignKey("referral_campaigns.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("referrer_customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("invitee_customer_id", UUID(as_uuid=True), nullable=True),

        # 邀请码
        sa.Column("invite_code", sa.String(16), nullable=False, unique=True,
                  comment="唯一邀请码（8位大写字母数字）"),
        sa.Column("invite_url", sa.String(500), nullable=False),

        # 状态
        sa.Column("status", sa.String(20), nullable=False, server_default="pending",
                  comment="pending|registered|rewarded|fraud_detected|expired"),

        # 时间戳
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_order_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rewarded_at", sa.DateTime(timezone=True), nullable=True),

        # 防刷记录
        sa.Column("invitee_device_id", sa.String(128), nullable=True),
        sa.Column("invitee_ip", sa.String(64), nullable=True),
        sa.Column("invitee_phone", sa.String(20), nullable=True),

        # 奖励发放状态
        sa.Column("referrer_rewarded", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("invitee_rewarded", sa.Boolean(), nullable=False, server_default="false"),

        comment="邀请记录表",
    )

    # invite_code 已由 unique=True 建立唯一索引，再建复合查询索引
    op.create_index(
        "idx_referral_records_campaign_referrer",
        "referral_records",
        ["campaign_id", "referrer_customer_id"],
    )
    op.create_index(
        "idx_referral_records_device_campaign",
        "referral_records",
        ["invitee_device_id", "campaign_id"],
        postgresql_where=sa.text("invitee_device_id IS NOT NULL"),
    )
    op.create_index(
        "idx_referral_records_invitee_campaign",
        "referral_records",
        ["invitee_customer_id", "campaign_id"],
        postgresql_where=sa.text("invitee_customer_id IS NOT NULL"),
    )
    op.create_index(
        "idx_referral_records_tenant_status",
        "referral_records",
        ["tenant_id", "status"],
    )
    op.create_index(
        "idx_referral_records_tenant_id",
        "referral_records",
        ["tenant_id"],
    )

    # ----------------------------------------------------------------
    # 3. RLS — referral_campaigns
    # ----------------------------------------------------------------
    op.execute("ALTER TABLE referral_campaigns ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE referral_campaigns FORCE ROW LEVEL SECURITY;")

    op.execute(f"""
        CREATE POLICY rls_referral_campaigns_select
            ON referral_campaigns FOR SELECT
            USING ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_referral_campaigns_insert
            ON referral_campaigns FOR INSERT
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_referral_campaigns_update
            ON referral_campaigns FOR UPDATE
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_referral_campaigns_delete
            ON referral_campaigns FOR DELETE
            USING ({_RLS_COND});
    """)

    # ----------------------------------------------------------------
    # 4. RLS — referral_records
    # ----------------------------------------------------------------
    op.execute("ALTER TABLE referral_records ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE referral_records FORCE ROW LEVEL SECURITY;")

    op.execute(f"""
        CREATE POLICY rls_referral_records_select
            ON referral_records FOR SELECT
            USING ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_referral_records_insert
            ON referral_records FOR INSERT
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_referral_records_update
            ON referral_records FOR UPDATE
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_referral_records_delete
            ON referral_records FOR DELETE
            USING ({_RLS_COND});
    """)


def downgrade() -> None:
    # 先删 RLS 策略再删表

    # referral_records
    for policy in [
        "rls_referral_records_select",
        "rls_referral_records_insert",
        "rls_referral_records_update",
        "rls_referral_records_delete",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON referral_records;")
    op.execute("ALTER TABLE referral_records DISABLE ROW LEVEL SECURITY;")

    # referral_campaigns
    for policy in [
        "rls_referral_campaigns_select",
        "rls_referral_campaigns_insert",
        "rls_referral_campaigns_update",
        "rls_referral_campaigns_delete",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON referral_campaigns;")
    op.execute("ALTER TABLE referral_campaigns DISABLE ROW LEVEL SECURITY;")

    # 删索引
    for idx in [
        ("idx_referral_records_tenant_id", "referral_records"),
        ("idx_referral_records_tenant_status", "referral_records"),
        ("idx_referral_records_invitee_campaign", "referral_records"),
        ("idx_referral_records_device_campaign", "referral_records"),
        ("idx_referral_records_campaign_referrer", "referral_records"),
        ("idx_referral_campaigns_tenant_status", "referral_campaigns"),
        ("idx_referral_campaigns_tenant_id", "referral_campaigns"),
    ]:
        op.drop_index(idx[0], table_name=idx[1])

    op.drop_table("referral_records")
    op.drop_table("referral_campaigns")
