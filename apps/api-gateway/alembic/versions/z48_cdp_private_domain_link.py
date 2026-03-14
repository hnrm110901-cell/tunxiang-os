"""CDP Sprint 2 — PrivateDomainMember 加 consumer_id + RFM 1-5 评分

- private_domain_members 加 consumer_id UUID 字段（链接 consumer_identities）
- private_domain_members 加 r_score/f_score/m_score 字段（1-5 标准化评分）

Revision ID: z48_cdp_pdm_link
Revises: z47_cdp_consumer
Create Date: 2026-03-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "z48_cdp_pdm_link"
down_revision = "z47_cdp_consumer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # consumer_id 链接到 ConsumerIdentity
    op.add_column(
        "private_domain_members",
        sa.Column("consumer_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "idx_pdm_consumer_id",
        "private_domain_members",
        ["consumer_id"],
    )

    # RFM 1-5 标准化评分
    op.add_column(
        "private_domain_members",
        sa.Column("r_score", sa.Integer, nullable=True, comment="R评分1-5"),
    )
    op.add_column(
        "private_domain_members",
        sa.Column("f_score", sa.Integer, nullable=True, comment="F评分1-5"),
    )
    op.add_column(
        "private_domain_members",
        sa.Column("m_score", sa.Integer, nullable=True, comment="M评分1-5"),
    )


def downgrade() -> None:
    op.drop_column("private_domain_members", "m_score")
    op.drop_column("private_domain_members", "f_score")
    op.drop_column("private_domain_members", "r_score")
    op.drop_index("idx_pdm_consumer_id", "private_domain_members")
    op.drop_column("private_domain_members", "consumer_id")
