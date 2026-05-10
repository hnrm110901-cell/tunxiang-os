# Migration Table Ownership Audit (Route a — Per-service migrations)

> 由 `/tmp/ownership-audit.py` 自动生成。每张表按 `services/*/src/` 中 ORM
> models / repositories / services 文件 grep 命中数推断 canonical owner.
> 
> **Confidence 解释**：
> - **clear** — 单一 service 命中 3+ 文件，强信号
> - **weak** — 单一 service 命中 1-2 文件，弱信号需 audit
> - **ambiguous** — 多 service 同等命中数，**founder 必须决策保留哪个 service**
> - **shared** — 0 service 命中，候选 `shared/db-migrations-core/`
> - **multi-creator** — 表名出现在 2+ migration 文件的 CREATE TABLE 块（类 A 撞名）

## 总计：471 张表

- **clear**：126
- **weak**：298
- **ambiguous**：26
- **shared (no service ref)**：21
- **multi-creator (类 A 撞名)**：25

---

## Owner: `gateway` (15 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `api_access_tokens` | weak | gateway=1 | — |
| `api_applications` | weak | gateway=2 | — |
| `api_request_logs` | weak | gateway=1 | — |
| `api_webhooks` | weak | gateway=1 | — |
| `audit_logs` | clear | gateway=6, tx-org=1 | — |
| `billing_rules` | weak | gateway=2, tx-trade=1 | — |
| `group_mass_sends` | weak | gateway=1 | — |
| `group_tag_bindings` | weak | gateway=1 | — |
| `group_tags` | weak | gateway=1 | — |
| `material_groups` | weak | gateway=1 | — |
| `material_library` | weak | gateway=1 | — |
| `member_migration_pending` | weak | gateway=1 | — |
| `refresh_tokens` | weak | gateway=2 | — |
| `tenant_agent_configs` | clear | gateway=3 | — |
| `users` | clear | gateway=4, tx-growth=1, tx-org=1 | — |

## Owner: `gateway | tx-trade` (1 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `kds_display_rules` | ambiguous | gateway=1, tx-trade=1 | — |

## Owner: `shared/core` (21 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `ceo_cockpit_snapshots` | shared | — | — |
| `crew_schedules` | shared | — | — |
| `device_heartbeats` | shared | — | — |
| `kg_communities` | shared | — | — |
| `kg_edges` | shared | — | — |
| `kg_nodes` | shared | — | — |
| `knowledge_query_logs` | shared | — | — |
| `mv_session_analytics` | shared | — | — |
| `mv_table_turnover` | shared | — | — |
| `mv_waiter_performance` | shared | — | — |
| `offline_order_queue` | shared | — | — |
| `ota_check_logs` | shared | — | — |
| `payroll_deductions` | shared | — | — |
| `perf_score_items` | shared | — | — |
| `projector_rebuild_locks` | shared | — | — |
| `retail_cart_items` | shared | — | — |
| `retail_order_items` | shared | — | — |
| `retail_orders` | shared | — | — |
| `stocktake_loss_case_no_seq` | shared | — | — |
| `sync_checkpoints` | shared | — | — |
| `user_roles` | shared | — | — |

## Owner: `tx-agent` (30 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `agent_decision_logs` | clear | tx-agent=13, tx-analytics=2, tx-brain=1, tx-forge=3, tx-member=1, tx-org=1 | — |
| `agent_episodes` | clear | tx-agent=3 | — |
| `agent_memory_history` | weak | tx-agent=2 | — |
| `agent_procedures` | clear | tx-agent=3 | — |
| `banquet_ai_decisions` | weak | tx-agent=2, tx-trade=1 | — |
| `business_diagnosis_reports` | weak | tx-agent=2 | — |
| `customer_journey_enrollments` | weak | tx-agent=1 | — |
| `customer_journey_step_logs` | weak | tx-agent=1 | — |
| `customer_journey_steps` | weak | tx-agent=1 | — |
| `customer_journey_templates` | weak | tx-agent=1 | — |
| `knowledge_chunks` | weak | tx-agent=1 | — |
| `knowledge_documents` | weak | tx-agent=1 | — |
| `memory_feedback_signals` | weak | tx-agent=1 | — |
| `mv_discount_health` | clear | tx-agent=4, tx-analytics=1, tx-brain=3 | — |
| `operation_plans` | weak | tx-agent=1 | — |
| `pilot_items` | clear | tx-agent=3 | — |
| `pilot_metrics` | weak | tx-agent=2 | — |
| `pilot_programs` | clear | tx-agent=4 | — |
| `pilot_reviews` | weak | tx-agent=1 | — |
| `projector_checkpoints` | weak | tx-agent=2 | — |
| `sop_coaching_logs` | weak | tx-agent=2 | — |
| `sop_corrective_actions` | clear | tx-agent=4 | — |
| `sop_im_interactions` | weak | tx-agent=1 | — |
| `sop_quick_actions` | weak | tx-agent=1 | — |
| `sop_store_configs` | weak | tx-agent=2 | — |
| `sop_task_instances` | clear | tx-agent=4 | — |
| `sop_tasks` | clear | tx-agent=3 | — |
| `sop_templates` | clear | tx-agent=3 | — |
| `sop_time_slots` | clear | tx-agent=3 | — |
| `store_baselines` | weak | tx-agent=2 | — |

## Owner: `tx-agent | tx-brain | tx-org` (1 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `mv_store_pnl` | ambiguous | tx-agent=6, tx-analytics=4, tx-brain=6, tx-org=6 | — |

## Owner: `tx-agent | tx-forge` (1 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `model_call_logs` | ambiguous | tx-agent=1, tx-forge=1 | — |

## Owner: `tx-agent | tx-growth` (1 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `growth_agent_strategy_suggestions` | ambiguous | tx-agent=2, tx-growth=2 | — |

## Owner: `tx-agent | tx-org` (1 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `point_transactions` | ambiguous | tx-agent=1, tx-org=1 | — |

## Owner: `tx-agent | tx-trade` (2 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `banquet_demand_forecasts` | ambiguous | tx-agent=1, tx-trade=1 | — |
| `banquet_menu_templates` | ambiguous | tx-agent=1, tx-trade=1 | YES (2 files) |

## Owner: `tx-analytics` (10 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `banquet_analytics_snapshots` | weak | tx-analytics=1 | — |
| `banquet_lost_reasons` | weak | tx-analytics=2 | — |
| `brands` | clear | gateway=3, tx-analytics=6, tx-brain=1, tx-growth=2, tx-intel=1, tx-member=4, tx-ops=1, tx-org=3 | — |
| `experiment_definitions` | weak | tx-analytics=2 | — |
| `experiment_exposures` | weak | tx-analytics=1 | — |
| `ontology_snapshots` | weak | tx-analytics=2 | — |
| `report_exports` | weak | tx-analytics=1 | — |
| `report_instances` | weak | tx-analytics=1 | — |
| `report_subscriptions` | weak | tx-analytics=1 | — |
| `report_templates` | weak | tx-analytics=1 | — |

## Owner: `tx-analytics | tx-trade` (3 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `banquet_kds_dishes` | ambiguous | tx-analytics=1, tx-trade=1 | — |
| `banquet_session_deposits` | ambiguous | tx-analytics=1, tx-trade=1 | — |
| `table_sessions` | ambiguous | tx-analytics=2, tx-trade=2 | — |

## Owner: `tx-brain` (9 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `ab_experiment_arms` | weak | tx-brain=2 | — |
| `ab_experiment_assignments` | weak | tx-brain=1 | — |
| `ab_experiment_events` | weak | tx-brain=1 | — |
| `ab_experiments` | weak | tx-brain=2 | — |
| `mv_channel_margin` | clear | tx-agent=1, tx-brain=4, tx-growth=1, tx-trade=1 | — |
| `mv_daily_settlement` | clear | tx-agent=2, tx-analytics=1, tx-brain=3 | — |
| `mv_energy_efficiency` | clear | mcp-server=1, tx-analytics=1, tx-brain=3, tx-ops=1 | — |
| `mv_inventory_bom` | clear | tx-agent=2, tx-brain=5 | — |
| `mv_member_clv` | clear | mcp-server=1, tx-agent=2, tx-analytics=1, tx-brain=5, tx-growth=1, tx-member=1 | — |

## Owner: `tx-expense` (15 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `approval_nodes` | weak | tx-expense=1 | — |
| `approval_routing_rules` | weak | tx-expense=1 | — |
| `expense_applications` | clear | tx-expense=10 | — |
| `expense_attachments` | weak | tx-expense=2 | — |
| `expense_categories` | clear | tx-expense=7 | — |
| `expense_items` | clear | tx-expense=5 | — |
| `expense_notifications` | weak | tx-expense=2 | — |
| `expense_scenarios` | weak | tx-expense=1 | — |
| `expense_standards` | weak | tx-expense=1 | — |
| `invoice_items` | weak | tx-expense=2 | — |
| `invoices` | clear | gateway=1, tx-expense=9, tx-finance=7, tx-malaysia=1, tx-member=2, tx-trade=3 | YES (2 files) |
| `petty_cash_accounts` | weak | tx-expense=2 | — |
| `petty_cash_settlements` | weak | tx-expense=1 | — |
| `petty_cash_transactions` | weak | tx-expense=1 | — |
| `standard_city_tiers` | clear | tx-expense=3 | — |

## Owner: `tx-finance` (20 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `budget_executions` | clear | tx-finance=3 | — |
| `budget_forecast_analyses` | weak | tx-finance=2 | — |
| `budget_plans` | weak | tx-finance=2 | — |
| `cost_root_cause_analyses` | weak | tx-finance=2 | — |
| `cost_snapshots` | clear | tx-finance=9 | — |
| `erp_push_log` | clear | tx-finance=3 | — |
| `financial_vouchers` | clear | tx-finance=10 | — |
| `invoice_ocr_results` | weak | tx-finance=1 | — |
| `platform_bills` | weak | tx-finance=2 | — |
| `profit_split_records` | weak | tx-finance=2 | — |
| `profit_split_rules` | weak | tx-finance=1 | — |
| `purchase_invoices` | weak | tx-finance=1 | — |
| `purchase_match_records` | weak | tx-finance=2 | — |
| `receivable_forecasts` | weak | tx-finance=1 | — |
| `settlement_discrepancies` | weak | tx-finance=2 | — |
| `stored_value_split_ledger` | weak | tx-finance=2 | — |
| `stored_value_split_rules` | weak | tx-finance=1 | — |
| `sv_settlement_batches` | weak | tx-finance=1 | — |
| `vat_declarations` | weak | tx-finance=1 | — |
| `vat_input_invoices` | weak | tx-finance=1 | — |

## Owner: `tx-finance | tx-trade` (1 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `receiving_items` | ambiguous | tx-finance=1, tx-trade=1 | — |

## Owner: `tx-growth` (48 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `attribution_conversions` | clear | tx-growth=3 | — |
| `audience_pack_members` | weak | tx-growth=1 | — |
| `audience_pack_presets` | weak | tx-growth=1 | — |
| `audience_packs` | weak | tx-growth=1 | — |
| `brand_content_constraints` | weak | tx-growth=2 | — |
| `brand_profiles` | clear | tx-growth=3, tx-member=2 | — |
| `brand_seasonal_calendar` | weak | tx-growth=2 | — |
| `campaign_optimization_logs` | weak | tx-growth=2 | — |
| `campaign_participants` | clear | tx-growth=3 | — |
| `campaign_rewards` | weak | tx-growth=2 | — |
| `campaign_summaries` | weak | tx-agent=1, tx-growth=2 | — |
| `campaigns` | clear | gateway=1, tx-agent=6, tx-growth=23, tx-member=4, tx-trade=1 | — |
| `content_calendar` | clear | tx-growth=3 | — |
| `customer_growth_profiles` | clear | tx-growth=6 | — |
| `customer_profile_scores` | weak | tx-growth=1 | — |
| `discount_rules` | clear | tx-agent=1, tx-growth=6, tx-trade=3 | — |
| `dual_rewards` | weak | tx-growth=2 | — |
| `group_deal_participants` | weak | tx-growth=1 | — |
| `group_deals` | weak | tx-growth=1 | — |
| `growth_brand_configs` | clear | tx-growth=3 | — |
| `growth_journey_enrollments` | clear | tx-growth=3 | — |
| `growth_journey_template_steps` | clear | tx-growth=3 | — |
| `growth_journey_templates` | clear | tx-growth=4 | — |
| `growth_service_repair_cases` | weak | tx-growth=2 | — |
| `growth_touch_executions` | clear | tx-growth=7 | — |
| `growth_touch_templates` | weak | tx-growth=2 | — |
| `journey_definitions` | clear | tx-growth=5 | — |
| `journey_enrollments` | clear | tx-growth=3 | — |
| `journey_step_executions` | weak | tx-growth=2 | — |
| `live_code_channel_stats` | weak | tx-growth=1 | — |
| `live_code_scans` | weak | tx-growth=1 | — |
| `live_code_store_bindings` | weak | tx-growth=1 | — |
| `live_codes` | weak | tx-growth=1 | — |
| `live_coupons` | weak | tx-growth=2 | — |
| `live_events` | weak | tx-growth=2 | — |
| `marketing_task_assignments` | weak | tx-growth=1 | — |
| `marketing_task_effects` | weak | tx-growth=1 | — |
| `marketing_task_executions` | weak | tx-growth=2 | — |
| `marketing_tasks` | weak | tx-growth=2 | — |
| `sales_leads` | weak | tx-growth=1 | — |
| `sales_tasks` | weak | tx-growth=2 | — |
| `sales_visit_logs` | weak | tx-growth=1 | — |
| `stamp_card_instances` | weak | tx-growth=2, tx-member=1 | — |
| `stamp_card_stamps` | weak | tx-growth=2, tx-member=1 | — |
| `stamp_card_templates` | weak | tx-growth=2, tx-member=1 | — |
| `touch_events` | clear | tx-agent=1, tx-growth=3 | — |
| `ugc_submissions` | clear | tx-growth=3 | — |
| `viral_invite_chains` | weak | tx-growth=1 | — |

## Owner: `tx-growth | tx-predict` (1 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `churn_interventions` | ambiguous | tx-growth=1, tx-predict=1 | — |

## Owner: `tx-growth | tx-trade` (3 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `group_buy_activities` | ambiguous | tx-growth=1, tx-trade=1 | — |
| `group_buy_members` | ambiguous | tx-growth=1, tx-trade=1 | — |
| `group_buy_teams` | ambiguous | tx-growth=1, tx-trade=1 | — |

## Owner: `tx-intel` (10 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `ai_citation_monitors` | weak | tx-intel=2 | — |
| `competitor_brands` | clear | tx-intel=3 | — |
| `competitor_snapshots` | clear | tx-agent=1, tx-intel=4 | — |
| `geo_brand_profiles` | clear | tx-intel=3 | — |
| `intel_crawl_tasks` | weak | tx-intel=2 | — |
| `market_trend_signals` | weak | tx-agent=1, tx-intel=2 | — |
| `nps_surveys` | weak | tx-intel=2 | — |
| `reputation_alerts` | clear | tx-intel=3 | — |
| `review_auto_replies` | weak | tx-intel=2 | — |
| `review_intel` | clear | tx-agent=1, tx-intel=3 | — |

## Owner: `tx-malaysia` (2 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `pdpa_consent_logs` | weak | tx-malaysia=1 | — |
| `pdpa_requests` | weak | tx-malaysia=1 | — |

## Owner: `tx-member` (32 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `alliance_partners` | weak | tx-member=1 | — |
| `alliance_transactions` | weak | tx-member=2 | — |
| `badges` | clear | tx-member=3 | — |
| `campaign_roi_forecasts` | weak | tx-member=2 | — |
| `card_types` | weak | tx-member=2 | — |
| `challenge_progress` | weak | tx-member=2 | — |
| `challenges` | clear | tx-member=3 | — |
| `coupon_send_logs` | weak | tx-member=2 | — |
| `customer_lifecycle_state` | weak | tx-member=2 | — |
| `customer_suggestions` | weak | tx-member=1 | — |
| `external_order_imports` | weak | tx-member=2 | — |
| `gdpr_requests` | weak | tx-member=2 | — |
| `lifecycle_configs` | clear | tx-member=3 | — |
| `lifecycle_events` | clear | tx-member=3 | — |
| `marketing_schemes` | weak | tx-member=2 | — |
| `member_badges` | clear | tx-member=3 | — |
| `member_cards` | clear | tx-member=12 | — |
| `member_level_configs` | clear | tx-member=3 | — |
| `member_level_history` | clear | tx-member=3 | — |
| `member_points_balance` | clear | tx-member=3 | — |
| `points_log` | clear | tx-member=5 | — |
| `points_mall_achievement_configs` | clear | tx-member=3 | — |
| `points_mall_categories` | weak | tx-member=2 | — |
| `points_rules` | weak | tx-member=2 | — |
| `recharge_commission_rules` | weak | tx-member=1 | — |
| `recharge_performance` | weak | tx-member=1 | — |
| `rfm_outreach_campaigns` | clear | tx-member=3 | — |
| `smart_recharge_recommendations` | weak | tx-member=1 | — |
| `smart_recharge_rules` | weak | tx-member=1 | — |
| `stored_value_transactions` | clear | tx-analytics=1, tx-finance=1, tx-member=4, tx-trade=3 | YES (2 files) |
| `surprise_rules` | weak | tx-member=2 | — |
| `wifi_visit_logs` | clear | tx-member=3, tx-ops=1 | — |

## Owner: `tx-member | tx-trade` (1 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `stored_value_accounts` | ambiguous | tx-analytics=1, tx-growth=1, tx-member=4, tx-trade=4 | YES (2 files) |

## Owner: `tx-menu` (19 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `channel_menu_items` | clear | tx-menu=6 | — |
| `channel_menu_versions` | weak | tx-menu=2 | — |
| `channel_pricing_rules` | weak | tx-menu=1 | — |
| `dish_affinity_matrix` | weak | tx-menu=2 | — |
| `dish_co_occurrence` | weak | tx-menu=1 | — |
| `dish_pricing_suggestions` | clear | tx-menu=3 | YES (2 files) |
| `dynamic_pricing_logs` | weak | tx-menu=1 | — |
| `dynamic_pricing_rules` | weak | tx-menu=1 | — |
| `menu_channel_prices` | weak | tx-menu=1 | — |
| `menu_dispatch_records` | weak | tx-menu=1 | — |
| `menu_publish_requests` | weak | tx-menu=2 | — |
| `menu_template_dishes` | weak | tx-menu=1 | — |
| `menu_templates` | weak | tx-menu=2 | — |
| `menu_versions` | weak | tx-menu=1 | — |
| `store_menu_permissions` | weak | tx-menu=1 | — |
| `store_menu_publishes` | weak | tx-menu=2 | — |
| `store_room_menus` | weak | tx-menu=1 | — |
| `store_seasonal_menus` | weak | tx-menu=1 | — |
| `upsell_prompts` | weak | tx-menu=2 | — |

## Owner: `tx-menu | tx-trade` (1 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `platform_dish_mappings` | ambiguous | tx-menu=1, tx-trade=1 | — |

## Owner: `tx-ops` (11 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `approval_step_records` | clear | tx-ops=3, tx-org=2 | — |
| `conversion_funnel_daily` | weak | tx-ops=1 | — |
| `customer_journey_timings` | weak | tx-ops=2, tx-org=1 | — |
| `energy_alert_rules` | weak | tx-ops=1 | — |
| `energy_budgets` | weak | tx-ops=2 | — |
| `inspection_reports` | weak | tx-ops=2 | — |
| `mv_safety_compliance` | weak | tx-ops=1 | — |
| `ops_issues` | weak | tx-ops=2 | — |
| `shift_device_checklist` | weak | tx-ops=2 | — |
| `shift_records` | weak | tx-ops=2 | — |
| `staff_performance_records` | weak | tx-ops=1 | — |

## Owner: `tx-ops | tx-org` (5 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `patrol_issues` | ambiguous | tx-ops=1, tx-org=1 | — |
| `patrol_record_items` | ambiguous | tx-ops=1, tx-org=1 | — |
| `patrol_records` | ambiguous | tx-ops=1, tx-org=1 | — |
| `patrol_template_items` | ambiguous | tx-ops=1, tx-org=1 | — |
| `satisfaction_ratings` | ambiguous | tx-ops=1, tx-org=1 | — |

## Owner: `tx-ops | tx-trade` (1 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `queue_tickets` | ambiguous | tx-ops=1, tx-trade=1 | — |

## Owner: `tx-org` (51 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `app_versions` | weak | tx-org=1 | — |
| `approval_flow_definitions` | weak | tx-org=1 | — |
| `approval_flow_nodes` | clear | tx-org=3 | — |
| `approval_flow_templates` | clear | tx-org=4 | — |
| `approval_instances` | clear | tx-expense=1, tx-ops=3, tx-org=7 | YES (3 files) |
| `approval_node_instances` | clear | tx-org=3 | — |
| `approval_records` | weak | tx-org=1 | — |
| `approval_workflow_templates` | weak | tx-org=2 | — |
| `attendance_compliance_logs` | weak | tx-org=1 | — |
| `attendance_records` | clear | tx-analytics=1, tx-org=9 | — |
| `bonus_rules` | weak | tx-org=1 | — |
| `compliance_alerts` | clear | tx-agent=1, tx-analytics=3, tx-intel=3, tx-ops=5, tx-org=6 | — |
| `contract_signing_records` | weak | tx-org=1 | — |
| `contract_templates` | weak | tx-org=1 | — |
| `daily_scorecards` | weak | tx-org=2 | — |
| `device_registry` | weak | tx-org=2, tx-trade=1 | — |
| `employee_point_logs` | weak | tx-org=2 | — |
| `employee_role_assignments` | weak | tx-org=1 | — |
| `employee_salary_configs` | weak | tx-org=2 | — |
| `employee_trainings` | clear | tx-analytics=1, tx-intel=1, tx-org=3 | — |
| `employee_transfers` | weak | tx-org=1 | — |
| `franchisee_stores` | clear | tx-org=4, tx-trade=3 | YES (2 files) |
| `franchisees` | clear | tx-org=14, tx-trade=3 | YES (2 files) |
| `horse_race_seasons` | weak | tx-org=1 | — |
| `job_grades` | clear | tx-org=3 | — |
| `patrol_templates` | weak | tx-org=1 | — |
| `payroll_records` | clear | tx-analytics=1, tx-finance=4, tx-org=8, tx-supply=1 | — |
| `payroll_records_v2` | clear | tx-org=5 | — |
| `payroll_summaries` | weak | tx-agent=1, tx-analytics=1, tx-org=2 | — |
| `payslip_records` | weak | tx-org=1 | — |
| `permission_check_logs` | weak | tx-org=1 | — |
| `point_redemptions` | weak | tx-org=1 | — |
| `point_rewards` | weak | tx-org=1 | — |
| `review_cycles` | weak | tx-org=2 | — |
| `review_scores` | weak | tx-org=2 | — |
| `role_configs` | clear | tx-agent=1, tx-org=6 | — |
| `role_level_defaults` | weak | tx-org=1 | — |
| `salary_anomaly_analyses` | weak | tx-org=2 | — |
| `salary_item_templates` | weak | tx-org=2 | — |
| `salary_schemes` | weak | tx-org=2 | — |
| `sales_progress` | clear | tx-org=3 | — |
| `sales_targets` | clear | tx-growth=1, tx-org=4 | YES (2 files) |
| `shift_gaps` | clear | tx-agent=1, tx-org=4 | — |
| `shift_templates` | clear | tx-org=4 | — |
| `social_insurance_configs` | weak | tx-org=2 | — |
| `store_lifecycle_stages` | weak | tx-org=1 | — |
| `store_push_configs` | clear | tx-org=3, tx-trade=2 | — |
| `store_transfer_orders` | weak | tx-org=2 | — |
| `tax_declarations` | weak | tx-org=1 | — |
| `transfer_cost_allocations` | weak | tx-org=1 | — |
| `unified_schedules` | clear | tx-agent=2, tx-org=7 | — |

## Owner: `tx-org | tx-trade` (3 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `crew_shift_swaps` | ambiguous | tx-org=1, tx-trade=1 | — |
| `departments` | ambiguous | tx-agent=2, tx-analytics=1, tx-expense=1, tx-ops=2, tx-org=6, tx-trade=6 | — |
| `royalty_bills` | ambiguous | tx-org=3, tx-trade=3 | YES (2 files) |

## Owner: `tx-pay` (2 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `payment_channel_configs` | weak | tx-pay=2 | — |
| `payment_idempotency` | weak | tx-pay=1 | — |

## Owner: `tx-predict` (1 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `churn_scores` | weak | tx-predict=2 | — |

## Owner: `tx-supply` (39 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `central_kitchen_profiles` | weak | tx-supply=1 | — |
| `delivery_items` | weak | tx-supply=2 | — |
| `delivery_temperature_logs` | weak | tx-supply=2 | — |
| `delivery_trips` | weak | tx-supply=2 | — |
| `distribution_drivers` | weak | tx-supply=1 | — |
| `distribution_orders` | weak | tx-supply=2 | — |
| `distribution_plans` | weak | tx-supply=2 | — |
| `distribution_store_geos` | weak | tx-supply=1 | — |
| `distribution_warehouses` | weak | tx-supply=2 | — |
| `ingredient_location_bindings` | weak | tx-supply=2 | — |
| `inventory_by_location` | clear | tx-supply=4 | — |
| `inventory_thresholds` | clear | tx-supply=3 | — |
| `mrp_demand_lines` | weak | tx-supply=1 | — |
| `mrp_forecast_plans` | weak | tx-supply=1 | — |
| `mrp_planned_issues` | weak | tx-supply=1 | — |
| `mrp_procurement_suggestions` | weak | tx-supply=1 | — |
| `mrp_production_suggestions` | weak | tx-supply=1 | — |
| `procurement_feedback_logs` | weak | tx-supply=2 | — |
| `production_orders` | weak | tx-supply=1 | — |
| `production_plans` | clear | tx-supply=3 | YES (2 files) |
| `production_tasks` | clear | tx-supply=3 | — |
| `receiving_orders` | weak | tx-finance=1, tx-supply=2, tx-trade=1 | — |
| `stocktake_items` | clear | tx-supply=3, tx-trade=1 | YES (2 files) |
| `stocktake_loss_approvals` | weak | tx-supply=2 | — |
| `stocktake_loss_cases` | weak | tx-supply=2 | — |
| `stocktake_loss_items` | weak | tx-supply=2 | — |
| `stocktake_loss_writeoffs` | weak | tx-supply=2 | — |
| `stocktakes` | clear | tx-supply=3 | — |
| `store_receiving_confirmations` | weak | tx-supply=2 | — |
| `supplier_accounts` | weak | tx-supply=2 | — |
| `supplier_profiles` | clear | tx-supply=3 | — |
| `supplier_quotations` | weak | tx-supply=1 | — |
| `supplier_reconciliations` | weak | tx-supply=1 | — |
| `supplier_score_history` | clear | tx-supply=4 | — |
| `warehouse_locations` | weak | tx-supply=2 | — |
| `warehouse_transfer_items` | weak | tx-supply=1 | — |
| `warehouse_transfers` | weak | tx-supply=1 | — |
| `warehouse_zones` | weak | tx-supply=2 | — |
| `yield_alerts` | weak | tx-supply=1 | — |

## Owner: `tx-trade` (110 tables)

| Table | Confidence | Service refs | Multi-creator? |
|---|---|---|---|
| `api_idempotency_cache` | clear | tx-trade=3 | — |
| `banquet_approval_logs` | weak | tx-trade=1 | — |
| `banquet_capacity_conflicts` | weak | tx-trade=2 | — |
| `banquet_competitive_benchmarks` | weak | tx-trade=2 | — |
| `banquet_confirmations` | weak | tx-trade=2 | — |
| `banquet_contract_amendments` | weak | tx-trade=1 | — |
| `banquet_contracts` | clear | tx-agent=2, tx-trade=7 | YES (2 files) |
| `banquet_day_schedules` | weak | tx-trade=2 | — |
| `banquet_deposits` | clear | tx-trade=3 | — |
| `banquet_eo_tickets` | weak | tx-trade=2 | — |
| `banquet_execution_logs` | weak | tx-trade=2 | — |
| `banquet_execution_plans` | weak | tx-agent=1, tx-trade=2 | — |
| `banquet_feedbacks` | clear | tx-trade=4 | — |
| `banquet_guest_check_ins` | weak | tx-trade=1 | — |
| `banquet_kpi_snapshots` | weak | tx-trade=2 | — |
| `banquet_lead_follow_ups` | weak | tx-trade=2 | YES (2 files) |
| `banquet_lead_transfers` | weak | tx-trade=2 | YES (2 files) |
| `banquet_leads` | clear | tx-agent=4, tx-analytics=1, tx-trade=14 | YES (3 files) |
| `banquet_live_orders` | clear | tx-trade=3 | — |
| `banquet_material_requirements` | weak | tx-agent=1, tx-trade=2 | — |
| `banquet_production_plans` | weak | tx-agent=1, tx-trade=2 | — |
| `banquet_production_tasks` | weak | tx-trade=2 | — |
| `banquet_purchase_orders` | weak | tx-trade=2 | — |
| `banquet_quote_items` | weak | tx-trade=2 | YES (2 files) |
| `banquet_quotes` | clear | tx-trade=3 | YES (2 files) |
| `banquet_referrals` | weak | tx-trade=2 | — |
| `banquet_settlement_items` | weak | tx-trade=2 | — |
| `banquet_settlements` | weak | tx-trade=2 | — |
| `banquet_status_logs` | weak | tx-trade=2 | YES (2 files) |
| `banquet_table_groups` | weak | tx-trade=1 | YES (2 files) |
| `banquet_venue_bookings` | clear | tx-trade=3 | YES (2 files) |
| `banquet_venues` | clear | tx-trade=4 | YES (2 files) |
| `banquets` | clear | tx-agent=6, tx-trade=9 | YES (2 files) |
| `booking_prep_tasks` | weak | tx-trade=2 | — |
| `call_customer_matches` | weak | tx-trade=1 | — |
| `call_records` | weak | tx-trade=1 | — |
| `callback_tasks` | weak | tx-trade=2 | — |
| `canonical_delivery_items` | weak | tx-trade=1 | — |
| `canonical_delivery_orders` | weak | tx-trade=2 | — |
| `channel_canonical_orders` | weak | tx-trade=2 | — |
| `channel_disputes` | weak | tx-trade=1 | — |
| `checkout_discount_log` | clear | tx-trade=3 | — |
| `chef_performance_daily` | clear | tx-trade=3 | — |
| `crew_checkin_records` | weak | tx-trade=1 | — |
| `crew_shift_summaries` | weak | tx-trade=2 | — |
| `customer_bookings` | weak | tx-trade=1 | — |
| `delivery_dispatches` | clear | tx-trade=5 | — |
| `delivery_dispute_messages` | clear | tx-trade=3 | — |
| `delivery_disputes` | clear | tx-trade=4 | YES (2 files) |
| `delivery_orders` | clear | tx-analytics=1, tx-finance=1, tx-trade=14 | — |
| `delivery_platform_configs` | clear | tx-trade=3 | — |
| `delivery_platform_items` | weak | tx-trade=1 | — |
| `delivery_provider_configs` | clear | tx-trade=4 | — |
| `delivery_reviews` | weak | tx-trade=1 | — |
| `delivery_store_configs` | weak | tx-trade=1 | — |
| `discount_audit_log` | weak | tx-analytics=1, tx-trade=2 | — |
| `dish_allergens` | weak | tx-trade=1 | — |
| `dish_dept_mappings` | clear | tx-agent=1, tx-org=1, tx-trade=7 | — |
| `dish_publish_registry` | weak | tx-trade=2 | — |
| `dish_publish_tasks` | weak | tx-trade=2 | — |
| `dish_scan_logs` | weak | tx-trade=1 | — |
| `dispatch_codes` | weak | tx-trade=1 | — |
| `edge_device_registry` | clear | tx-trade=4 | — |
| `enterprise_accounts` | weak | tx-trade=2 | — |
| `enterprise_agreement_prices` | weak | tx-trade=1 | — |
| `enterprise_bills` | weak | tx-trade=1 | — |
| `enterprise_meal_accounts` | weak | tx-trade=1 | — |
| `enterprise_meal_menus` | weak | tx-trade=1 | — |
| `enterprise_meal_orders` | weak | tx-trade=2 | — |
| `enterprise_sign_records` | weak | tx-trade=2 | — |
| `events` | clear | gateway=3, mcp-server=2, tx-agent=24, tx-analytics=7, tx-brain=4, tx-civic=3, tx-devforge=1, tx-expense=3, tx-finance=12, tx-forge=2, tx-growth=17, tx-intel=1, tx-member=16, tx-menu=6, tx-ops=22, tx-org=19, tx-pay=3, tx-supply=18, tx-trade=52 | — |
| `franchise_audits` | clear | tx-org=2, tx-trade=3 | — |
| `franchise_settlement_items` | clear | tx-org=1, tx-trade=3 | — |
| `franchise_settlements` | clear | tx-org=1, tx-trade=3 | — |
| `invitation_instances` | weak | tx-trade=1 | — |
| `invitation_templates` | weak | tx-trade=1 | — |
| `kds_display_configs` | weak | tx-trade=1 | — |
| `kds_piecework_records` | weak | tx-trade=2 | — |
| `kds_piecework_schemes` | weak | tx-trade=1 | — |
| `kds_task_steps` | weak | tx-trade=2 | — |
| `kitchen_capacity_slots` | clear | tx-trade=3 | — |
| `manager_discount_requests` | weak | tx-trade=1 | — |
| `offline_order_mapping` | clear | tx-trade=6 | — |
| `order_courses` | weak | tx-trade=1 | — |
| `order_seats` | weak | tx-trade=1 | — |
| `patrol_logs` | weak | tx-trade=1 | — |
| `payment_sagas` | weak | tx-ops=1, tx-pay=1, tx-trade=2 | YES (2 files) |
| `platform_health_snapshots` | weak | tx-trade=2 | — |
| `printer_routes` | clear | tx-trade=3 | — |
| `printers` | clear | gateway=2, tx-org=1, tx-trade=5 | — |
| `production_steps` | weak | tx-trade=2 | — |
| `refund_requests` | weak | tx-trade=2 | — |
| `reservation_invitations` | clear | tx-agent=2, tx-trade=4 | — |
| `retail_products` | weak | tx-trade=1 | — |
| `saga_buffer_meta` | weak | tx-trade=1 | — |
| `scan_pay_transactions` | weak | tx-trade=2 | — |
| `service_bell_calls` | weak | tx-trade=1 | — |
| `soldout_records` | clear | tx-trade=3 | — |
| `split_payments` | weak | tx-trade=1 | — |
| `stocktake_sessions` | weak | tx-trade=1 | — |
| `table_layouts` | weak | tx-trade=1 | — |
| `tasks` | clear | gateway=3, mcp-server=2, tx-agent=21, tx-analytics=2, tx-expense=3, tx-finance=2, tx-growth=6, tx-intel=2, tx-member=1, tx-menu=1, tx-ops=5, tx-org=6, tx-supply=5, tx-trade=30 | — |
| `trade_audit_logs` | clear | tx-trade=11 | — |
| `waiter_calls` | weak | tx-trade=1 | — |
| `waitlist_call_logs` | weak | tx-trade=1 | — |
| `waitlist_entries` | weak | tx-trade=1 | — |
| `xhs_coupon_verifications` | weak | tx-trade=1 | — |
| `xhs_poi_mappings` | weak | tx-trade=1 | — |
| `xiaohongshu_shop_bindings` | weak | tx-trade=2 | — |
| `xiaohongshu_verify_events` | weak | tx-trade=2 | — |
