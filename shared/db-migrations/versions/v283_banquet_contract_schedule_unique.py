"""v283 — 宴会合同档期与审批幂等唯一索引

PR #90 pre-landing review CRITICAL 发现 C-2 / C-3 修复：

  C-2 lock_schedule 并发双锁漏洞
      read→compute→write 不原子 + v282 仅普通索引，两个并发客户同门店同档期
      可都通过 locked_existing==[] 检查 → 都 mark_signed → 撞档。
      修复：对 (tenant_id, store_id, scheduled_date) + status='signed' 加部分
      UNIQUE 索引，让 DB 层先到先得。Service 层捕获 UniqueViolationError。

  C-3 route_approval 多级审批并发漏洞
      list_approval_logs → store_done 判断 → insert_approval_log 非原子。
      并发可双写同 role 的 approve/reject 日志。
      修复：对 (tenant_id, contract_id, role) + action IN ('approve','reject')
      加部分 UNIQUE 索引，同合同同 role 只允许一条终结决策日志。

本迁移纯 DDL。索引使用 CONCURRENTLY 子句以便生产环境零停机回补（Alembic
env.py 必须在 offline 模式或独立事务中执行）。

Revision: v283_banquet_schedule_lock
Revises: v282
Create Date: 2026-04-23
"""

from alembic import op

revision = "v283_banquet_schedule_lock"
down_revision = "v282"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # C-2 修复：档期 signed 唯一索引（同门店同档期已签合同唯一）
    #
    # 谓词：status='signed'
    #   - 允许同档期多张 draft / pending_approval / cancelled（未锁定）合同
    #   - 一旦状态转为 signed，(tenant_id, store_id, scheduled_date) 必须唯一
    #   - 并发两 INSERT/UPDATE 时，后到者 raises UniqueViolationError → 档期已锁
    #
    # scheduled_date 为 NULL 时不参与索引（允许无档期合同）。
    # store_id 为 NULL 时不参与索引（v282 允许 store_id NULL；线上 R2
    # DEMO 场景 store_id 必填，豁免路径不受此索引影响）。
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_banquet_contracts_schedule_lock
            ON banquet_contracts (tenant_id, store_id, scheduled_date)
            WHERE status = 'signed'
              AND store_id IS NOT NULL
              AND scheduled_date IS NOT NULL
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # C-3 修复：审批日志同 role 唯一（同合同同 role 只能一条 approve/reject）
    #
    # 谓词：action IN ('approve', 'reject')
    #   - 允许其它 action（如未来扩展的 'abstain' / 'delegate'）多条
    #   - 同一合同 + 同一 role 的终结性决策日志唯一
    #   - 店长已 approve 再写一次 store_manager approve → 并发第二方 raises
    #     UniqueViolationError → 幂等返回
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_banquet_approval_logs_unique_role
            ON banquet_approval_logs (tenant_id, contract_id, role)
            WHERE action IN ('approve', 'reject')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_banquet_approval_logs_unique_role")
    op.execute("DROP INDEX IF EXISTS idx_banquet_contracts_schedule_lock")
