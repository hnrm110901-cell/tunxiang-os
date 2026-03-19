"""add decision_weight_configs table for online weight learning

Revision ID: z47_decision_weight_learning
Revises: z46_merge_edge_and_fct_heads
Create Date: 2026-03-19
"""

revision = "z47_decision_weight_learning"
down_revision = "z46_merge_edge_and_fct_heads"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def upgrade() -> None:
    op.create_table(
        "decision_weight_configs",
        sa.Column("id",             sa.String(64),  primary_key=True,  comment="scope: global | store:{store_id}"),
        sa.Column("w_financial",    sa.Float(),     nullable=False, server_default="0.40"),
        sa.Column("w_urgency",      sa.Float(),     nullable=False, server_default="0.30"),
        sa.Column("w_confidence",   sa.Float(),     nullable=False, server_default="0.20"),
        sa.Column("w_execution",    sa.Float(),     nullable=False, server_default="0.10"),
        sa.Column("sample_count",   sa.Integer(),   nullable=False, server_default="0"),
        sa.Column("last_updated",   sa.DateTime(),  nullable=True),
        sa.Column("update_history", JSONB,          nullable=False, server_default="[]"),
    )
    # 插入全局默认行（系统初始状态）
    op.execute("""
        INSERT INTO decision_weight_configs
            (id, w_financial, w_urgency, w_confidence, w_execution, sample_count, update_history)
        VALUES
            ('global', 0.40, 0.30, 0.20, 0.10, 0, '[]'::jsonb)
        ON CONFLICT (id) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table("decision_weight_configs")
