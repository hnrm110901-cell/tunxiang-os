# Phase 3 Materialized View Switch Checklist

> Event Sourcing + CQRS Phase 3: "Agent 和报表切换为只读物化视图（不再跨服务查询）"
>
> Gate: 环境变量 `TX_AGENT_USE_MV_READS=true` 启用 MV 读路径，默认 false（降级到直接查询）
>
> 创建日期: 2026-05-03

---

## Materialized Views (13 total)

### v148 — 原始 8 个（因果链系列）

| # | 物化视图 | 因果链 | 消费者 | 状态 |
|---|----------|--------|--------|------|
| 1 | `mv_discount_health` | 1 — 折扣率/授权链/泄漏类型 | discount_guard, 老板报表 | [x] switched |
| 2 | `mv_channel_margin` | 2 — 各渠道真实到手毛利 | ai_marketing_orchestrator, 财务报表 | [x] switched |
| 3 | `mv_inventory_bom` | 3 — BOM理论vs实际耗用差异 | inventory_alert, 后厨管理 | [ ] not switched |
| 4 | `mv_member_clv` | 5 — 会员生命周期价值 | member_insight, 营销决策 | [x] switched |
| 5 | `mv_store_pnl` | 4 — 门店实时P&L | salary_advisor, 老板仪表盘 | [x] switched |
| 6 | `mv_daily_settlement` | 7 — 日清日结状态/差异项 | closing_agent, 财务 | [ ] not switched |
| 7 | `mv_safety_compliance` | 8 — 食安检查完成率/违规 | store_inspect, 管理后台 | [ ] not switched |
| 8 | `mv_energy_efficiency` | 9 — 能耗/营收比/IoT异常 | 管理后台 | [ ] not switched |

### v385 — 新增 4 个

| # | 物化视图 | 用途 | 消费者 | 状态 |
|---|----------|------|--------|------|
| 9 | `mv_table_turnover` | 翻台率/桌均营收 | table_dispatch, 店长报表 | [x] switched |
| 10 | `mv_dish_profitability` | 菜品维度的真实盈利 | menu_advisor, ai_marketing_orchestrator | [x] switched |
| 11 | `mv_employee_efficiency` | 人效指标/出勤评分 | turnover_risk, salary_advisor | [x] switched |
| 12 | `mv_customer_ltv` | 客户LTV/流失风险 | member_insight, CRM报表 | [x] switched |

### 单独迁移

| # | 物化视图 | 用途 | 消费者 | 状态 |
|---|----------|------|--------|------|
| 13 | `mv_public_opinion` | 舆情/点评聚合 | review_insight, intel_reporter | [ ] not switched |

### 附加

| # | 物化视图 | 用途 | 消费者 | 状态 |
|---|----------|------|--------|------|
| - | `mv_agent_roi_monthly` | Agent ROI 月度汇总 | tx-agent | [ ] not switched |
| - | `mv_table_utilization` | 桌台利用率（v287） | table_dispatch | [ ] not switched |

---

## Agent Skills — MV Switch Status

### Switched (C2-Agent, 2026-05-03)

| Skill | 文件 | 使用 MV | 方法 | Gate 模式 |
|-------|------|---------|------|-----------|
| discount_guard | `skills/discount_guard.py` | mv_discount_health | `_get_daily_discount_health` → `_get_discount_health_from_mv` | `_USE_MV_READS` gate + `_get_discount_health_direct` fallback |
| discount_guard | `skills/discount_guard.py` | mv_discount_health | `_build_discount_health_result` (shared result builder) | dynamic `source` tag |
| member_insight | `skills/member_insight.py` | mv_member_clv, mv_customer_ltv | `_rfm_analysis` → `_rfm_from_mv` | `_USE_MV_READS` gate + `_rfm_direct` fallback |
| member_insight | `skills/member_insight.py` | mv_member_clv | `_update_customer_rfm` (single customer lookup) | `_USE_MV_READS` gate + orders direct fallback |
| member_insight | `skills/member_insight.py` | mv_member_clv | `_get_clv_snapshot` (already Phase 3) | direct MV read |
| turnover_risk | `skills/turnover_risk.py` | mv_employee_efficiency | `_calculate_risk_score` (enrichment) | `_scan_from_mv_employee_efficiency` enriches dimension scores |
| salary_advisor | `skills/salary_advisor.py` | mv_employee_efficiency | `_load_current_staffing` | `_USE_MV_READS` gate + employees direct fallback |
| salary_advisor | `skills/salary_advisor.py` | mv_store_pnl | `_load_store_pnl` (already using MV) | direct MV read |
| table_dispatch | `skills/table_dispatch.py` | mv_table_turnover | `_analyze_utilization` (enrichment) | `_USE_MV_READS` gate + params fallback |
| ai_marketing_orchestrator | `skills/ai_marketing_orchestrator.py` | mv_dish_profitability, mv_channel_margin | `_check_marketing_constraints` | `_fetch_mv_margin_data` + DEFAULT_AVG_ORDER_FEN fallback |
| ai_marketing_orchestrator | `skills/ai_marketing_orchestrator.py` | mv_channel_margin | `_marketing_health_score` (channel coverage enrichment) | `_USE_MV_READS` gate + params fallback |

### Not Yet Switched (Candidates for future phases)

| Skill | 文件 | 当前查询 | 候选 MV | 优先级 | 原因 |
|-------|------|----------|---------|--------|------|
| inventory_alert | `skills/inventory_alert.py` | direct: inventory | mv_inventory_bom | P1 | 库存预警 Agent |
| closing_agent | `skills/closing_agent.py` | direct: settlement tables | mv_daily_settlement | P1 | 日清日结 Agent |
| store_inspect | `skills/store_inspect.py` | direct: safety tables | mv_safety_compliance | P2 | 巡店质检 Agent |
| review_insight | `skills/review_insight.py` | — | mv_public_opinion | P2 | 差评分析 Agent |
| intel_reporter | `skills/intel_reporter.py` | — | mv_public_opinion | P2 | 商业智能 Agent |
| cost_diagnosis | `skills/cost_diagnosis.py` | direct: cost tables | mv_store_pnl | P1 | 成本诊断 Agent |
| stockout_alert | `skills/stockout_alert.py` | direct: inventory | mv_inventory_bom | P1 | 断货预警 Agent |
| kitchen_overtime | `skills/kitchen_overtime.py` | direct: order/KDS | mv_table_turnover | P1 | 出餐延迟 Agent |
| discount_guard (detect) | `skills/discount_guard.py` | orders (single-row) | N/A | N/A | 事件驱动的单行查询，不适合 MV |

---

## Analytics Routes — MV Switch Status

> 待评估，未包含在本次 C2-Agent 变更范围内。

| Service | 文件/路由 | 当前数据源 | 候选 MV | 状态 |
|---------|-----------|-----------|---------|------|
| tx-analytics | `nlq_routes.py` | direct cross-service | mv_* (various) | [ ] not switched |
| tx-analytics | dashboard routes | direct cross-service | mv_store_pnl, mv_channel_margin | [ ] not switched |
| tx-analytics | CEO cockpit | direct cross-service | mv_store_pnl, mv_daily_settlement | [ ] not switched |

---

## Shared MV Reader

**文件**: `services/tx-agent/src/agents/mv_reader.py`

提供 13 个异步读取函数，对应所有物化视图：

| 函数 | 读取视图 | 参数 |
|------|---------|------|
| `get_discount_health()` | mv_discount_health | tenant_id, store_id?, stat_date?, days |
| `get_channel_margin()` | mv_channel_margin | tenant_id, store_id?, channel?, stat_date?, days |
| `get_inventory_bom()` | mv_inventory_bom | tenant_id, store_id?, stat_date?, days, min_loss_rate |
| `get_member_clv()` | mv_member_clv | tenant_id, min_clv_fen?, churn_threshold?, top_n |
| `get_store_pnl()` | mv_store_pnl | tenant_id, store_id?, stat_date?, months |
| `get_daily_settlement()` | mv_daily_settlement | tenant_id, store_id?, stat_date?, status?, days |
| `get_safety_compliance()` | mv_safety_compliance | tenant_id, store_id?, weeks |
| `get_energy_efficiency()` | mv_energy_efficiency | tenant_id, store_id?, stat_date?, days |
| `get_table_turnover()` | mv_table_turnover | tenant_id, store_id?, stat_date?, stat_hour?, days |
| `get_dish_profitability()` | mv_dish_profitability | tenant_id, store_id?, stat_date?, category?, min_margin_rate?, days, top_n |
| `get_employee_efficiency()` | mv_employee_efficiency | tenant_id, store_id?, employee_id?, stat_date?, role_type?, days, top_n |
| `get_customer_ltv()` | mv_customer_ltv | tenant_id, min_predicted_ltv_fen?, churn_risk_threshold?, ltv_tier?, top_n |
| `get_public_opinion()` | mv_public_opinion | tenant_id, store_id?, platform?, days, min_sentiment_score?, top_n |

---

## Rollout Plan

### Phase C2 (current)
- [x] Create `mv_reader.py` shared helper
- [x] Add MV gate to 6 agent skill files
- [x] Default: `TX_AGENT_USE_MV_READS=false` (safe fallback)

### Phase C2-verify
- [ ] Run agent tests with `TX_AGENT_USE_MV_READS=true`
- [ ] Verify MV data freshness vs direct queries
- [ ] Compare response times (target: < 5ms for MV vs > 100ms for cross-service)

### Phase C2-default
- [ ] After verification, set `TX_AGENT_USE_MV_READS=true` as default
- [ ] Remove direct query fallbacks (or keep as emergency rollback)

### Phase C3 (analytics)
- [ ] Switch tx-analytics dashboard routes to MV reads
- [ ] Switch CEO cockpit to MV reads
- [ ] Switch NLQ routes to MV reads

### Phase C4 (remaining agents)
- [ ] inventory_alert → mv_inventory_bom
- [ ] closing_agent → mv_daily_settlement
- [ ] store_inspect → mv_safety_compliance
- [ ] review_insight → mv_public_opinion
- [ ] cost_diagnosis → mv_store_pnl
- [ ] stockout_alert → mv_inventory_bom

---

## Performance Targets

| 指标 | 当前（直接查询） | 目标（MV 读取） |
|------|-----------------|----------------|
| 单视图查询延迟 | 50-200ms (跨服务) | < 5ms (本地 PG) |
| Agent 决策延迟 | 500ms-2s | < 200ms |
| 跨服务调用次数 | 3-5 per agent action | 0 (MV) |
| 数据库连接数 | 1 per service | 1 (单 PG) |

---

## Known Risks

1. **MV 数据新鲜度**: 物化视图由投影器异步更新，可能有 300 秒延迟（sync-engine 周期）。实时性要求高的场景（如折扣异常检测的单笔订单）不适合 MV，应保持直接查询。
2. **MV 未填充**: 新安装环境或事件流中断时，MV 可能为空。所有 MV 读函数都有降级路径。
3. **mv_public_opinion 表结构**: 该表由单独迁移创建，列名可能与 mv_reader.py 中的通用模式不完全对齐。
