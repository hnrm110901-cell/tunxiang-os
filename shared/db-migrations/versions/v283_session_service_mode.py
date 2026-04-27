"""v283 — dining_sessions 继承区域服务模式

开台时从 table_zones.service_mode 写入 dining_sessions.service_mode。
retail 模式不创建 dining_session（直接创建零售订单）。

Revision ID: v283
Revises: v282
Create Date: 2026-04-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v283"
down_revision: Union[str, None] = "v282"
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
    # ── 1. dining_sessions.service_mode ────────────────────────────────────
    if not _col_exists("dining_sessions", "service_mode"):
        op.add_column(
            "dining_sessions",
            sa.Column(
                "service_mode", sa.String(20), nullable=False,
                server_default="dine_first",
                comment="服务模式（开台时继承自 table_zones.service_mode）",
            ),
        )

    # ── 2. 部分索引：活跃会话按门店+服务模式查询 ───────────────────────────
    op.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_ds_service_mode
        ON dining_sessions (store_id, service_mode)
        WHERE status NOT IN ('paid', 'clearing', 'disabled');
    """))

    # ── 3. 用已有 pay_mode 回填 service_mode ──────────────────────────────
    op.execute(sa.text("""
        UPDATE dining_sessions
        SET service_mode = CASE
            WHEN pay_mode = 'prepay' THEN 'scan_and_pay'
            ELSE 'dine_first'
        END
        WHERE service_mode = 'dine_first';
    """))


def downgrade() -> None:
    op.execute(sa.text(
        "DROP INDEX IF EXISTS idx_ds_service_mode;"
    ))
    op.execute(sa.text(
        "ALTER TABLE dining_sessions DROP COLUMN IF EXISTS service_mode;"
    ))
