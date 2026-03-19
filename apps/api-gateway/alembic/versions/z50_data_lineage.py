"""add data_lineage table for computation traceability

Revision ID: z50_data_lineage
Revises: z49_signal_routing_rules
Create Date: 2026-03-19
"""

revision = "z50_data_lineage"
down_revision = "z49_signal_routing_rules"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def upgrade() -> None:
    op.create_table(
        "data_lineage",
        sa.Column("id",             sa.Integer(),    primary_key=True, autoincrement=True),
        sa.Column("transform_id",   sa.String(32),   nullable=False, unique=True, index=True),
        sa.Column("step_name",      sa.String(128),  nullable=False, index=True),
        sa.Column("store_id",       sa.String(36),   nullable=False, index=True),
        sa.Column("output_id",      sa.String(256),  nullable=False, index=True),
        sa.Column("parent_ids",     JSONB,           nullable=False, server_default="[]"),
        sa.Column("input_summary",  JSONB,           nullable=False, server_default="{}"),
        sa.Column("meta",           JSONB,           nullable=False, server_default="{}"),
        sa.Column("recorded_at",    sa.DateTime(),   nullable=False),
    )
    op.create_index(
        "ix_data_lineage_output_id",
        "data_lineage",
        ["output_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_data_lineage_output_id", "data_lineage")
    op.drop_table("data_lineage")
