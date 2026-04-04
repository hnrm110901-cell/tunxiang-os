"""v129 — 中央厨房 + 审批中心正式表

新增五张表：
  store_requisitions       — 门店备货需求单
  store_requisition_items  — 需求单明细行
  production_plans         — 中央厨房排产计划
  production_plan_items    — 排产计划明细行
  approval_records         — 统一审批记录

Revision ID: v129
Revises: v128
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v129"
down_revision = "v128"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── store_requisitions 门店备货需求单 ────────────────────────
    if "store_requisitions" not in _existing:
        op.create_table(
            "store_requisitions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("delivery_date", sa.Date, nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="'pending'"),
            sa.Column("approved_by", sa.String(100), nullable=True),
            sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='store_requisitions' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_store_requisitions_tenant_store ON store_requisitions (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='store_requisitions' AND column_name IN ('tenant_id', 'delivery_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_store_requisitions_delivery_date ON store_requisitions (tenant_id, delivery_date)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE store_requisitions ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS store_requisitions_tenant_isolation ON store_requisitions;")
    op.execute("DROP POLICY IF EXISTS store_requisitions_tenant_isolation ON store_requisitions;")
    op.execute("""
        CREATE POLICY store_requisitions_tenant_isolation ON store_requisitions
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── store_requisition_items 需求单明细 ───────────────────────
    if "store_requisition_items" not in _existing:
        op.create_table(
            "store_requisition_items",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("requisition_id", UUID(as_uuid=True), nullable=False),
            sa.Column("ingredient_id", UUID(as_uuid=True), nullable=True),
            sa.Column("ingredient_name", sa.String(100), nullable=False),
            sa.Column("quantity", sa.Numeric(10, 3), nullable=False),
            sa.Column("unit", sa.String(20), nullable=False),
            sa.Column("notes", sa.Text, nullable=True),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='store_requisition_items' AND (column_name = 'requisition_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_store_requisition_items_req ON store_requisition_items (requisition_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE store_requisition_items ADD CONSTRAINT fk_store_requisition_items_req
                FOREIGN KEY (requisition_id) REFERENCES store_requisitions(id) ON DELETE CASCADE;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("ALTER TABLE store_requisition_items ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS store_requisition_items_tenant_isolation ON store_requisition_items;")
    op.execute("DROP POLICY IF EXISTS store_requisition_items_tenant_isolation ON store_requisition_items;")
    op.execute("""
        CREATE POLICY store_requisition_items_tenant_isolation ON store_requisition_items
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── production_plans 排产计划 ────────────────────────────────
    if "production_plans" not in _existing:
        op.create_table(
        "production_plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("plan_date", sa.Date, nullable=False),
        sa.Column("shift", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="'draft'"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='production_plans' AND column_name IN ('tenant_id', 'plan_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_production_plans_tenant_date ON production_plans (tenant_id, plan_date)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE production_plans ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS production_plans_tenant_isolation ON production_plans;")
    op.execute("DROP POLICY IF EXISTS production_plans_tenant_isolation ON production_plans;")
    op.execute("""
        CREATE POLICY production_plans_tenant_isolation ON production_plans
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── production_plan_items 排产明细 ──────────────────────────
    if "production_plan_items" not in _existing:
        op.create_table(
            "production_plan_items",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("plan_id", UUID(as_uuid=True), nullable=False),
            sa.Column("ingredient_id", UUID(as_uuid=True), nullable=True),
            sa.Column("ingredient_name", sa.String(100), nullable=False),
            sa.Column("planned_quantity", sa.Numeric(10, 3), nullable=False),
            sa.Column("actual_quantity", sa.Numeric(10, 3), nullable=True),
            sa.Column("unit", sa.String(20), nullable=False),
            sa.Column("processing_type", sa.String(20), nullable=False),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='production_plan_items' AND (column_name = 'plan_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_production_plan_items_plan ON production_plan_items (plan_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE production_plan_items ADD CONSTRAINT fk_production_plan_items_plan
                FOREIGN KEY (plan_id) REFERENCES production_plans(id) ON DELETE CASCADE;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("ALTER TABLE production_plan_items ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS production_plan_items_tenant_isolation ON production_plan_items;")
    op.execute("DROP POLICY IF EXISTS production_plan_items_tenant_isolation ON production_plan_items;")
    op.execute("""
        CREATE POLICY production_plan_items_tenant_isolation ON production_plan_items
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── approval_records 统一审批记录 ────────────────────────────
    if "approval_records" not in _existing:
        op.create_table(
        "approval_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("approval_type", sa.String(30), nullable=False),
        sa.Column("reference_id", UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("amount_fen", sa.BigInteger, nullable=True),
        sa.Column("applicant_id", UUID(as_uuid=True), nullable=True),
        sa.Column("applicant_name", sa.String(100), nullable=True),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True),
        sa.Column("urgency", sa.String(20), nullable=False, server_default="'normal'"),
        sa.Column("status", sa.String(20), nullable=False, server_default="'pending'"),
        sa.Column("approver_id", UUID(as_uuid=True), nullable=True),
        sa.Column("approver_name", sa.String(100), nullable=True),
        sa.Column("action_comment", sa.Text, nullable=True),
        sa.Column("action_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("extra_data", JSONB, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='approval_records' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_approval_records_tenant_status ON approval_records (tenant_id, status)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='approval_records' AND column_name IN ('tenant_id', 'approval_type')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_approval_records_tenant_type ON approval_records (tenant_id, approval_type)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='approval_records' AND column_name IN ('tenant_id', 'created_at')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_approval_records_created ON approval_records (tenant_id, created_at)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE approval_records ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS approval_records_tenant_isolation ON approval_records;")
    op.execute("DROP POLICY IF EXISTS approval_records_tenant_isolation ON approval_records;")
    op.execute("""
        CREATE POLICY approval_records_tenant_isolation ON approval_records
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS approval_records_tenant_isolation ON approval_records;")
    op.drop_table("approval_records")

    op.execute("DROP POLICY IF EXISTS production_plan_items_tenant_isolation ON production_plan_items;")
    op.drop_table("production_plan_items")

    op.execute("DROP POLICY IF EXISTS production_plans_tenant_isolation ON production_plans;")
    op.drop_table("production_plans")

    op.execute("DROP POLICY IF EXISTS store_requisition_items_tenant_isolation ON store_requisition_items;")
    op.drop_table("store_requisition_items")

    op.execute("DROP POLICY IF EXISTS store_requisitions_tenant_isolation ON store_requisitions;")
    op.drop_table("store_requisitions")
