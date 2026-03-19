"""add store_health_snapshots table for unified health index

Revision ID: z48_store_health_index
Revises: z47_decision_weight_learning
Create Date: 2026-03-19
"""

revision = "z48_store_health_index"
down_revision = "z47_decision_weight_learning"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "store_health_snapshots",
        sa.Column("id",                   sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id",             sa.String(36), nullable=False, index=True),
        sa.Column("snapshot_date",        sa.Date(),     nullable=False),
        sa.Column("composite_score",      sa.Float(),    nullable=False),
        sa.Column("operational_score",    sa.Float(),    nullable=True),
        sa.Column("private_domain_score", sa.Float(),    nullable=True),
        sa.Column("ai_diagnosis_score",   sa.Float(),    nullable=True),
        sa.Column("computed_at",          sa.DateTime(), nullable=False),
        sa.UniqueConstraint("store_id", "snapshot_date", name="uq_store_health_snapshot"),
    )
    op.create_index(
        "ix_store_health_snapshots_date",
        "store_health_snapshots",
        ["snapshot_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_store_health_snapshots_date", "store_health_snapshots")
    op.drop_table("store_health_snapshots")
