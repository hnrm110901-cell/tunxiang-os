"""v158 — 高峰预测相关表

新增两张表：
  peak_forecast_configs   — 高峰时段预测配置（AI/手动预测结果）
  peak_actual_records     — 高峰实际记录（事后对比用）

RLS 策略：NULLIF(current_setting('app.tenant_id', true), '')::uuid 标准安全模式。

Revision ID: v158
Revises: v157
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "v158"
down_revision: Union[str, None] = "v157"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

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

    # ── peak_forecast_configs 高峰时段预测配置 ───────────────────────────
    if "peak_forecast_configs" not in _existing:
        op.create_table(
            "peak_forecast_configs",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("date", sa.Date, nullable=False, comment="预测日期"),
            sa.Column(
                "forecast_source",
                sa.String(20),
                nullable=False,
                server_default="ai",
                comment="预测来源：ai | manual",
            ),
            sa.Column(
                "peak_hours",
                JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
                comment="高峰时段列表：[{hour:int, expected_covers:int, staff_needed:int}]",
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
        "CREATE INDEX IF NOT EXISTS ix_pfc_tenant_store "
        "ON peak_forecast_configs (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pfc_tenant_store_date "
        "ON peak_forecast_configs (tenant_id, store_id, date)"
    )
    _apply_rls("peak_forecast_configs")

    # ── peak_actual_records 高峰实际记录 ────────────────────────────────
    if "peak_actual_records" not in _existing:
        op.create_table(
            "peak_actual_records",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("date", sa.Date, nullable=False, comment="记录日期"),
            sa.Column(
                "hour",
                sa.Integer,
                nullable=False,
                comment="小时（0-23）",
            ),
            sa.Column(
                "actual_covers",
                sa.Integer,
                nullable=False,
                server_default="0",
                comment="实际就餐人数",
            ),
            sa.Column(
                "actual_revenue_fen",
                sa.BigInteger,
                nullable=False,
                server_default="0",
                comment="实际营收（分）",
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint("hour BETWEEN 0 AND 23", name="ck_par_hour_range"),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_par_tenant_store "
        "ON peak_actual_records (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_par_tenant_store_date "
        "ON peak_actual_records (tenant_id, store_id, date)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uix_par_store_date_hour "
        "ON peak_actual_records (tenant_id, store_id, date, hour)"
    )
    _apply_rls("peak_actual_records")


def downgrade() -> None:
    for table in [
        "peak_actual_records",
        "peak_forecast_configs",
    ]:
        for policy in ["rls_delete", "rls_update", "rls_insert", "rls_select"]:
            op.execute(f"DROP POLICY IF EXISTS {table}_{policy} ON {table}")
        op.drop_table(table)
