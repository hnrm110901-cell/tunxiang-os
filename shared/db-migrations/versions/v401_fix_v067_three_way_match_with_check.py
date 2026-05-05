"""v401 — 修补 v067 三单匹配 helper 创建的 2 表 UPDATE policy 缺 WITH CHECK [PG.7][SECURITY][Tier1]

v067_three_way_match.py 内部 helper `_create_rls(table)` 为
`purchase_invoices` / `purchase_match_records` 两张表创建 4 条 RLS policy。
其中 INSERT 用 WITH CHECK（line 39），但 UPDATE 仅用 USING（line 43）：

    CREATE POLICY {table}_update ON {table} FOR UPDATE USING ({_SAFE_CONDITION})

漏洞同 v399 头部注释：仅 USING 校验"我能 SELECT 哪些行"，不校验 UPDATE 后行的
tenant_id 是否仍属于我；攻击者若能写入 tenant_id 列即可跨租户逃逸。

修补：DROP 2 表 × UPDATE policy → CREATE WITH CHECK + USING 双校验。

CLAUDE.md §18：已应用迁移禁止修改，故不动 v067 本身，本 v401 单独承接修补。
关联：
  - PG.7 v399 (in main): 积分系统 3 表
  - PG.7 v400 (PR #187):  patrol/payment/subsidy/users 13 表
  - 本 v401:              v067 helper 涉及 2 表

按 docs/security/pg7-rls-update-policy-residual.md，main 上还有 13 处其它历史
违规（v020/v052/v053/v055/v068/v069/v151）未在本 PR 范围。

Revision ID: v401
Revises: v400
Create Date: 2026-05-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v401"
down_revision: Union[str, Sequence[str], None] = "v400"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 与 v067 _SAFE_CONDITION 完全等价（v067 line 23-27），保持表达式一致避免行为漂移
_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id', TRUE)::UUID"
)

_TABLES = ("purchase_invoices", "purchase_match_records")


def upgrade() -> None:
    """修补 2 表 UPDATE policy：USING-only → USING + WITH CHECK"""
    for table in _TABLES:
        policy = f"{table}_update"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            f"FOR UPDATE USING ({_SAFE_CONDITION}) "
            f"WITH CHECK ({_SAFE_CONDITION})"
        )


def downgrade() -> None:
    """回退到 v067 USING-only 模式 — 仅用于回退测试，不建议生产执行（重新引入跨租户逃逸面）"""
    for table in _TABLES:
        policy = f"{table}_update"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            f"FOR UPDATE USING ({_SAFE_CONDITION})"
        )
