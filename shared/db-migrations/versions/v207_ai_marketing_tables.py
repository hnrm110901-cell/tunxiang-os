"""AI营销自动化基础表 — AIGC缓存 / 渠道账号 / 触达记录

Revision ID: v207
Revises: v206
Create Date: 2026-04-11

新增3张表：
  1. ai_content_cache         — AIGC 内容缓存（节省 Token 成本）
  2. marketing_channel_accounts — 渠道账号配置（微信OA/企微/美团/抖音等）
  3. marketing_touch_log      — 营销触达记录（归因闭环核心）
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v207b"
down_revision = "v207"
branch_labels = None
depends_on = None

TABLES = [
    "ai_content_cache",
    "marketing_channel_accounts",
    "marketing_touch_log",
]


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()


    # ─── 1. ai_content_cache — AIGC 内容缓存 ────────────────────────────────

    if 'ai_content_cache' not in existing:
        op.create_table(
            "ai_content_cache",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "cache_key",
                sa.VARCHAR(255),
                nullable=False,
                comment="SHA256 of (campaign_type + brand_voice_hash + context_hash)",
            ),
            sa.Column("campaign_type", sa.VARCHAR(100), nullable=False),
            sa.Column(
                "package_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
                comment="完整 CampaignContentPackage JSON",
            ),
            sa.Column(
                "tokens_used",
                sa.Integer(),
                nullable=False,
                server_default="0",
                comment="Claude API token 消耗",
            ),
            sa.Column(
                "hit_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
                comment="缓存命中次数（追踪节省成本）",
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("NOW()"),
                nullable=False,
            ),
            sa.Column(
                "expires_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                comment="缓存过期时间（默认24小时后）",
            ),
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
        )

        # 唯一索引：每个租户下 cache_key 唯一（未删除）
        op.create_index(
            "uq_ai_content_cache_key",
            "ai_content_cache",
            ["tenant_id", "cache_key"],
            unique=True,
            postgresql_where=sa.text("NOT is_deleted"),
        )
        # 过期清理索引
        op.create_index(
            "idx_ai_content_cache_expires",
            "ai_content_cache",
            ["tenant_id", "expires_at"],
        )
        # 活动类型查询索引
        op.create_index(
            "idx_ai_content_cache_type",
            "ai_content_cache",
            ["tenant_id", "campaign_type"],
        )

        # RLS
        op.execute("ALTER TABLE ai_content_cache ENABLE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY tenant_isolation ON ai_content_cache
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
        """)

        # ─── 2. marketing_channel_accounts — 渠道账号配置 ────────────────────────

    if 'marketing_channel_accounts' not in existing:
        op.create_table(
            "marketing_channel_accounts",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=True,
                      comment="NULL 表示品牌级账号（全门店共用）"),
            sa.Column(
                "channel_type",
                sa.VARCHAR(50),
                nullable=False,
                comment="wechat_oa/wecom/meituan/eleme/douyin/xiaohongshu/sms",
            ),
            sa.Column("account_name", sa.VARCHAR(200), nullable=False),
            sa.Column(
                "credentials_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
                comment="加密凭据引用（key_id 指向 KMS，不存明文 secret）",
            ),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column(
                "daily_send_limit",
                sa.Integer(),
                nullable=False,
                server_default="1000",
                comment="每日发送上限（合规频控）",
            ),
            sa.Column(
                "daily_sent_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
                comment="今日已发送数（每日0点重置）",
            ),
            sa.Column("last_reset_date", sa.Date(), nullable=True),
            sa.Column(
                "config_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
                comment="渠道特有配置（模板 ID 映射、发送规则等）",
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("NOW()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("NOW()"),
                nullable=False,
            ),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        )

        op.create_index(
            "idx_mktg_channel_accounts_tenant",
            "marketing_channel_accounts",
            ["tenant_id", "channel_type"],
            postgresql_where=sa.text("is_active AND NOT is_deleted"),
        )
        op.create_index(
            "idx_mktg_channel_accounts_store",
            "marketing_channel_accounts",
            ["tenant_id", "store_id"],
        )

        op.execute("ALTER TABLE marketing_channel_accounts ENABLE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY tenant_isolation ON marketing_channel_accounts
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
        """)

        # ─── 3. marketing_touch_log — 营销触达记录 ────────────────────────────────

    if 'marketing_touch_log' not in existing:
        op.create_table(
            "marketing_touch_log",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "channel",
                sa.VARCHAR(50),
                nullable=False,
                comment="sms/wechat_subscribe/wechat_oa/wecom_chat/miniapp/meituan/douyin",
            ),
            sa.Column(
                "campaign_type",
                sa.VARCHAR(100),
                nullable=True,
                comment="post_order_touch/welcome_journey/winback/birthday_care 等",
            ),
            sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "message_id",
                sa.VARCHAR(200),
                nullable=True,
                comment="外部渠道消息 ID（用于状态回查）",
            ),
            sa.Column(
                "content_hash",
                sa.VARCHAR(64),
                nullable=True,
                comment="消息内容 SHA256（去重防重复发送）",
            ),
            sa.Column(
                "status",
                sa.VARCHAR(20),
                nullable=False,
                server_default="pending",
                comment="pending/sent/delivered/failed/clicked/converted",
            ),
            sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("delivered_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("clicked_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("converted_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column(
                "attribution_order_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
                comment="归因到的订单 ID",
            ),
            sa.Column(
                "attribution_revenue_fen",
                sa.Integer(),
                nullable=True,
                comment="归因收入（分）",
            ),
            sa.Column(
                "attribution_window_hours",
                sa.Integer(),
                nullable=True,
                server_default="72",
                comment="归因窗口期（小时）",
            ),
            sa.Column("error_message", sa.TEXT(), nullable=True),
            sa.Column(
                "metadata_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("NOW()"),
                nullable=False,
            ),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        )

        # 查询索引
        op.create_index(
            "idx_mktg_touch_log_member",
            "marketing_touch_log",
            ["tenant_id", "member_id", "created_at"],
            postgresql_ops={"created_at": "DESC"},
        )
        op.create_index(
            "idx_mktg_touch_log_campaign",
            "marketing_touch_log",
            ["tenant_id", "campaign_id"],
        )
        op.create_index(
            "idx_mktg_touch_log_status",
            "marketing_touch_log",
            ["tenant_id", "status", "sent_at"],
        )
        op.create_index(
            "idx_mktg_touch_log_attribution",
            "marketing_touch_log",
            ["tenant_id", "attribution_order_id"],
            postgresql_where=sa.text("attribution_order_id IS NOT NULL"),
        )
        # 内容去重索引
        op.create_index(
            "idx_mktg_touch_log_content_hash",
            "marketing_touch_log",
            ["tenant_id", "member_id", "content_hash"],
            postgresql_where=sa.text("content_hash IS NOT NULL AND NOT is_deleted"),
        )

        op.execute("ALTER TABLE marketing_touch_log ENABLE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY tenant_isolation ON marketing_touch_log
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
        """)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
