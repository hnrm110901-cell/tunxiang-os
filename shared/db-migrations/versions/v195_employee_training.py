"""员工培训管理持久化 — _training_store 内存→DB

Revision ID: v195
Revises: v194
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'v195'
down_revision = 'v194'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    # ─── 1. employee_trainings — 培训记录 ──────────────────────────────────────
    if 'employee_trainings' not in existing:
        op.create_table(
            'employee_trainings',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('employee_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('training_type', sa.VARCHAR(50), nullable=True),
            sa.Column('training_name', sa.VARCHAR(100), nullable=False),
            sa.Column('trainer_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('training_date', sa.Date(), nullable=False),
            sa.Column('duration_hours', sa.Numeric(4, 1), nullable=False, server_default='0'),
            sa.Column('location', sa.VARCHAR(100), nullable=True),
            sa.Column('score', sa.Numeric(5, 2), nullable=True),
            sa.Column('passed', sa.Boolean(), nullable=True),
            sa.Column('certificate_no', sa.VARCHAR(50), nullable=True),
            sa.Column('certificate_expires_at', sa.Date(), nullable=True),
            sa.Column('notes', sa.TEXT(), nullable=True),
            sa.Column('status', sa.VARCHAR(20), nullable=False, server_default='completed'),
            sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('NOW()'), nullable=False),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('NOW()'), nullable=False),
        )
        op.create_index('idx_employee_trainings_tenant', 'employee_trainings', ['tenant_id'])
        op.create_index('idx_employee_trainings_employee', 'employee_trainings',
                        ['tenant_id', 'employee_id'])
        op.create_index('idx_employee_trainings_date', 'employee_trainings',
                        ['tenant_id', 'training_date'])
        op.create_index(
            'idx_employee_trainings_cert',
            'employee_trainings',
            ['tenant_id', 'certificate_expires_at'],
            postgresql_where=sa.text('certificate_expires_at IS NOT NULL'),
        )

    # ─── 2. training_plans — 培训计划 ──────────────────────────────────────────
    if 'training_plans' not in existing:
        op.create_table(
            'training_plans',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('name', sa.VARCHAR(100), nullable=False),
            sa.Column('training_type', sa.VARCHAR(50), nullable=True),
            sa.Column('frequency', sa.VARCHAR(20), nullable=True),
            sa.Column('required_roles', postgresql.JSONB(astext_type=sa.Text()),
                      nullable=False, server_default='[]'),
            sa.Column('is_mandatory', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('reminder_days_before', sa.Integer(), nullable=False, server_default='7'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('NOW()'), nullable=False),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('NOW()'), nullable=False),
        )
        op.create_index('idx_training_plans_tenant', 'training_plans', ['tenant_id'])

    # ─── RLS 策略（幂等） ────────────────────────────────────────────────────
    for table in ('employee_trainings', 'training_plans'):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = '{table}'
                    AND policyname = '{table}_tenant_isolation'
                ) THEN
                    EXECUTE 'CREATE POLICY {table}_tenant_isolation ON {table}
                        USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::UUID)';
                END IF;
            END$$;
        """)


def downgrade() -> None:
    for table in ('employee_trainings', 'training_plans'):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.drop_index('idx_employee_trainings_cert', table_name='employee_trainings')
    op.drop_index('idx_employee_trainings_date', table_name='employee_trainings')
    op.drop_index('idx_employee_trainings_employee', table_name='employee_trainings')
    op.drop_index('idx_employee_trainings_tenant', table_name='employee_trainings')
    op.drop_table('employee_trainings')

    op.drop_index('idx_training_plans_tenant', table_name='training_plans')
    op.drop_table('training_plans')
