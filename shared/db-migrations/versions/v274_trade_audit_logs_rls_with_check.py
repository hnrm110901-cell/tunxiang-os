"""v274 — trade_audit_logs RLS WITH CHECK 修补（Tier1 §19 A4 (a)）

§19 独立验证发现 v261_trade_audit_logs RLS 策略漏洞：

  原策略（v261）：
      CREATE POLICY trade_audit_logs_tenant ON trade_audit_logs
          USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

  漏洞影响（取证证据链污染）：
    PostgreSQL Row Security 中 USING 子句默认仅约束 SELECT/UPDATE/DELETE 可见性。
    若策略未声明 WITH CHECK，则 INSERT 与 UPDATE 写入侧不受限。
    任一租户 admin（或任何能拿到 db session 的代码路径）理论上可以
    `INSERT INTO trade_audit_logs (..., tenant_id='B', ...)` 写入 B 租户的审计行，
    从而污染 B 租户的取证证据链。这与"租户 A 不能读 B 数据"的 USING 形成不对称缺口。

修补：
  - DROP 旧 POLICY（PG 不支持 ALTER POLICY 加 WITH CHECK 子句）
  - CREATE POLICY 同时声明 USING + WITH CHECK，且条件相同
  - WITH CHECK 在 INSERT/UPDATE 时校验目标行 tenant_id 必须等于当前会话
    set_config('app.tenant_id') 的值，否则 PG 返回
    "new row violates row-level security policy for table"

  注意：策略名 `trade_audit_logs_tenant_isolation`（更明确表达意图）替换 v261 的
  `trade_audit_logs_tenant`（仅在物理上换名，逻辑等价）。downgrade 还原 v261 命名。

向后兼容：
  - 现有 write_audit() 调用路径（先 set_config → 再 INSERT）天然满足 WITH CHECK
  - 新策略对合规读写零行为差异，仅"补漏"
  - 若 RLS 写入被拒，PG 抛 InternalError，不会静默成功

部署约束（CLAUDE.md §17 Tier1 + §21 灰度）：
  - DROP/CREATE POLICY 持表的 ACCESS EXCLUSIVE LOCK，但仅元数据级，毫秒级完成
  - 上线前于 DEMO 跑 RLS 写入测试（test_xujihaixian_rls_with_check_blocks_cross_tenant_insert）

Revision ID: v274
Revises: v273
Create Date: 2026-04-25
"""

import sqlalchemy as sa
from alembic import op

revision = "v274"
down_revision = "v273"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "trade_audit_logs" not in set(inspector.get_table_names()):
        # 父迁移未应用 — no-op（新环境从头初始化时 v261 会带最终策略）
        return

    # 1. DROP 旧策略（v261 仅 USING / 无 WITH CHECK）
    op.execute("DROP POLICY IF EXISTS trade_audit_logs_tenant ON trade_audit_logs;")
    # 防御：若环境上已先行手动建过新名策略，先清掉
    op.execute(
        "DROP POLICY IF EXISTS trade_audit_logs_tenant_isolation "
        "ON trade_audit_logs;"
    )

    # 2. CREATE POLICY USING + WITH CHECK 等价对称
    op.execute(
        """
        CREATE POLICY trade_audit_logs_tenant_isolation ON trade_audit_logs
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            );
        """
    )

    # 确保 RLS 仍启用（v261 启用过；防御幂等）
    op.execute("ALTER TABLE trade_audit_logs ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "trade_audit_logs" not in set(inspector.get_table_names()):
        return

    # 反向：DROP 新策略，重建 v261 仅 USING 的旧策略（保持 down 等价回滚）
    op.execute(
        "DROP POLICY IF EXISTS trade_audit_logs_tenant_isolation "
        "ON trade_audit_logs;"
    )
    op.execute(
        """
        CREATE POLICY trade_audit_logs_tenant ON trade_audit_logs
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            );
        """
    )
