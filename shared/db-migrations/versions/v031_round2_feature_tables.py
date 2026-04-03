"""v031: Round2特性表 — 成本快照/储值/发票/菜单版本/生命周期/审批/加盟/生产计划

新增14张业务表（含RLS）：

财务域(tx-finance):
  cost_snapshots          — BOM级成本快照，每日批次
  financial_vouchers      — 财务凭证骨架

会员域(tx-member):
  stored_value_accounts       — 储值账户（余额/礼品金/赠送金）
  stored_value_transactions   — 储值明细流水
  lifecycle_events            — 会员生命周期事件
  lifecycle_configs           — 生命周期分类配置

菜单域(tx-menu):
  menu_versions           — 菜单版本（草稿/发布/归档）
  menu_dispatch_records   — 版本下发记录

组织域(tx-org):
  payroll_records             — 薪资计算结果留档
  approval_flow_definitions   — 审批流定义（JSONB steps）
  approval_instances          — 审批流实例
  approval_records            — 审批操作记录
  franchisees                 — 加盟商合同
  franchisee_stores           — 加盟商门店关联
  royalty_bills               — 月度分润账单

供应链域(tx-supply):
  production_plans        — 中央厨房生产计划
  production_tasks        — 加工任务（档口级）
  delivery_trips          — 配送趟次
  delivery_items          — 配送清单行项
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "v031"
down_revision: Union[str, None] = "v030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 财务：成本快照 ────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS cost_snapshots (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id     UUID NOT NULL,
        dish_id       UUID NOT NULL,
        snapshot_date DATE NOT NULL,
        batch_id      TEXT NOT NULL,
        cost_breakdown JSONB NOT NULL DEFAULT '{}',
        total_cost    NUMERIC(12,4) NOT NULL DEFAULT 0,
        ingredient_count INT NOT NULL DEFAULT 0,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (tenant_id, dish_id, snapshot_date, batch_id)
    );
    ALTER TABLE cost_snapshots ENABLE ROW LEVEL SECURITY;
    CREATE POLICY cost_snapshots_tenant ON cost_snapshots
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    # ── 财务：凭证 ────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS financial_vouchers (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id     UUID NOT NULL,
        voucher_no    TEXT NOT NULL,
        voucher_type  TEXT NOT NULL DEFAULT 'settlement',
        period_start  DATE NOT NULL,
        period_end    DATE NOT NULL,
        total_debit   NUMERIC(14,2) NOT NULL DEFAULT 0,
        total_credit  NUMERIC(14,2) NOT NULL DEFAULT 0,
        entries       JSONB NOT NULL DEFAULT '[]',
        status        TEXT NOT NULL DEFAULT 'draft',
        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (tenant_id, voucher_no)
    );
    ALTER TABLE financial_vouchers ENABLE ROW LEVEL SECURITY;
    CREATE POLICY financial_vouchers_tenant ON financial_vouchers
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    # ── 财务：发票 ────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        order_id        UUID,
        invoice_code    TEXT,
        invoice_no      TEXT,
        status          TEXT NOT NULL DEFAULT 'pending',
        amount          NUMERIC(12,2) NOT NULL,
        tax_amount      NUMERIC(12,2) NOT NULL DEFAULT 0,
        buyer_name      TEXT,
        buyer_tax_no    TEXT,
        external_id     TEXT,
        pdf_url         TEXT,
        failed_reason   TEXT,
        applied_at      TIMESTAMPTZ,
        issued_at       TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
    CREATE POLICY invoices_tenant ON invoices
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    # ── 会员：储值账户 ────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS stored_value_accounts (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        customer_id     UUID NOT NULL,
        balance         NUMERIC(12,2) NOT NULL DEFAULT 0,
        gift_balance    NUMERIC(12,2) NOT NULL DEFAULT 0,
        bonus_balance   NUMERIC(12,2) NOT NULL DEFAULT 0,
        status          TEXT NOT NULL DEFAULT 'active',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (tenant_id, customer_id)
    );
    ALTER TABLE stored_value_accounts ENABLE ROW LEVEL SECURITY;
    CREATE POLICY stored_value_accounts_tenant ON stored_value_accounts
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS stored_value_transactions (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        account_id      UUID NOT NULL REFERENCES stored_value_accounts(id),
        txn_type        TEXT NOT NULL,
        amount          NUMERIC(12,2) NOT NULL,
        balance_after   NUMERIC(12,2) NOT NULL,
        order_id        UUID,
        note            TEXT,
        operator_id     UUID,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE stored_value_transactions ENABLE ROW LEVEL SECURITY;
    CREATE POLICY stored_value_transactions_tenant ON stored_value_transactions
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    # ── 会员：生命周期 ────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS lifecycle_events (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        customer_id     UUID NOT NULL,
        from_stage      TEXT,
        to_stage        TEXT NOT NULL,
        trigger         TEXT NOT NULL DEFAULT 'batch',
        metadata        JSONB NOT NULL DEFAULT '{}',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE lifecycle_events ENABLE ROW LEVEL SECURITY;
    CREATE POLICY lifecycle_events_tenant ON lifecycle_events
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS lifecycle_configs (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        active_days     INT NOT NULL DEFAULT 30,
        dormant_days    INT NOT NULL DEFAULT 90,
        churn_days      INT NOT NULL DEFAULT 180,
        reactivated_days INT NOT NULL DEFAULT 14,
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (tenant_id)
    );
    ALTER TABLE lifecycle_configs ENABLE ROW LEVEL SECURITY;
    CREATE POLICY lifecycle_configs_tenant ON lifecycle_configs
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    # ── 菜单：版本管理 ────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS menu_versions (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        brand_id        UUID,
        version_no      TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'draft',
        dishes_snapshot JSONB NOT NULL DEFAULT '{}',
        published_at    TIMESTAMPTZ,
        archived_at     TIMESTAMPTZ,
        created_by      UUID,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (tenant_id, version_no)
    );
    ALTER TABLE menu_versions ENABLE ROW LEVEL SECURITY;
    CREATE POLICY menu_versions_tenant ON menu_versions
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS menu_dispatch_records (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        version_id      UUID NOT NULL REFERENCES menu_versions(id),
        store_id        UUID NOT NULL,
        dispatch_type   TEXT NOT NULL DEFAULT 'full',
        status          TEXT NOT NULL DEFAULT 'pending',
        store_overrides JSONB NOT NULL DEFAULT '{}',
        dispatched_at   TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE menu_dispatch_records ENABLE ROW LEVEL SECURITY;
    CREATE POLICY menu_dispatch_records_tenant ON menu_dispatch_records
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    # ── 组织：薪资记录 ────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS payroll_records (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        employee_id     UUID NOT NULL,
        period_year     INT NOT NULL,
        period_month    INT NOT NULL,
        gross_salary    NUMERIC(12,2) NOT NULL DEFAULT 0,
        social_insurance NUMERIC(12,2) NOT NULL DEFAULT 0,
        income_tax      NUMERIC(12,2) NOT NULL DEFAULT 0,
        net_salary      NUMERIC(12,2) NOT NULL DEFAULT 0,
        details         JSONB NOT NULL DEFAULT '{}',
        status          TEXT NOT NULL DEFAULT 'draft',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (tenant_id, employee_id, period_year, period_month)
    );
    ALTER TABLE payroll_records ENABLE ROW LEVEL SECURITY;
    CREATE POLICY payroll_records_tenant ON payroll_records
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    # ── 组织：审批引擎 ────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS approval_flow_definitions (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        flow_name       TEXT NOT NULL,
        business_type   TEXT NOT NULL,
        steps           JSONB NOT NULL DEFAULT '[]',
        is_active       BOOLEAN NOT NULL DEFAULT TRUE,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (tenant_id, business_type, flow_name)
    );
    ALTER TABLE approval_flow_definitions ENABLE ROW LEVEL SECURITY;
    CREATE POLICY approval_flow_definitions_tenant ON approval_flow_definitions
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS approval_instances (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        flow_def_id     UUID NOT NULL REFERENCES approval_flow_definitions(id),
        business_type   TEXT NOT NULL,
        subject_id      UUID,
        context         JSONB NOT NULL DEFAULT '{}',
        current_step    INT NOT NULL DEFAULT 0,
        status          TEXT NOT NULL DEFAULT 'pending',
        submitted_by    UUID NOT NULL,
        submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at    TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE approval_instances ENABLE ROW LEVEL SECURITY;
    CREATE POLICY approval_instances_tenant ON approval_instances
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS approval_records (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        instance_id     UUID NOT NULL REFERENCES approval_instances(id),
        step_index      INT NOT NULL,
        approver_id     UUID NOT NULL,
        action          TEXT NOT NULL,
        comment         TEXT,
        acted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE approval_records ENABLE ROW LEVEL SECURITY;
    CREATE POLICY approval_records_tenant ON approval_records
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    # ── 组织：加盟体系 ────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS franchisees (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        name            TEXT NOT NULL,
        contact_name    TEXT,
        contact_phone   TEXT,
        contract_start  DATE NOT NULL,
        contract_end    DATE,
        base_royalty_rate NUMERIC(5,4) NOT NULL DEFAULT 0.05,
        royalty_tiers   JSONB NOT NULL DEFAULT '[]',
        status          TEXT NOT NULL DEFAULT 'active',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE franchisees ENABLE ROW LEVEL SECURITY;
    CREATE POLICY franchisees_tenant ON franchisees
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS franchisee_stores (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        franchisee_id   UUID NOT NULL REFERENCES franchisees(id),
        store_id        UUID NOT NULL,
        joined_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (tenant_id, store_id)
    );
    ALTER TABLE franchisee_stores ENABLE ROW LEVEL SECURITY;
    CREATE POLICY franchisee_stores_tenant ON franchisee_stores
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS royalty_bills (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        franchisee_id   UUID NOT NULL REFERENCES franchisees(id),
        period_year     INT NOT NULL,
        period_month    INT NOT NULL,
        revenue         NUMERIC(14,2) NOT NULL DEFAULT 0,
        royalty_amount  NUMERIC(12,2) NOT NULL DEFAULT 0,
        due_date        DATE NOT NULL,
        status          TEXT NOT NULL DEFAULT 'pending',
        paid_at         TIMESTAMPTZ,
        overdue_at      TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (tenant_id, franchisee_id, period_year, period_month)
    );
    ALTER TABLE royalty_bills ENABLE ROW LEVEL SECURITY;
    CREATE POLICY royalty_bills_tenant ON royalty_bills
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    # ── 供应链：中央厨房 ──────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS production_plans (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        plan_date       DATE NOT NULL,
        brand_id        UUID,
        status          TEXT NOT NULL DEFAULT 'draft',
        total_demand_kg NUMERIC(12,3) NOT NULL DEFAULT 0,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (tenant_id, plan_date, brand_id)
    );
    ALTER TABLE production_plans ENABLE ROW LEVEL SECURITY;
    CREATE POLICY production_plans_tenant ON production_plans
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS production_tasks (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        plan_id         UUID NOT NULL REFERENCES production_plans(id),
        station_id      TEXT NOT NULL,
        ingredient_id   UUID NOT NULL,
        ingredient_name TEXT NOT NULL,
        quantity_kg     NUMERIC(12,3) NOT NULL DEFAULT 0,
        status          TEXT NOT NULL DEFAULT 'pending',
        started_at      TIMESTAMPTZ,
        completed_at    TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE production_tasks ENABLE ROW LEVEL SECURITY;
    CREATE POLICY production_tasks_tenant ON production_tasks
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS delivery_trips (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        plan_id         UUID NOT NULL REFERENCES production_plans(id),
        trip_no         INT NOT NULL DEFAULT 1,
        driver_id       UUID,
        vehicle_no      TEXT,
        status          TEXT NOT NULL DEFAULT 'pending',
        route_order     JSONB NOT NULL DEFAULT '[]',
        departed_at     TIMESTAMPTZ,
        completed_at    TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE delivery_trips ENABLE ROW LEVEL SECURITY;
    CREATE POLICY delivery_trips_tenant ON delivery_trips
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS delivery_items (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID NOT NULL,
        trip_id         UUID NOT NULL REFERENCES delivery_trips(id),
        store_id        UUID NOT NULL,
        ingredient_id   UUID NOT NULL,
        ingredient_name TEXT NOT NULL,
        planned_qty_kg  NUMERIC(12,3) NOT NULL DEFAULT 0,
        received_qty_kg NUMERIC(12,3),
        status          TEXT NOT NULL DEFAULT 'pending',
        received_at     TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE delivery_items ENABLE ROW LEVEL SECURITY;
    CREATE POLICY delivery_items_tenant ON delivery_items
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
    """)


def downgrade() -> None:
    tables = [
        "delivery_items", "delivery_trips", "production_tasks", "production_plans",
        "royalty_bills", "franchisee_stores", "franchisees",
        "approval_records", "approval_instances", "approval_flow_definitions",
        "payroll_records",
        "menu_dispatch_records", "menu_versions",
        "lifecycle_configs", "lifecycle_events",
        "stored_value_transactions", "stored_value_accounts",
        "invoices", "financial_vouchers", "cost_snapshots",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
