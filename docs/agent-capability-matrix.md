# Agent 能力矩阵（31 个 Agent → 9+1 合并映射）

> 完整梳理现有 31 个 Agent 的能力清单，确保合并为 V3.0 的 9 Skill Agent + 1 Master Agent 时不丢失能力。

## 合并映射总表

| V3.0 Agent | 来源 Agent | 方法数合计 | 核心能力 |
|-----------|-----------|-----------|---------|
| **Master Agent** | LLMEnhancedAgent(532行) + OntologyAdapter(237行) | 13 | Tool Use Loop/流式/Memory Bus/Neo4j 查询/BOM/损耗溯源 |
| **1.折扣守护** | ComplianceAgent(219行) + FctAgent 部分(136行) | 10 | 证照扫描/告警推送/凭证解释/对账状态/7种报表 |
| **2.智能排菜** | dish_rd(738行) + QualityAgent(201行) + menu_ranker | 8+3 | 成本仿真/试点推荐/复盘/上市检查/风险预警/图片质检 |
| **3.出餐调度** | order(1100行) + schedule(1050行) + ops_flow(950行) | 30+12+5 | 点餐全流程/排班/客流分析/RL优化/链式告警/订单异常 |
| **4.会员洞察** | private_domain(960行) + service(1050行) | 11+7 | RFM/旅程/信号/竞对/差评/反馈/投诉/服务质量 |
| **5.库存预警** | InventoryAgent(337行) + inventory(921行) + supplier(1050行) | 5+6+5 | 需求预测/库存优化/损耗/保质期/补货/供应商评级/合同风险 |
| **6.财务稽核** | FctAgent(136行) + DecisionAgent(260行) + business_intel(800行) | 7+3+5 | 财务报表/营收异常/KPI快照/订单预测/洞察/场景识别 |
| **7.巡店质检** | OpsAgent(456行) + QualityAgent(201行) + ops_flow 部分 | 11+3 | 健康检查/故障诊断/Runbook/预测维护/安全/食安/质检 |
| **8.智能客服** | service(1050行) + training(1400行) | 7+8 | 反馈/投诉/质量监控/培训需求/计划/进度/效果/证书 |
| **9.私域运营** | private_domain(960行) + people_agent(600行) + reservation(1200行) + banquet(430行) | 11+5+9+5 | 私域全链路/人力管理/预订/宴会 |

## 详细能力清单

### Master Agent（编排中心）
- `execute_with_tools()` — Claude Tool Use 完整 agentic loop
- `execute_with_llm()` — 单轮 LLM 调用
- `execute_with_fallback()` — LLM + 规则降级
- `stream_response()` — WebSocket 流式输出
- `publish_finding()` / `get_peer_context()` — Agent Memory Bus
- `query_ontology()` — Neo4j Cypher 查询
- `get_dish_bom()` / `get_waste_events()` / `explain_reasoning()` — 本体数据

### 1. 折扣守护 Agent
来源：ComplianceAgent + FctAgent
- 证照扫描：scan_store / scan_all / check_license
- 企微告警推送
- 财务报表：7种报表类型 + 凭证解释 + 对账状态
- **新增（V3.0）**：实时折扣异常检测（边缘 Core ML）

### 2. 智能排菜 Agent
来源：dish_rd + QualityAgent
- 成本仿真：BOM 计算 + 多定价方案 + 涨价压力测试
- 试点推荐：门店匹配度评分 + 建议规模/周期
- 复盘优化：销售/退菜/差评聚合 → keep/optimize/monitor/retire
- 上市检查：配方/成本/SOP/试点/审批 Checklist
- 风险预警：成本超标/试点低分/高退菜/差评聚集
- 图片质检：视觉模型评分 + 不合格告警
- **新增（V3.0）**：四象限分类、各渠道价格管理

### 3. 出餐调度 Agent
来源：order + schedule + ops_flow
- 点餐全流程：开单/加菜/动态定价/推荐/AR菜单/语音点餐/结算/支付
- 排班：客流分析 → 需求计算 → 生成 → 多目标优化 → 满意度评估
- 跨店排班/跨区域调配/强化学习优化
- 链式告警：1→3层联动（订单/库存/质检）
- 订单异常检测 + 库存预警
- **新增（V3.0）**：边缘出餐时间预测（Core ML）

### 4. 会员洞察 Agent
来源：private_domain + service
- RFM 分层 + 行为信号检测 + 竞对监控
- 会员自动化旅程（欢迎/生日/召回/会员日）
- 差评处理（情感分析 + 自动回复 + 挽留旅程）
- 服务反馈收集/分析 + 投诉处理闭环
- 服务质量监控 + 员工服务追踪
- **新增（V3.0）**：Golden ID 全渠道画像

### 5. 库存预警 Agent
来源：InventoryAgent + inventory + supplier
- 需求预测（4种算法：移动平均/加权/线性/季节性）
- 低库存告警（Critical/Urgent/Warning 三级）
- 库存优化（安全/最低/最高三水位线）
- 损耗分析 + 保质期管理
- 补货计划生成
- 供应商评级/价格对比/自动寻源/合同风险/供应链风险
- **新增（V3.0）**：边缘库存消耗计算（Core ML）

### 6. 财务稽核 Agent
来源：FctAgent + DecisionAgent + business_intel
- 7种财务报表 + 凭证解释 + 对账状态
- 营收异常分析 + 订单趋势分析
- KPI 快照 + 订单量预测 + 经营洞察
- 场景识别 + 经营建议生成
- **新增（V3.0）**：银企直连、多实体合并、税务自动申报

### 7. 巡店质检 Agent
来源：OpsAgent + ops_flow 部分
- 健康检查（软件/硬件/网络三域）
- 故障诊断 + Runbook + 预测维护
- 安全加固建议 + 链路切换决策
- IT 资产台账 + 自然语言运维问答
- 告警收敛 + 食安合规状态
- 菜品图片质检

### 8. 智能客服 Agent
来源：service + training
- 反馈收集/分析/情感分析
- 投诉处理（优先级/分配/方案/闭环）
- 培训需求评估 + 计划生成 + 进度追踪 + 效果评估
- 技能差距分析 + 证书管理
- 服务改进建议

### 9. 私域运营 Agent
来源：private_domain + people_agent + reservation + banquet
- 私域：门店象限/流失风险/旅程/信号
- 人力：排班优化/绩效/人力成本/出勤/人力规划
- 预订：创建/确认/取消/座位分配/提醒/分析/BEO
- 宴会：跟进/报价/排期/执行/复盘

## 绩效与提成（独立模块，不合并到 Agent）

PerformanceAgent(1303行) + performance(480行) 的绩效计分和提成计算能力建议作为 tx-org 域的独立 Service，而非 Agent。原因：纯规则引擎，不需要 LLM 推理。

## 三条硬约束校验（V3.0 新增）

所有 9 个 Skill Agent 的决策输出必须通过：
1. **毛利底线** — 折扣/赠送不可使单笔毛利低于阈值
2. **食安合规** — 临期/过期食材不可用于出品
3. **客户体验** — 出餐时间不可超过门店设定上限

现有 DecisionValidator 已在 5 个 API 层 Agent 中使用，V3.0 扩展为全 Agent 强制中间件。
