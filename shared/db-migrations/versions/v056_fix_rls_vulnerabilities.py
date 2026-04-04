"""fix RLS vulnerabilities - use correct session variable with NULL guard

Revision ID: v056
Revises: v047
Create Date: 2026-03-31

修复内容：
1. dish_practices / dish_combos（v012）：
   - 原策略：current_setting('app.tenant_id')::uuid（无 true 参数，无 NULL guard）
   - 漏洞：app.tenant_id 未设置时 current_setting 抛出异常或返回 NULL，
     空字符串强转 UUID 报错，UPDATE/DELETE 无策略，FORCE RLS 缺失
   - 修复：统一 NULLIF 安全模式 + 四操作 + FORCE ROW LEVEL SECURITY

2. ab_tests / ab_test_assignments（v032）：
   - 原策略：current_setting('app.tenant_id')::uuid（无 true 参数，无 NULL guard）
   - 漏洞：仅有 SELECT 策略（无 INSERT / UPDATE / DELETE），
     INSERT/UPDATE/DELETE 操作无 RLS 限制，完全暴露跨租户写入风险
   - 修复：添加缺失的三个操作策略 + NULLIF NULL guard + FORCE ROW LEVEL SECURITY

3. 统一升级所有仍使用旧三段条件（IS NOT NULL AND <> '' AND ...）的现存策略至
   NULLIF 简化模式，保持代码库 RLS 模式一致性：
   涉及表（均已在前序修复迁移中被修复过，此处最终统一）：
   - 来自 v006+：所有使用三段条件的表
   - 来自 v007/v008/v014/v017/v023 等修复迁移中的表

标准 RLS 模式（严格遵守）：
  正确：NULLIF(current_setting('app.tenant_id', true), '')::UUID
  错误1：current_setting('app.current_store_id', true)::UUID  — 变量名错误
  错误2：current_setting('app.tenant_id', true)::UUID  — 缺少 NULLIF，空值绕过
  错误3：current_setting('app.tenant_id', TRUE) IS NULL OR ...  — IS NULL 允许未认证

并行分支说明：
  此迁移与 v055（巡台日志）并行，均以 v047 为基础。
  分支合并后请确认 alembic heads 状态正常。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v056"
down_revision: Union[str, None] = "v047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 标准 NULLIF NULL guard 条件（单一表达式，不可绕过）
_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"

# ─────────────────────────────────────────────────────────────────────────────
# 漏洞组1：v012 表（dish_practices / dish_combos）
#   原策略名：{table}_tenant_select / insert / update / delete
#   问题：current_setting('app.tenant_id')::uuid — 无 true 参数，无 NULLIF
# ─────────────────────────────────────────────────────────────────────────────
V012_TABLES = ["dish_practices", "dish_combos"]

# ─────────────────────────────────────────────────────────────────────────────
# 漏洞组2：v032 表（ab_tests / ab_test_assignments）
#   原策略名：{table}_tenant_isolation（仅 SELECT，无 INSERT/UPDATE/DELETE）
#   问题：current_setting('app.tenant_id')::uuid — 无 true 参数，无 NULLIF，
#         且缺少 INSERT/UPDATE/DELETE 策略
# ─────────────────────────────────────────────────────────────────────────────
V032_TABLES = ["ab_tests", "ab_test_assignments"]

# ─────────────────────────────────────────────────────────────────────────────
# 升级组：所有使用旧三段条件（IS NOT NULL AND <> '' AND ...）的表，
#   统一升级为 NULLIF 模式，保持一致性。
#   这些表已有正确的四操作策略覆盖，仅需重建策略内容。
# ─────────────────────────────────────────────────────────────────────────────
LEGACY_CONDITION_TABLES = [
    # v006 修复的 v001-v005 全部表
    "customers", "stores", "dish_categories", "dishes", "dish_ingredients",
    "orders", "order_items", "ingredient_masters", "ingredients",
    "ingredient_transactions", "employees",
    "tables", "payments", "refunds", "settlements", "shift_handovers",
    "receipt_templates", "receipt_logs", "production_depts", "dish_dept_mappings",
    "daily_ops_flows", "daily_ops_nodes", "agent_decision_logs",
    "payment_records", "reconciliation_batches", "reconciliation_diffs",
    "tri_reconciliation_records", "store_daily_settlements", "payment_fees",
    "reservations", "queues", "banquet_halls", "banquet_leads",
    "banquet_orders", "banquet_contracts", "menu_packages", "banquet_checklists",
    "attendance_rules", "clock_records", "daily_attendance",
    "payroll_batches", "payroll_items", "leave_requests",
    "leave_balances", "settlement_records",
    # v007 新增表
    "bom_templates", "bom_items", "waste_events",
    "suppliers", "supply_orders", "member_transactions",
    "notifications", "notification_preferences",
    "training_courses", "training_enrollments",
    "service_feedbacks", "complaints", "tasks",
    # v008 修复的队列相关表
    "reservation_queues", "queue_tickets",
    # v014 修复的 v013 宴会表
    "banquet_proposals", "banquet_quotations", "banquet_feedbacks", "banquet_cases",
    # v017 修复的 KDS 相关表
    "kds_tasks",
    # v023 修复的 v018-v021 表
    "table_production_plans", "cook_time_baselines", "dispatch_rules", "shift_configs",
    # v024-v029 新增表
    "brand_groups", "store_brand_mappings",
    "referral_campaigns", "referral_records",
    "journey_instances", "journey_steps",
    "premium_cards", "premium_card_tiers", "premium_card_records",
    "points_mall_items", "points_exchange_records",
    "attribution_touchpoints", "attribution_conversions",
    # v038 外卖运营表
    "delivery_zones", "delivery_time_configs", "delivery_fee_rules",
    # v049 服务铃表
    "service_bell_records",
    # v054 经营诊断表
    "business_diagnoses", "diagnosis_items",
]


def _drop_all_known_policies(table: str) -> None:
    """删除该表所有已知命名模式的 RLS 策略，确保无残留冲突策略。"""
    # v001-v005 / v013 命名模式（两个策略）
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
    op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table} ON {table}")
    # v006+ / v007+ 四操作命名模式
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_select ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_insert ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_update ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_delete ON {table}")
    # v012 命名模式
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_select ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_insert ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_update ON {table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_delete ON {table}")
    # v032 命名模式（单策略）
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")


def _apply_safe_rls(table: str) -> None:
    """创建标准安全 RLS：四操作 PERMISSIVE + NULLIF NULL guard + FORCE。"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_select ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_select ON {table} "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_insert ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_insert ON {table} "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_update ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_update ON {table} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_delete ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_delete ON {table} "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )


def upgrade() -> None:
    """修复所有 RLS 漏洞，统一使用 NULLIF 安全模式。"""

    # 组1：修复 v012 漏洞（缺少 NULL guard + 四操作不完整）
    for table in V012_TABLES:
        _drop_all_known_policies(table)
        _apply_safe_rls(table)

    # 组2：修复 v032 漏洞（缺少 NULL guard + 仅有 SELECT 策略）
    for table in V032_TABLES:
        _drop_all_known_policies(table)
        _apply_safe_rls(table)

    # 组3：统一升级旧三段条件至 NULLIF 模式（幂等操作，DROP IF EXISTS 安全）
    for table in LEGACY_CONDITION_TABLES:
        _drop_all_known_policies(table)
        _apply_safe_rls(table)


def downgrade() -> None:
    """回退：恢复 v006+ 旧三段条件模式（安全但非 NULLIF 标准）。

    WARNING: v012/v032 的回退会重新引入 NULL guard 缺失漏洞。
    """
    _OLD_CONDITION = (
        "current_setting('app.tenant_id', TRUE) IS NOT NULL "
        "AND current_setting('app.tenant_id', TRUE) <> '' "
        "AND tenant_id = current_setting('app.tenant_id')::UUID"
    )

    all_tables = V012_TABLES + V032_TABLES + LEGACY_CONDITION_TABLES

    for table in all_tables:
        # 删除 NULLIF 版本策略
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}")

        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

        # 恢复旧三段条件四操作策略
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
