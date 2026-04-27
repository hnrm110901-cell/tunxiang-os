"""v272 — orders KDS delta 增量轮询复合索引（Tier1 零容忍）

§19 独立验证发现：C3 KDS `/orders/delta` 路由 SQL
    WHERE tenant_id = ? AND store_id = ? AND updated_at > ?
在百万级 orders 表上无对应复合索引，真 PG 上 P99 必然 > 200ms，
违反 §22 DEMO 验收门槛（200 桌并发 P99 < 200ms）。

本迁移：
  - 新建复合索引 ix_orders_kds_delta(tenant_id, store_id, updated_at)
  - 部分索引 WHERE is_deleted IS NOT TRUE（节省空间，软删订单不参与 KDS 出餐）
  - 必须 CREATE INDEX CONCURRENTLY，避免在生产 orders 大表上长时间锁表
  - CONCURRENTLY 不能在事务内执行 → 用 op.get_context().autocommit_block() 包裹

部署约束（CLAUDE.md §17 Tier1 + §21 灰度）：
  - 本文件不在 CI 自动 alembic upgrade 链路中执行 CONCURRENTLY 部分
  - 生产由 DBA 在低峰期独立审核执行
  - DEV/DEMO 环境可由 alembic upgrade head 直接应用（小表无锁压力）

# alembic_version 必须自动提交（CONCURRENTLY 不能在显式事务内）

Revision ID: v272
Revises: v271
Create Date: 2026-04-25
"""

from alembic import op

revision = "v272"
down_revision = "v271"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_orders_kds_delta "
            "ON orders(tenant_id, store_id, updated_at) "
            "WHERE is_deleted IS NOT TRUE"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_orders_kds_delta")
