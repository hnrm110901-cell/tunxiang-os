"""CEO今日经营驾驶舱增强 — Sprint G6

增强 ceo_cockpit_snapshots 表（v371已创建基础版），新增字段：
  - snapshot_hour SMALLINT（小时级快照粒度）
  - delivery_commission_fen（拆分平台佣金）
  - top_dishes / loss_dishes JSONB（TOP5利润菜/亏损菜）
  - ai_decisions JSONB（AI决策卡片）
  - updated_at TIMESTAMPTZ
  - 修改唯一约束为 (tenant_id, store_id, snapshot_date, snapshot_hour)

RLS：复用 v371 已有策略，本迁移只做 ALTER TABLE。

Revision ID: v375_ceo_cockpit
Revises: v374_yield_alerts
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v375_ceo_cockpit"
down_revision: Union[str, None] = "v374_yield_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "ceo_cockpit_snapshots"


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. 新增小时级快照字段
    # ─────────────────────────────────────────────────────────────────
    op.execute(f"""
        ALTER TABLE {_TABLE}
            ADD COLUMN IF NOT EXISTS snapshot_hour SMALLINT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS delivery_commission_fen BIGINT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS top_dishes JSONB NOT NULL DEFAULT '[]'::JSONB,
            ADD COLUMN IF NOT EXISTS loss_dishes JSONB NOT NULL DEFAULT '[]'::JSONB,
            ADD COLUMN IF NOT EXISTS ai_decisions JSONB NOT NULL DEFAULT '[]'::JSONB,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    """)

    # ─────────────────────────────────────────────────────────────────
    # 2. 修改唯一约束：加入 snapshot_hour 支持小时级快照
    # ─────────────────────────────────────────────────────────────────
    op.execute(f"""
        ALTER TABLE {_TABLE}
            DROP CONSTRAINT IF EXISTS uq_ceo_cockpit_tenant_store_date
    """)
    op.execute(f"""
        ALTER TABLE {_TABLE}
            ADD CONSTRAINT uq_ceo_cockpit_tenant_store_date_hour
            UNIQUE (tenant_id, store_id, snapshot_date, snapshot_hour)
    """)

    # ─────────────────────────────────────────────────────────────────
    # 3. 小时级快照索引
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_ceo_cockpit_snapshot_hour "
        f"ON {_TABLE} (tenant_id, store_id, snapshot_date, snapshot_hour) "
        f"WHERE is_deleted = FALSE"
    )


def downgrade() -> None:
    op.execute(f"""
        ALTER TABLE {_TABLE}
            DROP CONSTRAINT IF EXISTS uq_ceo_cockpit_tenant_store_date_hour
    """)
    op.execute(f"""
        ALTER TABLE {_TABLE}
            ADD CONSTRAINT uq_ceo_cockpit_tenant_store_date
            UNIQUE (tenant_id, store_id, snapshot_date)
    """)
    op.execute(f"DROP INDEX IF EXISTS idx_ceo_cockpit_snapshot_hour")
    op.execute(f"""
        ALTER TABLE {_TABLE}
            DROP COLUMN IF EXISTS snapshot_hour,
            DROP COLUMN IF EXISTS delivery_commission_fen,
            DROP COLUMN IF EXISTS top_dishes,
            DROP COLUMN IF EXISTS loss_dishes,
            DROP COLUMN IF EXISTS ai_decisions,
            DROP COLUMN IF EXISTS updated_at
    """)
