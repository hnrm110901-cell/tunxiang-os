"""v388 — 补齐 29 张历史表 RLS 技术债

CLAUDE.md § 13 禁止事项：禁止跳过 RLS — 所有 DB 操作必须带 tenant_id。
CLAUDE.md § 17 Tier 1：RLS 多租户隔离是硬约束。

    tests/tier1/test_rls_all_tables_tier1.py 静态扫描发现 29 张业务表
    在"全部 migration"范围内无 ALTER TABLE ... ENABLE ROW LEVEL SECURITY。
    在 v382 修复 14 张表后，这是剩余的历史缺口（原 DEVLOG 记 26 张，
    后续 audit 追加 v372/v374/v375 共 3 张）。

    这 29 张表的 CREATE TABLE 分布在 12 个迁移文件中，每张表均有
    tenant_id UUID NOT NULL 列，可安全补启用 RLS。

    修复清单（按原 migration 来源）：

    v282_banquet_contracts.py
      · banquet_approval_logs        宴会审批日志
      · banquet_eo_tickets           宴会 EO 工单

    v346_stored_value_settlement.py
      · stored_value_split_ledger    储值分账明细
      · stored_value_split_rules     储值分账规则
      · sv_settlement_batches        储值结算批次

    v367_warehouse_locations.py
      · ingredient_location_bindings 原料库位绑定
      · inventory_by_location        按库位库存
      · warehouse_locations          库位定义
      · warehouse_zones              库区定义

    v368_delivery_temperature.py
      · delivery_temperature_logs           配送测温记录主表
      · delivery_temperature_logs_default   配送测温分区默认

    v370_stocktake_loss.py
      · stocktake_loss_approvals    损耗审批
      · stocktake_loss_case_no_seq  损耗编号序列
      · stocktake_loss_cases        损耗案例
      · stocktake_loss_items        损耗明细
      · stocktake_loss_writeoffs    损耗核销

    v372_ceo_cockpit.py
      · ceo_cockpit_snapshots        CEO 驾驶舱快照

    v373_dish_profit_enhanced.py
      · dish_co_occurrence          菜品共现矩阵

    v374_procurement_feedback.py
      · procurement_feedback_logs    采购反馈日志

    v375_yield_alerts.py
      · yield_alerts                 出成率预警

    v375_yield_alerts.py
      · yield_alerts                 出成率预警

    v377_customer_journey.py
      · conversion_funnel_daily     日转化漏斗
      · customer_journey_timings    客户旅程时序
      · satisfaction_ratings        满意度评分

    v378_daily_scorecard.py
      · bonus_rules                 奖金规则
      · daily_scorecards            日评分卡
      · store_lifecycle_stages      门店生命周期阶段

    v379_dynamic_pricing_ai.py
      · dynamic_pricing_logs        动态定价日志
      · dynamic_pricing_rules       动态定价规则

    v380_invoice_ocr.py
      · invoice_ocr_results         发票 OCR 结果

    v381_delivery_disputes.py
      · delivery_disputes            外卖异议（已用 helper 启用 RLS，补字面量供静态分析）

    v373_dish_profit_enhanced.py 中额外表
      · dish_pricing_suggestions     菜品定价建议（已用 helper 启用 RLS，补字面量供静态分析）

Revision ID: v388
Revises: v387
Create Date: 2026-05-04
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "v388"
down_revision: Union[str, Sequence[str], None] = "v387"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 26 张待补表 — 直接用字面量 op.execute() 调用
# 每个表执行 4 条 SQL（ENABLE RLS + FORCE RLS + DROP POLICY + CREATE POLICY）
# 不做动态 SQL 循环，让 tests/tier1/test_rls_all_tables_tier1.py 的
# 正则扫描可以直接匹配到 ALTER TABLE <name> ENABLE ROW LEVEL SECURITY。
#
# ENABLE/FORCE 幂等：已启用不会报错
# DROP POLICY IF EXISTS 幂等：不存在跳过
# CREATE POLICY 用 current_setting('app.tenant_id', true) 标准模板


def upgrade() -> None:
    # ── v282 — banquet ────────────────────────────────────────────
    op.execute("ALTER TABLE banquet_approval_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE banquet_approval_logs FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_approval_logs_tenant_isolation ON banquet_approval_logs")
    op.execute("CREATE POLICY banquet_approval_logs_tenant_isolation ON banquet_approval_logs "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE banquet_eo_tickets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE banquet_eo_tickets FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_eo_tickets_tenant_isolation ON banquet_eo_tickets")
    op.execute("CREATE POLICY banquet_eo_tickets_tenant_isolation ON banquet_eo_tickets "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v346 — stored value settlement ─────────────────────────────
    op.execute("ALTER TABLE stored_value_split_ledger ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stored_value_split_ledger FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS stored_value_split_ledger_tenant_isolation ON stored_value_split_ledger")
    op.execute("CREATE POLICY stored_value_split_ledger_tenant_isolation ON stored_value_split_ledger "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE stored_value_split_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stored_value_split_rules FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS stored_value_split_rules_tenant_isolation ON stored_value_split_rules")
    op.execute("CREATE POLICY stored_value_split_rules_tenant_isolation ON stored_value_split_rules "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE sv_settlement_batches ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sv_settlement_batches FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sv_settlement_batches_tenant_isolation ON sv_settlement_batches")
    op.execute("CREATE POLICY sv_settlement_batches_tenant_isolation ON sv_settlement_batches "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v367 — warehouse locations ─────────────────────────────────
    op.execute("ALTER TABLE ingredient_location_bindings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ingredient_location_bindings FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS ingredient_location_bindings_tenant_isolation ON ingredient_location_bindings")
    op.execute("CREATE POLICY ingredient_location_bindings_tenant_isolation ON ingredient_location_bindings "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE inventory_by_location ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE inventory_by_location FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS inventory_by_location_tenant_isolation ON inventory_by_location")
    op.execute("CREATE POLICY inventory_by_location_tenant_isolation ON inventory_by_location "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE warehouse_locations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE warehouse_locations FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS warehouse_locations_tenant_isolation ON warehouse_locations")
    op.execute("CREATE POLICY warehouse_locations_tenant_isolation ON warehouse_locations "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE warehouse_zones ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE warehouse_zones FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS warehouse_zones_tenant_isolation ON warehouse_zones")
    op.execute("CREATE POLICY warehouse_zones_tenant_isolation ON warehouse_zones "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v368 — delivery temperature ────────────────────────────────
    op.execute("ALTER TABLE delivery_temperature_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE delivery_temperature_logs FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS delivery_temperature_logs_tenant_isolation ON delivery_temperature_logs")
    op.execute("CREATE POLICY delivery_temperature_logs_tenant_isolation ON delivery_temperature_logs "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE delivery_temperature_logs_default ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE delivery_temperature_logs_default FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS delivery_temperature_logs_default_tenant_isolation ON delivery_temperature_logs_default")
    op.execute("CREATE POLICY delivery_temperature_logs_default_tenant_isolation ON delivery_temperature_logs_default "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v370 — stocktake loss ──────────────────────────────────────
    op.execute("ALTER TABLE stocktake_loss_approvals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stocktake_loss_approvals FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS stocktake_loss_approvals_tenant_isolation ON stocktake_loss_approvals")
    op.execute("CREATE POLICY stocktake_loss_approvals_tenant_isolation ON stocktake_loss_approvals "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE stocktake_loss_case_no_seq ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stocktake_loss_case_no_seq FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS stocktake_loss_case_no_seq_tenant_isolation ON stocktake_loss_case_no_seq")
    op.execute("CREATE POLICY stocktake_loss_case_no_seq_tenant_isolation ON stocktake_loss_case_no_seq "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE stocktake_loss_cases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stocktake_loss_cases FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS stocktake_loss_cases_tenant_isolation ON stocktake_loss_cases")
    op.execute("CREATE POLICY stocktake_loss_cases_tenant_isolation ON stocktake_loss_cases "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE stocktake_loss_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stocktake_loss_items FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS stocktake_loss_items_tenant_isolation ON stocktake_loss_items")
    op.execute("CREATE POLICY stocktake_loss_items_tenant_isolation ON stocktake_loss_items "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE stocktake_loss_writeoffs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stocktake_loss_writeoffs FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS stocktake_loss_writeoffs_tenant_isolation ON stocktake_loss_writeoffs")
    op.execute("CREATE POLICY stocktake_loss_writeoffs_tenant_isolation ON stocktake_loss_writeoffs "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v372 — ceo cockpit ────────────────────────────────────────
    op.execute("ALTER TABLE ceo_cockpit_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ceo_cockpit_snapshots FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS ceo_cockpit_snapshots_tenant_isolation ON ceo_cockpit_snapshots")
    op.execute("CREATE POLICY ceo_cockpit_snapshots_tenant_isolation ON ceo_cockpit_snapshots "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v373 — dish profit ─────────────────────────────────────────
    op.execute("ALTER TABLE dish_co_occurrence ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dish_co_occurrence FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS dish_co_occurrence_tenant_isolation ON dish_co_occurrence")
    op.execute("CREATE POLICY dish_co_occurrence_tenant_isolation ON dish_co_occurrence "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v374 — procurement feedback ────────────────────────────────
    op.execute("ALTER TABLE procurement_feedback_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE procurement_feedback_logs FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS procurement_feedback_logs_tenant_isolation ON procurement_feedback_logs")
    op.execute("CREATE POLICY procurement_feedback_logs_tenant_isolation ON procurement_feedback_logs "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v375 — yield alerts ────────────────────────────────────────
    op.execute("ALTER TABLE yield_alerts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE yield_alerts FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS yield_alerts_tenant_isolation ON yield_alerts")
    op.execute("CREATE POLICY yield_alerts_tenant_isolation ON yield_alerts "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v377 — customer journey ────────────────────────────────────
    op.execute("ALTER TABLE conversion_funnel_daily ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE conversion_funnel_daily FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS conversion_funnel_daily_tenant_isolation ON conversion_funnel_daily")
    op.execute("CREATE POLICY conversion_funnel_daily_tenant_isolation ON conversion_funnel_daily "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE customer_journey_timings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE customer_journey_timings FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS customer_journey_timings_tenant_isolation ON customer_journey_timings")
    op.execute("CREATE POLICY customer_journey_timings_tenant_isolation ON customer_journey_timings "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE satisfaction_ratings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE satisfaction_ratings FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS satisfaction_ratings_tenant_isolation ON satisfaction_ratings")
    op.execute("CREATE POLICY satisfaction_ratings_tenant_isolation ON satisfaction_ratings "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v378 — daily scorecard ─────────────────────────────────────
    op.execute("ALTER TABLE bonus_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE bonus_rules FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS bonus_rules_tenant_isolation ON bonus_rules")
    op.execute("CREATE POLICY bonus_rules_tenant_isolation ON bonus_rules "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE daily_scorecards ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE daily_scorecards FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS daily_scorecards_tenant_isolation ON daily_scorecards")
    op.execute("CREATE POLICY daily_scorecards_tenant_isolation ON daily_scorecards "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE store_lifecycle_stages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE store_lifecycle_stages FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS store_lifecycle_stages_tenant_isolation ON store_lifecycle_stages")
    op.execute("CREATE POLICY store_lifecycle_stages_tenant_isolation ON store_lifecycle_stages "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v379 — dynamic pricing ─────────────────────────────────────
    op.execute("ALTER TABLE dynamic_pricing_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dynamic_pricing_logs FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS dynamic_pricing_logs_tenant_isolation ON dynamic_pricing_logs")
    op.execute("CREATE POLICY dynamic_pricing_logs_tenant_isolation ON dynamic_pricing_logs "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    op.execute("ALTER TABLE dynamic_pricing_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dynamic_pricing_rules FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS dynamic_pricing_rules_tenant_isolation ON dynamic_pricing_rules")
    op.execute("CREATE POLICY dynamic_pricing_rules_tenant_isolation ON dynamic_pricing_rules "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v380 — invoice ocr ─────────────────────────────────────────
    op.execute("ALTER TABLE invoice_ocr_results ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE invoice_ocr_results FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS invoice_ocr_results_tenant_isolation ON invoice_ocr_results")
    op.execute("CREATE POLICY invoice_ocr_results_tenant_isolation ON invoice_ocr_results "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v381 — delivery disputes（已用 helper 启用 RLS，补字面量供静态分析）───
    op.execute("ALTER TABLE delivery_disputes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE delivery_disputes FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS delivery_disputes_tenant_isolation ON delivery_disputes")
    op.execute("CREATE POLICY delivery_disputes_tenant_isolation ON delivery_disputes "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")

    # ── v373 — dish_pricing_suggestions（已用 helper 启用 RLS，补字面量供静态分析）─
    op.execute("ALTER TABLE dish_pricing_suggestions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dish_pricing_suggestions FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS dish_pricing_suggestions_tenant_isolation ON dish_pricing_suggestions")
    op.execute("CREATE POLICY dish_pricing_suggestions_tenant_isolation ON dish_pricing_suggestions "
               "USING (tenant_id::text = current_setting('app.tenant_id', true)) "
               "WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))")


def downgrade() -> None:
    """仅 DROP POLICY + DISABLE RLS；不 DROP TABLE。

    业务数据不受影响，但恢复为"无 RLS"的原始状态。
    """
    tables = (
        "banquet_approval_logs", "banquet_eo_tickets",
        "stored_value_split_ledger", "stored_value_split_rules", "sv_settlement_batches",
        "ingredient_location_bindings", "inventory_by_location", "warehouse_locations", "warehouse_zones",
        "delivery_temperature_logs", "delivery_temperature_logs_default",
        "stocktake_loss_approvals", "stocktake_loss_case_no_seq", "stocktake_loss_cases",
        "stocktake_loss_items", "stocktake_loss_writeoffs",
        "ceo_cockpit_snapshots",
        "dish_co_occurrence",
        "procurement_feedback_logs",
        "yield_alerts",
        "conversion_funnel_daily", "customer_journey_timings", "satisfaction_ratings",
        "bonus_rules", "daily_scorecards", "store_lifecycle_stages",
        "dynamic_pricing_logs", "dynamic_pricing_rules",
        "invoice_ocr_results",
        "delivery_disputes",
        "dish_pricing_suggestions",
    )
    for table in tables:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
