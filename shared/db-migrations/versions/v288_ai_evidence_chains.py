"""v235 — AI 结论可追溯证据链表

新增：
  ai_evidence_chains — AI结论及其支撑证据（支持可追溯审计）

背景：B-04差距关闭，AI结论必须附带可追溯证据链，
以支持管理层信任AI建议、进行合规审计。

Revision ID: v235
Revises: v234
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v288b"
down_revision = "v234"
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
    if "ai_evidence_chains" in sa.inspect(conn).get_table_names():
        return

    # ── 1. 创建 ai_evidence_chains 表 ──
    op.create_table(
        "ai_evidence_chains",
        sa.Column(
            "id",
            postgresql.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("chain_id", sa.Text(), nullable=False),
        sa.Column("merchant_code", sa.Text(), nullable=False),
        sa.Column("conclusion_type", sa.Text(), nullable=False),
        sa.Column("conclusion_text", sa.Text(), nullable=False),
        sa.Column(
            "evidence_links",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "merchant_target_refs",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    # ── 2. 创建索引 ──
    op.create_index(
        "ix_evidence_chains_chain_id",
        "ai_evidence_chains",
        ["chain_id"],
        unique=True,
    )
    op.create_index(
        "ix_evidence_chains_merchant",
        "ai_evidence_chains",
        [
            "tenant_id",
            "merchant_code",
            sa.text("created_at DESC"),
        ],
    )

    # ── 3. RLS ──
    _add_rls("ai_evidence_chains", "aec_tenant")


def downgrade() -> None:
    op.drop_table("ai_evidence_chains", if_exists=True)
