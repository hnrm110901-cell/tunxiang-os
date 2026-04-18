"""z70 — D14 应用市场 / AI 增值工厂 / 行业方案

新增 5 张表：
  applications          应用/数智员工/行业方案主表
  app_pricing_tiers     定价档
  app_installations     租户安装记录
  app_reviews           租户评价
  app_billing_records   月度计费流水

所有金额字段使用 BIGINT 存「分」。

Revision ID: z70_d14_marketplace
Revises: z69_merge_wave5
Create Date: 2026-04-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision = "z70_d14_marketplace"
down_revision = "z69_merge_wave5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── applications ─────────────────────────────────────────
    op.create_table(
        "applications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(32), nullable=False, index=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("icon_url", sa.String(500), nullable=True),
        sa.Column("provider", sa.String(64), nullable=False, server_default="tunxiang"),
        sa.Column("price_model", sa.String(32), nullable=False, server_default="monthly"),
        sa.Column("price_fen", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="CNY"),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft", index=True),
        sa.Column("trial_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("feature_flags_json", JSONB, nullable=True),
        sa.Column("supported_roles_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ── app_pricing_tiers ────────────────────────────────────
    op.create_table(
        "app_pricing_tiers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("app_id", UUID(as_uuid=True),
                  sa.ForeignKey("applications.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("tier_name", sa.String(32), nullable=False),
        sa.Column("monthly_fee_fen", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("usage_limits_json", JSONB, nullable=True),
        sa.Column("features_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ── app_installations ────────────────────────────────────
    op.create_table(
        "app_installations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("app_id", UUID(as_uuid=True),
                  sa.ForeignKey("applications.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("tier_name", sa.String(32), nullable=True),
        sa.Column("installed_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(16), nullable=False, server_default="active", index=True),
        sa.Column("trial_ends_at", sa.DateTime, nullable=True),
        sa.Column("config_json", JSONB, nullable=True),
        sa.Column("installed_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_app_installations_tenant_app",
        "app_installations", ["tenant_id", "app_id"],
    )

    # ── app_reviews ──────────────────────────────────────────
    op.create_table(
        "app_reviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("app_id", UUID(as_uuid=True),
                  sa.ForeignKey("applications.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("rating", sa.Integer, nullable=False),
        sa.Column("review_text", sa.Text, nullable=True),
        sa.Column("reviewed_by", sa.String(64), nullable=True),
        sa.Column("helpful_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="visible"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ── app_billing_records ──────────────────────────────────
    op.create_table(
        "app_billing_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("installation_id", UUID(as_uuid=True),
                  sa.ForeignKey("app_installations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("billing_period", sa.String(7), nullable=False, index=True),
        sa.Column("amount_fen", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("usage_data_json", JSONB, nullable=True),
        sa.Column("paid_at", sa.DateTime, nullable=True),
        sa.Column("invoice_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_billing_installation_period",
        "app_billing_records",
        ["installation_id", "billing_period"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_billing_installation_period", table_name="app_billing_records")
    op.drop_table("app_billing_records")
    op.drop_table("app_reviews")
    op.drop_index("ix_app_installations_tenant_app", table_name="app_installations")
    op.drop_table("app_installations")
    op.drop_table("app_pricing_tiers")
    op.drop_table("applications")
