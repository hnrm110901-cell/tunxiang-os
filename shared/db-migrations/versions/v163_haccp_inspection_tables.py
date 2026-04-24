"""v163 — HACCP关键控制点检查计划表

新增两张表：
  haccp_check_plans    — HACCP检查计划（计划名称/检查类型/频率/检查清单）
  haccp_check_records  — 检查执行记录（执行结果/合格判断/关键失控点数/整改措施）

RLS 策略：NULLIF(current_setting('app.tenant_id', true), '')::uuid 标准安全模式。

Revision ID: v163
Revises: v162
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v163"
down_revision= "v162"
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

    # ── haccp_check_plans HACCP检查计划 ──────────────────────────────────
    if "haccp_check_plans" not in _existing:
        op.create_table(
            "haccp_check_plans",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("plan_name", sa.String(100), nullable=False),
            sa.Column(
                "check_type",
                sa.String(30),
                nullable=False,
                comment="temperature|hygiene|pest|supplier|equipment",
            ),
            sa.Column(
                "frequency",
                sa.String(20),
                nullable=False,
                comment="daily|weekly|monthly",
            ),
            sa.Column("responsible_role", sa.String(50), nullable=True),
            sa.Column(
                "checklist",
                JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
                comment="[{item: str, standard: str, critical: bool}]",
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
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_haccp_check_plans_tenant_store "
        "ON haccp_check_plans (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_haccp_check_plans_tenant_active "
        "ON haccp_check_plans (tenant_id, is_active)"
    )
    _apply_rls("haccp_check_plans")

    # ── haccp_check_records 检查执行记录 ─────────────────────────────────
    if "haccp_check_records" not in _existing:
        op.create_table(
            "haccp_check_records",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "plan_id",
                UUID(as_uuid=True),
                nullable=False,
                comment="关联检查计划",
            ),
            sa.Column("operator_id", UUID(as_uuid=True), nullable=True),
            sa.Column("check_date", sa.Date, nullable=False),
            sa.Column(
                "results",
                JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
                comment="[{item: str, passed: bool, value: str, note: str}]",
            ),
            sa.Column("overall_passed", sa.Boolean, nullable=True),
            sa.Column(
                "critical_failures",
                sa.Integer,
                nullable=False,
                server_default="0",
                comment="关键控制点失控数量",
            ),
            sa.Column("corrective_actions", sa.Text, nullable=True),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["plan_id"],
                ["haccp_check_plans.id"],
                name="fk_haccp_check_records_plan_id",
            ),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_haccp_check_records_tenant_store "
        "ON haccp_check_records (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_haccp_check_records_tenant_date "
        "ON haccp_check_records (tenant_id, check_date DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_haccp_check_records_plan "
        "ON haccp_check_records (plan_id)"
    )
    _apply_rls("haccp_check_records")


def downgrade() -> None:
    # 按依赖顺序逆向删除
    for table in ["haccp_check_records", "haccp_check_plans"]:
        for policy in ["rls_delete", "rls_update", "rls_insert", "rls_select"]:
            op.execute(f"DROP POLICY IF EXISTS {table}_{policy} ON {table}")
        op.drop_table(table)
