"""v402 — 修补 PG.7 余下 14 表 UPDATE policy 缺 WITH CHECK [SECURITY][Tier1]

PR #186 lint 工具发现 main 上 v399/v400/v401 范围外还有 14 张历史表的 UPDATE
policy 仅 USING 缺 WITH CHECK。本 v402 一次性补齐。

按 docs/security/pg7-rls-update-policy-residual.md 路径 A（一次性补一刀）。

不同源 migration 用了 3 种不同 USING 表达式，**保持原表达式**避免行为漂移。

──────────────────── 形态 1 (NULLIF + ::UUID) ────────────────────
来源：v020_dispatch_rules / v068_ontology_snapshots / v069_open_api_platform
  - dispatch_rules        → policy dispatch_rules_update
  - ontology_snapshots    → policy onto_snap_update
  - api_applications      → policy api_apps_update
  - api_access_tokens     → policy api_tokens_update
  - api_request_logs      → policy api_logs_update
  - api_webhooks          → policy api_webhooks_update

──────────────────── 形态 2 (3-clause AND) ─────────────────────
来源：v052_allergen_management / v053_supply_chain_mobile / v055_patrol_logs
  - dish_allergens        → policy dish_allergens_update
  - receiving_orders      → policy receiving_orders_update
  - stocktake_sessions    → policy stocktake_sessions_update
  - patrol_logs           → policy patrol_logs_update

──────────────────── 形态 3 (text-cast 比较) ───────────────────
来源：v151_crew_schedule_tables
  - crew_schedules        → policy crew_schedules_update
  - crew_checkin_records  → policy crew_checkin_records_update
  - crew_shift_swaps      → policy crew_shift_swaps_update
  - crew_shift_summaries  → policy crew_shift_summaries_update

CLAUDE.md §18：不修改原 migration，本 v402 单独承接修补。

链路：v397 → v398 → v399 → v400 → v401 → **v402**

Revision ID: v402
Revises: v401
Create Date: 2026-05-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v402"
down_revision: Union[str, Sequence[str], None] = "v401"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ───────────────── USING 表达式（3 种，与原 migration 完全等价） ─────────────
_EXPR_NULLIF_UUID = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"
)

_EXPR_3CLAUSE = (
    "tenant_id = current_setting('app.tenant_id', TRUE)::UUID "
    "AND current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> ''"
)

_EXPR_TEXT_CAST = (
    "tenant_id IS NOT NULL "
    "AND tenant_id::text = current_setting('app.tenant_id', true)"
)


# ───────────────── (table, policy_name) 三组分类 ─────────────────────────
_NULLIF_TABLES = (
    ("dispatch_rules", "dispatch_rules_update"),
    ("ontology_snapshots", "onto_snap_update"),
    ("api_applications", "api_apps_update"),
    ("api_access_tokens", "api_tokens_update"),
    ("api_request_logs", "api_logs_update"),
    ("api_webhooks", "api_webhooks_update"),
)

_3CLAUSE_TABLES = (
    ("dish_allergens", "dish_allergens_update"),
    ("receiving_orders", "receiving_orders_update"),
    ("stocktake_sessions", "stocktake_sessions_update"),
    ("patrol_logs", "patrol_logs_update"),
)

_TEXT_CAST_TABLES = (
    ("crew_schedules", "crew_schedules_update"),
    ("crew_checkin_records", "crew_checkin_records_update"),
    ("crew_shift_swaps", "crew_shift_swaps_update"),
    ("crew_shift_summaries", "crew_shift_summaries_update"),
)


def _replace_update_policy(table: str, policy: str, expr: str, with_check: bool) -> None:
    """DROP+CREATE UPDATE policy；with_check=True 加 WITH CHECK 等价表达式。"""
    op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    if with_check:
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            f"FOR UPDATE USING ({expr}) WITH CHECK ({expr})"
        )
    else:
        op.execute(
            f"CREATE POLICY {policy} ON {table} FOR UPDATE USING ({expr})"
        )


def upgrade() -> None:
    """补 14 表 UPDATE policy: USING-only → USING + WITH CHECK"""
    for table, policy in _NULLIF_TABLES:
        _replace_update_policy(table, policy, _EXPR_NULLIF_UUID, with_check=True)
    for table, policy in _3CLAUSE_TABLES:
        _replace_update_policy(table, policy, _EXPR_3CLAUSE, with_check=True)
    for table, policy in _TEXT_CAST_TABLES:
        _replace_update_policy(table, policy, _EXPR_TEXT_CAST, with_check=True)


def downgrade() -> None:
    """回退到 USING-only 模式 — 仅用于回退测试，不建议生产执行（重新引入跨租户逃逸面）"""
    for table, policy in _NULLIF_TABLES:
        _replace_update_policy(table, policy, _EXPR_NULLIF_UUID, with_check=False)
    for table, policy in _3CLAUSE_TABLES:
        _replace_update_policy(table, policy, _EXPR_3CLAUSE, with_check=False)
    for table, policy in _TEXT_CAST_TABLES:
        _replace_update_policy(table, policy, _EXPR_TEXT_CAST, with_check=False)
