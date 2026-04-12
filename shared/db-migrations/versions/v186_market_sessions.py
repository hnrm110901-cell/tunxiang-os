"""市别档案 — 营业时段管理（早市/午市/晚市/夜宵）

变更：
  market_session_templates — 集团/品牌级市别模板（如早市06:00-11:00）
  store_market_sessions    — 门店级市别配置（可覆盖模板时间段）
  dining_sessions          — 新增 market_session_id 外键字段（关联开台时所在市别）

Revision: v186
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v186b"
down_revision = "v186"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 市别模板表（集团/品牌级别定义）──
    op.create_table(
        "market_session_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="NULL=全集团通用，非NULL=仅对该品牌生效"),
        sa.Column("name", sa.VARCHAR(50), nullable=False, comment="如：早市/午市/晚市/夜宵"),
        sa.Column("code", sa.VARCHAR(20), nullable=False,
                  comment="如：breakfast/lunch/dinner/late_night"),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("start_time", sa.Time(), nullable=False, comment="如 06:00"),
        sa.Column("end_time", sa.Time(), nullable=False, comment="如 11:00"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="TRUE"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mst_tenant "
        "ON market_session_templates (tenant_id, brand_id, display_order)"
    )

    # ── 门店市别配置表（门店级别覆盖）──
    op.create_table(
        "store_market_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="NULL=门店自定义，非NULL=引用模板"),
        sa.Column("name", sa.VARCHAR(50), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("menu_plan_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="可选：绑定菜谱方案ID"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="TRUE"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sms_store "
        "ON store_market_sessions (tenant_id, store_id) "
        "WHERE is_active = TRUE"
    )

    # ── RLS 策略：market_session_templates ──
    op.execute("""
        ALTER TABLE market_session_templates ENABLE ROW LEVEL SECURITY;

        CREATE POLICY market_session_templates_tenant ON market_session_templates
            USING (tenant_id = current_setting('app.tenant_id')::uuid);
    """)

    # ── RLS 策略：store_market_sessions ──
    op.execute("""
        ALTER TABLE store_market_sessions ENABLE ROW LEVEL SECURITY;

        CREATE POLICY store_market_sessions_tenant ON store_market_sessions
            USING (tenant_id = current_setting('app.tenant_id')::uuid);
    """)

    # ── 给 dining_sessions 表添加 market_session_id 字段（如果表存在）──
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'dining_sessions'
            ) THEN
                ALTER TABLE dining_sessions
                    ADD COLUMN IF NOT EXISTS market_session_id UUID;
            END IF;
        END$$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'dining_sessions'
            ) THEN
                CREATE INDEX IF NOT EXISTS idx_ds_market_session
                ON dining_sessions (tenant_id, market_session_id)
                WHERE market_session_id IS NOT NULL;
            END IF;
        END$$;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ds_market_session")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'dining_sessions'
            ) THEN
                ALTER TABLE dining_sessions DROP COLUMN IF EXISTS market_session_id;
            END IF;
        END$$;
    """)

    op.execute("DROP POLICY IF EXISTS store_market_sessions_tenant ON store_market_sessions")
    op.execute("DROP POLICY IF EXISTS market_session_templates_tenant ON market_session_templates")

    op.execute("DROP INDEX IF EXISTS idx_sms_store")
    op.execute("DROP INDEX IF EXISTS idx_mst_tenant")

    op.drop_table("store_market_sessions")
    op.drop_table("market_session_templates")
