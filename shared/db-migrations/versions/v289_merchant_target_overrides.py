"""v236 — 商户KPI目标覆盖配置表

新增：
  merchant_target_overrides — 商户自定义KPI目标（覆盖内置默认值）

背景：B-03差距关闭，merchant_targets_routes.py PUT端点需要持久化目标覆盖，
支持商户差异化KPI目标配置。

Revision ID: v236b
Revises: v235
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v236b"
down_revision = "v235"
branch_labels = None
depends_on = None


def _add_rls(table: str, policy: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='{table}' AND policyname='{policy}') THEN
                EXECUTE $pol$
                    CREATE POLICY {policy} ON {table}
                    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                $pol$;
            END IF;
        END; $$
    """)


def upgrade() -> None:
    conn = op.get_bind()
    if "merchant_target_overrides" in sa.inspect(conn).get_table_names():
        return

    # ── 1. 创建 merchant_target_overrides 表 ──
    op.create_table(
        "merchant_target_overrides",
        sa.Column(
            "id",
            postgresql.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("merchant_code", sa.Text(), nullable=False),
        sa.Column("target_key", sa.Text(), nullable=False),
        sa.Column("target_value", sa.Numeric(12, 4), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "merchant_code",
            "target_key",
            name="uq_merchant_target",
        ),
    )

    # ── 2. 创建索引 ──
    op.create_index(
        "ix_merchant_target_tenant",
        "merchant_target_overrides",
        ["tenant_id", "merchant_code"],
    )

    # ── 3. RLS ──
    _add_rls("merchant_target_overrides", "mto_tenant")


def downgrade() -> None:
    op.drop_table("merchant_target_overrides", if_exists=True)
