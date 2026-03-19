"""add signal_routing_rules table for configurable SignalBus

Revision ID: z49_signal_routing_rules
Revises: z48_store_health_index
Create Date: 2026-03-19
"""

revision = "z49_signal_routing_rules"
down_revision = "z48_store_health_index"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def upgrade() -> None:
    op.create_table(
        "signal_routing_rules",
        sa.Column("id",               sa.Integer(),    primary_key=True, autoincrement=True),
        sa.Column("condition_type",   sa.String(64),   nullable=False, index=True),
        sa.Column("condition_params", JSONB,           nullable=False, server_default="{}"),
        sa.Column("action_type",      sa.String(64),   nullable=False),
        sa.Column("action_params",    JSONB,           nullable=False, server_default="{}"),
        sa.Column("priority",         sa.Integer(),    nullable=False, server_default="100"),
        sa.Column("enabled",          sa.Boolean(),    nullable=False, server_default="true"),
        sa.Column("created_by",       sa.String(64),   nullable=True),
        sa.Column("created_at",       sa.DateTime(),   nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at",       sa.DateTime(),   nullable=False, server_default=sa.text("NOW()")),
        sa.Column("description",      sa.String(256),  nullable=True),
    )

    # 迁移原有 3 条硬编码路由为数据库规则（保留向后兼容）
    op.execute("""
        INSERT INTO signal_routing_rules
            (condition_type, condition_params, action_type, action_params, priority, enabled, description)
        VALUES
            ('review_negative',       '{"rating_threshold": 3}',     'repair_journey',  '{"journey_template": "review_repair"}', 10, true, '差评→私域修复旅程'),
            ('inventory_near_expiry', '{"statuses": ["critical","low"]}', 'waste_push', '{}',                                    20, true, '临期库存→废料预警推送'),
            ('large_table_booking',   '{"min_table_size": 6}',        'referral_engine', '{}',                                   30, true, '大桌≥6人→裂变识别')
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table("signal_routing_rules")
