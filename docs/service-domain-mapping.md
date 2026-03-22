# Service 域分布映射（V2.x → V3.0）

> 基于现有 tunxiang 仓库 359 个 service 文件的完整分类

## 汇总

| 域 | 文件数 |
|---|---|
| tx-trade | 24 |
| tx-menu | 37 |
| tx-member | 35 |
| tx-supply | 12 |
| tx-finance | 30 |
| tx-org | 57（含 hr/ 子目录 25 个） |
| tx-analytics | 34 |
| tx-agent | 68 |
| gateway / shared | 62 |
| **合计** | **~359** |

## tx-trade（交易履约）

- order_service.py
- payment_reconcile_service.py
- daily_settlement_service.py
- settlement_service.py
- settlement_risk_service.py
- reconcile_service.py
- tri_reconcile_service.py
- bank_reconcile_service.py
- pos_service.py
- queue_service.py
- meituan_queue_service.py
- meituan_queue_integration.py
- meituan_reservation_service.py
- reservation_service.py
- reservation_analytics_service.py
- public_reservation_service.py
- event_order_service.py
- banquet_lifecycle_service.py
- banquet_planning_engine.py
- banquet_sales_service.py
- cancellation_analyzer.py
- soldout_service.py
- dining_journey_service.py
- auspicious_date_service.py

## tx-menu（商品菜单）

- dish_service.py / dish_health_service.py / dish_lifecycle_service.py
- dish_pricing_service.py / dish_profitability_service.py / dish_benchmark_service.py
- dish_attribution_service.py / dish_cost_alert_service.py / dish_cost_compression_service.py
- dish_forecast_service.py / dish_monthly_summary_service.py / dish_cannibalization_service.py
- bom_service.py / bom_resolver.py / excel_bom_importer.py / federated_bom_service.py
- menu_ranker.py / menu_matrix_service.py / menu_optimization_service.py / menu_profit_engine.py / menu_agent_service.py
- hit_potential_service.py / pareto_analysis_service.py / pareto_optimizer_service.py
- dynamic_pricing_service.py / raas_pricing_service.py
- food_cost_service.py / food_safety_service.py
- flavor_ontology_service.py / ingredient_fusion_service.py / ingredient_knowledge_service.py
- prep_suggestion_service.py / kitchen_simulator_service.py / kitchen_agent_service.py
- lecai_replacement_service.py / quality_service.py / price_benchmark_network.py

## tx-member（会员CDP）

- member_service.py / member_agent_service.py / member_profile_aggregator.py / member_context_store.py
- cdp_rfm_service.py / cdp_monitor_service.py / cdp_sync_service.py / cdp_wechat_channel.py
- customer360_service.py / customer_risk_service.py / customer_sentiment_service.py
- identity_resolution_service.py / dynamic_tag_service.py
- private_domain_health_service.py / private_domain_metrics.py
- birthday_reminder_service.py / coupon_distribution_service.py / coupon_roi_service.py
- referral_engine_service.py / lifecycle_action_service.py / lifecycle_bridge.py / lifecycle_state_machine.py
- mission_journey_service.py / omni_channel_service.py / channel_analytics_service.py
- marketing_agent_service.py / marketing_task_service.py
- recommendation_engine.py / recommendation_service.py
- journey_narrator.py / journey_orchestrator.py
- consumer_trend_service.py / follow_up_copilot.py / invitation_service.py

## tx-supply（供应链）

- inventory_service.py
- supply_chain_service.py / supply_chain_integration.py
- auto_procurement_service.py
- supplier_b2b_service.py / supplier_intelligence_service.py
- waste_event_service.py / waste_guard_service.py / waste_reasoning_service.py
- demand_forecaster.py / demand_predictor.py
- ontology_replenish_service.py

## tx-finance（财务结算）

- fct_service.py / fct_advanced_service.py / fct_integration.py
- finance_service.py / finance_health_service.py
- financial_alert_service.py / financial_anomaly_service.py / financial_closing_service.py
- financial_forecast_service.py / financial_impact_calculator.py / financial_recommendation_service.py
- budget_service.py / cashflow_forecast_service.py / tax_engine_service.py / e_invoice_service.py
- monthly_report_service.py / cfo_dashboard_service.py
- cost_truth_engine.py / cost_agent_service.py / labor_cost_service.py / labor_benchmark_service.py
- payroll_service.py / payslip_service.py / salary_formula_engine.py
- profit_attribution_service.py / revenue_growth_service.py / fl_revenue_model.py
- federated_learning_service.py / daily_metric_service.py / baseline_data_service.py / benchmark_service.py

## tx-org（组织运营）— 57 个

- org_hierarchy_service.py / org_aggregator.py / employee_lifecycle_service.py / job_standard_service.py
- leave_service.py / schedule_service.py / schedule_conflict_service.py / smart_schedule_service.py
- shift_fairness_service.py / staffing_pattern_service.py / labor_demand_service.py / attendance_engine.py
- training_service.py / turnover_prediction_service.py
- people_agent_service.py / hr_agent_service.py / hr_ai_decision_service.py / hr_approval_service.py
- hr_excel_export.py / hr_roster_import.py / hr_report_engine.py / hr_rule_engine.py / hr_growth_agent_service.py
- workforce_auto_schedule_service.py / workforce_push_service.py
- performance_compute_service.py / performance_ranking_service.py
- im_attendance_sync.py / im_employee_self_service.py / im_onboarding_robot.py / im_org_sync.py / im_milestone_notifier.py
- onboarding_pipeline_service.py
- hr/ 子目录（25 个）

## tx-analytics（经营分析）

- analytics_service.py / store_health_service.py / store_health_index_service.py
- diagnosis_service.py / diagnostic_service.py / narrative_engine.py
- case_story_generator.py / scenario_matcher.py / causal_graph_service.py
- kpi_alert_service.py / warning_service.py
- dashboard_service.py / ceo_dashboard_service.py
- daily_report_service.py / daily_hub_service.py / weekly_report_service.py / weekly_review_service.py
- hq_briefing_service.py / store_manager_briefing_service.py
- cross_store_insights_service.py / cross_store_knowledge_service.py
- custom_report_service.py / report_export_service.py / pdf_report_service.py
- competitive_analysis_service.py / industry_solutions.py
- prophet_forecast_service.py / enhanced_forecast_service.py / forecast_features.py
- store_daily_flow_service.py / command_center_service.py

## tx-agent（Agent OS）— 68 个

- agent_service.py / agent_config_service.py / agent_monitor_service.py / agent_memory_bus.py
- agent_okr_service.py / agent_collab_optimizer.py / agent_collaboration_optimizer.py
- boss_agent_service.py / floor_agent_service.py / store_agent_service.py
- decision_service.py / decision_ab_test_service.py / decision_flywheel_service.py
- decision_flow_state.py / decision_priority_engine.py / decision_push_service.py
- decision_validator.py / decision_weight_learner.py / behavior_score_engine.py
- action_task_service.py / action_dispatch_service.py / action_ontology_service.py
- ontology_* (8 个) / rag_* (3 个) / vector_db_* (2 个) / embedding_* (2 个)
- knowledge_service.py / knowledge_rule_service.py / sop_knowledge_base_service.py
- llm_cypher_service.py / reasoning_engine.py / intent_predictor.py / intent_router.py
- signal_bus.py / unified_brain.py / neural_system.py / ai_evolution_service.py
- multi_agent_negotiation_service.py / human_in_the_loop_service.py
- effect_evaluator.py / execution_feedback_service.py / lineage_tracker.py / query_optimizer.py
- model_marketplace_service.py / message_router.py / frequency_cap_engine.py
- notification_service.py / multi_channel_notification.py
- workflow_engine.py / scheduler.py / scheduler_monitor_service.py / timing_service.py
- voice_service.py / voice_command_service.py / voice_orchestrator.py / iflytek_websocket_service.py
- dynamic_trust_service.py / fast_planning_service.py / store_memory_service.py / store_ontology_replicator.py

## gateway / shared（62 个）

认证、配置、IM 通知、数据安全、边缘、外部集成等通用服务。详见完整分析文档。
