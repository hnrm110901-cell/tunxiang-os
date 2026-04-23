"""v270 — tasks 表幂等唯一索引（独立验证 P1-2 修复）

独立验证报告（docs/sprint-r1-independent-review.md §Q1）指出：
    v265 的 ``idx_tasks_assignee_status_due`` 建在 ``(tenant_id, assignee,
    status, due_at)``，无法覆盖 ``DATE(due_at AT TIME ZONE 'UTC')`` 函数表达式。
    因此幂等 SQL 需要全表扫描，且业务层依赖 ``asyncio.Lock`` 按租户大锁
    串行化派单 — 200 桌并发结账必然退化为单线程。

修复策略（v270，不动 v265 已应用迁移）：
    新增一个部分表达式唯一索引：
      UNIQUE (tenant_id, task_type, assignee_employee_id,
              COALESCE(customer_id, '00000000-0000-0000-0000-000000000000'::UUID),
              DATE(due_at))
      WHERE status IN ('pending', 'completed', 'escalated')
    语义：
      - 同租户/同类型/同受派人/同客户/同一天内只允许 1 条"非取消"任务
      - cancelled 任务不参与幂等约束，取消后可重新派单
      - NULL customer_id 用 ZERO UUID 作哨兵（COALESCE），避免 NULL 语义
        让同租户同员工同日多个"无客户任务"被误判为唯一
      - CONCURRENTLY：在生产不阻塞读写（v265 tasks 表可能已有数据）

表达式索引 + 部分索引是 PG 标准功能（版本 >= 10）。

并发语义：
    PgTaskRepository.create 使用 ``INSERT ... ON CONFLICT DO NOTHING RETURNING``，
    命中本索引时 RETURNING 零行，调用方落回 ``find_by_idempotency_key``
    拿出既有任务。应用层的 asyncio.Lock 随之删除。

时区注意（次生风险）：
    DATE(due_at) 使用 PostgreSQL 会话时区。生产运维必须保证所有
    tx-org 进程连接时 ``SET TIME ZONE 'UTC'``（或容器 TZ=UTC）；
    否则跨时区节点对同一 due_at 算出不同日期，索引不生效。
    当前配置：docker-compose 所有服务默认 TZ=UTC；迁移无需额外处理。

Revision: v270_tasks_idem
Revises: v267
Create Date: 2026-04-24
"""

from alembic import op

revision = "v270_tasks_idem"
down_revision = "v267"
branch_labels = None
depends_on = None


_INDEX_NAME = "idx_tasks_idempotency"
_NULL_UUID_SENTINEL = "'00000000-0000-0000-0000-000000000000'::UUID"


def upgrade() -> None:
    # CONCURRENTLY 不能在事务块内执行，需要切换到 autocommit 模式。
    # 同时 IF NOT EXISTS 保证重复部署幂等。
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME}
                ON tasks (
                    tenant_id,
                    task_type,
                    assignee_employee_id,
                    COALESCE(customer_id, {_NULL_UUID_SENTINEL}),
                    DATE(due_at)
                )
                WHERE status IN ('pending', 'completed', 'escalated')
            """
        )

    op.execute(
        f"COMMENT ON INDEX {_INDEX_NAME} IS "
        f"'幂等派单唯一约束 — 同 (tenant, task_type, assignee, customer, 当日 DATE(due_at)) "
        f"下非取消态只允许一条。独立验证 P1-2 修复（docs/sprint-r1-independent-review.md §Q1）'"
    )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")
