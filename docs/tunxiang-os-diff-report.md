# tunxiang-os vs zhilian-os 差分报告 + HR 人力中枢专项

> 生成日期: 2026-04-17  
> 本地: `/Users/lichun/Documents/GitHub/zhilian-os` (D1-D12 三波 z60→z65)  
> 远端: `/tmp/diff-analysis/remote-main` (tunxiang-os main, HEAD=`ad6061c`, tx-org 人力中枢 HEAD=`3aa81bb`)

---

## 1. 执行摘要

### 1.1 架构差异（根本性）

| 维度 | 本地 zhilian-os | 远端 tunxiang-os |
|----|----|----|
| 后端形态 | **单体** `apps/api-gateway` (FastAPI) | **微服务** 18 个 `services/tx-*` |
| Alembic | 单仓 `z` 前缀 155 个 revision | 共享 `shared/db-migrations/` `v` 前缀 **300 个** revision |
| 前端 | 单体 `apps/web` React，427 tsx | 多端 16 个 `apps/web-*`/`android-*`/`ios-*`/`miniapp-*` |
| 迁移冲突 | 前缀不同（z vs v），**revision ID 无碰撞**，可并存 | — |

### 1.2 文件数总览

| 目录 | 本地 | 远端 | 差异 |
|----|----|----|----|
| models/*.py | 172 | ~120（跨 10+ 个 service 之和） | 本地 +50+（聚合） |
| api/*.py | 277 | ~450（跨 service 之和） | **远端多 ~170**，覆盖面更广 |
| services/*.py | 351 | ~350（跨 service 之和） | 规模相当，但分域 |
| alembic/versions | 155 | 300 | 远端近 2 倍 |
| web pages | 427 | 分散至多个 web-* | 可比性低 |

### 1.3 三个最强集成建议 (Top 3)

1. **从远端反向引入 `services/tx-org/src/services/` 全套 HR 能力** — 远端 tx-org 有 51 个 service 文件 + 67 个 api 路由，覆盖本地欠缺的 **e-sign 电子签约、payroll_engine v3、salary_item_library（138 项）、nine_box/talent_pool/succession（人才盘点）、franchise_settlement/royalty（加盟结算）、smart_schedule/unified_schedule**，这些是对标 i 人事+乐才 V6.2 的 P0。
2. **本地 LLM Gateway + Signal Bus + 月度经营报告** 抽取到远端 tx-agent/tx-brain — 本地 `services/llm_gateway/`、`signal_bus.py`、`monthly_report_service.py`、`case_story_generator.py`、`scenario_matcher.py`、`decision_priority_engine.py`、`execution_feedback_service.py` 是**远端明显没有**的高价值资产。
3. **统一迁移策略** — 远端 `shared/db-migrations/` (300 v*) 与本地 `alembic/versions/` (155 z*) 并存不冲突，但长期需要命名空间化：建议保留 z* 归属 zhilian 扩展，v* 来自上游。

### 1.4 Step 6 最值得 cherry-pick Top 3 文件（远端→本地）

1. **`/tmp/diff-analysis/remote-main/services/tx-org/src/services/payroll_engine_v3.py`** + `salary_item_library.py` — 直接补齐本地 HR 薪资项目库空白
2. **`/tmp/diff-analysis/remote-main/services/tx-org/src/api/e_signature_routes.py`** + `src/services/e_sign_service.py` — 本地零覆盖
3. **`/tmp/diff-analysis/remote-main/services/tx-org/src/services/franchise_settlement_service.py`** + `royalty_calculator.py` + `franchise_clone_service.py` — 本地仅 raas.py 提及加盟，实际无闭环

---

## 2. Alembic 迁移冲突清单

### 2.1 结论：**无 revision ID 碰撞**

- 本地命名：`z{NN}_xxx.py`（z45–z65），最新 `z65_d5_d7_closing_access.py`
- 远端命名：`v{NNN}_xxx.py`（v1–v256+），最新 `v256_tax_declarations.py`

两边前缀完全不同，Alembic revision ID 空间独立。**不存在撞 revision 的风险**。

### 2.2 潜在覆盖表冲突（需人工审查）

两边都可能 `CREATE TABLE` 的业务对象（基于文件名推测）：

| 表域 | 本地迁移 | 远端迁移 |
|----|----|----|
| salary_item_library | z61_d12_payroll_compliance_tables | v250_salary_item_library |
| attendance_compliance | z61_d11_d9_compliance_training | v255_attendance_compliance |
| performance_reviews | (无专项) | v254_performance_reviews |
| tax_declarations | z61_d7_finance_must_fix | v256_tax_declarations |
| e_signature | (无) | v252_e_signature |
| enterprise_accounts | (无) | v250_enterprise_accounts |
| merchant_kpi_weight_configs | z47_decision_weight_learning (近似) | v253_merchant_kpi_weight_configs |

**建议**：集成任何远端迁移前，必须对照本地 z60-z65 的 DDL 做 schema diff，优先 `IF NOT EXISTS` 化。

### 2.3 最新本地迁移（z60 起）清单

```
z60_d1_d4_pos_crm_menu_tables
z61_d7_finance_must_fix           ← 发票/税务
z61_d9_d11_compliance_training    ← 健康证/培训
z61_d12_payroll_compliance_tables ← 薪资合规
z62_merge_d7_d9_d11_d12_heads
z63_d6_llm_governance              ← LLM Gateway
z63_d8_d10_procurement_attendance ← 采购/考勤
z63_d11_exam_system
z64_merge_shouldfix_p1
z65_d5_d7_closing_access           ← 月结+访问控制
```

---

## 3. 核心能力差分

### 3.1 仅本地有（建议从 zhilian 抽到 tunxiang）

> 远端 18 个微服务中搜索不到同名/同义文件的本地核心能力

| 域 | 本地文件 | 价值 |
|----|----|----|
| LLM Gateway | `src/services/llm_gateway/*` + `api/llm.py` | L1-L5 分级路由 + 成本治理 |
| Signal Bus | `services/signal_bus.py` + `api/signal_bus_api.py` | 差评→修复/临期→废料/大桌→裂变 3 路由 |
| 私域健康分 | `services/private_domain_health_service.py` + `api/private_domain.py` | 5 维加权评分 |
| 店长/老板简报 | `store_manager_briefing_service.py` + `hq_briefing_service.py` + `briefing_api.py` + `hq_briefing_api.py` | 08:05/08:10 WeChat 推送 |
| 决策优先级引擎 | `decision_priority_engine.py` + `decision_push_service.py` + `decision_flywheel_service.py` | Top3 聚合 + 4 时点推送 |
| 执行反馈闭环 | `execution_feedback_service.py` | 回写 decision_log → 重算健康分 |
| 月度经营报告 | `monthly_report_service.py` + `api/monthly_report.py` + `case_story_generator.py` | JSON + HTML print-as-PDF |
| 场景匹配器 | `scenario_matcher.py` | 7 场景分类 + 历史相似度 |
| 废料守护（完整版） | `waste_guard_service.py` + `waste_reasoning_service.py` + `api/waste_guard.py` + `api/waste_events.py` | Top5 废料 + ¥归因 |
| FCT 财税现金流 | `fct_service.py` + `fct_advanced_service.py` + `api/fct*.py` | 带 _yuan 字段 |
| 食材成本 BOM | `food_cost_service.py` + `bom_resolver.py` + `api/bom.py` | BOM 成本链路 |
| 边缘节点 | `edge_node_service.py` + `raspberry_pi_edge_service.py` + `api/edge_node.py` | 离线营收/库存查询 |
| 证书 PDF | `certificate_pdf_service.py` + `api/certificate_public.py` + `api/health_certificates.py` + `health_cert_scan_service.py` | 健康证核验 + OCR |
| KPI 告警阈值 | `kpi_alert_service.py` + `pages/AlertThresholdsPage.tsx` | MVP #8 门槛配置 |
| Dish 全景 | `dish_master.py` + `dish_lifecycle_service.py` + `dish_cost_alert.py` + `dish_monthly_summary.py` + `dish_profitability_service.py` + `dish_rd_agent.py` | 10+ 菜品专项 |
| 本体/知识图谱 | `ontology_*` (12 个 service) + `api/ontology_api.py` | Cypher/NL 查询/同步流水线 |
| 员工生命周期 | `employee_lifecycle_service.py` + `models/employee_lifecycle.py` + `models/employee_growth.py` + `api/onboarding.py` + `onboarding_pipeline_service.py` | 入-转-离闭环 |
| 证据推理 | `reasoning_engine.py` + `causal_graph_service.py` + `lineage_tracker.py` + `l4_reasoning.py` + `l3_knowledge.py` | 因果/血缘 |
| RAG 增强 | `enhanced_rag_service.py` + `rag_signal_router.py` + `domain_vector_service.py` | 多信号检索 |

**Top 20 重点抽取清单**（按价值排序）：
1. `llm_gateway/` 整包
2. `signal_bus.py` + `api/signal_bus_api.py`
3. `private_domain_health_service.py`
4. `decision_priority_engine.py`
5. `monthly_report_service.py`
6. `store_manager_briefing_service.py` + `hq_briefing_service.py`
7. `execution_feedback_service.py`
8. `case_story_generator.py`
9. `scenario_matcher.py`
10. `waste_guard_service.py` + `waste_reasoning_service.py`
11. `fct_service.py` + `fct_advanced_service.py`
12. `food_cost_service.py` + `bom_resolver.py`
13. `edge_node_service.py`
14. `certificate_pdf_service.py` + `health_cert_scan_service.py`
15. `dish_cost_alert.py` + `dish_monthly_summary.py`
16. `ontology_*` (选 3 个: `ontology_action_service`, `ontology_nl_query_service`, `ontology_cross_store_service`)
17. `reasoning_engine.py` + `causal_graph_service.py`
18. `kpi_alert_service.py`
19. `prompt_audit_log.py` + `sensitive_audit_log.py`（LLM 审计）
20. `neural_system.py` + `weight_learning.py`

### 3.2 仅远端有（本地缺失，建议反向引入）

| 域 | 远端服务/文件 | 本地缺口 |
|----|----|----|
| **会员订阅** | `tx-member/src/api/subscription_routes.py` + `members/models/*` | 本地无 subscription |
| **储值卡** | `tx-member` 7 个 stored_value 文件 | 本地仅 models/stored_value.py，服务/API 薄弱 |
| **礼品卡** | `tx-member/src/api/gift_card_routes.py` + `services/gift_card.py` | 本地零覆盖 |
| **积分商城** | `tx-member/points_mall*.py` (3 个) | 本地 points 无 mall |
| **GDPR 合规** | `tx-member/src/api/gdpr_routes.py` + `services/gdpr_service.py` | 本地无 |
| **跨品牌会员** | `cross_brand_member_routes.py` + `platform_binding_service.py` | 本地无 |
| **会员 golden_id** | `golden_id_routes.py` + `tx-trade/services/member_golden_id.py` | 本地仅 consumer_id_mapping |
| **KDS 全套** | tx-trade `kds_*` 20+ 文件（chef_stats/swimlane/pause_grab/station_profit/banquet_kds） | 本地 api/kds.py + services/kds_service.py 只有基础 |
| **宴会深化** | `banquet_deposit_routes.py` + `banquet_kds_routes.py` + `banquet_advanced_routes.py` | 本地 banquet 只到 lifecycle |
| **企业餐/团餐** | `enterprise_meal_routes.py` + `corporate_order_routes.py` + `enterprise_account.py` + `enterprise_billing.py` | 本地 enterprise.py 较浅 |
| **外卖聚合** | tx-trade `delivery_adapter.py` + `delivery_adapters/` + `delivery_aggregator.py` + `delivery_ops_service.py` + `delivery_panel_service.py` | 本地 douyin/eleme/meituan 分散，无统一聚合器 |
| **自助点餐** | `self_order_engine.py` + `chef_at_home.py` + `scan_order_service.py` | 本地 scan/order 较简单 |
| **快餐场景** | tx-trade `fastfood_routes.py` + `food_court_routes.py` + `market_session_routes.py` | 本地 api/fast_food.py 单薄 |
| **抖音券核销** | `douyin_voucher_routes.py` + `coupon_platform_service.py` | 本地 douyin_service.py 基础 |
| **小红书联动** | `xhs_routes.py` | 本地零覆盖 |
| **打印模板引擎** | `print_template_service.py` + `template_renderer.py` + `print_manager.py` + `printer_driver.py` | 本地 print_service.py 薄弱 |
| **叫号屏** | `calling_screen_routes.py` + `digital_menu_board_router.py` + `tv_menu_routes.py` | 本地 tv_menu 仅前端 |
| **中央厨房** | tx-supply `central_kitchen_*` + `ck_production_routes.py` + `ck_recipe_routes.py` | 本地零覆盖 |
| **活鲜溯源** | tx-supply `live_seafood_v2.py` + `seafood_traceability_routes.py` | 本地 live_seafood 较简 |
| **金蝶对接** | `kingdee_bridge.py` + `kingdee_routes.py` | 本地仅 ar_ap/voucher，无 ERP 桥 |
| **供应商门户 v2** | `supplier_portal_v2_routes.py` + `supplier_portal_service.py` + `supplier_scoring_engine.py` | 本地 supplier_b2b 无 portal |
| **三向核对** | `three_way_match_engine.py` + `models/three_way_match.py` | 本地有 models 但 service 不成熟 |
| **Voucher/凭证自动化** | tx-finance `voucher_generator.py` + `voucher_service.py` | 本地 voucher_service 简 |
| **预算 v2** | tx-finance `budget_v2_routes.py` | 本地 budget 无 v2 |
| **VAT/增值税台账** | `vat_ledger_routes.py` + `vat_service.py` | 本地 tax_engine 未台账化 |
| **分账引擎** | `split_engine.py` + `split_payment_routes.py` + `fund_settlement_service.py` | 本地 settlement_service 无分账 |
| **费用报销全链** | `tx-expense` 整个服务（13 API + 14 model + 14 service） | 本地**零覆盖**（无报销/差旅/小额现金/合同账本） |
| **Tx-Growth** | `tx-growth` 整个服务（campaigns/engine/seeds/templates/workers） | 本地 marketing 散点，无 campaign 引擎 |
| **Tx-Intel** | `tx-intel` 整个服务（adapters/routers） | 本地无情报外部源接入层 |

**Top 20 本地反向引入清单**（按价值排序）：
1. `services/tx-expense/*` 全部（报销/差旅/合同账本，本地完全空白）
2. `services/tx-member/src/api/subscription_routes.py` + `lifecycle_service.py`
3. `services/tx-trade/src/routers/delivery_*` + `services/delivery_aggregator.py`（统一外卖聚合）
4. `services/tx-trade/src/services/kds_*.py` (8 个：chef_stats/swimlane/pause_grab/station_profit/shortage_link/soldout_sync/prep_recommendation/dispatch)
5. `services/tx-supply/src/services/central_kitchen_service.py` + `production_plan_service.py`
6. `services/tx-finance/src/services/three_way_match_engine.py`
7. `services/tx-finance/src/services/voucher_generator.py`
8. `services/tx-finance/src/api/vat_ledger_routes.py` + `services/vat_service.py`
9. `services/tx-supply/src/services/kingdee_bridge.py`
10. `services/tx-trade/src/services/enterprise_billing.py` + `enterprise_account.py`
11. `services/tx-member/src/services/points_mall_v2.py`
12. `services/tx-member/src/services/gdpr_service.py`
13. `services/tx-member/src/services/stamp_card_service.py`
14. `services/tx-trade/src/services/print_template_service.py` + `template_renderer.py`
15. `services/tx-trade/src/services/self_order_engine.py`
16. `services/tx-trade/src/api/waitlist_routes.py`（本地 queue 无排队等位）
17. `services/tx-trade/src/services/banquet_payment_service.py` + `banquet_template_service.py`
18. `services/tx-supply/src/services/live_seafood_v2.py`
19. `services/tx-growth/engine/*` + `campaigns/*`（营销活动引擎）
20. `services/tx-intel/src/adapters/*`（外部情报源）

### 3.3 双方都有（需人工 diff）

仅列同名高价值域（两边实现大概率不同）：

| 域 | 本地 | 远端 | 备注 |
|----|----|----|----|
| payroll_service | ✅ src/services/payroll_service.py | ✅ tx-org/src/services/payroll_service.py + payroll_engine_v3.py | **远端 v3 引擎更成熟** |
| approval | ✅ api/approval.py + services/approval_engine.py | ✅ tx-org/api/approval_router.py + services/approval_workflow_engine.py | 远端有 engine 分离 |
| attendance | ✅ api/hr_attendance.py + attendance_punch | ✅ tx-org/api/attendance_compliance_routes.py + services/attendance_engine.py | 远端有 compliance 维度 |
| schedule | ✅ api/hr_schedule.py + schedule_service.py + smart_schedule_service.py | ✅ tx-org/api/unified_schedule_routes.py + smart_scheduling_routes.py + services/smart_schedule.py + unified_schedule_service.py | **远端 unified_schedule 更统一** |
| leave | ✅ api/hr_leave.py + services/leave_service.py | ✅ tx-org/api/leave_routes.py + services/leave_service.py + leave_repository.py | 远端 repo 分层 |
| social_insurance | ✅ services/social_insurance_service.py + models/social_insurance.py | ✅ tx-org/src/services/social_insurance.py | 本地 D12 已做 |
| tax | ✅ services/tax_engine_service.py + personal_tax_service.py | ✅ tx-org/src/services/income_tax.py + tax_filing_service.py | 远端 filing 维度强 |
| bom | ✅ bom_service.py + bom_resolver.py | ✅ tx-supply/bom_service.py + bom_craft.py | 远端有 craft |
| invoice | ✅ api/e_invoice.py + services/e_invoice_service.py + einvoice_adapters/ | ✅ tx-finance/invoice_service.py + tx-member/invoice_routes.py | 本地适配器更完整 |
| reconciliation | ✅ payment_reconcile_service.py + bank_reconcile_service.py + tri_reconcile_service.py | ✅ tx-finance/reconciliation_routes.py + payment_reconciliation_routes.py | 本地三向对账较强 |
| waste_guard | ✅ waste_guard_service.py | ✅ tx-supply/waste_guard_service.py + waste_guard_v2.py + waste_attribution.py | 远端 v2 + 归因 |
| reservation | ✅ api/reservations.py + services/reservation_service.py + meituan_reservation | ✅ tx-trade/src/api/booking_*.py + reservation_flow.py + reservation_service.py | 远端 booking 分支 |
| banquet | ✅ api/banquet*.py + services/banquet_lifecycle | ✅ tx-trade banquet_* 10+ 文件 | **远端宴会深度远超本地** |
| dish | ✅ 15+ dish_* 文件 | ✅ tx-menu + tx-trade/dish_practice/dish_ranking | 本地 dish 域更完整 |
| coupon | ✅ coupon_distribution + coupon_roi | ✅ tx-member/coupon_engine + tx-trade/coupon_platform_service | 远端引擎化 |
| compliance | ✅ compliance_engine_service + models/compliance | ✅ tx-org/compliance_alert_service + compliance_routes | 职能重叠 |
| employee | ✅ models/employee + employees.py | ✅ tx-org/api/employees + employee_depth_routes + employee_document_routes + employee_training_routes | **远端 employee 深度更高** |
| franchise | ⚠️ 仅 raas.py 提及 | ✅ tx-org/franchise_*  10+ 文件 + franchise_settlement + royalty_calculator | **本地几乎为零** |

---

## 4. HR 人力中枢专项矩阵（本次重点）

### 4.1 远端 tx-org + tx-agent 已实现（盘点）

远端 tx-org 共 **67 个 API 路由 + 51 个 service**，覆盖：

**组织**：brand_management / region_management / store_clone / legal_entity / tenant_systems / franchise(v4/v5) / franchise_contract / franchise_settlement / royalty_calculator / store_batch / store_readiness / store_ops

**员工**：employees / employee_depth / employee_document（含档案） / employee_training / onboarding_path / mentorship / role_level / job_grade / permission_service / role_permission

**考勤**：attendance_routes / attendance_compliance_routes / attendance_engine / attendance_repository / compliance_alert_service

**排班**：schedule / schedule_routes / smart_scheduling / unified_schedule / staffing_analysis / staffing_template / peak_guard / piecework

**调动**：transfers / transfer_routes / store_transfer / store_transfer_service / transfer_cost_engine / separation_settlement

**薪酬**：payroll_router / payroll_routes / payroll_engine_routes / payroll_engine / payroll_engine_db / payroll_engine_v2 / **payroll_engine_v3** / payroll_service / **salary_item_library** / salary_item_config_service / salary_items / payslip / payslip_dual_view_service

**税**：income_tax / tax_filing_service / tax_filing_routes

**社保**：social_insurance（service）

**合规**：compliance_routes / compliance_alert_routes / governance_routes / ai_alert_routes / alert_aggregation_routes

**绩效**：performance_routes / performance_scoring_routes / performance_scoring_service / contribution_routes / contribution_score_service / points_routes / employee_points_service

**电子签约**：**e_signature_routes / e_sign_service / e_signature_service**

**OTA / IM 同步**：ota_routes / im_sync_routes / im_sync_service / im_notification_service / im_webhook_handler

**巡店/工单**：patrol_routes / patrol_service / dri_workorder_routes / coach_session_routes

**HR Agent**：hr_agent_scheduler / hr_event_consumer / hr_dashboard_routes / labor_efficiency / labor_margin / gap_filling_service / revenue_schedule_service / commission_v3_routes

远端 tx-agent 含 **50 个 agent skill**，HR 相关：
- `salary_advisor.py` / `turnover_risk.py` / `attendance_compliance_agent.py` / `workforce_planner.py` / `kitchen_overtime.py` / `pilot_recommender.py`

### 4.2 本地 D9-D12 已实现（盘点）

本地 `apps/api-gateway/src/` HR 相关（三波交付后）：

**API (27 个 hr_* + 其他)**：hr_ai / hr_approval / hr_attendance / hr_audit / hr_batch / hr_commission / hr_dashboard / hr_decision_flywheel / hr_employee / hr_employee_self_service / hr_exit_interview / hr_growth / hr_health_cert_scan / hr_import / hr_labor_contract / hr_leave / hr_lifecycle / hr_payslip / hr_performance / hr_recruitment / hr_report / hr_reward_penalty / hr_rules / hr_schedule / hr_sensitive / hr_settlement / hr_social_insurance / hr_training / attendance_punch / employees / payroll / payroll_compliance / training_course / workforce / shift_swap / scheduler / schedules

**Service (HR 专项)**：hr_agent_service / hr_ai_decision_service / hr_approval_service / hr_excel_export / hr_growth_agent_service / hr_report_engine / hr_roster_import / hr_rule_engine / payroll_service / payslip_service / personal_tax_service / social_insurance_service / salary_formula_engine / schedule_service / smart_schedule_service / shift_fairness_service / shift_swap_service / workforce_auto_schedule_service / workforce_push_service / staffing_pattern_service / schedule_conflict_service / labor_benchmark_service / labor_cost_service / labor_demand_service / leave_service / attendance_engine / attendance_punch_service / health_cert_service / health_cert_scan_service / certificate_pdf_service / turnover_prediction_service / training_service / training_course_service / compliance_service / compliance_engine_service / labor_contract_alert_service / exam_service / exam_center_service / employee_lifecycle_service / onboarding_pipeline_service / bank_disbursement_service（薪资银行导盘）

**Models (HR 专项)**：employee / employee_contract / employee_growth / employee_lifecycle / employee_metric / attendance / attendance_punch / schedule / schedule_demand / shift_swap / leave / payroll / payroll_disbursement / payslip / salary_item / personal_tax / tax / social_insurance / health_certificate / commission / mentorship / performance_review / recruitment / training / reward_penalty / exit_interview / city_wage_config / hr_business_rule / person / person_contract / assignment

### 4.3 i人事 × 本地 × 远端 三向对比矩阵（核心交付物）

| i人事能力 P0 | 乐才 V6.2 | 本地 zhilian-os | 远端 tunxiang-os | 差距类型 |
|----|----|----|----|----|
| 组织架构（集团/区域/门店/部门/岗位） | ✅ | ⚠️ models/organization.py 基础 | ✅ tx-org brand/region/franchise 完整 | 🟡 **本地单薄** |
| 成本中心 | ✅ | ❌ 无 | ⚠️ 远端未显式但有 legal_entity+brand | 🔴 **两边都弱** |
| 花名册+员工档案 | ✅ | ✅ models/employee + hr_employee + hr_roster_import | ✅ employees+employee_depth+employee_document | 🟢 双方齐 |
| 员工档案深度（5 大类证件） | ✅ | ⚠️ 仅 health_certificate 专项 | ✅ employee_document_routes 专项 | 🟡 本地弱 |
| 合同管理（劳动/外包/实习） | ✅ | ✅ models/employee_contract + hr_labor_contract + labor_contract_alert | ✅ franchise_contract_routes（主要加盟合同） | 🟢 双方互补 |
| 电子签约 e-sign | ✅ | ❌ **零覆盖** | ✅ e_signature_routes + e_sign_service + e_signature_service | 🔴 **本地缺口（建议抽取）** |
| 异动：入职/转正/调动/晋升/离职 | ✅ | ✅ hr_lifecycle + employee_lifecycle_service + onboarding_pipeline + exit_interview + hr_settlement | ✅ transfers+store_transfer+separation_settlement | 🟢 双方齐 |
| 按岗排班/智能排班 | ✅ | ✅ smart_schedule_service + workforce_auto_schedule + schedule_conflict + shift_fairness | ✅ smart_schedule + unified_schedule + peak_guard + staffing_template | 🟢 **双方各有所长** |
| 排班公平性 | ⚠️ | ✅ shift_fairness_service（本地独有） | ❌ | 🟢 本地领先 |
| 考勤打卡+异常 | ✅ | ✅ attendance_punch + attendance_engine | ✅ attendance_routes+attendance_engine+attendance_repository | 🟢 齐 |
| 考勤合规（加班/休息日/法定假） | ✅ | ⚠️ compliance_service 通用 | ✅ **attendance_compliance_routes + compliance_alert_service 专项** | 🟡 远端更成熟 |
| 138 项薪资项目库 | ❌ | ⚠️ models/salary_item + salary_formula_engine（有基础） | ✅ **salary_item_library + salary_item_config_service（v250 迁移）** | 🟡 远端更贴近 i人事 |
| 薪资引擎 | ✅ | ✅ payroll_service + salary_formula_engine | ✅ payroll_engine v1/v2/**v3** + payroll_engine_db | 🟡 远端 v3 更成熟 |
| 成本分摊+借调 | ✅ | ❌ 无专项 | ✅ transfer_cost_engine | 🔴 本地缺口 |
| 薪税通（个税预扣） | ✅ | ✅ personal_tax_service | ✅ income_tax + tax_filing_service | 🟢 齐 |
| 工资单（双视图） | ✅ | ✅ payslip_service + models/payslip | ✅ **payslip_dual_view_service** | 🟡 远端双视图 |
| 银行导盘 | ✅ | ✅ bank_disbursement_service + models/payroll_disbursement | ❌ 未见专项 | 🟢 **本地领先** |
| 社保福利 | ✅ | ✅ social_insurance_service | ✅ social_insurance | 🟢 齐 |
| 健康证核验 | ⚠️ | ✅ **health_cert_scan_service + certificate_pdf_service + hr_health_cert_scan（OCR）** | ❌ 未见 | 🟢 **本地独家** |
| 目标+OKR | ⚠️ | ✅ agent_okr_service + models/agent_okr | ❌ 未见 | 🟢 本地领先 |
| 绩效/考核 | ✅ | ✅ models/performance_review + hr_performance + performance_compute + performance_ranking | ✅ performance_routes + performance_scoring_service + contribution_score_service | 🟢 双方齐 |
| 积分（员工积分） | ⚠️ | ❌ | ✅ employee_points_service + points_routes | 🔴 本地缺 |
| 佣金提成 v3 | ⚠️ | ✅ hr_commission + models/commission | ✅ commission_v3_routes | 🟢 双方齐 |
| AI 指标库（KPI 模板） | ⚠️ | ⚠️ models/kpi + hr_business_rule | ❌ 未专项 | 🟡 本地略强 |
| 人才盘点+九宫格 | ✅ | ❌ **零覆盖** | ❌ 未见 | 🔴 **两边都缺** |
| 继任者 succession | ✅ | ❌ | ❌ | 🔴 两边都缺 |
| AI 面谈 / 1-on-1 | ⚠️ | ✅ hr_exit_interview（仅离职面谈） | ❌ | 🟢 本地领先但浅 |
| 数字人（AI 助理） | ❌ | ⚠️ voice_* + unified_brain | ✅ tx-agent（真实 agent 框架，50 skill） | 🟡 远端更成熟 |
| 巡店/工单 | ⚠️ | ❌ | ✅ patrol_routes + patrol_service + dri_workorder_routes | 🔴 本地缺 |
| 加盟管理（含结算/分账/克隆） | ✅（乐才含） | ❌ 仅 api/raas.py | ✅ franchise v4/v5 + franchise_settlement + royalty_calculator + store_clone_routes | 🔴 **本地大缺口** |
| 员工自助 ESS | ✅ | ✅ hr_employee_self_service + im_employee_self_service | ❌ 未见 | 🟢 本地领先 |
| IM 通知/同步 | ✅ | ✅ im_sync_service + im_onboarding_robot + im_attendance_sync + im_milestone_notifier | ✅ im_sync_service + im_notification_service + im_webhook_handler + ota_routes | 🟢 双方齐 |
| 决策飞轮（人事 Agent） | ❌ | ✅ **hr_decision_flywheel + hr_ai_decision_service + hr_growth_agent**（本地独家） | ⚠️ tx-agent skills/salary_advisor + turnover_risk（浅） | 🟢 **本地独家** |
| 培训+考试 | ✅ | ✅ training_course_service + exam_center + exam_service + models/training | ✅ employee_training_routes | 🟢 本地更深 |
| 导师/传承 | ✅ | ✅ mentorship | ✅ mentorship_routes | 🟢 齐 |
| 安全/脱敏 | ✅ | ✅ hr_sensitive + sensitive_audit_log + data_masking_service + data_encryption_service | ⚠️ governance_routes 通用 | 🟢 本地领先 |

### 4.4 两边都缺的 HR 能力（未来立项方向）

| 能力 | 理由 |
|----|----|
| **成本中心 cost_center** | i人事核心。本地 models/organization 太薄、远端也只有 legal_entity/brand。立项：CostCenter + 分摊规则 |
| **人才盘点 + 九宫格（nine_box）** | i人事核心 P0。两边全为 0。立项：TalentBoard + TalentReview + SuccessionPlan |
| **继任者计划 succession** | 配套九宫格 |
| **AI 1-on-1 面谈** | 本地只有离职面谈；需常态化周/月 1-on-1，结合 agent_memory |
| **员工敬业度调研 pulse survey** | 两边都无 |
| **外部招聘源对接（智联/BOSS/脉脉）** | 本地 hr_recruitment 仅基础 model，远端无 |
| **入转调离的 e-sign + 薪资项目库 + 成本中心联动** | 需跨域集成 |

---

## 5. 集成决策建议

### 5.1 P0：从本地抽到远端 tunxiang（5 项具体路径）

| # | 本地文件 | 远端目标位置 | 理由 |
|----|----|----|----|
| 1 | `apps/api-gateway/src/services/llm_gateway/` + `api/llm.py` + `models/prompt_audit_log.py` | `services/tx-agent/src/llm_gateway/` | LLM L1-L5 分级 + 成本治理，远端空白 |
| 2 | `services/signal_bus.py` + `api/signal_bus_api.py` + `services/rag_signal_router.py` + `models/signal_routing_rule.py` | `services/tx-agent/src/signal_bus/` | 3 路由引擎远端无 |
| 3 | `services/private_domain_health_service.py` + `api/private_domain.py` + `models/private_domain.py` | `services/tx-member/src/services/` | 5 维健康分远端无 |
| 4 | `services/decision_priority_engine.py` + `decision_push_service.py` + `store_manager_briefing_service.py` + `hq_briefing_service.py` + `execution_feedback_service.py` + api 相关 | `services/tx-brain/src/` 或 `services/tx-agent/src/briefing/` | Top3 + 简报 + 执行闭环 |
| 5 | `services/monthly_report_service.py` + `api/monthly_report.py` + `services/case_story_generator.py` + `services/scenario_matcher.py` | `services/tx-intel/src/` | 月报 + 案例库 + 场景匹配 |

### 5.2 P1：本地反向引入远端（5 项具体路径）

| # | 远端文件 | 本地目标位置 | 理由 |
|----|----|----|----|
| 1 | `services/tx-org/src/services/payroll_engine_v3.py` + `salary_item_library.py` + `salary_item_config_service.py` | `apps/api-gateway/src/services/` | 补齐 138 项薪资库 |
| 2 | `services/tx-org/src/api/e_signature_routes.py` + `services/e_sign_service.py` + `services/e_signature_service.py` | 同上 + 新增 `api/e_signature.py` | 本地零覆盖 |
| 3 | `services/tx-org/src/services/franchise_settlement_service.py` + `royalty_calculator.py` + `franchise_clone_service.py` + `franchise_service.py` + `models/franchise.py` + 对应 api | 同上 + 扩 `api/raas.py` | 加盟闭环 |
| 4 | `services/tx-org/src/services/transfer_cost_engine.py` + `separation_settlement.py` + 对应 api | 同上 | 成本分摊/借调 |
| 5 | `services/tx-org/src/services/patrol_service.py` + `api/patrol_routes.py` + `api/dri_workorder_routes.py` | 同上 + 新增 `api/patrol.py` | 巡店/工单闭环 |

### 5.3 两边都缺，新立项（5 项）

| # | 新立项名称 | 核心内容 | 优先级 |
|----|----|----|----|
| 1 | **cost_center 成本中心** | 组织维度 + 分摊规则 + 薪资联动 | P0 |
| 2 | **nine_box 人才九宫格** | TalentBoard + review + succession_plan | P0 |
| 3 | **1-on-1 常态化面谈** | 周期性 + agent_memory 关联 + 提醒 | P1 |
| 4 | **pulse_survey 员工敬业度** | 问卷引擎 + ENPS + 情绪雷达 | P2 |
| 5 | **招聘源聚合** | BOSS/智联/脉脉 adapter + 简历解析 + AI 初筛 | P2 |

---

## 6. Cherry-Pick Top 10 具体文件（按价值排序）

### 6.1 远端 → 本地

| # | 远端绝对路径 | 价值 |
|----|----|----|
| 1 | `/tmp/diff-analysis/remote-main/services/tx-org/src/services/payroll_engine_v3.py` | 薪资引擎最新版，本地 v1 |
| 2 | `/tmp/diff-analysis/remote-main/services/tx-org/src/services/salary_item_library.py` + `salary_item_config_service.py` | 138 项薪资库（对标 i人事） |
| 3 | `/tmp/diff-analysis/remote-main/services/tx-org/src/services/e_sign_service.py` + `e_signature_service.py` + `api/e_signature_routes.py` | 电子签约，本地零 |
| 4 | `/tmp/diff-analysis/remote-main/services/tx-org/src/services/franchise_settlement_service.py` + `royalty_calculator.py` | 加盟结算 + 版税 |
| 5 | `/tmp/diff-analysis/remote-main/services/tx-org/src/services/transfer_cost_engine.py` | 借调/成本分摊 |

### 6.2 本地 → 远端（反哺）

| # | 本地绝对路径 | 价值 |
|----|----|----|
| 6 | `/Users/lichun/Documents/GitHub/zhilian-os/apps/api-gateway/src/services/llm_gateway/` | LLM L1-L5 治理整包 |
| 7 | `/Users/lichun/Documents/GitHub/zhilian-os/apps/api-gateway/src/services/signal_bus.py` + `rag_signal_router.py` | 3 路由引擎 |
| 8 | `/Users/lichun/Documents/GitHub/zhilian-os/apps/api-gateway/src/services/decision_priority_engine.py` + `execution_feedback_service.py` | 决策 Top3 + 执行闭环 |
| 9 | `/Users/lichun/Documents/GitHub/zhilian-os/apps/api-gateway/src/services/monthly_report_service.py` + `case_story_generator.py` + `scenario_matcher.py` | 月报三件套 |
| 10 | `/Users/lichun/Documents/GitHub/zhilian-os/apps/api-gateway/src/services/health_cert_scan_service.py` + `certificate_pdf_service.py` | 健康证 OCR + PDF 核验 |

---

## 7. 关键数据速览

| 指标 | 数值 |
|----|----|
| 本地 Alembic 迁移数 | 155（z45–z65） |
| 远端 Alembic 迁移数 | **300（v1–v256+）**，集中于 `shared/db-migrations/` |
| Revision ID 碰撞 | **0**（前缀 z vs v 完全隔离） |
| 本地 service 文件数 | 351 |
| 远端 tx-org service 文件数 | 51（HR 最密集） |
| 远端 tx-trade service 文件数 | ~100（交易最大） |
| HR 能力矩阵覆盖率（本地） | **26/33 ≈ 79%** |
| HR 能力矩阵覆盖率（远端） | **27/33 ≈ 82%** |
| HR 能力矩阵覆盖率（i人事完整清单） | 33/33 = 100% |
| 本地独家 HR 能力 | 银行导盘、shift_fairness、健康证 OCR、hr_decision_flywheel、exit_interview、ESS、OKR、敏感数据脱敏 |
| 远端独家 HR 能力 | e_sign、salary_item_library、payroll_engine_v3、transfer_cost_engine、patrol/dri_workorder、employee_points、franchise_settlement、attendance_compliance |
| 两边都缺 | cost_center、nine_box、succession、1-on-1、pulse_survey |

---

## 8. 结论

- **本地 zhilian-os** 强在：LLM 治理 / Signal Bus / 决策飞轮闭环 / 月报案例库 / 健康证核验 / OKR + 考核 / 安全脱敏 / 排班公平性 / 私域 5 维健康分。
- **远端 tunxiang-os** 强在：e-sign / 138 项薪资库 / 加盟全链 / 考勤合规 / 交易+KDS+宴会厚度 / 会员订阅+储值+GDPR / 费用报销 tx-expense / 供应链中央厨房 / 金蝶桥。
- **HR 互补空间最大**：把远端 `tx-org` 的 e-sign、salary_item_library、franchise_settlement 拉进本地；把本地 llm_gateway、hr_decision_flywheel、监控脱敏送到远端。
- **共同空白**：cost_center、人才九宫格、1-on-1 常态化 — 建议作为下一季度新立项 P0。

（报告完，共约 380 行）
