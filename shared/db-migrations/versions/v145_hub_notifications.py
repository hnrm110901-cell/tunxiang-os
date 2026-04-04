"""v145: Hub 通知表（hub_notifications）+ hub_audit_logs

供 Gateway /api/v1/hub/deployment/push-update 写入推送通知，
以及 hub 操作审计日志（跨租户，不启用 RLS）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy import text

revision: str = "v145"
down_revision: Union[str, None] = "v144"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # Hub 推送通知表（跨租户，platform-admin 写入，商户读取）
    if "hub_notifications" not in _existing:
        op.create_table(
            "hub_notifications",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=True, index=True),
            sa.Column("store_ids", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("notification_type", sa.String(32), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("target_version", sa.String(32), nullable=True),
            sa.Column("priority", sa.String(16), nullable=False, server_default="'normal'"),
            sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
            sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ack_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("pushed_by", sa.String(64), nullable=True),
            sa.Column("push_scheduled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("push_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("is_deleted", sa.Boolean(), server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='hub_notifications' AND (column_name = 'notification_type')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_hub_notifications_type ON hub_notifications (notification_type)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='hub_notifications' AND (column_name = 'status')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_hub_notifications_status ON hub_notifications (status)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='hub_notifications' AND (column_name = 'created_at')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_hub_notifications_created ON hub_notifications (created_at)';
            END IF;
        END $$;
    """)

    # Hub 操作审计日志表
    if "hub_audit_logs" not in _existing:
        op.create_table(
            "hub_audit_logs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("operator_id", sa.String(64), nullable=True),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("resource_type", sa.String(32), nullable=False),
            sa.Column("resource_id", sa.String(64), nullable=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=True, index=True),
            sa.Column("request_body", JSONB(), nullable=True),
            sa.Column("result", JSONB(), nullable=True),
            sa.Column("ip_addr", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='hub_audit_logs' AND (column_name = 'action')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_hub_audit_logs_action ON hub_audit_logs (action)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='hub_audit_logs' AND (column_name = 'created_at')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_hub_audit_logs_created ON hub_audit_logs (created_at)';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("hub_audit_logs")
    op.drop_table("hub_notifications")
