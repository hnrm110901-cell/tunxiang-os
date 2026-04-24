"""v164 — 能耗预算配置与智能告警规则表

新增两张表：
  energy_budgets      — 月度能耗预算配置（电/气/水/总成本）
  energy_alert_rules  — 能耗告警规则（绝对值/预算占比/同比）

RLS 策略：NULLIF(current_setting('app.tenant_id', true), '')::uuid 标准安全模式。

Revision ID: v164
Revises: v163
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v164"
down_revision= "v163"
branch_labels= None
depends_on= None

_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _apply_rls(table_name: str) -> None:
    """标准三段式 RLS：ENABLE → FORCE → 四条策略"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table_name}_rls_select ON {table_name} "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_rls_insert ON {table_name} "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_rls_update ON {table_name} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table_name}_rls_delete ON {table_name} "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── energy_budgets 月度能耗预算配置 ──────────────────────────────────
    if "energy_budgets" not in _existing:
        op.create_table(
            "energy_budgets",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("budget_year", sa.Integer, nullable=False),
            sa.Column(
                "budget_month",
                sa.Integer,
                nullable=False,
                comment="1-12",
            ),
            sa.Column(
                "electricity_kwh_budget",
                sa.Numeric(10, 2),
                nullable=True,
                comment="月度电量预算（kWh）",
            ),
            sa.Column(
                "gas_m3_budget",
                sa.Numeric(10, 2),
                nullable=True,
                comment="月度燃气预算（m³）",
            ),
            sa.Column(
                "water_ton_budget",
                sa.Numeric(10, 2),
                nullable=True,
                comment="月度用水预算（吨）",
            ),
            sa.Column(
                "total_cost_budget_fen",
                sa.BigInteger,
                nullable=True,
                comment="月度总能耗成本预算（分）",
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint(
                "budget_month BETWEEN 1 AND 12",
                name="ck_energy_budgets_month_range",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "store_id",
                "budget_year",
                "budget_month",
                name="uq_energy_budgets_tenant_store_ym",
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_energy_budgets_tenant_store "
        "ON energy_budgets (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_energy_budgets_tenant_ym "
        "ON energy_budgets (tenant_id, budget_year DESC, budget_month DESC)"
    )
    _apply_rls("energy_budgets")

    # ── energy_alert_rules 能耗告警规则 ──────────────────────────────────
    if "energy_alert_rules" not in _existing:
        op.create_table(
            "energy_alert_rules",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("rule_name", sa.String(100), nullable=False),
            sa.Column(
                "metric",
                sa.String(30),
                nullable=False,
                comment="electricity_kwh|gas_m3|water_ton|cost_fen|ratio",
            ),
            sa.Column(
                "threshold_type",
                sa.String(20),
                nullable=False,
                comment="absolute|budget_pct|yoy_pct",
            ),
            sa.Column("threshold_value", sa.Numeric(10, 2), nullable=False),
            sa.Column(
                "severity",
                sa.String(10),
                nullable=False,
                server_default=sa.text("'warning'"),
                comment="info|warning|critical",
            ),
            sa.Column(
                "is_active",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("TRUE"),
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_energy_alert_rules_tenant_store "
        "ON energy_alert_rules (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_energy_alert_rules_tenant_active "
        "ON energy_alert_rules (tenant_id, is_active)"
    )
    _apply_rls("energy_alert_rules")


def downgrade() -> None:
    for table in ["energy_alert_rules", "energy_budgets"]:
        for policy in ["rls_delete", "rls_update", "rls_insert", "rls_select"]:
            op.execute(f"DROP POLICY IF EXISTS {table}_{policy} ON {table}")
        op.drop_table(table)
