"""v400 — 批量修补 13 表 UPDATE policy 缺 WITH CHECK [PG.7][SECURITY][Tier1]

继 v399 修补 v392 积分系统 3 表后，本 v400 继续清理同类 RLS 漏洞：
6 个 migration 中 13 张表的 UPDATE policy 仅有 USING 而无 WITH CHECK，
存在跨租户写入逃逸面（详见 v399 docstring 漏洞模型）。

涉及的 migration（按 PG.7 audit 命中）：
  - v065_patrol_inspection: patrol_templates / patrol_template_items / patrol_records
                             / patrol_record_items / patrol_issues (5)
  - v072_mfa_auth:           users (1)
  - v073_rbac_roles:         user_roles (1)
  - v076_role_permission_levels: employee_role_assignments (1)
  - v284_payment_nexus:      payment_channel_configs / payment_sagas / payment_idempotency (3)
  - v386_subsidy_programs:   tenant_subsidies / subsidy_bills (2)
  共 6 文件 / 13 张表

修补策略：DROP + CREATE 每张表 UPDATE policy，加 WITH CHECK <原 USING 表达式>。
保留 USING 不变（不影响读视野）。各表原始 USING 表达式不完全一致（v072/v073/v076
用 NULLIF 形式，v284 用三段 AND 形式，v386 用裸 ::UUID 形式），WITH CHECK 沿用
对应原表达式以保留语义。

威胁场景（针对 payment 域尤为关键）：
  租户 A 应用层调用 `UPDATE payment_idempotency SET tenant_id='B' WHERE ...`
  → USING-only 允许 → 行成功改属 B → A 的支付幂等键脱离视野，B 反而能 SELECT
  → 后续相同 idempotency_key 被 B 误判已用 / A 误判未用 → 双扣费风险

CLAUDE.md §18：不修改 v065/v072/v073/v076/v284/v386 本身。down_revision = v399。

Revision ID: v400
Revises: v399
Create Date: 2026-05-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v400"
down_revision: Union[str, Sequence[str], None] = "v399"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 各表的 USING / WITH CHECK 表达式 — 与原 migration 保持一致
_NULLIF_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"

_PAYMENT_NEXUS_EXPR = (
    "tenant_id = current_setting('app.tenant_id', TRUE)::UUID "
    "AND current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> ''"
)

_SUBSIDY_EXPR = "tenant_id = current_setting('app.tenant_id')::uuid"

# (table_name, policy_name, expr)
_TARGETS = [
    # v065 patrol_inspection
    ("patrol_templates", "patrol_templates_update", _NULLIF_EXPR),
    ("patrol_template_items", "patrol_template_items_update", _NULLIF_EXPR),
    ("patrol_records", "patrol_records_update", _NULLIF_EXPR),
    ("patrol_record_items", "patrol_record_items_update", _NULLIF_EXPR),
    ("patrol_issues", "patrol_issues_update", _NULLIF_EXPR),
    # v072 mfa_auth
    ("users", "users_update", _NULLIF_EXPR),
    # v073 rbac_roles
    ("user_roles", "user_roles_update", _NULLIF_EXPR),
    # v076 role_permission_levels
    ("employee_role_assignments", "era_update", _NULLIF_EXPR),
    # v284 payment_nexus（金额安全敏感 — 双扣费风险）
    ("payment_channel_configs", "pcc_update", _PAYMENT_NEXUS_EXPR),
    ("payment_sagas", "ps_update", _PAYMENT_NEXUS_EXPR),
    ("payment_idempotency", "pi_update", _PAYMENT_NEXUS_EXPR),
    # v386 subsidy_programs
    ("tenant_subsidies", "tenant_subsidies_update", _SUBSIDY_EXPR),
    ("subsidy_bills", "subsidy_bills_update", _SUBSIDY_EXPR),
]


def upgrade() -> None:
    """13 表 UPDATE policy：USING-only → USING + WITH CHECK"""
    for table, policy, expr in _TARGETS:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            f"FOR UPDATE "
            f"USING ({expr}) "
            f"WITH CHECK ({expr})"
        )


def downgrade() -> None:
    """回退到 USING-only 模式 — 仅供回退测试，不建议生产执行（重新引入跨租户逃逸面）"""
    for table, policy, expr in _TARGETS:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            f"FOR UPDATE "
            f"USING ({expr})"
        )
