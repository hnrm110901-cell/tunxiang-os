# 屯象 Forge 升级迭代路线图 v3.0

> 对标 Salesforce AgentExchange · ServiceNow AI Control Tower · Anthropic Claude Marketplace · Palantir AIP
> 基准日期: 2026-04-26 · 当前版本: Forge v1.0 (39端点/9表/18页面)

---

## 一、战略定位升级

### 从"开发者市场"到"Agent Exchange"

| 维度 | v1.0 当前 | v3.0 目标 |
|------|----------|----------|
| **定位** | ISV 应用商店 | 餐饮AI Agent Exchange — 统一 Agent/Skill/Action/Adapter/Tool 发现平台 |
| **核心资产** | 10类应用 + 6种定价 | Ontology-bound Agent 生态 + MCP 协议原生 + 结果计价 |
| **治理** | 人工审核 + RLS | AI Control Tower + 信任分级 + 实时熔断 + OWASP Agentic Top 10 |
| **发现** | 分类浏览 + 文本搜索 | 意图推断搜索 + 场景推荐 + Agent 组合建议 |
| **计价** | 固定6模型(免费→按量) | +结果计价(每次成功转化/每笔挽回GMV) + Token 计量 |
| **协议** | REST API + Webhook | MCP (Model Context Protocol) 原生 + Event Sourcing |

---

## 二、版本规划总览

```
v1.0  ████████████ 当前 — 基础市场(39端点/9表/18页面/AI OPS)
v1.5  ████         W1-W2 — 治理地基 + 信任体系 + MCP
v2.0  ████████     W3-W6 — Agent Exchange + 结果计价 + 智能发现
v2.5  ████         W7-W8 — 开发者赋能 + 自动化审核
v3.0  ████████     W9-W14 — 生态飞轮 + 跨品牌联盟 + 全球化
```

---

## 三、v1.5 治理地基 (Week 1-2, 12张表, ~45端点)

> 核心理念: "先治理,后规模" — ServiceNow 和 Salesforce 的共同教训

### Sprint G1: Agent 治理框架 (Week 1)

#### 1.1 信任分级体系 (Trust Tiers)

| 等级 | 名称 | 要求 | 能力范围 |
|------|------|------|----------|
| T0 | 实验室 | Labs Alpha 提交 | 只能在沙箱运行,不触及生产数据 |
| T1 | 社区 | 实名认证 + 代码扫描通过 | 只读数据访问,无资金操作 |
| T2 | 认证 | 安全审计 + 3个月运行记录 + ★4.0+ | 读写数据,可触发非资金类Action |
| T3 | 信赖 | 屯象团队审计 + 等保合规 + ★4.5+ | 完整能力,含资金操作(折扣/退款) |
| T4 | 官方 | 屯象自研 | 无限制 |

**新表**: `forge_trust_tiers` — 信任等级定义 + 能力矩阵
**新表**: `forge_trust_audits` — 等级升降审计日志

```python
# 信任等级决定 Agent 运行时权限边界
class TrustTierPolicy:
    T0_SANDBOX_ONLY = {"data_access": "none", "actions": "none", "financial": False}
    T1_COMMUNITY    = {"data_access": "read", "actions": "none", "financial": False}
    T2_CERTIFIED    = {"data_access": "read_write", "actions": "non_financial", "financial": False}
    T3_TRUSTED      = {"data_access": "read_write", "actions": "all", "financial": True}
    T4_OFFICIAL     = {"data_access": "full", "actions": "all", "financial": True}
```

#### 1.2 Agent 运行时沙箱 (Runtime Sandbox)

对标 Microsoft Agent Governance Toolkit + OWASP Agentic Top 10:

**新表**: `forge_runtime_policies` — Agent 运行时权限策略
- `app_id` → 关联应用
- `trust_tier` → 当前信任等级
- `allowed_entities` JSONB → 可访问的 Ontology 实体 (Store/Order/Customer/Dish/...)
- `allowed_actions` JSONB → 可执行的 Action 白名单
- `token_budget_daily` → 日 Token 预算上限
- `rate_limit_rpm` → 每分钟请求限制
- `kill_switch` BOOLEAN → 紧急熔断开关
- `sandbox_mode` BOOLEAN → 沙箱模式(不写入生产)

**新表**: `forge_runtime_violations` — 运行时违规记录
- `violation_type` → permission_denied / token_exceeded / rate_limited / constraint_violated / kill_switched
- `agent_id`, `app_id`, `context` JSONB
- 触发自动降级规则: 3次P1违规 → 自动降一级信任

#### 1.3 OWASP Agentic Top 10 合规检查

在审核流程中嵌入10项安全检查:

| # | 威胁 | 检查方式 | 自动化 |
|---|------|----------|--------|
| 1 | 目标劫持 | Prompt 注入测试套件 | ✅ CI自动 |
| 2 | 工具滥用 | Action 白名单 + 调用审计 | ✅ 运行时 |
| 3 | 权限过度 | 最小权限原则检查 | ✅ 审核时 |
| 4 | 失控 Agent | Token 预算 + 熔断开关 | ✅ 运行时 |
| 5 | 记忆投毒 | 记忆内容审计 + 签名 | 🔶 人工抽检 |
| 6 | 级联失败 | 依赖图分析 + 断路器 | ✅ 运行时 |
| 7 | 数据泄露 | PII 检测 + 数据流审计 | ✅ CI自动 |
| 8 | 输出篡改 | 三条硬约束强制校验 | ✅ 运行时 |
| 9 | 模型窃取 | API 速率限制 + 异常检测 | ✅ 运行时 |
| 10 | 供应链攻击 | 依赖 CVE 扫描 + 签名验证 | ✅ CI自动 |

### Sprint G2: MCP 原生集成 (Week 2)

#### 2.1 MCP Server 注册表

对标 Anthropic MCP 生态 (5,000+ servers, 2,000+ official):

**新表**: `forge_mcp_servers` — MCP Server 注册
- `server_id`, `app_id` → 关联应用
- `transport` → stdio / sse / streamable-http
- `capabilities` JSONB → tools[] / resources[] / prompts[]
- `schema_version` → MCP 协议版本
- `health_endpoint` → 健康检查 URL
- `auto_discovery` BOOLEAN → 是否支持自动发现

**新表**: `forge_mcp_tools` — MCP Tool 目录
- `tool_id`, `server_id`
- `tool_name`, `description`
- `input_schema` JSONB → JSON Schema
- `ontology_bindings` JSONB → 绑定到哪些 Ontology 实体
- `trust_tier_required` → 调用此工具需要的最低信任等级

#### 2.2 Ontology Binding (对标 Palantir AIP)

每个 Forge 应用必须声明它操作的 Ontology 实体:

```yaml
# FORGE_MANIFEST.yaml (新的应用清单格式)
forge_version: "1.5"
app_id: "app_smart_pricing"
trust_tier: T2

ontology:
  reads:
    - entity: Dish
      fields: [name, price_fen, cost_fen, category]
    - entity: Order
      fields: [total_fen, items, created_at]
  writes:
    - entity: Dish
      fields: [price_fen]  # 只能修改价格
      constraints:
        - "new_price >= cost_fen * 1.28"  # 毛利底线

mcp:
  tools:
    - name: adjust_dish_price
      description: "调整菜品价格(受毛利底线约束)"
      input_schema: { dish_id: string, new_price_fen: integer }

triggers:
  - event: "order.completed"
    condition: "payload.item_count > 0"
```

**新表**: `forge_ontology_bindings` — 应用↔实体绑定映射
**新表**: `forge_manifest_versions` — 清单版本管理

#### 2.3 端点规划 (~25 新端点)

```
# 信任管理
POST   /api/v1/forge/trust/audit              — 提交信任审计
GET    /api/v1/forge/trust/tiers              — 查询信任等级定义
GET    /api/v1/forge/trust/{app_id}/status    — 查询应用信任状态
POST   /api/v1/forge/trust/{app_id}/upgrade   — 申请升级信任等级
POST   /api/v1/forge/trust/{app_id}/downgrade — 降级(违规触发)

# 运行时策略
GET    /api/v1/forge/runtime/{app_id}/policy   — 查询运行时策略
PUT    /api/v1/forge/runtime/{app_id}/policy   — 更新策略
POST   /api/v1/forge/runtime/{app_id}/kill     — 紧急熔断
GET    /api/v1/forge/runtime/violations         — 违规记录列表

# MCP
POST   /api/v1/forge/mcp/servers               — 注册 MCP Server
GET    /api/v1/forge/mcp/servers                — MCP Server 列表
GET    /api/v1/forge/mcp/tools                  — MCP Tool 目录
GET    /api/v1/forge/mcp/tools/{tool_id}/schema — 工具 Schema

# Ontology
GET    /api/v1/forge/ontology/bindings          — 实体绑定矩阵
GET    /api/v1/forge/ontology/{entity}/apps     — 操作某实体的所有应用
POST   /api/v1/forge/manifest/validate          — 清单格式校验
```

---

## 四、v2.0 Agent Exchange (Week 3-6, 10张表, ~40端点)

> 核心理念: "不卖应用,卖结果" — Intercom Fin 的 $0.99/resolution 模式

### Sprint E1: 结果计价引擎 (Week 3)

#### 3.1 三层定价模型

```
Layer 1: 基础订阅 (现有6种 — 免费/买断/月付/按店/按量/免费增值)
Layer 2: Token 计量 (新增 — 按 AI 推理消耗计费)
Layer 3: 结果计价 (新增 — 按可量化业务结果计费)
```

**新表**: `forge_outcome_definitions` — 结果定义
- `outcome_id`, `app_id`
- `outcome_type` → conversion / retention / revenue_lift / cost_saved / complaint_resolved
- `measurement_method` → event_count / delta_compare / attribution
- `price_fen_per_outcome` → 每次结果的价格
- `attribution_window_hours` → 归因窗口
- `verification_method` → auto / manual / hybrid

**新表**: `forge_outcome_events` — 结果事件记录 (append-only)
- `outcome_id`, `app_id`, `tenant_id`, `store_id`
- `outcome_data` JSONB → 业务上下文
- `verified` BOOLEAN → 是否通过验证
- `revenue_fen` → 该结果产生的收入

**新表**: `forge_token_meters` — Token 计量表
- `app_id`, `tenant_id`
- `period` → 计量周期 (daily/monthly)
- `input_tokens`, `output_tokens`
- `cost_fen` → 该周期 Token 成本
- `budget_fen` → 预算上限
- `alert_threshold` → 预警阈值(%)

```
示例: 智能配菜 Agent
- 基础订阅: ¥299/月/店 (访问权)
- Token 用量: ¥0.02/千 Token (推理成本透传)
- 结果计价: ¥5/次成功推荐(客户接受推荐菜品 → 归因到 Agent)
```

#### 3.2 结果归因引擎

```python
class OutcomeAttributor:
    """
    多触点归因: 哪个 Agent 的哪次决策导致了业务结果?
    
    归因链: Agent决策 → 门店执行 → 业务结果 → 收入确认
    """
    async def attribute(self, outcome_event):
        # 1. 从 agent_decision_logs 查找归因窗口内的相关决策
        # 2. 按时间衰减 + 因果强度加权
        # 3. 多 Agent 分摊 (如果多个 Agent 参与)
        # 4. 写入 forge_outcome_events
        # 5. 触发 record_revenue() 计费
```

### Sprint E2: 智能发现引擎 (Week 4)

#### 4.1 意图推断搜索

不再是关键词搜索,而是理解"我想解决什么问题":

**新表**: `forge_search_intents` — 搜索意图日志
**新表**: `forge_app_embeddings` — 应用向量嵌入 (pgvector)

```
用户输入: "午市客流下降怎么办"
↓ Claude 推断意图
意图: [客流预测, 营销触达, 菜品优化, 定价调整]
↓ 向量搜索 + 场景匹配
推荐:
1. 客流预测 Agent (安装量 3.2k, ★4.6) — 预测明日客流
2. 智能配菜 Agent (安装量 2.1k, ★4.8) — 优化午市菜单
3. 支付后营销 (安装量 1.8k, ★4.5) — 自动发券引流
4. [组合推荐] 以上3个协同使用,效果提升 40%
```

#### 4.2 Agent 组合推荐

**新表**: `forge_app_combos` — 应用组合推荐
- `combo_id`, `name`, `description`
- `app_ids` JSONB → 组合中的应用
- `synergy_score` FLOAT → 协同效应分数
- `use_case` → 适用场景描述
- `evidence` JSONB → 数据支撑(A+B 比单独用 A 效果好 X%)

#### 4.3 场景化着陆页

不按分类浏览,按"我是谁 + 我的痛点"浏览:

| 角色 | 痛点场景 | 推荐 Agent 组合 |
|------|----------|----------------|
| 品牌总监 | "食材成本涨了8%" | 智能排菜 + 库存预警 + 动态定价 |
| 门店店长 | "周末晚市排队太长" | 客流预测 + 出餐调度 + 排队管理 |
| 运营经理 | "会员沉睡率30%" | 会员洞察 + 私域运营 + 支付后营销 |
| 财务总监 | "跨品牌对账效率低" | 财务稽核 + 多方结算 + 发票自动化 |

### Sprint E3: 证据卡片系统 (Week 5)

对标 Salesforce AgentExchange "Trust Signals":

**新表**: `forge_evidence_cards` — 证据卡片
- `app_id`
- `card_type` → security_scan / performance_benchmark / compliance_cert / guardrail_test / customer_case
- `title`, `summary`
- `evidence_data` JSONB → 具体证据
- `verified_by` → 验证人/系统
- `expires_at` → 有效期

```
智能配菜 Agent 的证据卡片:
┌─────────────────────────────────────┐
│ 🔒 安全扫描    SAST通过 · 0 CVE     │
│ ⚡ 性能基准    p99 84ms · 32MB内存   │
│ 🛡️ 护栏测试    注入防护 99.97%       │
│ 📊 业务验证    42店实测 · 推荐接受率 67% │
│ 🏅 合规认证    等保三级 · 数据不出境    │
│ ⭐ 客户案例    徐记海鲜 · 毛利提升 4.2% │
└─────────────────────────────────────┘
```

### Sprint E4: 实时大盘升级 (Week 6)

将 OverviewPage 升级为 Agent Exchange 总控中心:

**新增面板**:
- 实时 Agent 活动流 (WebSocket)
- 全网 Token 消耗燃烧图
- 结果计价实时收入
- 信任事件时间线
- 生态健康综合评分 (0-100, 含12个维度)

---

## 五、v2.5 开发者赋能 (Week 7-8, 6张表, ~20端点)

### Sprint D1: AI 辅助开发 (Week 7)

#### 5.1 Forge Builder (可视化 Agent 构建器)

对标 Salesforce Agentforce Builder + Palantir Model Studio:

**新表**: `forge_builder_projects` — 可视化构建项目
- `project_id`, `developer_id`
- `canvas` JSONB → 可视化画布状态
- `generated_code` TEXT → 生成的代码
- `template_id` → 基于哪个模板

提供5种 Agent 脚手架模板:
1. **数据分析型** — 读取 Ontology 数据 → Claude 分析 → 生成报告
2. **自动化执行型** — 事件触发 → 条件判断 → 执行 Action
3. **对话交互型** — 用户提问 → 检索知识库 → 回答
4. **监控预警型** — 定时巡检 → 异常检测 → 告警 + 建议
5. **优化决策型** — 收集数据 → 建模 → 推荐方案 → 人类审批

#### 5.2 即时预览 (Live Preview)

- 开发者提交代码 → 30秒内在沙箱中运行 → 看到真实效果
- 预灌装测试数据(基于徐记海鲜脱敏数据)
- 支持 Hot Reload

#### 5.3 TTHW 优化目标

| 指标 | 当前 | v2.5 目标 |
|------|------|----------|
| 注册→首次API调用 | ~47 min | ≤ 15 min |
| 首次提交 Alpha | ~3 天 | ≤ 2 小时 (模板) |
| Alpha → GA | ~12 周 | ≤ 6 周 |

### Sprint D2: 自动化审核 (Week 8)

#### 6.1 AI 审核官

用 Claude 辅助审核流程:

```python
class AIReviewAgent:
    """
    自动化审核 70% 的检查项,人工只负责 30% 判断题
    """
    async def auto_review(self, app_submission):
        # Phase 1: 自动化 (10项)
        security_scan = await self.run_sast(app_submission.package)
        performance = await self.run_benchmark(app_submission)
        compatibility = await self.check_master_agent_compat(app_submission)
        ontology_audit = await self.verify_ontology_bindings(app_submission)
        license_check = await self.scan_licenses(app_submission)
        # ...
        
        # Phase 2: AI 辅助 (5项)
        description_quality = await claude.evaluate(app_submission.description)
        pricing_reasonableness = await claude.compare_pricing(app_submission, market_data)
        
        # Phase 3: 人工必须 (3项)
        # - 商业合理性判断
        # - 用户体验主观评估
        # - 屯象品牌一致性
        
        return AutoReviewResult(
            auto_pass=all_auto_checks_pass,
            ai_suggestions=ai_findings,
            human_required=human_checklist
        )
```

**新表**: `forge_auto_review_results` — AI审核结果
**新表**: `forge_review_templates` — 审核模板(按应用类型不同)

---

## 六、v3.0 生态飞轮 (Week 9-14, 8张表, ~30端点)

### Sprint F1: 跨品牌 Agent 联盟 (Week 9-10)

#### 7.1 联盟市场

让多个餐饮品牌共享 Agent 能力:

**新表**: `forge_alliance_listings` — 联盟共享清单
- `listing_id`, `app_id`, `owner_tenant_id`
- `sharing_mode` → public / invited / private
- `shared_tenants` JSONB → 被授权使用的租户列表
- `revenue_share_rate` → 联盟分成比例

```
示例: 徐记海鲜开发了"海鲜溯源 Agent"
→ 共享给其他海鲜品牌使用
→ 使用方每月按结果付费
→ 徐记获得 70%,屯象平台获得 30%
→ 开发成本分摊,全行业受益
```

### Sprint F2: Agent 编排市场 (Week 11-12)

#### 8.1 可组合 Agent 编排

不只卖单个 Agent,卖"Agent 工作流":

**新表**: `forge_workflows` — 工作流定义
- `workflow_id`, `name`, `description`
- `steps` JSONB → 编排步骤 [{agent_id, action, condition, next}]
- `trigger` JSONB → 触发条件
- `estimated_value` → 预估业务价值

```yaml
# 示例: "午市利润最大化" 工作流
workflow: lunch_profit_maximizer
trigger: { event: "schedule.11:00", daily: true }
steps:
  - agent: traffic_predictor
    action: predict_lunch_traffic
    output: predicted_count
  - agent: menu_recommender
    action: optimize_lunch_menu
    input: { traffic: "${predicted_count}" }
    condition: "predicted_count > 100"
  - agent: inventory_alerter
    action: check_ingredient_availability
    input: { recommended_dishes: "${previous.output}" }
  - agent: discount_guardian
    action: validate_pricing
    input: { menu: "${previous.output}" }
    constraint: "margin_floor >= 28%"
```

### Sprint F3: 生态健康仪表盘 (Week 13-14)

#### 9.1 平台飞轮指标

**新表**: `forge_ecosystem_metrics` — 生态指标时序

| 指标 | 公式 | 目标 |
|------|------|------|
| ISV 活跃度 | 月活ISV / 注册ISV | ≥ 60% |
| 商品质量分 | AVG(rating) × (1 - 退订率) | ≥ 4.2 |
| 安装密度 | 活跃安装 / 活跃门店 | ≥ 8 件/店 |
| 结果转化率 | 结果事件 / Agent 调用 | ≥ 15% |
| Token 效率 | 业务结果 / 千Token | ↑ 月环比 |
| 开发者 NPS | 季度调研 | ≥ 50 |
| TTHW | 注册→首次成功 | ≤ 15 min |
| 生态 GMV | 月度总交易额 | ↑ 20% MoM |

#### 9.2 飞轮效应

```
更多 ISV 开发 Agent
  → 更丰富的 Agent 组合
    → 更高的门店安装密度
      → 更多的结果计价收入
        → 更高的 ISV 分成
          → 吸引更多 ISV
            → 飞轮加速 🔄
```

---

## 七、数据库变更汇总

| 版本 | 新表 | 累计表 | 新端点 | 累计端点 |
|------|------|--------|--------|----------|
| v1.0 | 9 | 9 | 39 | 39 |
| v1.5 | +8 | 17 | +25 | 64 |
| v2.0 | +7 | 24 | +20 | 84 |
| v2.5 | +4 | 28 | +12 | 96 |
| v3.0 | +5 | 33 | +15 | 111 |

---

## 八、前端页面变更

| 版本 | 新增/改造页面 | 说明 |
|------|-------------|------|
| v1.5 | TrustTierPage, RuntimePolicyPage, MCPRegistryPage, OntologyMapPage | 治理+MCP+Ontology |
| v2.0 | OutcomePricingPage, TokenMeterPage, SmartDiscoveryPage, EvidenceCardsPage, ExchangeDashboard(改造Overview) | 结果计价+智能发现 |
| v2.5 | ForgeBuilderPage, AutoReviewPage, DevJourneyPage(改造Makers) | 开发者赋能 |
| v3.0 | AllianceMarketPage, WorkflowEditorPage, EcosystemHealthPage | 生态飞轮 |

---

## 九、技术架构演进

### v1.0 → v1.5: 加入治理层

```
                    ┌──────────────────┐
                    │  Trust Gateway   │ ← 新增: 信任网关
                    │  (权限检查点)     │
                    └────────┬─────────┘
                             │
┌──────────┐   ┌─────────────┴──────────────┐   ┌──────────┐
│ web-forge │──→│       tx-forge :8013       │──→│ tx-agent │
│(开发者端) │   │  +trust +runtime +mcp      │   │ :8008    │
└──────────┘   └─────────────┬──────────────┘   └──────────┘
                             │
               ┌─────────────┴──────────────┐
               │  forge-admin :5176          │
               │  +TrustTier +Runtime +MCP   │
               └────────────────────────────┘
```

### v2.0 → v3.0: 加入结果引擎 + 编排层

```
┌─────────────────────────────────────────────────┐
│              Agent Exchange Platform             │
│                                                  │
│  ┌─────────┐  ┌──────────┐  ┌────────────────┐ │
│  │ Trust    │  │ Outcome  │  │ Workflow       │ │
│  │ Gateway  │  │ Attribut │  │ Orchestrator   │ │
│  └────┬────┘  └────┬─────┘  └───────┬────────┘ │
│       │            │                │           │
│  ┌────┴────────────┴────────────────┴────────┐  │
│  │            tx-forge :8013                  │  │
│  │  39 base + 25 trust + 20 exchange          │  │
│  │  + 12 builder + 15 ecosystem = 111 端点     │  │
│  └────────────────────┬───────────────────────┘  │
│                       │                          │
│  ┌────────────────────┴────────────┐             │
│  │    PostgreSQL (33 tables + RLS) │             │
│  └─────────────────────────────────┘             │
└─────────────────────────────────────────────────┘
```

---

## 十、优先级排序与里程碑

### 必须先做 (v1.5 Week 1-2) — 信任地基

| 优先级 | 功能 | 原因 |
|--------|------|------|
| P0 | 信任分级 T0-T4 | 没有治理就不能规模化,Salesforce/ServiceNow 的共识 |
| P0 | 运行时沙箱 + 熔断 | OWASP Agentic Top 10 要求,Agent 可能失控 |
| P0 | Ontology Binding | 屯象OS 的核心差异化 — 像 Palantir 一样绑定数据模型 |
| P1 | MCP 协议支持 | 行业标准趋势, Anthropic 5000+ servers |
| P1 | FORGE_MANIFEST.yaml | 统一应用声明格式,替代松散的 JSONB permissions |

### 高价值 (v2.0 Week 3-6) — 商业引擎

| 优先级 | 功能 | 原因 |
|--------|------|------|
| P0 | 结果计价引擎 | Intercom $0.99/resolution 模式验证,餐饮天然适合 |
| P0 | Token 计量 | LLM 成本透传是 AI Agent 平台必备 |
| P1 | 意图搜索 | 从"浏览分类"到"描述问题" |
| P1 | Agent 组合推荐 | 单个 Agent 价值有限,组合才是生态 |
| P2 | 证据卡片 | 建立信任的可视化手段 |

### 加速器 (v2.5-v3.0 Week 7-14) — 飞轮效应

| 优先级 | 功能 | 原因 |
|--------|------|------|
| P1 | Forge Builder | 降低开发门槛 = 更多 ISV |
| P1 | AI 审核官 | 审核是瓶颈,自动化 70% |
| P2 | 跨品牌联盟 | 网络效应,餐饮行业独特 |
| P2 | Agent 编排市场 | 从卖零件到卖解决方案 |
| P2 | 生态健康仪表盘 | 量化飞轮,指导运营 |

---

## 十一、竞争力对标评分

| 维度 | v1.0 | v1.5 | v2.0 | v3.0 | Salesforce AE | ServiceNow |
|------|------|------|------|------|--------------|-----------|
| 基础市场功能 | 85 | 85 | 85 | 85 | 95 | 80 |
| AI Agent 治理 | 20 | 75 | 80 | 90 | 70 | 95 |
| 定价灵活性 | 60 | 60 | 90 | 95 | 75 | 60 |
| 开发者体验 | 40 | 45 | 55 | 80 | 85 | 70 |
| 智能发现 | 10 | 10 | 70 | 85 | 80 | 50 |
| 生态飞轮 | 5 | 15 | 40 | 75 | 90 | 60 |
| 行业深度(餐饮) | 95 | 95 | 95 | 95 | 20 | 30 |
| **综合** | **45** | **55** | **74** | **86** | **74** | **64** |

> v3.0 目标: 全球领先的**垂直行业 AI Agent Exchange**,在餐饮垂直领域超越 Salesforce 通用平台

---

*屯象科技 · Forge 升级路线图 v3.0 · 2026-04-26*
