"""add customer_dish_interactions table for online recommendation learning

Revision ID: z51_customer_dish_interactions
Revises: z50_data_lineage
Create Date: 2026-03-19
"""

revision = "z51_customer_dish_interactions"
down_revision = "z50_data_lineage"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "customer_dish_interactions",
        sa.Column("id",           sa.Integer(),  primary_key=True, autoincrement=True),
        sa.Column("store_id",     sa.String(36), nullable=False, index=True),
        sa.Column("customer_id",  sa.String(64), nullable=False, index=True),
        sa.Column("dish_id",      sa.String(36), nullable=False, index=True),
        sa.Column("score",        sa.Float(),    nullable=False, comment="交互分(0-5): 点单=1,复购=2,好评=3,差评=-1"),
        sa.Column("interaction_type", sa.String(32), nullable=False, comment="order/reorder/review_pos/review_neg"),
        sa.Column("order_id",     sa.String(36), nullable=True),
        sa.Column("recorded_at",  sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_cdi_store_customer",
        "customer_dish_interactions",
        ["store_id", "customer_id"],
    )
    op.create_index(
        "ix_cdi_store_dish",
        "customer_dish_interactions",
        ["store_id", "dish_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cdi_store_dish", "customer_dish_interactions")
    op.drop_index("ix_cdi_store_customer", "customer_dish_interactions")
    op.drop_table("customer_dish_interactions")
