"""v091: 支付Saga补偿事务日志表

payment_sagas: 记录每次支付Saga的执行状态与补偿结果
  - saga_id: UUID主键
  - tenant_id: 租户隔离
  - order_id: 关联订单
  - payment_id: 关联支付记录（支付成功后填入）
  - step: 当前执行步骤 (validating/paying/completing/done/compensating/compensated/failed)
  - idempotency_key: 客户端幂等键
  - payment_amount_fen: 支付金额（分）
  - payment_method: 支付方式
  - compensation_reason: 补偿原因（step失败时填入）
  - compensated_at: 补偿完成时间
  - created_at / updated_at

设计要点：
  - step 用 VARCHAR(20)，不用枚举（便于扩展）
  - INDEX(tenant_id, order_id) 便于查某订单的Saga记录
  - RLS 启用 ENABLE + FORCE，v006+ 标准安全模式（禁止 NULL 绕过）

Revision ID: v091
Revises: v090
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v091"
down_revision = "v090"
branch_labels = None
depends_on = None

# v006+ 标准 RLS 条件（禁止 NULL 绕过）
_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        policy_name = f"{table}_{action.lower()}_tenant"
        using_clause = f"USING ({_RLS_COND})" if action != "INSERT" else ""
        check_clause = f"WITH CHECK ({_RLS_COND})" if action in ("INSERT", "UPDATE") else ""
        op.execute(
            f"CREATE POLICY {policy_name} "
            f"ON {table} FOR {action} "
            f"{using_clause} "
            f"{check_clause}"
        )


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS payment_sagas (
            saga_id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id             UUID         NOT NULL,
            order_id              UUID         NOT NULL,
            payment_id            UUID,

            step                  VARCHAR(20)  NOT NULL DEFAULT 'validating',

            idempotency_key       VARCHAR(200),

            payment_amount_fen    INTEGER      NOT NULL,
            payment_method        VARCHAR(50)  NOT NULL,

            compensation_reason   TEXT,
            compensated_at        TIMESTAMPTZ,

            created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_sagas_tenant_order "
        "ON payment_sagas(tenant_id, order_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_sagas_step "
        "ON payment_sagas(tenant_id, step)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_sagas_idempotency "
        "ON payment_sagas(tenant_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_sagas_updated "
        "ON payment_sagas(updated_at) "
        "WHERE step IN ('paying', 'completing')"
    )

    _enable_rls("payment_sagas")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payment_sagas CASCADE")
