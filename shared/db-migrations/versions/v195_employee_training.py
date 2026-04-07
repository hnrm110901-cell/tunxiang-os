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
    # ─── 1. employee_trainings — 培训记录 ──────────────────────────────────────
    op.create_table(
        'employee_trainings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('employee_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='关联员工ID'),
        sa.Column('training_type', sa.VARCHAR(50), nullable=True,
                  comment='onboarding/food_safety/service/skills/compliance/other'),
        sa.Column('training_name', sa.VARCHAR(100), nullable=False,
                  comment='培训名称'),
        sa.Column('trainer_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='培训师/讲师员工ID'),
        sa.Column('training_date', sa.Date(), nullable=False,
                  comment='培训日期'),
        sa.Column('duration_hours', sa.Numeric(4, 1), nullable=False,
                  server_default='0',
                  comment='培训时长（小时）'),
        sa.Column('location', sa.VARCHAR(100), nullable=True,
                  comment='线下/线上/门店'),
        sa.Column('score', sa.Numeric(5, 2), nullable=True,
                  comment='考核分数，NULL=未考核'),
        sa.Column('passed', sa.Boolean(), nullable=True,
                  comment='是否通过'),
        sa.Column('certificate_no', sa.VARCHAR(50), nullable=True,
                  comment='证书编号（食安/消防等）'),
        sa.Column('certificate_expires_at', sa.Date(), nullable=True,
                  comment='证书有效期'),
        sa.Column('notes', sa.TEXT(), nullable=True),
        sa.Column('status', sa.VARCHAR(20), nullable=False,
                  server_default='completed',
                  comment='scheduled/in_progress/completed/failed'),
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
    op.create_table(
        'training_plans',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='门店级计划，NULL=集团'),
        sa.Column('name', sa.VARCHAR(100), nullable=False,
                  comment='计划名称'),
        sa.Column('training_type', sa.VARCHAR(50), nullable=True,
                  comment='培训类型'),
        sa.Column('frequency', sa.VARCHAR(20), nullable=True,
                  comment='once/monthly/quarterly/annual'),
        sa.Column('required_roles', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default='[]',
                  comment='必须参加的岗位角色列表'),
        sa.Column('is_mandatory', sa.Boolean(), nullable=False, server_default='true',
                  comment='是否强制参加'),
        sa.Column('reminder_days_before', sa.Integer(), nullable=False, server_default='7',
                  comment='提前N天提醒'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('idx_training_plans_tenant', 'training_plans', ['tenant_id'])

    # ─── RLS 策略（2张表） ────────────────────────────────────────────────────
    for table in ('employee_trainings', 'training_plans'):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
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
