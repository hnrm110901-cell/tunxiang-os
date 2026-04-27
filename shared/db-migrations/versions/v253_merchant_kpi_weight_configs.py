"""v253 — 商户 KPI 权重配置表

新增：
  merchant_kpi_weight_configs — 三商户差异化 KPI 权重（JSONB），含 RLS

背景：三商户（czyz/zqx/sgc）经营重点不同，KPI 权重需差异化配置，
以支撑 merchant_kpi_config_routes.py 端点的 UPSERT 写入与查询。

Revision ID: v253
Revises: v252
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v253"
down_revision = "v252"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    if "merchant_kpi_weight_configs" not in existing:
        op.create_table(
            "merchant_kpi_weight_configs",
            sa.Column("id", sa.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.UUID, nullable=False, comment="租户ID（RLS）"),
            sa.Column(
                "merchant_code",
                sa.Text,
                nullable=False,
                comment="商户代码：czyz / zqx / sgc 或自定义",
            ),
            sa.Column(
                "weights",
                sa.JSON,
                nullable=False,
                comment='KPI权重配置 JSONB，如 {"revenue_growth": 0.20, ...}',
            ),
            sa.Column("notes", sa.Text, nullable=True, comment="配置说明"),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.UniqueConstraint("tenant_id", "merchant_code", name="uq_merchant_kpi_tenant_code"),
        )
        op.create_index(
            "ix_merchant_kpi_tenant",
            "merchant_kpi_weight_configs",
            ["tenant_id"],
        )
        op.execute("ALTER TABLE merchant_kpi_weight_configs ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE merchant_kpi_weight_configs FORCE ROW LEVEL SECURITY")
        op.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = 'merchant_kpi_weight_configs'
                      AND policyname = 'mkc_tenant'
                ) THEN
                    EXECUTE $pol$
                        CREATE POLICY mkc_tenant ON merchant_kpi_weight_configs
                        USING (
                            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        )
                    $pol$;
                END IF;
            END;
            $$
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS merchant_kpi_weight_configs CASCADE")
