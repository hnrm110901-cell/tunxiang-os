"""采购反馈日志 — 闭环学习

新增 procurement_feedback_logs 表:
  - 建议量 vs 实际采购量 vs 实际消耗量
  - 偏差率 → 修正系数（EMA 学习）
  - 天气/节假日 上下文

RLS：使用 v064+ 标准（NULLIF + FORCE ROW LEVEL SECURITY）

Revision ID: v374_procurement_feedback
Revises: v373_dish_profit_enhanced
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v374_procurement_feedback"
down_revision: Union[str, None] = "v373_dish_profit_enhanced"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ─────────────────────────────────────────────────────────────────────────────
# 安全 RLS 条件（v056+ 标准）
# ─────────────────────────────────────────────────────────────────────────────
_SAFE_CONDITION = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"
)

_TABLE = "procurement_feedback_logs"


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
    # procurement_feedback_logs — 采购反馈日志（闭环学习）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS procurement_feedback_logs (
            id                    UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id             UUID          NOT NULL,
            store_id              UUID          NOT NULL,
            ingredient_id         UUID          NOT NULL,
            feedback_date         DATE          NOT NULL,
            recommended_qty       NUMERIC(10,2) NOT NULL,
            actual_purchased_qty  NUMERIC(10,2),
            actual_consumed_qty   NUMERIC(10,2),
            waste_qty             NUMERIC(10,2) DEFAULT 0,
            deviation_pct         NUMERIC(5,2),
            weather_condition     VARCHAR(20),
            is_holiday            BOOLEAN       DEFAULT FALSE,
            holiday_name          VARCHAR(50),
            correction_factor     NUMERIC(5,3)  DEFAULT 1.0,
            created_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            is_deleted            BOOLEAN       NOT NULL DEFAULT FALSE
        )
    """)

    # 索引：按租户+原料+日期查询（修正系数计算）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_procurement_feedback_ingredient "
        "ON procurement_feedback_logs (tenant_id, ingredient_id, feedback_date DESC) "
        "WHERE is_deleted = FALSE"
    )
    # 索引：按租户+门店+日期查询（门店汇总）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_procurement_feedback_store_date "
        "ON procurement_feedback_logs (tenant_id, store_id, feedback_date DESC) "
        "WHERE is_deleted = FALSE"
    )

    _apply_safe_rls(_TABLE)


def downgrade() -> None:
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {_TABLE}_rls_{suffix} ON {_TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {_TABLE} CASCADE")
