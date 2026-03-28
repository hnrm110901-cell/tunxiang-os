"""v006: Activate full RLS enforcement + tenants table

Revision ID: v006
Revises: v005
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision: str = "v006"
down_revision: Union[str, None] = "v005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

V001_TABLES = ["customers", "stores", "dish_categories", "dishes", "dish_ingredients", "orders", "order_items", "ingredient_masters", "ingredients", "ingredient_transactions", "employees"]
V002_TABLES = ["tables", "payments", "refunds", "settlements", "shift_handovers", "receipt_templates", "receipt_logs", "production_depts", "dish_dept_mappings", "daily_ops_flows", "daily_ops_nodes", "agent_decision_logs"]
V003_TABLES = ["payment_records", "reconciliation_batches", "reconciliation_diffs", "tri_reconciliation_records", "store_daily_settlements", "payment_fees"]
V004_TABLES = ["reservations", "queues", "banquet_halls", "banquet_leads", "banquet_orders", "banquet_contracts", "menu_packages", "banquet_checklists"]
V005_TABLES = ["attendance_rules", "clock_records", "daily_attendance", "payroll_batches", "payroll_items", "leave_requests", "leave_balances", "settlement_records"]
ALL_RLS_TABLES = V001_TABLES + V002_TABLES + V003_TABLES + V004_TABLES + V005_TABLES


def _upgrade_rls(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}")
    op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table_name} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table_name} USING (tenant_id::text = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")


def _downgrade_rls(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation_{table_name} ON {table_name} USING (tenant_id = current_setting('app.tenant_id')::UUID)")
    op.execute(f"CREATE POLICY tenant_insert_{table_name} ON {table_name} FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(50), unique=True, nullable=False, comment="租户编码"),
        sa.Column("name", sa.String(200), nullable=False, comment="租户名称"),
        sa.Column("brand_name", sa.String(200)),
        sa.Column("pos_system", sa.String(50), server_default="pinzhi"),
        sa.Column("pos_config", JSON, server_default="{}"),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute("INSERT INTO tenants (id, code, name, brand_name) VALUES ('10000000-0000-0000-0000-000000000001', 't-czq', '尝在一起', '尝在一起'), ('10000000-0000-0000-0000-000000000002', 't-zqx', '最黔线', '最黔线'), ('10000000-0000-0000-0000-000000000003', 't-sgc', '尚宫厨', '尚宫厨')")
    for table in ALL_RLS_TABLES:
        _upgrade_rls(table)


def downgrade() -> None:
    for table in reversed(ALL_RLS_TABLES):
        _downgrade_rls(table)
    op.drop_table("tenants")
