"""配送商对接 — 配送调度单 + 配送商配置

Revision: v216
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v216"
down_revision = "v215"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 配送调度单 ──
    op.create_table(
        "delivery_dispatches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", sa.VARCHAR(64), nullable=False, comment="关联交易订单ID"),
        sa.Column("provider", sa.VARCHAR(20), nullable=False,
                  comment="配送商: dada / shunfeng / self_rider"),
        sa.Column("provider_order_id", sa.VARCHAR(128), nullable=True,
                  comment="三方配送单号"),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="pending",
                  comment="pending/dispatched/accepted/picked_up/delivering/delivered/cancelled/failed"),
        sa.Column("rider_name", sa.VARCHAR(50), nullable=True),
        sa.Column("rider_phone", sa.VARCHAR(20), nullable=True),
        sa.Column("rider_lat", sa.NUMERIC(10, 7), nullable=True),
        sa.Column("rider_lng", sa.NUMERIC(10, 7), nullable=True),
        sa.Column("rider_updated_at", sa.TIMESTAMP(timezone=True), nullable=True,
                  comment="骑手位置最后更新时间"),
        sa.Column("delivery_address", sa.VARCHAR(500), nullable=False),
        sa.Column("delivery_lat", sa.NUMERIC(10, 7), nullable=True),
        sa.Column("delivery_lng", sa.NUMERIC(10, 7), nullable=True),
        sa.Column("distance_meters", sa.INTEGER, server_default="0"),
        sa.Column("delivery_fee_fen", sa.BIGINT, server_default="0"),
        sa.Column("tip_fen", sa.BIGINT, server_default="0"),
        sa.Column("estimated_minutes", sa.INTEGER, nullable=True),
        sa.Column("actual_minutes", sa.INTEGER, nullable=True),
        sa.Column("dispatched_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("picked_up_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.VARCHAR(200), nullable=True),
        sa.Column("fail_reason", sa.VARCHAR(200), nullable=True),
        sa.Column("provider_callback_raw", postgresql.JSONB, nullable=True,
                  comment="三方回调原始数据"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
    )
    op.create_index("ix_dd_tenant", "delivery_dispatches", ["tenant_id"])
    op.create_index("ix_dd_store", "delivery_dispatches", ["tenant_id", "store_id"])
    op.create_index("ix_dd_order", "delivery_dispatches", ["tenant_id", "order_id"])
    op.create_index("ix_dd_status", "delivery_dispatches", ["tenant_id", "status"])
    op.execute("ALTER TABLE delivery_dispatches ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE delivery_dispatches FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY dd_tenant ON delivery_dispatches
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)

    # ── 配送商配置 ──
    op.create_table(
        "delivery_provider_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.VARCHAR(20), nullable=False,
                  comment="dada / shunfeng / self_rider"),
        sa.Column("enabled", sa.BOOLEAN, server_default="false", nullable=False),
        sa.Column("priority", sa.INTEGER, server_default="0",
                  comment="优先级, 数字越小越优先"),
        sa.Column("app_key", sa.VARCHAR(200), nullable=True,
                  comment="三方 AppKey（加密存储）"),
        sa.Column("app_secret", sa.VARCHAR(200), nullable=True,
                  comment="三方 AppSecret（加密存储）"),
        sa.Column("merchant_id", sa.VARCHAR(100), nullable=True,
                  comment="三方商户号"),
        sa.Column("shop_no", sa.VARCHAR(100), nullable=True,
                  comment="三方门店编号"),
        sa.Column("callback_url", sa.VARCHAR(500), nullable=True,
                  comment="回调地址"),
        sa.Column("extra_config", postgresql.JSONB, server_default="{}",
                  comment="额外配置（如超时秒数、自动取消阈值等）"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
    )
    op.create_index("ix_dpc_tenant", "delivery_provider_configs", ["tenant_id"])
    op.create_index("ix_dpc_store_provider", "delivery_provider_configs",
                    ["tenant_id", "store_id", "provider"], unique=True)
    op.execute("ALTER TABLE delivery_provider_configs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE delivery_provider_configs FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY dpc_tenant ON delivery_provider_configs
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS dpc_tenant ON delivery_provider_configs")
    op.drop_table("delivery_provider_configs")
    op.execute("DROP POLICY IF EXISTS dd_tenant ON delivery_dispatches")
    op.drop_table("delivery_dispatches")
