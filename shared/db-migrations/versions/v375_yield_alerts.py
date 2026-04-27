"""损耗告警表 — 理论vs实际超标自动告警

新增 yield_alerts 表:
  - 理论用量 vs 实际用量差异
  - 班次归因（morning/afternoon/evening）
  - 告警状态机（open → acknowledged → resolved）
  - 根因分类 + 操作员关联

RLS：使用 v064+ 标准（NULLIF + FORCE ROW LEVEL SECURITY）

Revision ID: v375_yield_alerts
Revises: v374_procurement_feedback
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v375_yield_alerts"
down_revision: Union[str, None] = "v374_procurement_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ─────────────────────────────────────────────────────────────────────────────
# 安全 RLS 条件（v056+ 标准）
# ─────────────────────────────────────────────────────────────────────────────
_SAFE_CONDITION = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"
)

_TABLE = "yield_alerts"


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
    # yield_alerts — 损耗告警（理论vs实际超标）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS yield_alerts (
            id                UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID          NOT NULL,
            store_id          UUID          NOT NULL,
            alert_date        DATE          NOT NULL,
            ingredient_id     UUID          NOT NULL,
            ingredient_name   VARCHAR(100),
            theory_qty        NUMERIC(10,2) NOT NULL,
            actual_qty        NUMERIC(10,2) NOT NULL,
            variance_qty      NUMERIC(10,2) NOT NULL,
            variance_pct      NUMERIC(5,2)  NOT NULL,
            shift_id          VARCHAR(50),
            operator_ids      JSONB         DEFAULT '[]'::JSONB,
            root_cause        VARCHAR(50),
            severity          VARCHAR(20)   NOT NULL,
            status            VARCHAR(20)   NOT NULL DEFAULT 'open',
            resolved_by       UUID,
            resolved_at       TIMESTAMPTZ,
            resolution_note   TEXT,
            created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            is_deleted        BOOLEAN       NOT NULL DEFAULT FALSE
        )
    """)

    # 索引：按租户+门店+日期查询（每日告警列表）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_yield_alerts_store_date "
        "ON yield_alerts (tenant_id, store_id, alert_date DESC) "
        "WHERE is_deleted = FALSE"
    )
    # 索引：按状态过滤（待处理告警队列）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_yield_alerts_status "
        "ON yield_alerts (tenant_id, status, severity) "
        "WHERE is_deleted = FALSE AND status != 'resolved'"
    )
    # 索引：按原料查趋势（损耗趋势分析）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_yield_alerts_ingredient "
        "ON yield_alerts (tenant_id, ingredient_id, alert_date DESC) "
        "WHERE is_deleted = FALSE"
    )

    _apply_safe_rls(_TABLE)


def downgrade() -> None:
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {_TABLE}_rls_{suffix} ON {_TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {_TABLE} CASCADE")
