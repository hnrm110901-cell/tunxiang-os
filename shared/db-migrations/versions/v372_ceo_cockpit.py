"""CEO今日经营驾驶舱 — 快照表

新增 1 张表 ceo_cockpit_snapshots：
  - 时段P&L（午市/晚市/闲时独立核算）
  - 外卖真实利润（扣除佣金/包装/补贴/人力）
  - 月度进度（目标vs实际）
  - 异常标记 + 决策卡片（JSONB）

RLS：使用 v064+ 标准（NULLIF + FORCE ROW LEVEL SECURITY）

Revision ID: v372_ceo_cockpit
Revises: v371_hotfix_rls_partitions_seq
Create Date: 2026-04-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v372_ceo_cockpit"
down_revision: Union[str, None] = "v371_hotfix_rls_partitions_seq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ─────────────────────────────────────────────────────────────────────────────
# 安全 RLS 条件（v056+ 标准）
# ─────────────────────────────────────────────────────────────────────────────
_SAFE_CONDITION = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"
)

_TABLE = "ceo_cockpit_snapshots"


def _apply_safe_rls(table: str) -> None:
    """4 操作 PERMISSIVE + NULLIF NULL-guard + FORCE。"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for action, clause in [
        ("SELECT", f"FOR SELECT USING ({_SAFE_CONDITION})"),
        ("INSERT", f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"),
        ("UPDATE", f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"),
        ("DELETE", f"FOR DELETE USING ({_SAFE_CONDITION})"),
    ]:
        policy_name = f"{table}_rls_{action.lower()}"
        op.execute(f"DROP POLICY IF EXISTS {policy_name} ON {table}")
        op.execute(f"CREATE POLICY {policy_name} ON {table} {clause}")


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. ceo_cockpit_snapshots — CEO 驾驶舱每日快照
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS ceo_cockpit_snapshots (
            id                        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                 UUID         NOT NULL,
            store_id                  UUID         NOT NULL,
            snapshot_date             DATE         NOT NULL,

            -- 时段P&L
            lunch_revenue_fen         BIGINT       NOT NULL DEFAULT 0,
            lunch_cost_fen            BIGINT       NOT NULL DEFAULT 0,
            lunch_profit_fen          BIGINT       NOT NULL DEFAULT 0,
            dinner_revenue_fen        BIGINT       NOT NULL DEFAULT 0,
            dinner_cost_fen           BIGINT       NOT NULL DEFAULT 0,
            dinner_profit_fen         BIGINT       NOT NULL DEFAULT 0,
            off_peak_revenue_fen      BIGINT       NOT NULL DEFAULT 0,
            off_peak_cost_fen         BIGINT       NOT NULL DEFAULT 0,
            off_peak_profit_fen       BIGINT       NOT NULL DEFAULT 0,

            -- 外卖真实利润
            delivery_revenue_fen      BIGINT       NOT NULL DEFAULT 0,
            delivery_platform_fee_fen BIGINT       NOT NULL DEFAULT 0,
            delivery_packaging_fen    BIGINT       NOT NULL DEFAULT 0,
            delivery_subsidy_fen      BIGINT       NOT NULL DEFAULT 0,
            delivery_extra_labor_fen  BIGINT       NOT NULL DEFAULT 0,
            delivery_real_profit_fen  BIGINT       NOT NULL DEFAULT 0,

            -- 汇总
            total_revenue_fen         BIGINT       NOT NULL DEFAULT 0,
            total_cost_fen            BIGINT       NOT NULL DEFAULT 0,
            total_profit_fen          BIGINT       NOT NULL DEFAULT 0,
            customer_count            INTEGER      NOT NULL DEFAULT 0,
            turnover_rate             NUMERIC(5,2) NOT NULL DEFAULT 0,

            -- 月度进度
            month_target_fen          BIGINT       NOT NULL DEFAULT 0,
            month_actual_fen          BIGINT       NOT NULL DEFAULT 0,
            month_progress_pct        NUMERIC(5,2) NOT NULL DEFAULT 0,

            -- 异常标记
            anomalies                 JSONB        NOT NULL DEFAULT '[]'::JSONB,

            -- 决策卡片
            decision_cards            JSONB        NOT NULL DEFAULT '[]'::JSONB,

            created_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted                BOOLEAN      NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_ceo_cockpit_tenant_store_date
                UNIQUE (tenant_id, store_id, snapshot_date)
        )
    """)

    # 索引：按租户+日期查询（驾驶舱首页）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ceo_cockpit_tenant_date "
        "ON ceo_cockpit_snapshots (tenant_id, snapshot_date DESC) "
        "WHERE is_deleted = FALSE"
    )
    # 索引：按租户+门店+日期范围查询（月度趋势）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ceo_cockpit_tenant_store_date "
        "ON ceo_cockpit_snapshots (tenant_id, store_id, snapshot_date DESC) "
        "WHERE is_deleted = FALSE"
    )

    _apply_safe_rls(_TABLE)


def downgrade() -> None:
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {_TABLE}_rls_{suffix} ON {_TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {_TABLE} CASCADE")
