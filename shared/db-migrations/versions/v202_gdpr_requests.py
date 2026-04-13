"""gdpr data deletion and export requests

Revision ID: v202
Revises: v201
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = 'v202'
down_revision = 'v201'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    if 'gdpr_requests' not in existing:
        op.create_table(
            'gdpr_requests',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('tenant_id', UUID(as_uuid=True), nullable=False),
            sa.Column('customer_id', UUID(as_uuid=True), nullable=True),
            sa.Column('request_type', sa.String(20), nullable=False),  # deletion/export/rectification
            sa.Column('status', sa.String(20), nullable=False, server_default='pending'),  # pending/processing/completed/rejected
            sa.Column('requester_email', sa.String(255), nullable=True),
            sa.Column('requester_phone_hash', sa.String(64), nullable=True),
            sa.Column('reason', sa.Text, nullable=True),
            sa.Column('processed_at', sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column('processed_by', sa.String(64), nullable=True),
            sa.Column('result_url', sa.Text, nullable=True),  # 导出数据的临时链接（加密）
            sa.Column('result_expires_at', sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column('extra', JSONB, nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
            sa.Column('is_deleted', sa.Boolean, server_default='false'),
        )
        op.create_index('ix_gdpr_requests_tenant', 'gdpr_requests', ['tenant_id'])
        op.create_index('ix_gdpr_requests_status', 'gdpr_requests', ['tenant_id', 'status'])
        op.execute("""
            ALTER TABLE gdpr_requests ENABLE ROW LEVEL SECURITY;
            CREATE POLICY gdpr_requests_tenant_isolation ON gdpr_requests
                USING (tenant_id = current_setting('app.tenant_id', true)::UUID);
        """)

        # 数据保留期策略配置

    if 'data_retention_policies' not in existing:
        op.create_table(
            'data_retention_policies',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('tenant_id', UUID(as_uuid=True), nullable=False),
            sa.Column('data_category', sa.String(50), nullable=False),  # orders/members/logs/payments
            sa.Column('retention_days', sa.Integer, nullable=False, server_default='365'),
            sa.Column('anonymize_after_days', sa.Integer, nullable=True),  # 匿名化而非删除
            sa.Column('legal_basis', sa.String(100), nullable=True),  # GDPR 合法依据
            sa.Column('is_active', sa.Boolean, server_default='true'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        )
        op.create_index(
            'ix_data_retention_policies_unique',
            'data_retention_policies',
            ['tenant_id', 'data_category'],
            unique=True
        )
        op.execute("""
            ALTER TABLE data_retention_policies ENABLE ROW LEVEL SECURITY;
            CREATE POLICY data_retention_policies_tenant_isolation ON data_retention_policies
                USING (tenant_id = current_setting('app.tenant_id', true)::UUID);
        """)


def downgrade() -> None:
    op.drop_table('data_retention_policies')
    op.drop_table('gdpr_requests')
