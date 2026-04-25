# Sprint D1 D1 — 51 Skill ConstraintChecker 批次推进计划

**版本**：v1（2026-04-25 落地批次 1）  
**对应 PR**：services/tx-agent constraints 框架 + decorator + 10 P0 Skill 接入  
**主线规范**：CLAUDE.md §6（三条硬约束）、§9（决策留痕）、§13（禁止突破约束）、§17（Tier 2）

---

## 1. 目标

将 `services/tx-agent/src/agents/skills/` 下 51 个 Skill **全部**接入 `@with_constraint_check`，
使每次决策都经过三条硬约束（毛利底线 / 食安合规 / 客户体验）的硬阻断校验，关闭 base.py
soft-warn 路径里"违反约束的决策仍会被返回"的风险。

**完成定义**：
- 51 个 Skill 的 `execute()` 都打了 `DECORATOR_MARKER_ATTR` 标记
- `test_constraint_coverage_all_p0_skills_decorated` 在 51 个 Skill 上全绿
- 没有任何 Skill 用 `constraint_scope=set()` 避开约束而不附带 ≥30 字符的 `constraint_waived_reason`
- AgentDecisionLog schema 完全不变（D2 决策点 #1 创始人签字到位前，绝不动 schema）

---

## 2. 已接入清单（批次 1，本 PR 落地）

| # | agent_id | 类 | 优先级 | 主 scope | 备注 |
|---|---|---|---|---|---|
| 1 | discount_guard | DiscountGuardAgent | P0 | margin/safety/experience（默认全 3） | 类未声明 scope，全 3 自动校验 |
| 2 | smart_menu | SmartMenuAgent | P0 | margin | simulate_cost 直接算 margin |
| 3 | serve_dispatch | ServeDispatchAgent | P1 | experience | predict_serve_time 已填 estimated_serve_minutes |
| 4 | inventory_alert | InventoryAlertAgent | P1 | margin+safety | check_expiration 填 IngredientSnapshot 列表 |
| 5 | finance_audit | FinanceAuditAgent | P1 | margin/safety/experience（默认全 3） | flag_discount_anomaly 用 margin |
| 6 | cashier_audit | CashierAuditAgent | P0 | margin | audit_transaction 折扣/挂账核销 |
| 7 | member_insight | MemberInsightAgent | P1 | margin | trigger_journey 发券冲毛利 |
| 8 | compliance_alert | ComplianceAlertAgent | P1 | waived | 类级 scope=set()，装饰器仅作 CI 标识 |
| 9 | ingredient_radar | IngredientRadarAgent | P1 | margin/safety/experience（默认全 3） | predict_cost 用 margin, check_compliance 用 safety |
| 10 | menu_advisor | MenuAdvisorAgent | P1 | margin | optimize_pricing 取最差毛利菜品作基准 |

10 个 Skill 标记验证：`pytest services/tx-agent/src/tests/test_constraint_coverage.py::test_constraint_coverage_all_p0_skills_decorated`

---

## 3. 待接入清单（批次 2-7，41 Skill）

按业务域分类，每周接入一批，每批 7-8 个 Skill。批次顺序按"业务影响"由高到低排：
**资金 → 出餐 → 库存 → 客户触达 → HR/合规 → 内容/洞察 → 边缘剩余项**。

### 批次 2（W22 / 2026-W22）—— 出餐体验 + 资金补强（7 Skill）

| agent_id | 类 | 优先级 | 主 scope | 接入要点 |
|---|---|---|---|---|
| ai_waiter | AIWaiterAgent | P1 | margin+experience | 推菜决策的 dish.price+cost 已存在；experience 字段需在响应里补 estimated_serve_minutes |
| voice_order | VoiceOrderAgent | P0 | experience | 语音点单完成后 result.data 需追加 estimated_serve_time_seconds |
| smart_service | SmartServiceAgent | P2 | experience | 服务推送决策填 estimated_serve_minutes |
| queue_seating | QueueSeatingAgent | P1 | experience | 排队叫号填 estimated_serve_minutes |
| kitchen_overtime | KitchenOvertimeAgent | P1 | experience | 厨房超时告警直接复用 estimated_serve_minutes |
| table_dispatch | TableDispatchAgent | P1 | experience | 已填 ConstraintContext，仅缺装饰器 |
| billing_anomaly | BillingAnomalyAgent | P1 | margin | 账单异常已带 price+cost |

### 批次 3（W23）—— 库存原料（7 Skill）

| agent_id | 类 | 主 scope | 接入要点 |
|---|---|---|---|
| stockout_alert | StockoutAlertAgent | margin+safety | 缺货告警含临期判断；result.data 已带 ingredients |
| new_product_scout | NewProductScoutAgent | margin+safety | 新品 BOM 试算 |
| trend_discovery | TrendDiscoveryAgent | waived | 类级已声明 set()，仅打 CI 标识 |
| pilot_recommender | PilotRecommenderAgent | waived | 同上 |
| banquet_growth | BanquetGrowthAgent | margin | 宴会金额预算 |
| private_ops | PrivateOpsAgent | margin | 私域发券 |
| enterprise_activation | EnterpriseActivationAgent | margin | 企业开户金额 |

### 批次 4（W24）—— 定价营销（7 Skill）

| agent_id | 类 | 主 scope | 接入要点 |
|---|---|---|---|
| points_advisor | PointsAdvisorAgent | margin | 积分兑换金额 |
| seasonal_campaign | SeasonalCampaignAgent | margin | 活动折扣金额 |
| personalization_agent | PersonalizationAgent | margin | 个性化优惠金额 |
| new_customer_convert | NewCustomerConvertAgent | margin | 首单优惠金额 |
| referral_growth | ReferralGrowthAgent | margin | 推荐奖励金额 |
| dormant_recall | DormantRecallAgent | margin | 召回券金额 |
| high_value_member | HighValueMemberAgent | margin | VIP 维护成本 |

### 批次 5（W25）—— 合规运营 / HR（8 Skill，4 豁免 + 4 真实）

| agent_id | 类 | 主 scope | 接入要点 |
|---|---|---|---|
| attendance_compliance_agent | AttendanceComplianceAgent | waived | HR 观察类 |
| attendance_recovery | AttendanceRecoveryAgent | waived | HR 观察类 |
| turnover_risk | TurnoverRiskAgent | waived | HR 观察类 |
| salary_anomaly | SalaryAnomalyAgent | waived | HR 观察类（薪资异常本身不冲约束） |
| workforce_planner | WorkforcePlannerAgent | margin | 排班成本 |
| store_inspect | StoreInspectAgent | safety | 巡店食安项 |
| off_peak_traffic | OffPeakTrafficAgent | margin+experience | 引流活动毛利 + 客流出餐节奏 |
| salary_advisor | SalaryAdvisorAgent | waived | HR 建议类 |

### 批次 6（W26）—— 内容洞察 / 客服（7 Skill）

| agent_id | 类 | 主 scope | 接入要点 |
|---|---|---|---|
| review_insight | ReviewInsightAgent | waived | 评论分析观察类 |
| review_summary | ReviewSummaryAgent | waived | 评论汇总观察类 |
| intel_reporter | IntelReporterAgent | waived | 情报报告观察类 |
| audit_trail | AuditTrailAgent | waived | 审计追溯观察类 |
| growth_coach | GrowthCoachAgent | waived | 增长教练建议类 |
| smart_customer_service | SmartCustomerServiceAgent | waived | 客服观察类 |
| competitor_watch | CompetitorWatchAgent | waived | 竞争监控观察类 |

### 批次 7（W27）—— 边缘剩余项（5 Skill）

| agent_id | 类 | 主 scope | 接入要点 |
|---|---|---|---|
| ai_marketing_orchestrator | AiMarketingOrchestratorAgent | margin | 营销编排 |
| growth_attribution | GrowthAttributionAgent | margin | 已填 ConstraintContext，仅加装饰器 |
| closing_agent | ClosingAgent | margin+safety | 闭店流程含食安+预算 |
| content_generation | ContentGenerationAgent | waived | 纯生成内容 |
| cost_diagnosis | CostDiagnosisAgent | margin | 成本诊断 |

### Sprint D3/D4 新增 Skill（4 个）

到批次 6 时同步纳入：
- `cost_root_cause` (D4a) — margin
- `rfm_outreach` (D3a) — margin
- `salary_anomaly` (D4b) — waived
- `budget_forecast` (D4c) — margin

---

## 4. 每批次的接入要点（哪些 Skill 需要业务侧补 payload）

### 4.1 Skill 决策已带相关字段（最简单，纯加装饰器）

直接 `@with_constraint_check(skill_name="...")` 即可，例：
- `growth_attribution.execute` 已 return AgentResult(context=ConstraintContext(...))
- `table_dispatch.execute` 已填 estimated_serve_minutes
- `closing_agent` 已填 price/cost/ingredients

### 4.2 Skill 漏字段需补（约 60% Skill）

需在 `execute()` 路径里识别决策是否真实触发金额/食材/出餐，
然后补入 result.data 对应字段。规则：
- 涉及金额变更（折扣/赠送/返现/会员价）→ 补 `price_fen` + `cost_fen`
- 涉及食材出品（菜品/套餐/赠送）→ 补 `ingredients` 列表
- 涉及出餐节奏（推菜/排队/排班）→ 补 `estimated_serve_minutes`

如果 Skill 真不触碰任何一类决策，类级声明 `constraint_scope = set()` +
`constraint_waived_reason`（≥30 字符，禁用"N/A"/"不适用"/"跳过"黑名单）。

### 4.3 需要 InventoryRepository 注入的 Skill（食安路径）

只持有 `ingredient_ids` 不持有 `remaining_hours` 的 Skill（如 menu_advisor /
smart_menu 提建议时）需要在初始化阶段注入 `inventory_repository`：
```python
agent = MenuAdvisorAgent(tenant_id=..., db=db_session)
agent.inventory_repository = my_inventory_repo  # SkillContext 自动从 self 取
```
食安 check 会自动调 `repository.fetch_expiry_status(tenant_id, ingredient_ids)`。
**批次 4-5 集中铺设这条注入链**，由 Master Agent 编排时统一注入，单 Skill 不应自查。

### 4.4 阈值门店化（批次 7 + 后续运维迭代）

当前 `SkillContext` 阈值：min_margin_rate=15% / expiry_buffer_hours=24 / max_serve_minutes=30。
门店配置接入路径（待 D2 后启动）：
- `store_config` 表加 3 列（如有需要可加 RLS-aware 视图）
- `_build_context()` 优先级：`params._store_thresholds` > `Skill 实例属性` > 模块默认
- 路由层在创建 SkillAgent 时从 store_config 注入

---

## 5. 风险与边界

### 5.1 不得触碰（与本 PR 一致，整个 D1 周期持续生效）

- `services/tx-trade/**` — 25 commits 等 §19 二次审查（与本 D1 PR 完全无交叉）
- `shared/ontology/**` — 冻结
- `AgentDecisionLog` 表结构 — D2 决策点 #1 待签字
- 任何 Skill 的业务 happy path / dispatch / handler — 装饰器只在外层套约束

### 5.2 兼容性边界

- `with_constraint_check` 默认 `raise_on_block=False`：result 透传 + 注入 `_constraint_blocked`
- `base.py::SkillAgent.run()` 既有 ConstraintChecker 仍会运行，与装饰器结果一致（同源逻辑）
- 显式硬阻断（`raise_on_block=True`）适用于 Master Agent 与外部业务路由直接 `await skill.execute()` 的场景，
  在本 D1 范围内 Master Agent 默认仍走 run()（软告警）—— 切到硬阻断的灰度策略待 D5/D6 评估

### 5.3 与既有 `constraint_scope` 框架的关系

- `agents/context.py::ConstraintContext` + `agents/constraints.py::ConstraintChecker` —— 既有的
  per-result soft-warn 体系，**保留**且不改动语义
- `constraints/` 包是上层硬阻断装饰器，复用既有 ConstraintChecker 阈值，独立模块化便于扩展
- 51 Skill 已 100% 在 `SKILL_REGISTRY`（既有 D1 批次 6 完成），本 PR 的覆盖建立在此基础上

---

## 6. CI 门禁演进路线

每接入一批，更新 `services/tx-agent/src/tests/test_constraint_coverage.py::D1_BATCH_1_DECORATED_SKILLS`：
- 批次 2 → 批次 1+2 共 17 个
- 批次 3 → 共 24 个
- 批次 4 → 共 31 个
- 批次 5 → 共 39 个
- 批次 6 → 共 46 个
- 批次 7 → 共 51 个（D1 完成）

到 51 个时再加一条：
```python
def test_all_skill_registry_entries_are_decorated():
    """100% 覆盖门禁：SKILL_REGISTRY 中每个 Skill 类都有 @with_constraint_check"""
    from agents.skills import SKILL_REGISTRY
    missing = [aid for aid, cls in SKILL_REGISTRY.items()
               if not getattr(cls.execute, DECORATOR_MARKER_ATTR, None)]
    assert not missing, f"未覆盖: {missing}"
```

之后 SKILL_REGISTRY 任何新增 Skill 都自动被门禁卡住。

---

## 7. 时间线

| 周次 | 批次 | Skill 数 | 累计 | 责任人 | 状态 |
|---|---|---|---|---|---|
| W21 | 1 | 10 | 10 | 本 PR | ✅ 完成 |
| W22 | 2 | 7 | 17 | 待分配 | 🔴 |
| W23 | 3 | 7 | 24 | 待分配 | 🔴 |
| W24 | 4 | 7 | 31 | 待分配 | 🔴 |
| W25 | 5 | 8 | 39 | 待分配 | 🔴 |
| W26 | 6 | 7 | 46 | 待分配 | 🔴 |
| W27 | 7 | 5+4 | 55 | 待分配 | 🔴 |

> 总数 55 = 51（既有）+ 4（D3/D4 新增）。批次 7 落地时 D1 D1 整体收敛。

---

## 8. 参考

- CLAUDE.md §6（三条硬约束）、§9（决策留痕）、§13（禁止突破）、§17（Tier 2）
- `services/tx-agent/src/agents/constraints.py` — 既有 soft-warn ConstraintChecker
- `services/tx-agent/src/agents/context.py` — ConstraintContext 与 IngredientSnapshot
- `services/tx-agent/src/constraints/` — 本 PR 新框架包
- `services/tx-agent/src/tests/test_constraint_context.py` — 既有 38 个 scope 测试
- `services/tx-agent/src/tests/test_constraint_coverage.py` — 本 PR 新 13 个 CI 门禁测试
