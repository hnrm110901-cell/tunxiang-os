"""v399 — 修补 v392 积分系统 3 表 UPDATE policy 缺 WITH CHECK [PG.7][SECURITY]

v392_points_system_core 创建了 3 张积分系统表（card_types / member_cards /
points_log），每张表 4 条 RLS policy（SELECT/INSERT/UPDATE/DELETE）。INSERT 用
WITH CHECK，但 UPDATE 仅用 USING（不带 WITH CHECK）。

漏洞：仅有 USING 的 UPDATE policy 只校验"我能 SELECT 哪些行"，不校验"UPDATE
后行的 tenant_id 是否仍属于我"。攻击者只要能找到任意可写 column 改 tenant_id
的路径（业务逻辑漏洞 / SQL 注入），就能把行的 tenant_id 改成其他租户 ID 实现
跨租户数据逃逸。

威胁场景（实例化）：
  租户 A 应用层调用 `UPDATE member_cards SET tenant_id='B' WHERE id=X`
  → USING-only policy 允许（A 可看 X 行）→ 行成功改属 B
  → 后续 A 跑 `SELECT * FROM member_cards` 看不到 X，B 反而看得到
  → A 的会员卡静默"逃"到 B 的租户域

修补：DROP 3 表 × UPDATE policy → CREATE WITH CHECK (tenant_id = <expr>)
保留 USING (tenant_id = <expr>) 不变（不影响读视野）。
WITH CHECK 在 UPDATE 之后校验新行的 tenant_id 必须等于当前租户 → 阻止逃逸。

CLAUDE.md §18：已应用迁移禁止修改，故不动 v392 本身，本 v399 单独承接修补。

关联：
  - PG.1 / PG.1.1: v391 INSERT policy USING-only 修补（已合并 v395 + v397）
  - 本 PR PG.7: v392 UPDATE policy USING-only 修补
  - 后续：扫余下 28 个 helper-style migrations（多数 helper 模式相同但抽样仅
    v392 命中 grep；CI guard 见独立 PR）

Revision ID: v399
Revises: v398
Create Date: 2026-05-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v399"
down_revision: Union[str, Sequence[str], None] = "v398"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::UUID"

_TABLES = ("card_types", "member_cards", "points_log")


def upgrade() -> None:
    """修补 3 表 UPDATE policy：USING-only → USING + WITH CHECK"""
    for table in _TABLES:
        policy = f"rls_{table}_update"
        # DROP 旧 USING-only policy
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        # CREATE 新 USING + WITH CHECK policy
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            f"AS PERMISSIVE FOR UPDATE TO PUBLIC "
            f"USING (tenant_id = {_RLS_EXPR}) "
            f"WITH CHECK (tenant_id = {_RLS_EXPR})"
        )


def downgrade() -> None:
    """回滚到 v392 USING-only 模式（仅用于回退测试，不建议生产执行 — 重新引入跨租户逃逸面）"""
    for table in _TABLES:
        policy = f"rls_{table}_update"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            f"AS PERMISSIVE FOR UPDATE TO PUBLIC "
            f"USING (tenant_id = {_RLS_EXPR})"
        )
