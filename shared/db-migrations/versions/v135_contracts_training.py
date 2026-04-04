"""v135 — 加盟合同 + 培训课程 + 学习记录 + 员工证书

新增四张表：
  franchise_contracts    — 加盟合同管理（签约/续约/补充协议）
  training_courses       — 培训课程库（入职/技能/食安/服务/管理）
  training_records       — 员工学习记录与考试成绩
  employee_certificates  — 员工证书管理（健康证/消防证等）

Revision ID: v135
Revises: v134
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v135"
down_revision = "v134"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── franchise_contracts 加盟合同 ─────────────────────────────
    if "franchise_contracts" not in _existing:
        op.create_table(
            "franchise_contracts",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("contract_no", sa.String(50), nullable=False, unique=True),
            sa.Column("franchisee_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True)),
            sa.Column("contract_type", sa.String(20), nullable=False,
                      server_default="franchise"),
            sa.Column("amount_fen", sa.BigInteger, nullable=False,
                      server_default="0"),
            sa.Column("start_date", sa.Date),
            sa.Column("end_date", sa.Date),
            sa.Column("terms", JSONB),
            sa.Column("status", sa.String(20), nullable=False,
                      server_default="draft"),
            sa.Column("signed_at", sa.DateTime(timezone=True)),
            sa.Column("terminated_at", sa.DateTime(timezone=True)),
            sa.Column("notes", sa.Text),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False,
                      server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='franchise_contracts' AND (column_name = 'tenant_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_franchise_contracts_tenant ON franchise_contracts (tenant_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='franchise_contracts' AND (column_name = 'franchisee_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_franchise_contracts_franchisee ON franchise_contracts (franchisee_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='franchise_contracts' AND (column_name = 'store_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_franchise_contracts_store ON franchise_contracts (store_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='franchise_contracts' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_franchise_contracts_status ON franchise_contracts (tenant_id, status)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='franchise_contracts' AND column_name IN ('tenant_id', 'end_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_franchise_contracts_end_date ON franchise_contracts (tenant_id, end_date)';
            END IF;
        END $$;
    """)
    # RLS
    op.execute(
        "ALTER TABLE franchise_contracts ENABLE ROW LEVEL SECURITY"
    )
    op.execute("""
        CREATE POLICY franchise_contracts_tenant_isolation
        ON franchise_contracts
        FOR ALL
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)

    # ── training_courses 培训课程 ────────────────────────────────
    if "training_courses" not in _existing:
        op.create_table(
        "training_courses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("instructor", sa.String(50)),
        sa.Column("duration_minutes", sa.Integer),
        sa.Column("target_roles", JSONB),
        sa.Column("chapters", JSONB),
        sa.Column("is_required", sa.Boolean, nullable=False,
                  server_default="false"),
        sa.Column("pass_score", sa.Integer, nullable=False,
                  server_default="60"),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False,
                  server_default="false"),
    )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='training_courses' AND (column_name = 'tenant_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_training_courses_tenant ON training_courses (tenant_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='training_courses' AND column_name IN ('tenant_id', 'category')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_training_courses_category ON training_courses (tenant_id, category)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='training_courses' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_training_courses_status ON training_courses (tenant_id, status)';
            END IF;
        END $$;
    """)
    # RLS
    op.execute(
        "ALTER TABLE training_courses ENABLE ROW LEVEL SECURITY"
    )
    op.execute("""
        CREATE POLICY training_courses_tenant_isolation
        ON training_courses
        FOR ALL
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)

    # ── training_records 学习记录 ────────────────────────────────
    if "training_records" not in _existing:
        op.create_table(
            "training_records",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("employee_id", UUID(as_uuid=True), nullable=False),
            sa.Column("course_id", UUID(as_uuid=True), nullable=False),
            sa.Column("progress_pct", sa.Integer, nullable=False,
                      server_default="0"),
            sa.Column("current_chapter", sa.Integer, nullable=False,
                      server_default="0"),
            sa.Column("status", sa.String(20), nullable=False,
                      server_default="not_started"),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("exam_score", sa.Integer),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["course_id"], ["training_courses.id"],
                                    name="fk_training_records_course"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='training_records' AND (column_name = 'tenant_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_training_records_tenant ON training_records (tenant_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='training_records' AND column_name IN ('tenant_id', 'employee_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_training_records_employee ON training_records (tenant_id, employee_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='training_records' AND (column_name = 'course_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_training_records_course ON training_records (course_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='training_records' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_training_records_status ON training_records (tenant_id, status)';
            END IF;
        END $$;
    """)
    # RLS
    op.execute(
        "ALTER TABLE training_records ENABLE ROW LEVEL SECURITY"
    )
    op.execute("""
        CREATE POLICY training_records_tenant_isolation
        ON training_records
        FOR ALL
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)

    # ── employee_certificates 员工证书 ───────────────────────────
    if "employee_certificates" not in _existing:
        op.create_table(
            "employee_certificates",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("employee_id", UUID(as_uuid=True), nullable=False),
            sa.Column("cert_name", sa.String(100), nullable=False),
            sa.Column("cert_type", sa.String(30), nullable=False),
            sa.Column("issue_date", sa.Date),
            sa.Column("expiry_date", sa.Date),
            sa.Column("issuer", sa.String(100)),
            sa.Column("cert_number", sa.String(50)),
            sa.Column("status", sa.String(20), nullable=False,
                      server_default="valid"),
            sa.Column("attachment_url", sa.Text),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False,
                      server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='employee_certificates' AND (column_name = 'tenant_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_employee_certs_tenant ON employee_certificates (tenant_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='employee_certificates' AND column_name IN ('tenant_id', 'employee_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_employee_certs_employee ON employee_certificates (tenant_id, employee_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='employee_certificates' AND column_name IN ('tenant_id', 'cert_type')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_employee_certs_type ON employee_certificates (tenant_id, cert_type)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='employee_certificates' AND column_name IN ('tenant_id', 'expiry_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_employee_certs_expiry ON employee_certificates (tenant_id, expiry_date)';
            END IF;
        END $$;
    """)
    # RLS
    op.execute(
        "ALTER TABLE employee_certificates ENABLE ROW LEVEL SECURITY"
    )
    op.execute("""
        CREATE POLICY employee_certificates_tenant_isolation
        ON employee_certificates
        FOR ALL
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS employee_certificates_tenant_isolation ON employee_certificates")
    op.drop_table("employee_certificates")

    op.execute("DROP POLICY IF EXISTS training_records_tenant_isolation ON training_records")
    op.drop_table("training_records")

    op.execute("DROP POLICY IF EXISTS training_courses_tenant_isolation ON training_courses")
    op.drop_table("training_courses")

    op.execute("DROP POLICY IF EXISTS franchise_contracts_tenant_isolation ON franchise_contracts")
    op.drop_table("franchise_contracts")
