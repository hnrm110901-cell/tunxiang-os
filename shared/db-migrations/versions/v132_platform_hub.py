"""v132: Platform Hub 运维表（跨租户，不启用 RLS）

供 Gateway /api/v1/hub/* 读写；应用层使用 get_db_no_rls()。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v132"
down_revision = "v131"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    if "platform_tenants" not in _existing:
        op.create_table(
            "platform_tenants",
            sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
            sa.Column("merchant_code", sa.String(32)),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("plan_template", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("subscription_expires_at", sa.Date()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("is_deleted", sa.Boolean(), server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='platform_tenants' AND (column_name = 'status')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_platform_tenants_status ON platform_tenants (status)';
            END IF;
        END $$;
    """)

    if "hub_store_overlay" not in _existing:
        op.create_table(
            "hub_store_overlay",
            sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("edge_online", sa.Boolean(), server_default="false"),
            sa.Column("last_sync_at", sa.DateTime(timezone=True)),
            sa.Column("client_version", sa.String(32)),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "hub_adapter_connections" not in _existing:
        op.create_table(
            "hub_adapter_connections",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=True, index=True),
            sa.Column("adapter_key", sa.String(64), nullable=False),
            sa.Column("merchant_name", sa.String(100), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("last_sync_at", sa.DateTime(timezone=True)),
            sa.Column("success_rate", sa.Numeric(6, 2)),
            sa.Column("error_message", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("is_deleted", sa.Boolean(), server_default="false"),
        )

    if "hub_edge_devices" not in _existing:
        op.create_table(
            "hub_edge_devices",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=True, index=True),
            sa.Column("store_label", sa.String(120), nullable=False),
            sa.Column("ip", sa.String(64), nullable=False),
            sa.Column("tailscale_status", sa.String(32), nullable=False),
            sa.Column("client_version", sa.String(32)),
            sa.Column("last_heartbeat", sa.DateTime(timezone=True)),
            sa.Column("cpu_pct", sa.Integer(), server_default="0"),
            sa.Column("mem_pct", sa.Integer(), server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("is_deleted", sa.Boolean(), server_default="false"),
        )

    if "hub_tickets" not in _existing:
        op.create_table(
            "hub_tickets",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=True, index=True),
            sa.Column("merchant_name", sa.String(100), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("priority", sa.String(16), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("assignee", sa.String(64)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("is_deleted", sa.Boolean(), server_default="false"),
        )

    if "hub_billing_monthly" not in _existing:
        op.create_table(
            "hub_billing_monthly",
            sa.Column("month", sa.String(7), primary_key=True),
            sa.Column("total_revenue_yuan", sa.BigInteger(), nullable=False),
            sa.Column("haas_yuan", sa.BigInteger(), nullable=False),
            sa.Column("saas_yuan", sa.BigInteger(), nullable=False),
            sa.Column("ai_yuan", sa.BigInteger(), nullable=False),
            sa.Column("merchants_count", sa.Integer(), nullable=False),
            sa.Column("active_stores", sa.Integer(), nullable=False),
            sa.Column("arr_yuan", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "hub_agent_metrics_daily" not in _existing:
        op.create_table(
            "hub_agent_metrics_daily",
            sa.Column("stat_date", sa.Date(), primary_key=True),
            sa.Column("total_executions", sa.BigInteger(), nullable=False),
            sa.Column("success_rate", sa.Numeric(6, 2), nullable=False),
            sa.Column("constraint_violations", sa.Integer(), nullable=False),
            sa.Column("top_agents", JSONB(), nullable=False),
            sa.Column("avg_response_ms", sa.Integer(), server_default="45"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    op.execute(
        text("""
            INSERT INTO platform_tenants (
              tenant_id, merchant_code, name, plan_template, status, subscription_expires_at, is_deleted
            ) VALUES
              ('a0000000-0000-0000-0000-000000000002'::uuid, 'czyz', '尝在一起', 'standard', 'active', '2027-03-22', false),
              ('a0000000-0000-0000-0000-000000000005'::uuid, NULL, '徐记海鲜', 'pro', 'active', '2027-06-30', false),
              ('a0000000-0000-0000-0000-000000000003'::uuid, 'zqx', '最黔线', 'standard', 'trial', '2026-04-22', false),
              ('a0000000-0000-0000-0000-000000000004'::uuid, 'sgc', '尚宫厨', 'lite', 'active', '2027-01-15', false)
        """)
    )

    op.execute(
        text("""
            INSERT INTO stores (
              id, tenant_id, store_name, store_code, city, status, is_deleted
            ) VALUES
              ('a1000000-0000-0000-0000-000000000001'::uuid, 'a0000000-0000-0000-0000-000000000002'::uuid,
               '芙蓉路店', 'hub_seed_fr', '长沙', 'active', false),
              ('a1000000-0000-0000-0000-000000000002'::uuid, 'a0000000-0000-0000-0000-000000000002'::uuid,
               '岳麓店', 'hub_seed_yl', '长沙', 'active', false),
              ('a1000000-0000-0000-0000-000000000003'::uuid, 'a0000000-0000-0000-0000-000000000005'::uuid,
               '五一广场店', 'hub_seed_wy', '长沙', 'active', false)
        """)
    )

    op.execute(
        text("""
            INSERT INTO hub_store_overlay (store_id, tenant_id, edge_online, last_sync_at, client_version)
            VALUES
              ('a1000000-0000-0000-0000-000000000001'::uuid, 'a0000000-0000-0000-0000-000000000002'::uuid,
               true, NOW() - INTERVAL '2 minutes', '3.3.0'),
              ('a1000000-0000-0000-0000-000000000002'::uuid, 'a0000000-0000-0000-0000-000000000002'::uuid,
               true, NOW() - INTERVAL '3 minutes', '3.3.0'),
              ('a1000000-0000-0000-0000-000000000003'::uuid, 'a0000000-0000-0000-0000-000000000005'::uuid,
               false, NOW() - INTERVAL '5 hours', '3.2.0')
        """)
    )

    op.execute(
        text("""
            INSERT INTO hub_adapter_connections (
              id, tenant_id, adapter_key, merchant_name, status, last_sync_at, success_rate, error_message, is_deleted
            ) VALUES
              (gen_random_uuid(), 'a0000000-0000-0000-0000-000000000002'::uuid,
               'pinzhi', '尝在一起', 'connected', NOW() - INTERVAL '5 minutes', 99.2, NULL, false),
              (gen_random_uuid(), 'a0000000-0000-0000-0000-000000000005'::uuid,
               'aoqiwei', '徐记海鲜', 'connected', NOW() - INTERVAL '10 minutes', 98.5, NULL, false),
              (gen_random_uuid(), 'a0000000-0000-0000-0000-000000000005'::uuid,
               'kingdee', '徐记海鲜', 'error', NOW() - INTERVAL '8 hours', 85.0, 'Token expired', false)
        """)
    )

    op.execute(
        text("""
            INSERT INTO hub_edge_devices (
              id, tenant_id, store_label, ip, tailscale_status, client_version, last_heartbeat, cpu_pct, mem_pct, is_deleted
            ) VALUES
              (gen_random_uuid(), 'a0000000-0000-0000-0000-000000000002'::uuid,
               '芙蓉路店', '100.64.1.10', 'online', '3.3.0', NOW() - INTERVAL '1 minute', 12, 45, false),
              (gen_random_uuid(), 'a0000000-0000-0000-0000-000000000002'::uuid,
               '岳麓店', '100.64.1.11', 'online', '3.3.0', NOW() - INTERVAL '2 minutes', 8, 38, false),
              (gen_random_uuid(), 'a0000000-0000-0000-0000-000000000005'::uuid,
               '五一广场店', '100.64.1.20', 'offline', '3.2.0', NOW() - INTERVAL '6 hours', 0, 0, false)
        """)
    )

    op.execute(
        text("""
            INSERT INTO hub_tickets (id, tenant_id, merchant_name, title, priority, status, assignee, is_deleted)
            VALUES
              ('T001', 'a0000000-0000-0000-0000-000000000002'::uuid,
               '尝在一起', 'POS打印机故障', 'high', 'open', '张工', false),
              ('T002', 'a0000000-0000-0000-0000-000000000005'::uuid,
               '徐记海鲜', '金蝶凭证同步失败', 'medium', 'in_progress', '李工', false)
        """)
    )

    op.execute(
        text("""
            INSERT INTO hub_billing_monthly (
              month, total_revenue_yuan, haas_yuan, saas_yuan, ai_yuan, merchants_count, active_stores, arr_yuan
            ) VALUES (
              '2026-03', 325000, 100000, 175000, 50000, 4, 3, 3900000
            )
        """)
    )

    op.execute(
        text("""
            INSERT INTO hub_agent_metrics_daily (
              stat_date, total_executions, success_rate, constraint_violations, top_agents, avg_response_ms
            ) VALUES (
              CURRENT_DATE, 12500, 97.3, 23,
              '[
                {"agent": "discount_guard", "executions": 3200, "violations": 15},
                {"agent": "inventory_alert", "executions": 2800, "violations": 5},
                {"agent": "serve_dispatch", "executions": 2100, "violations": 3}
              ]'::jsonb,
              45
            )
        """)
    )


def downgrade() -> None:
    op.drop_table("hub_agent_metrics_daily")
    op.drop_table("hub_billing_monthly")
    op.drop_table("hub_tickets")
    op.drop_table("hub_edge_devices")
    op.drop_table("hub_adapter_connections")
    op.drop_table("hub_store_overlay")
    op.execute(text("DELETE FROM stores WHERE store_code IN ('hub_seed_fr', 'hub_seed_yl', 'hub_seed_wy')"))
    op.drop_table("platform_tenants")
