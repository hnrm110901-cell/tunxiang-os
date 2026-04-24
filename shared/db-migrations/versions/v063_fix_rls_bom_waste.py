"""修复 bom_templates / bom_items / waste_events 的 RLS 策略

Revision ID: v063
Revises: v056
Create Date: 2026-03-31

漏洞说明（参见 MEMORY: project_rls_vulnerability.md）：
  bom_templates、bom_items、waste_events 三张表的 RLS 策略使用了
  错误的 session 变量（app.current_store_id 或 app.current_tenant），
  而应用代码统一设置的是 app.tenant_id（见 CLAUDE.md 安全约束）。
  导致这三张表的 RLS 实际永远不生效，存在租户数据越权风险。

修复内容：
  1. DROP 旧策略（兼容所有已知命名模式）
  2. 以标准 NULLIF 安全模式重建四操作策略（SELECT/INSERT/UPDATE/DELETE）
  3. 确保 FORCE ROW LEVEL SECURITY 已设置

标准 RLS 模式（v056+ 规范）：
  正确：tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
  错误1：current_setting('app.current_store_id', true)  — 变量名错误
  错误2：current_setting('app.current_tenant', true)    — 变量名错误
  错误3：current_setting('app.tenant_id', true)::UUID   — 缺少 NULLIF，空值可绕过

并行分支说明：
  此迁移以 v056（fix_rls_vulnerabilities）为基础，修复 v056 未涵盖的
  变量名问题（v056 已修复三段条件统一为 NULLIF，但若原策略变量名完全不同
  则 DROP IF EXISTS 幂等操作已确保本次重建生效）。
"""
from typing import Sequence, Union

from alembic import op

revision = "v063"
down_revision= "v056"
branch_labels= None
depends_on= None

# 标准 NULLIF NULL guard 条件（v056+ 唯一正确模式）
_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"

# 本次修复的三张表
TARGET_TABLES = ["bom_templates", "bom_items", "waste_events"]


def _drop_all_known_policies(table: str) -> None:
    """删除该表所有已知命名模式的 RLS 策略，确保无残留冲突策略。

    兼容以下历史命名模式（包括错误变量名遗留策略）：
      - v001-v005 / v013 模式：tenant_isolation_{table} / tenant_insert_{table}
      - v006+ 四操作模式：{table}_rls_{select,insert,update,delete}
      - v012 模式：{table}_tenant_{select,insert,update,delete}
      - v032 单策略模式：{table}_tenant_isolation
      - 可能存在的旧漏洞策略（使用错误变量名但保持了命名规范）
    """
    # v001-v005 / v013 命名模式
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
    op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table} ON {table}")
    # v006+ 四操作命名模式
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_select ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_insert ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_update ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_delete ON {table}")
    # v012 命名模式
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_select ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_insert ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_update ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_delete ON {table}")
    # v032 单策略模式
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")


def _apply_safe_rls(table: str) -> None:
    """创建标准安全 RLS：四操作 PERMISSIVE + NULLIF NULL guard + FORCE ROW LEVEL SECURITY。"""
    op.execute(
        f"CREATE POLICY {table}_rls_select ON {table} "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table}_rls_insert ON {table} "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table}_rls_update ON {table} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {table}_rls_delete ON {table} "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    """修复 bom_templates / bom_items / waste_events 的 RLS 策略。

    将错误的 app.current_store_id / app.current_tenant 统一替换为
    项目标准 app.tenant_id，并升级为 NULLIF 安全模式。
    """
    for table in TARGET_TABLES:
        _drop_all_known_policies(table)
        _apply_safe_rls(table)


def downgrade() -> None:
    """回退：恢复 v056 NULLIF 模式（变量名已正确，仅重建策略）。

    注意：此回退不会重新引入错误变量名，而是回到 v056 状态。
    downgrade 到 v056 以前需运行 v056 的 downgrade。
    """
    _OLD_CONDITION = (
        "current_setting('app.tenant_id', TRUE) IS NOT NULL "
        "AND current_setting('app.tenant_id', TRUE) <> '' "
        "AND tenant_id = current_setting('app.tenant_id')::UUID"
    )

    for table in TARGET_TABLES:
        # 删除 v063 NULLIF 版本策略
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}")

        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

        # 恢复 v056 前的旧三段条件四操作策略（安全但非 NULLIF 标准）
        op.execute(
            f"CREATE POLICY {table}_rls_select ON {table} "
            f"FOR SELECT USING ({_OLD_CONDITION})"
        )
        op.execute(
            f"CREATE POLICY {table}_rls_insert ON {table} "
            f"FOR INSERT WITH CHECK ({_OLD_CONDITION})"
        )
        op.execute(
            f"CREATE POLICY {table}_rls_update ON {table} "
            f"FOR UPDATE USING ({_OLD_CONDITION}) WITH CHECK ({_OLD_CONDITION})"
        )
        op.execute(
            f"CREATE POLICY {table}_rls_delete ON {table} "
            f"FOR DELETE USING ({_OLD_CONDITION})"
        )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
