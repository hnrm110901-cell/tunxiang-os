"""v282 — 区域定价策略实体化（pricing_policy + zone_pricing_snapshot）

将 min_consume_multiplier（单一倍率）扩展为完整定价策略 JSONB。
dining_sessions 开台时快照区域定价，防止会话中途改配置影响已开台客人。

Revision ID: v282
Revises: v281
Create Date: 2026-04-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v282b"
down_revision: Union[str, None] = "v281"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column})
    return result.scalar() > 0


def upgrade() -> None:
    # ── 1. table_zones.pricing_policy ──────────────────────────────────────
    if not _col_exists("table_zones", "pricing_policy"):
        op.add_column(
            "table_zones",
            sa.Column(
                "pricing_policy", sa.dialects.postgresql.JSONB(),
                nullable=False, server_default="{}",
                comment="区域定价策略：{room_fee_fen, room_fee_waive_threshold_fen, "
                        "service_charge_rate, time_limit_min, "
                        "overtime_charge_fen_per_30min}",
            ),
        )

    # ── 2. dining_sessions.zone_pricing_snapshot ───────────────────────────
    if not _col_exists("dining_sessions", "zone_pricing_snapshot"):
        op.add_column(
            "dining_sessions",
            sa.Column(
                "zone_pricing_snapshot", sa.dialects.postgresql.JSONB(),
                nullable=True, server_default="{}",
                comment="开台时区域定价快照（防止会话中途改配置影响已开台客人）",
            ),
        )


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE dining_sessions DROP COLUMN IF EXISTS zone_pricing_snapshot;"
    ))
    op.execute(sa.text(
        "ALTER TABLE table_zones DROP COLUMN IF EXISTS pricing_policy;"
    ))
