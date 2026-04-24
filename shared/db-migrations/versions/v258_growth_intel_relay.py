"""v258 — 增长情报接力：opportunity_relays + pilot_feedbacks

新建：
  opportunity_relays  — 情报机会 -> 增长活动接力记录
  pilot_feedbacks     — 增长试点结果 -> 情报模型反馈

所有表含 tenant_id + RLS（app.tenant_id）。

Revision ID: v258
Revises: v257
Create Date: 2026-04-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v258"
down_revision = "v257"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ── opportunity_relays ────────────────────────────────────────────────────
    if "opportunity_relays" not in existing:
        op.create_table(
            "opportunity_relays",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("relay_id", sa.String(50), nullable=False, unique=True, comment="业务层ID，格式 relay-{hex8}"),
            sa.Column("opportunity_id", sa.String(100), nullable=False),
            sa.Column("opportunity_type", sa.String(50), nullable=False, comment="新品机会/竞对防御/需求趋势/原料机会"),
            sa.Column("opportunity_title", sa.Text, nullable=False),
            sa.Column("opportunity_score", sa.Numeric(5, 1), nullable=False, comment="机会评分 0-100"),
            sa.Column("campaign_draft_id", sa.String(100), nullable=True),
            sa.Column("campaign_type", sa.String(50), nullable=True),
            sa.Column("campaign_title", sa.Text, nullable=True),
            sa.Column("suggested_actions", JSONB, nullable=False, server_default="'[]'"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'pending'",
                comment="pending/draft_created/approved/executing/completed/rejected",
            ),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
        op.create_index("ix_opportunity_relays_tenant_status", "opportunity_relays", ["tenant_id", "status"])
        op.create_index("ix_opportunity_relays_opportunity_id", "opportunity_relays", ["opportunity_id"])

    op.execute("ALTER TABLE opportunity_relays ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS opportunity_relays_tenant ON opportunity_relays;")
    op.execute("""
        CREATE POLICY opportunity_relays_tenant ON opportunity_relays
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION trg_set_updated_at()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN NEW.updated_at = now(); RETURN NEW; END;
        $$;
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_opportunity_relays_updated_at ON opportunity_relays;
        CREATE TRIGGER trg_opportunity_relays_updated_at
        BEFORE UPDATE ON opportunity_relays
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
    """)

    # ── pilot_feedbacks ───────────────────────────────────────────────────────
    if "pilot_feedbacks" not in existing:
        op.create_table(
            "pilot_feedbacks",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("feedback_id", sa.String(50), nullable=False, unique=True, comment="业务层ID，格式 fb-{hex6}"),
            sa.Column("pilot_id", sa.String(100), nullable=False),
            sa.Column("relay_id", sa.String(50), nullable=False, comment="关联 opportunity_relays.relay_id"),
            sa.Column("results", JSONB, nullable=False, server_default="'{}'"),
            sa.Column("metrics", JSONB, nullable=False, server_default="'{}'"),
            sa.Column("intel_model_updated", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
        op.create_index("ix_pilot_feedbacks_tenant", "pilot_feedbacks", ["tenant_id"])
        op.create_index("ix_pilot_feedbacks_relay_id", "pilot_feedbacks", ["relay_id"])

    op.execute("ALTER TABLE pilot_feedbacks ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS pilot_feedbacks_tenant ON pilot_feedbacks;")
    op.execute("""
        CREATE POLICY pilot_feedbacks_tenant ON pilot_feedbacks
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.drop_table("pilot_feedbacks")
    op.drop_table("opportunity_relays")
