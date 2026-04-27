"""v167 — 桌台中心化：KDS任务 + 活鲜称重记录关联堂食会话

新增字段：
  kds_tasks.dining_session_id             — 堂食会话ID，finish_cooking后回调record_dish_served
  live_seafood_weigh_records.dining_session_id — 堂食会话ID，支持活鲜称重按会话聚合与AA分摊

Revision ID: v167
Revises: v166
Create Date: 2026-04-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v167"
down_revision = "v166"
branch_labels = None
depends_on = None


def _col_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text("SELECT COUNT(*) FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column},
    )
    return result.scalar() > 0


def upgrade() -> None:
    # ── 1. kds_tasks.dining_session_id ──────────────────────────────────────
    if not _col_exists("kds_tasks", "dining_session_id"):
        op.add_column(
            "kds_tasks",
            sa.Column(
                "dining_session_id",
                UUID(as_uuid=True),
                nullable=True,
                comment="关联堂食会话ID（v167）— finish_cooking后回调record_dish_served",
            ),
        )
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_kds_tasks_dining_session_id
            ON kds_tasks (dining_session_id)
            WHERE dining_session_id IS NOT NULL AND is_deleted = false;
        """)

    # ── 2. live_seafood_weigh_records.dining_session_id ─────────────────────
    if not _col_exists("live_seafood_weigh_records", "dining_session_id"):
        op.add_column(
            "live_seafood_weigh_records",
            sa.Column(
                "dining_session_id",
                UUID(as_uuid=True),
                nullable=True,
                comment="关联堂食会话ID（v167）— 支持活鲜称重按会话聚合，AA分摊时定位人均",
            ),
        )
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_live_seafood_weigh_records_session_id
            ON live_seafood_weigh_records (dining_session_id)
            WHERE dining_session_id IS NOT NULL;
        """)

    # ── 3. 回填：从 orders.dining_session_id 推导 kds_tasks.dining_session_id ──
    # 通过 kds_tasks.order_id → orders.dining_session_id 反向填充
    op.execute("""
        UPDATE kds_tasks kt
        SET dining_session_id = o.dining_session_id
        FROM orders o
        WHERE kt.order_id = o.id
          AND o.dining_session_id IS NOT NULL
          AND kt.dining_session_id IS NULL
          AND kt.is_deleted = false;
    """)

    # ── 4. 回填：从 orders.dining_session_id 推导 live_seafood_weigh_records ──
    op.execute("""
        UPDATE live_seafood_weigh_records lswr
        SET dining_session_id = o.dining_session_id
        FROM orders o
        WHERE lswr.order_id = o.id
          AND o.dining_session_id IS NOT NULL
          AND lswr.dining_session_id IS NULL;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_live_seafood_weigh_records_session_id;")
    op.execute(sa.text("ALTER TABLE live_seafood_weigh_records DROP COLUMN IF EXISTS dining_session_id;"))

    op.execute("DROP INDEX IF EXISTS ix_kds_tasks_dining_session_id;")
    op.execute(sa.text("ALTER TABLE kds_tasks DROP COLUMN IF EXISTS dining_session_id;"))
