"""v168 — 桌台中心化：堂食会话关联宴席场次 + 包间结账豁免审批

新增字段：
  dining_sessions.banquet_session_id   — 关联宴席场次ID（宴席桌台组管理）
  dining_sessions.min_spend_override   — 管理员豁免低消标志（需审批记录）
  dining_sessions.min_spend_override_by — 豁免审批人ID
  dining_sessions.min_spend_override_at — 豁免审批时间

场景说明：
  - 徐记海鲜宴席：多张桌台关联同一 banquet_session_id，统一出品调度和结账
  - 包间低消豁免：经理审批后设置 min_spend_override=true，跳过 request_bill() 的低消检查

Revision ID: v168
Revises: v167
Create Date: 2026-04-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v168"
down_revision = "v167"
branch_labels= None
depends_on= None


def _col_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column})
    return result.scalar() > 0


def upgrade() -> None:
    # ── 1. dining_sessions.banquet_session_id ───────────────────────────────
    if not _col_exists("dining_sessions", "banquet_session_id"):
        op.add_column(
            "dining_sessions",
            sa.Column(
                "banquet_session_id", UUID(as_uuid=True), nullable=True,
                comment="关联宴席场次ID（v168）— 宴席多桌聚合调度和统一结账",
            ),
        )
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_dining_sessions_banquet_session_id
            ON dining_sessions (banquet_session_id)
            WHERE banquet_session_id IS NOT NULL AND is_deleted = false;
        """)

    # ── 2. 低消豁免审批字段 ─────────────────────────────────────────────────
    if not _col_exists("dining_sessions", "min_spend_override"):
        op.add_column(
            "dining_sessions",
            sa.Column(
                "min_spend_override", sa.Boolean, nullable=False,
                server_default="false",
                comment="低消豁免标志（v168）— 管理员审批后设为true，跳过买单低消校验",
            ),
        )
    if not _col_exists("dining_sessions", "min_spend_override_by"):
        op.add_column(
            "dining_sessions",
            sa.Column(
                "min_spend_override_by", UUID(as_uuid=True), nullable=True,
                comment="低消豁免审批人ID（v168）",
            ),
        )
    if not _col_exists("dining_sessions", "min_spend_override_at"):
        op.add_column(
            "dining_sessions",
            sa.Column(
                "min_spend_override_at", sa.TIMESTAMP(timezone=True), nullable=True,
                comment="低消豁免审批时间（v168）",
            ),
        )


def downgrade() -> None:
    for col in ("min_spend_override_at", "min_spend_override_by", "min_spend_override"):
        op.execute(sa.text(
            f"ALTER TABLE dining_sessions DROP COLUMN IF EXISTS {col};"
        ))
    op.execute(
        "DROP INDEX IF EXISTS ix_dining_sessions_banquet_session_id;"
    )
    op.execute(sa.text(
        "ALTER TABLE dining_sessions DROP COLUMN IF EXISTS banquet_session_id;"
    ))
