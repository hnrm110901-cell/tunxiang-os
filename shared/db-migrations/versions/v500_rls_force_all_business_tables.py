"""v500 — 业务表批量加 FORCE ROW LEVEL SECURITY [SECURITY][Tier1]

⚠️⚠️ DO NOT RUN ON STAGING/PRODUCTION WITHOUT DRY-RUN ⚠️⚠️

本 migration 把所有 ENABLE ROW LEVEL SECURITY 但缺 FORCE ROW LEVEL SECURITY 的
业务表批量加 FORCE。详细 rollout 计划见 docs/security/rls-force-rollout.md。

## 为什么

审计 S-05（P0）：
  - shared/ontology/src/database.py 的 get_db_no_rls() 用 SET LOCAL row_security = off
    需要 app role 持有 BYPASSRLS 权限才能生效
  - 如果生产部署 GRANT BYPASSRLS ON ROLE tunxiang TO tunxiang 已经应用，
    那么任意调 get_db_no_rls 的代码路径（gateway hub_api / banquet_payment_routes /
    wechat_pay_notify_service / tx-analytics seed_loader / tx-brain brain_routes 等
    5 处合法用例）都能 SELECT/UPDATE 所有租户数据
  - 即便 v399/v400/v401/v402 已经把 WITH CHECK 补上，没 FORCE 时这些策略
    在 BYPASSRLS 角色下完全不生效
  - FORCE ROW LEVEL SECURITY = 即便表 owner / BYPASSRLS 角色也强制走 policy

## 为什么 v500 而不是 v403？

PR 链 v399 之后用户在做 v400/v401/v402 WITH CHECK 系列（在 sec/pg7-* 分支）。
本 migration 是独立的"FORCE 全表"批量操作，跟 WITH CHECK 修补不冲突，
但 alembic 链需要等 WITH CHECK 系列先合到 main 后再 rebase down_revision。
用 v500 留出 gap（v400-v499 给 WITH CHECK 系列 + 间隙），merge 时把
down_revision 指向 main 上最新的 head（届时大概率是 v402 或更高）。

## EXEMPT 列表

下列表必须**严格对齐**：
  - .github/workflows/rls-gate.yml L75-93
  - tests/tier1/test_rls_all_tables_tier1.py（如存在）
  - tests/tier1/test_rls_force_migration_tier1.py（本 PR 新增静态分析测试）

任一表错位都会导致：
  - 漏 FORCE：多租户隔离被绕过（BYPASSRLS 走 policy 失效）
  - 误 FORCE：app 在系统表（events / mv_* / 共享配置）上查询返回 0 行

## 5 阶段上线（详见 docs/security/rls-force-rollout.md）

  D1 ✅ 阶段 1 — CI 防新违规（PR #195 rls-gate.yml 已加 FORCE 检查）
  D2 ⏳ 阶段 2 — staging dry-run：真 PG 上跑 SELECT 查 ENABLE-without-FORCE 表
                列表，预估 ~176 张
  D3 ⏳ 阶段 3 — ✅ 本 PR 落代码（不 merge 不部署）
  D4 ⏳ 阶段 4 — 撤 BYPASSRLS + 引入 tx_system_role（独立 PR，DBA 操作）
  D5 ⏳ 阶段 5 — 灰度发布：demo → 1 店 → 1 品牌 → 全量

## 5 处合法 BYPASSRLS 调用方（迁移前必须确认每处仍可工作）

来自 shared/ontology/src/database.py:84-86 docstring：
  1. gateway / hub_api — 跨租户 hub API
  2. tx-trade / banquet_payment_routes — 微信回调跨租户查 tenant
     （已在 PR #195 加签名验证 S-04，仍走 SET ROLE 路径可兼容）
  3. tx-trade / wechat_pay_notify_service — 按 out_trade_no 跨租户查订单
  4. tx-analytics / seed_loader — 启动期一次性数据导入
  5. tx-brain / brain_routes — 跨租户聚合视图（应改读 mv_* 物化视图）

阶段 4 完成后 get_db_no_rls() 改用 SET LOCAL ROLE tx_system_role；
本 v500 必须在阶段 4 之前 merge，否则 5 处调用方在 FORCE 生效后立刻返回 0 行。

正确顺序：
  阶段 4 (撤 BYPASSRLS + tx_system_role + 改 get_db_no_rls)
    → 阶段 5 灰度
    → merge 本 v500 (FORCE 全表)
    → 全量 rollout

Revision ID: v500
Revises: v399  (合并时按 main 最新 head 调整)
Create Date: 2026-05-05
"""

from typing import Sequence, Union

from alembic import op

# ─── alembic revision identifiers ───
revision: str = "v500"
down_revision: Union[str, Sequence[str], None] = "v399"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ─── EXEMPT 表（必须与 .github/workflows/rls-gate.yml 严格对齐）───
# 任何修改必须同时改 rls-gate.yml + tests/tier1/test_rls_force_migration_tier1.py
_EXEMPT_TABLES = (
    "alembic_version",
    "events",
    "events_default",
    "projector_checkpoints",
    "projector_rebuild_locks",
    "system_config",
    "feature_flags_global",
    "skill_registry_global",
    "adapter_registry",
    "currency_codes",
    "city_codes",
    "industry_benchmarks",
    "role_level_defaults",
    "app_versions",
    "refresh_tokens",
    "sync_checkpoints",
    "device_registry",
    "device_heartbeats",
    "franchise_audits",
    "franchise_settlements",
    "franchise_settlement_items",
    "central_kitchen_profiles",
    "brand_profiles",
    "brand_content_constraints",
    "brand_seasonal_calendar",
    "competitor_brands",
    "competitor_snapshots",
    "market_trend_signals",
    "supplier_profiles",
    "supplier_score_history",
    "payment_events",
)

# 前缀豁免（与 rls-gate.yml MV_PREFIXES + PARTITION_PATTERNS 对齐）
# - mv_* : 物化视图（不存数据，由投影器从 events 重建）
# - events_2024_/2025_/2026_/2027_ : events 表的年度分区
_MV_PREFIX = "mv_"
_PARTITION_PREFIXES = ("events_2024_", "events_2025_", "events_2026_", "events_2027_")


def upgrade() -> None:
    """循环 pg_tables 给所有 ENABLE-without-FORCE 业务表加 FORCE。

    幂等：每次 ALTER TABLE FORCE 在已 FORCE 的表上是 no-op 但会刷状态；
    生产 dry-run 时可重跑确认稳定。
    """
    exempt_sql = ", ".join(f"'{t}'" for t in _EXEMPT_TABLES)
    partition_pattern_clauses = " AND ".join(
        f"tablename NOT LIKE '{p}%'" for p in _PARTITION_PREFIXES
    )

    op.execute(
        f"""
        DO $$
        DECLARE
            t record;
            applied_count int := 0;
        BEGIN
            FOR t IN
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND rowsecurity = true
                  AND forcerowsecurity = false
                  AND tablename NOT IN ({exempt_sql})
                  AND tablename NOT LIKE '{_MV_PREFIX}%'
                  AND {partition_pattern_clauses}
                ORDER BY tablename
            LOOP
                EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t.tablename);
                applied_count := applied_count + 1;
                RAISE NOTICE 'v500: FORCE ROW LEVEL SECURITY applied to %', t.tablename;
            END LOOP;
            RAISE NOTICE 'v500: FORCE ROW LEVEL SECURITY 应用完成，% 张表', applied_count;
        END $$;
        """
    )


def downgrade() -> None:
    """逆向 NO FORCE。

    ⚠️ **批量降级风险**：
    本 migration 不存"上线前哪些表已 FORCE / 哪些没"的快照。downgrade 会把
    本批次（按 EXEMPT + 前缀过滤后的所有 RLS-enabled 业务表）一律 NO FORCE，
    包括那些在 v500 之前手工已 FORCE 的表（如有）。
    建议：生产 downgrade 必须先在 staging dry-run 比对快照，逐表评估后再执行。
    """
    exempt_sql = ", ".join(f"'{t}'" for t in _EXEMPT_TABLES)
    partition_pattern_clauses = " AND ".join(
        f"tablename NOT LIKE '{p}%'" for p in _PARTITION_PREFIXES
    )

    op.execute(
        f"""
        DO $$
        DECLARE
            t record;
            reverted_count int := 0;
        BEGIN
            FOR t IN
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND rowsecurity = true
                  AND forcerowsecurity = true
                  AND tablename NOT IN ({exempt_sql})
                  AND tablename NOT LIKE '{_MV_PREFIX}%'
                  AND {partition_pattern_clauses}
                ORDER BY tablename
            LOOP
                EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', t.tablename);
                reverted_count := reverted_count + 1;
                RAISE WARNING 'v500 downgrade: NO FORCE applied to %', t.tablename;
            END LOOP;
            RAISE WARNING 'v500 downgrade: 还原 % 张表 — 检查多租户隔离是否仍有效', reverted_count;
        END $$;
        """
    )
