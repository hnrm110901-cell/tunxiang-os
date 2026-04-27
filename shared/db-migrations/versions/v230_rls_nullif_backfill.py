"""v230 — 全量回填 RLS NULLIF 安全保护（v112–v150 遗留策略）

CRITICAL 安全修复：v112 至 v150 之间创建的 70 张表的 RLS 策略均使用
`current_setting('app.tenant_id', true)::uuid` 直接强转，缺少 NULLIF 空串保护。
当 `app.tenant_id` 未设置或为空字符串时，::uuid 强转行为不确定，可能导致
策略失效，产生跨租户数据泄露风险。

已被其他迁移修复的表（跳过）：
  - v138: coupons / customer_coupons / notification_tasks / anomaly_dismissals / campaigns
  - v139: dish_boms / dish_bom_items
  - v224: corporate_customers / corporate_orders / corporate_bills /
          aggregator_orders / aggregator_reconcile_results / aggregator_discrepancies

修复方式：
  1. FORCE ROW LEVEL SECURITY（表所有者也受约束）
  2. DROP 旧策略（IF EXISTS，幂等）
  3. CREATE 新策略，使用 NULLIF + WITH CHECK 标准写法

Revision ID: v230
Revises: v229
Create Date: 2026-04-11
"""

from alembic import op

revision = "v230b"
down_revision = "v230"
branch_labels = None
depends_on = None

# 标准安全条件
_SAFE_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# (table, old_policy_name) — 按来源版本分组，便于审计追踪
_AFFECTED: list[tuple[str, str]] = [
    # ── v112: 徐记活鲜 ──────────────────────────────────────────────────────
    ("fish_tank_zones", "fish_tank_zones_tenant_isolation"),
    ("live_seafood_weigh_records", "live_seafood_weigh_records_tenant_isolation"),
    # ── v113: 套餐组合 ──────────────────────────────────────────────────────
    ("combo_groups", "combo_groups_tenant_isolation"),
    ("combo_group_items", "combo_group_items_tenant_isolation"),
    ("order_item_combo_selections", "order_item_combo_selections_tenant_isolation"),
    # ── v114: 宴席菜单 / 销售渠道 ──────────────────────────────────────────
    ("banquet_menus", "banquet_menus_tenant_isolation"),
    ("banquet_menu_sections", "banquet_menu_sections_tenant_isolation"),
    ("banquet_menu_items", "banquet_menu_items_tenant_isolation"),
    ("banquet_sessions", "banquet_sessions_tenant_isolation"),
    ("sales_channels", "sales_channels_tenant_isolation"),
    ("channel_dish_configs", "channel_dish_configs_tenant_isolation"),
    # ── v115: 档口-菜品映射 ─────────────────────────────────────────────────
    ("dish_dept_mappings", "dish_dept_mappings_tenant_isolation"),
    # ── v116: 运营日清 ──────────────────────────────────────────────────────
    ("shift_handovers", "shift_handovers_tenant_isolation"),
    ("daily_summaries", "daily_summaries_tenant_isolation"),
    ("daily_issues", "daily_issues_tenant_isolation"),
    ("inspection_reports", "inspection_reports_tenant_isolation"),
    ("employee_daily_performance", "employee_daily_performance_tenant_isolation"),
    # ── v117: 财务引擎 ──────────────────────────────────────────────────────
    ("daily_pnl", "daily_pnl_tenant_isolation"),
    ("cost_items", "cost_items_tenant_isolation"),
    ("revenue_records", "revenue_records_tenant_isolation"),
    ("finance_configs", "finance_configs_tenant_isolation"),
    # ── v119: 中央厨房（dish_boms/items 已由 v139 修复，跳过）──────────────
    ("ck_production_orders", "ck_production_orders_tenant_isolation"),
    ("ck_production_items", "ck_production_items_tenant_isolation"),
    ("ck_distribution_orders", "ck_distribution_orders_tenant_isolation"),
    ("ck_distribution_items", "ck_distribution_items_tenant_isolation"),
    # ── v120: 薪资引擎 ──────────────────────────────────────────────────────
    ("payroll_configs", "payroll_configs_tenant_isolation"),
    ("payroll_records", "payroll_records_tenant_isolation"),
    ("payroll_line_items", "payroll_line_items_tenant_isolation"),
    # ── v121: 审批工作流 ────────────────────────────────────────────────────
    ("approval_templates", "approval_templates_tenant_isolation"),
    ("approval_instances", "approval_instances_tenant_isolation"),
    ("approval_step_records", "approval_step_records_tenant_isolation"),
    ("approval_notifications", "approval_notifications_tenant_isolation"),
    # ── v125: 加盟管理 ──────────────────────────────────────────────────────
    ("franchisees", "franchisees_tenant_isolation"),
    ("franchise_stores", "franchise_stores_tenant_isolation"),
    ("franchise_royalty_rules", "franchise_royalty_rules_tenant_isolation"),
    ("franchise_royalty_bills", "franchise_royalty_bills_tenant_isolation"),
    ("franchise_kpi_records", "franchise_kpi_records_tenant_isolation"),
    # ── v126: 排班 ──────────────────────────────────────────────────────────
    ("work_schedules", "work_schedules_tenant_isolation"),
    # ── v127: 采购订单 ──────────────────────────────────────────────────────
    ("purchase_orders", "purchase_orders_tenant_isolation"),
    ("purchase_order_items", "purchase_order_items_tenant_isolation"),
    ("ingredient_batches", "ingredient_batches_tenant_isolation"),
    # ── v129: 中央厨房审批 ──────────────────────────────────────────────────
    ("store_requisitions", "store_requisitions_tenant_isolation"),
    ("store_requisition_items", "store_requisition_items_tenant_isolation"),
    ("production_plans", "production_plans_tenant_isolation"),
    ("production_plan_items", "production_plan_items_tenant_isolation"),
    ("approval_records", "approval_records_tenant_isolation"),
    # ── v130: 评价 / 会员等级 ───────────────────────────────────────────────
    ("order_reviews", "order_reviews_tenant_isolation"),
    ("review_media", "review_media_tenant_isolation"),
    ("member_tier_configs", "member_tier_configs_tenant_isolation"),
    ("tier_upgrade_logs", "tier_upgrade_logs_tenant_isolation"),
    # ── v131: 菜品规格 / 考勤 ───────────────────────────────────────────────
    ("dish_spec_groups", "dish_spec_groups_tenant_isolation"),
    ("dish_spec_options", "dish_spec_options_tenant_isolation"),
    ("attendance_records", "attendance_records_tenant_isolation"),
    ("attendance_leave_requests", "attendance_leave_requests_tenant_isolation"),
    # ── v133: 地址 / 通知 ───────────────────────────────────────────────────
    ("customer_addresses", "customer_addresses_tenant_isolation"),
    ("notifications", "notifications_tenant_isolation"),
    ("notification_templates", "notification_templates_tenant_isolation"),
    # ── v134: 报表归档 ──────────────────────────────────────────────────────
    ("daily_business_reports", "daily_business_reports_tenant_isolation"),
    ("archived_orders", "archived_orders_tenant_isolation"),
    ("search_hot_keywords", "search_hot_keywords_tenant_isolation"),
    # ── v135: 合同 / 培训 ───────────────────────────────────────────────────
    ("franchise_contracts", "franchise_contracts_tenant_isolation"),
    ("training_courses", "training_courses_tenant_isolation"),
    ("training_records", "training_records_tenant_isolation"),
    ("employee_certificates", "employee_certificates_tenant_isolation"),
    # ── v136: 系统字典 / 审计日志 / 特性开关（旧策略名为 tenant_isolation）──
    ("sys_dictionaries", "tenant_isolation"),
    ("sys_dictionary_items", "tenant_isolation"),
    ("audit_logs", "tenant_isolation"),
    ("feature_flags", "tenant_isolation"),
    ("gray_release_rules", "tenant_isolation"),
    # ── v150: 店长折扣申请 ──────────────────────────────────────────────────
    ("manager_discount_requests", "mdr_tenant_isolation"),
]


def upgrade() -> None:
    for table, old_policy in _AFFECTED:
        new_policy = f"{table}_rls_v230"

        # 1. 强制表所有者也受 RLS 约束
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")

        # 2. 删除旧策略（幂等）
        op.execute(f"DROP POLICY IF EXISTS {old_policy} ON {table};")

        # 3. 创建标准策略（幂等，IF NOT EXISTS 防重复）
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = '{table}' AND policyname = '{new_policy}'
                ) THEN
                    CREATE POLICY {new_policy} ON {table}
                        AS PERMISSIVE FOR ALL TO PUBLIC
                        USING ({_SAFE_COND})
                        WITH CHECK ({_SAFE_COND});
                END IF;
            END $$;
        """)


def downgrade() -> None:
    # 回滚：删除安全策略，恢复旧策略（仅用于紧急回滚，存在安全风险）
    for table, old_policy in _AFFECTED:
        new_policy = f"{table}_rls_v230"
        op.execute(f"DROP POLICY IF EXISTS {new_policy} ON {table};")
        op.execute(f"""
            CREATE POLICY {old_policy} ON {table}
            USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
        """)
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
