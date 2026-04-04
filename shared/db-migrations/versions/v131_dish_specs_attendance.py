"""v131 — 菜品规格表 + 员工考勤表

新增四张表：
  dish_spec_groups         — 菜品规格组（如"份量"/"温度"/"辣度"）
  dish_spec_options        — 规格选项（如"大份/小份"，含加减价）
  attendance_records       — 每日考勤记录（依赖薪资计算）
  attendance_leave_requests — 请假申请

Revision ID: v131
Revises: v130
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v131"
down_revision = "v130"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── dish_spec_groups 菜品规格组 ───────────────────────────────
    if "dish_spec_groups" not in _existing:
        op.create_table(
            "dish_spec_groups",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("dish_id", UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(50), nullable=False),
            sa.Column("is_required", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("min_select", sa.Integer, nullable=False, server_default="0"),
            sa.Column("max_select", sa.Integer, nullable=False, server_default="1"),
            sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_spec_groups' AND column_name IN ('tenant_id', 'dish_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dish_spec_groups_tenant_dish ON dish_spec_groups (tenant_id, dish_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_spec_groups' AND column_name IN ('tenant_id', 'sort_order')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dish_spec_groups_tenant_sort ON dish_spec_groups (tenant_id, sort_order)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE dish_spec_groups ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS dish_spec_groups_tenant_isolation ON dish_spec_groups;")
    op.execute("DROP POLICY IF EXISTS dish_spec_groups_tenant_isolation ON dish_spec_groups;")
    op.execute("""
        CREATE POLICY dish_spec_groups_tenant_isolation ON dish_spec_groups
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── dish_spec_options 规格选项 ────────────────────────────────
    if "dish_spec_options" not in _existing:
        op.create_table(
            "dish_spec_options",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("group_id", UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(50), nullable=False),
            sa.Column("price_delta_fen", sa.Integer, nullable=False, server_default="0"),
            sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
            sa.Column("stock_status", sa.String(20), nullable=False, server_default="'normal'"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_spec_options' AND (column_name = 'group_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dish_spec_options_group ON dish_spec_options (group_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dish_spec_options' AND column_name IN ('tenant_id', 'group_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dish_spec_options_tenant_group ON dish_spec_options (tenant_id, group_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE dish_spec_options ADD CONSTRAINT fk_dish_spec_options_group
                FOREIGN KEY (group_id) REFERENCES dish_spec_groups(id) ON DELETE CASCADE;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("ALTER TABLE dish_spec_options ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS dish_spec_options_tenant_isolation ON dish_spec_options;")
    op.execute("DROP POLICY IF EXISTS dish_spec_options_tenant_isolation ON dish_spec_options;")
    op.execute("""
        CREATE POLICY dish_spec_options_tenant_isolation ON dish_spec_options
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── attendance_records 每日考勤记录 ───────────────────────────
    if "attendance_records" not in _existing:
        op.create_table(
            "attendance_records",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("employee_id", UUID(as_uuid=True), nullable=False),
            sa.Column("work_date", sa.Date, nullable=False),
            sa.Column("clock_in", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("clock_out", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("work_hours", sa.Numeric(5, 2), nullable=True),
            sa.Column("overtime_hours", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("late_minutes", sa.Integer, nullable=False, server_default="0"),
            sa.Column("early_leave_minutes", sa.Integer, nullable=False, server_default="0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="'normal'"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='attendance_records' AND column_name IN ('tenant_id', 'work_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_attendance_records_tenant_date ON attendance_records (tenant_id, work_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='attendance_records' AND column_name IN ('employee_id', 'work_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_attendance_records_employee_date ON attendance_records (employee_id, work_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='attendance_records' AND column_name IN ('tenant_id', 'store_id', 'work_date')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_attendance_records_tenant_store_date ON attendance_records (tenant_id, store_id, work_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='attendance_records' AND column_name IN ('employee_id', 'work_date')) = 2 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_records_employee_date ON attendance_records (employee_id, work_date)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE attendance_records ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS attendance_records_tenant_isolation ON attendance_records;")
    op.execute("DROP POLICY IF EXISTS attendance_records_tenant_isolation ON attendance_records;")
    op.execute("""
        CREATE POLICY attendance_records_tenant_isolation ON attendance_records
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── attendance_leave_requests 请假申请 ────────────────────────
    if "attendance_leave_requests" not in _existing:
        op.create_table(
            "attendance_leave_requests",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("employee_id", UUID(as_uuid=True), nullable=False),
            sa.Column("leave_type", sa.String(20), nullable=False),
            sa.Column("start_date", sa.Date, nullable=False),
            sa.Column("end_date", sa.Date, nullable=False),
            sa.Column("total_days", sa.Numeric(4, 1), nullable=False),
            sa.Column("reason", sa.Text, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="'pending'"),
            sa.Column("approved_by", UUID(as_uuid=True), nullable=True),
            sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='attendance_leave_requests' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_attendance_leave_requests_tenant_status ON attendance_leave_requests (tenant_id, status)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='attendance_leave_requests' AND column_name IN ('employee_id', 'start_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_attendance_leave_requests_employee_date ON attendance_leave_requests (employee_id, start_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='attendance_leave_requests' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_attendance_leave_requests_tenant_store ON attendance_leave_requests (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE attendance_leave_requests ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS attendance_leave_requests_tenant_isolation ON attendance_leave_requests;")
    op.execute("DROP POLICY IF EXISTS attendance_leave_requests_tenant_isolation ON attendance_leave_requests;")
    op.execute("""
        CREATE POLICY attendance_leave_requests_tenant_isolation ON attendance_leave_requests
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    # 删除顺序：先子表/依赖表，再父表
    op.execute("DROP POLICY IF EXISTS attendance_leave_requests_tenant_isolation ON attendance_leave_requests;")
    op.drop_table("attendance_leave_requests")

    op.execute("DROP POLICY IF EXISTS attendance_records_tenant_isolation ON attendance_records;")
    op.drop_table("attendance_records")

    op.execute("DROP POLICY IF EXISTS dish_spec_options_tenant_isolation ON dish_spec_options;")
    op.drop_table("dish_spec_options")

    op.execute("DROP POLICY IF EXISTS dish_spec_groups_tenant_isolation ON dish_spec_groups;")
    op.drop_table("dish_spec_groups")
