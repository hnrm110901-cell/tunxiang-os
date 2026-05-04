"""v384 — 补齐剩余 RLS 技术债（29 张裸表 + ~344 张缺 FORCE RLS 的表）

CLAUDE.md § 13 禁止事项：禁止跳过 RLS — 所有 DB 操作必须带 tenant_id。
CLAUDE.md § 17 Tier 1：RLS 多租户隔离是硬约束。

check_rls_policies.py 发现两处 RLS 技术债：

  Part 1 — 29 张业务表历史遗留，完全没有 RLS（无 ENABLE、无 POLICY）。
    这些表均含 tenant_id 列，可安全补启用。
    使用 CLAUDE.md RLS 标准模板：
      · ENABLE ROW LEVEL SECURITY
      · FORCE ROW LEVEL SECURITY
      · 单 POLICY（FOR ALL）覆盖 SELECT/INSERT/UPDATE/DELETE
      · USING + WITH CHECK 用 current_setting('app.tenant_id', true) 对比

  Part 2 — ~344 张表已启用 RLS 但缺 FORCE ROW LEVEL SECURITY，
    导致表 owner（应用层连接用户）可绕过所有 RLS 策略。
    用 pg_class 动态查询补 FORCE RLS。

Part 2 排除的跨租户表：
  · events / events_*（事件溯源全局表，按 tenant_id 查询非隔离）
  · projector_*（投影器检查点，跨租户）
  · alembic_version（系统表）

Revision ID: v384_fill_rls_remaining_debt
Revises: v383_chain_consolidation
Create Date: 2026-05-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v384_fill_rls_remaining_debt"
down_revision: Union[str, Sequence[str], None] = "v383_chain_consolidation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 29 张待补表（check_rls_policies.py DB 扫描发现缺全部 RLS）
# (schema, table) 元组，所有表均在 public schema
TABLES_29: tuple[tuple[str, str], ...] = (
    ("public", "banquet_approval_logs"),
    ("public", "banquet_eo_tickets"),
    ("public", "bonus_rules"),
    ("public", "ceo_cockpit_snapshots"),
    ("public", "conversion_funnel_daily"),
    ("public", "customer_journey_timings"),
    ("public", "daily_scorecards"),
    ("public", "delivery_temperature_logs"),
    ("public", "delivery_temperature_logs_default"),
    ("public", "dish_co_occurrence"),
    ("public", "dynamic_pricing_logs"),
    ("public", "dynamic_pricing_rules"),
    ("public", "ingredient_location_bindings"),
    ("public", "inventory_by_location"),
    ("public", "invoice_ocr_results"),
    ("public", "procurement_feedback_logs"),
    ("public", "satisfaction_ratings"),
    ("public", "stocktake_loss_approvals"),
    ("public", "stocktake_loss_case_no_seq"),
    ("public", "stocktake_loss_cases"),
    ("public", "stocktake_loss_items"),
    ("public", "stocktake_loss_writeoffs"),
    ("public", "store_lifecycle_stages"),
    ("public", "stored_value_split_ledger"),
    ("public", "stored_value_split_rules"),
    ("public", "sv_settlement_batches"),
    ("public", "warehouse_locations"),
    ("public", "warehouse_zones"),
    ("public", "yield_alerts"),
)


# 跨租户 / 系统表名列表（Part 2 FORCE RLS 排除这些表）
# 这些表可能已启用 ENABLE RLS 但不应加 FORCE，因为它们是跨租户共享的
_SYSTEM_TABLES_EXCLUDED_FROM_FORCE: tuple[str, ...] = (
    "alembic_version",
    "events",
    "events_default",
    "projector_checkpoints",
    "projector_rebuild_locks",
)


def _table_exists(schema: str, table: str) -> str:
    """DO 块：表存在才执行（避免 legacy 环境 / 降级后未重建）

    注：schema/table 来自硬编码 TABLES_29，非用户输入。
    """
    return f"""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = '{schema}' AND table_name = '{table}'
        ) THEN
            RAISE NOTICE '跳过 {schema}.{table}（表不存在）';
            RETURN;
        END IF;

        -- 启用 RLS（幂等：已启用不报错）
        EXECUTE 'ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY';

        -- 先清理已有 policies（兼容旧 _rls_* 命名，统一到 _tenant_isolation）
        EXECUTE 'DROP POLICY IF EXISTS {table}_rls_select ON {schema}.{table}';
        EXECUTE 'DROP POLICY IF EXISTS {table}_rls_insert ON {schema}.{table}';
        EXECUTE 'DROP POLICY IF EXISTS {table}_rls_update ON {schema}.{table}';
        EXECUTE 'DROP POLICY IF EXISTS {table}_rls_delete ON {schema}.{table}';
        EXECUTE 'DROP POLICY IF EXISTS {table}_tenant_isolation ON {schema}.{table}';

        -- 创建统一标准 policy（FOR ALL = SELECT/INSERT/UPDATE/DELETE）
        EXECUTE $POLICY$
            CREATE POLICY {table}_tenant_isolation ON {schema}.{table}
                FOR ALL
                USING (tenant_id::text = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        $POLICY$;
    END $$;
    """  # noqa: S608 — table from hardcoded TABLES_29, not user input


def _force_rls_for_existing() -> str:
    """DO 块：所有已启用 RLS 但缺 FORCE 的表补 FORCE ROW LEVEL SECURITY

    用 pg_class 查询找 relrowsecurity=true AND relforcerowsecurity=false
    的 public schema 普通表。排除跨租户 / 系统表。
    """
    excluded_list = ", ".join(
        f"'{name}'" for name in _SYSTEM_TABLES_EXCLUDED_FROM_FORCE
    )
    return f"""
    DO $$
    DECLARE
        rec RECORD;
    BEGIN
        FOR rec IN
            SELECT n.nspname AS schema_name, c.relname AS table_name
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND c.relrowsecurity = true
              AND c.relforcerowsecurity = false
              -- 排除跨租户 / 系统表
              AND c.relname NOT IN ({excluded_list})
              -- 排除 events 分区表（继承 events 全局表的 RLS）
              AND c.relname NOT LIKE 'events\\_%'
              -- 排除 projector 分区表
              AND c.relname NOT LIKE 'projector\\_%'
        LOOP
            EXECUTE format(
                'ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',
                rec.schema_name, rec.table_name
            );
            RAISE NOTICE 'FORCE RLS applied: %.%', rec.schema_name, rec.table_name;
        END LOOP;
    END $$;
    """  # noqa: S608


def upgrade() -> None:
    # Part 1: 29 张裸表补 RLS（ENABLE + FORCE + POLICY）
    for schema, table in TABLES_29:
        op.execute(_table_exists(schema, table))

    # Part 2: 已启用 RLS 但缺 FORCE 的表补 FORCE ROW LEVEL SECURITY
    op.execute(_force_rls_for_existing())


def downgrade() -> None:
    """仅 DROP POLICY + DISABLE RLS；不 DROP TABLE（业务数据还在）

    Part 2 的 FORCE RLS 降级不在此处理——~344 张表逐个恢复可理论做到，
    但实际操作风险大于收益。如需降级，请逐个表手动 NO FORCE ROW LEVEL SECURITY。

    注意：downgrade 后表会重新变成"无 RLS"状态，这是原历史状态。
    """
    for schema, table in TABLES_29:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = '{schema}' AND table_name = '{table}'
                ) THEN
                    -- 清理统一标准 policy
                    EXECUTE 'DROP POLICY IF EXISTS {table}_tenant_isolation ON {schema}.{table}';
                    -- 同时清理可能遗留的旧 _rls_* policies
                    EXECUTE 'DROP POLICY IF EXISTS {table}_rls_select ON {schema}.{table}';
                    EXECUTE 'DROP POLICY IF EXISTS {table}_rls_insert ON {schema}.{table}';
                    EXECUTE 'DROP POLICY IF EXISTS {table}_rls_update ON {schema}.{table}';
                    EXECUTE 'DROP POLICY IF EXISTS {table}_rls_delete ON {schema}.{table}';
                    EXECUTE 'ALTER TABLE {schema}.{table} NO FORCE ROW LEVEL SECURITY';
                    EXECUTE 'ALTER TABLE {schema}.{table} DISABLE ROW LEVEL SECURITY';
                END IF;
            END $$;
        """)  # noqa: S608 — table from hardcoded TABLES_29, not user input
