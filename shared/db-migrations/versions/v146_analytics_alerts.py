"""v146: analytics_alerts 表

供 tx-agent Skill Agent（折扣守护、出餐调度、库存预警等）写入经营告警。
tx-analytics 服务读取此表，驱动实时告警 API。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "v146"
down_revision = "v145"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    if "analytics_alerts" not in _existing:
        op.create_table(
            "analytics_alerts",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column(
                "store_id",
                UUID(as_uuid=True),
                sa.ForeignKey("stores.id"),
                nullable=True,
                index=True,
            ),
            sa.Column(
                "brand_id",
                sa.String(50),
                nullable=True,
                index=True,
            ),
            sa.Column(
                "severity",
                sa.String(16),
                nullable=False,
            ),
            sa.Column(
                "alert_type",
                sa.String(64),
                nullable=False,
            ),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("message", sa.Text, nullable=False),
            sa.Column(
                "resolved",
                sa.Boolean,
                nullable=False,
                server_default="false",
            ),
            sa.Column(
                "resolved_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "agent_id",
                sa.String(100),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column(
                "is_deleted",
                sa.Boolean,
                nullable=False,
                server_default="false",
            ),
        )

    # 复合索引：按租户+门店+日期快速查询未解决告警
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='analytics_alerts' AND column_name IN ('tenant_id', 'store_id', 'created_at')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_analytics_alerts_tenant_store_created ON analytics_alerts (tenant_id, store_id, created_at)';
            END IF;
        END $$;
    """)
    # 按租户+品牌+日期索引（集团看板）
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='analytics_alerts' AND column_name IN ('tenant_id', 'brand_id', 'created_at')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_analytics_alerts_tenant_brand_created ON analytics_alerts (tenant_id, brand_id, created_at)';
            END IF;
        END $$;
    """)

    # RLS 策略（FORCE 确保即使 BYPASSRLS 角色也隔离租户）
    op.execute(text("ALTER TABLE analytics_alerts ENABLE ROW LEVEL SECURITY"))
    op.execute(text("ALTER TABLE analytics_alerts FORCE ROW LEVEL SECURITY"))

    op.execute(
        text("""
        CREATE POLICY analytics_alerts_tenant_isolation
        ON analytics_alerts
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        WITH CHECK (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    """)
    )

    # updated_at 自动更新触发器
    op.execute(
        text("""
        CREATE TRIGGER trg_analytics_alerts_updated_at
        BEFORE UPDATE ON analytics_alerts
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
    """)
    )


def downgrade() -> None:
    op.execute(text("DROP TRIGGER IF EXISTS trg_analytics_alerts_updated_at ON analytics_alerts"))
    op.execute(text("DROP POLICY IF EXISTS analytics_alerts_tenant_isolation ON analytics_alerts"))
    op.drop_index("ix_analytics_alerts_tenant_brand_created", table_name="analytics_alerts")
    op.drop_index("ix_analytics_alerts_tenant_store_created", table_name="analytics_alerts")
    op.drop_table("analytics_alerts")
