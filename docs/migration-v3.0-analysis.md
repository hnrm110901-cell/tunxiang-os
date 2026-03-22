# 屯象OS V2.x → V3.0 迁移分析与计划

> 分析日期：2026-03-22
> 基于：现有 tunxiang 仓库代码 + V3.0 务实混合架构方案 + CLAUDE.md V3.0

---

## 一、现有代码资产盘点

| 维度 | 数量 | 说明 |
|------|------|------|
| API 路由模块 | 253 | apps/api-gateway/src/api/ |
| Service 服务 | 335 | apps/api-gateway/src/services/ |
| ORM 模型 | 160 | apps/api-gateway/src/models/ |
| 内置 Agent | 16 | apps/api-gateway/src/agents/ |
| 独立 Agent 包 | 15 | packages/agents/*/ |
| POS 适配器 | 10 | packages/api-adapters/*/ |
| 前端页面 | 179 | apps/web/src/pages/ |
| Z 设计系统组件 | 25 | apps/web/src/design-system/ |
| DB 迁移 | 161 | apps/api-gateway/alembic/versions/ |
| Python 测试函数 | ~8,800 | packages + apps 测试 |
| 代码总量 | ~363K Python + ~93K TypeScript | |

---

## 二、架构差异全景对比

### 2.1 定位转变

| | V2.x | V3.0 |
|--|------|------|
| 产品定位 | POS 上层 AI 中间件 | 全替换型 AI-Native OS |
| 与 POS 关系 | 不替换，做增强层 | 替换所有 23 套系统 |
| 价值主张 | 帮老板每年多赚 30 万 | 一套系统替代所有 |
| 交付物 | 云端 SaaS + 企微推送 | 硬件套装 + 云端 + 边缘 |

**迁移影响**：V3.0 需要自建交易引擎（收银、开单、结算），这是 V2.x 完全没有的能力。现有代码主要做数据分析和 AI 决策，交易链路是全新开发。

### 2.2 后端架构

| | V2.x | V3.0 |
|--|------|------|
| 结构 | 单体 FastAPI monolith | 8 个域微服务 + gateway |
| 入口 | apps/api-gateway/src/main.py | services/gateway + services/tx-* |
| 服务层 | Service 直接操作 DB | Repository 模式（Service → Repo → DB） |
| 多租户 | brand_id/store_id 过滤 | PostgreSQL RLS + tenant_id |
| 日志 | Python logging | structlog JSON |
| 消息 | Celery + Redis broker | Redis Streams + PG LISTEN/NOTIFY |

**迁移影响**：
- 335 个 service 需要按域拆分到 8 个微服务
- 所有 model 需要加 tenant_id + RLS Policy
- Service → Repository 模式重构工作量巨大
- Celery 任务迁移到 Redis Streams

### 2.3 前端架构

| | V2.x | V3.0 |
|--|------|------|
| 应用数 | 1 个 SPA (apps/web) | 4 个 Web App + 2 个壳层 + 小程序 |
| UI 框架 | Ant Design 5 + Z 设计系统 | Tailwind CSS（全新） |
| 状态管理 | Zustand | Zustand（保留） |
| 图表 | ECharts + ChartTrend | ECharts + ChartTrend（保留） |
| 路由 | 角色前缀(/sm /chef /floor /hq) | 独立 App 按终端拆分 |
| 构建 | Vite 7.3 | Vite（保留） |
| 数据获取 | apiClient.get() | useTxAPI() 自定义 hook |
| 外设交互 | 无 | window.TXBridge JS Bridge |

**迁移影响**：
- 179 个页面需要按终端重新分配到 web-pos/web-kds/web-crew/web-admin
- Ant Design → Tailwind 是前端最大的重构工作（几乎重写样式层）
- Z 设计系统组件需要用 Tailwind 重写
- 新增 JS Bridge 外设抽象层

### 2.4 边缘计算

| | V2.x | V3.0 |
|--|------|------|
| 硬件 | Raspberry Pi 5 | Mac mini M4 |
| 能力 | 离线缓存查询 | 本地 PG 副本 + Core ML 推理 + 数据同步 |
| AI 推理 | 无本地推理 | Core ML (出餐预测/折扣检测/语音) |
| 网络 | 未明确 | Tailscale VPN |
| 同步 | edge_node_service.py 简单缓存 | sync-engine 增量同步（300s） |

**迁移影响**：
- 树莓派相关代码废弃
- 需要全新开发：mac-station / coreml-bridge (Swift) / sync-engine
- 现有 edge_node_service.py 的离线查询逻辑可迁移到 mac-station

### 2.5 Agent 系统

| | V2.x | V3.0 |
|--|------|------|
| Agent 数量 | 16 内置 + 15 独立包 = 31 | 9 个 Skill Agent + 1 Master Agent |
| 框架 | LangChain + LangGraph | 未指定（保留 LangChain 可行） |
| 推理 | 纯云端 Claude API | 双层：边缘 Core ML + 云端 Claude |
| 约束 | 无统一约束校验 | 三条硬约束强制校验 |
| 决策留痕 | NeuralEventLog | AgentDecisionLog（含约束校验字段） |

**迁移影响**：
- 31 个 Agent 需要整合为 9+1 个
- 现有 Agent 业务逻辑大部分可复用，需要重新编排
- 新增三条硬约束校验中间件
- 新增边缘推理调用链路

### 2.6 数据库

| | V2.x | V3.0 |
|--|------|------|
| 主键 | UUID | UUID（保留） |
| 金额 | 存分(fen) | 未明确（建议保留存分） |
| 多租户 | brand_id 应用层过滤 | tenant_id + RLS Policy |
| 向量 DB | Qdrant | 未提及（可保留） |
| 图 DB | Neo4j（迁移未完成） | 未提及（可暂缓） |
| 本地副本 | 无 | Mac mini 本地 PG |

---

## 三、可复用资产评估

### 3.1 高复用度（可直接迁移，改动 < 20%）

| 资产 | 文件数 | 迁移目标 | 改动点 |
|------|--------|---------|--------|
| ORM 模型 | 160 | shared/ontology/ | 加 tenant_id + RLS，改为 Pydantic + SQLAlchemy 双模 |
| POS 适配器 | 10 | shared/adapters/ | 路径调整，接口不变 |
| Agent 业务逻辑 | 31 | services/tx-agent/ | 合并重组，核心算法保留 |
| DB 迁移历史 | 161 | shared/db-migrations/ | 保留历史，新迁移加 RLS |
| Zustand 状态管理 | - | 各 web-* app | 直接迁移 |
| ECharts 图表配置 | - | 各 web-* app | 直接迁移 |

### 3.2 中复用度（需要重构，改动 30-60%）

| 资产 | 文件数 | 迁移目标 | 改动点 |
|------|--------|---------|--------|
| Service 层 | 335 | services/tx-* | 按域拆分 + Repository 模式 |
| API 路由 | 253 | services/tx-* | 按域拆分 + 统一响应格式 |
| 前端页面逻辑 | 179 | apps/web-* | 业务逻辑保留，UI 用 Tailwind 重写 |
| Celery 任务 | ~30 | Redis Streams | 改用 Streams 或保留 Celery |
| 测试 | ~8800 | 对应新目录 | 修改 import 路径 |

### 3.3 低复用度（需要全新开发）

| 模块 | 工作量 | 说明 |
|------|--------|------|
| 交易引擎 (tx-trade) | **极大** | 收银/开单/结算/退款/挂账——V2.x 完全没有 |
| 安卓 POS 壳层 | **大** | Kotlin WebView + JS Bridge + 商米 SDK |
| Core ML 桥接 | **中** | Swift HTTP Server + ML 模型 |
| Sync Engine | **中** | 本地 PG ↔ 云端 PG 增量同步 |
| Mac Station | **中** | 门店本地 FastAPI 服务 |
| iPad 壳层 | **小** | Swift WKWebView（可选） |
| 微信小程序 | **中** | 顾客点餐、大厨到家 |
| RLS 改造 | **中** | 所有表加 tenant_id + Policy |
| Tailwind 重写 | **大** | 179 页面 + 25 组件样式全部重写 |

---

## 四、域服务拆分映射

### 现有 Service → V3.0 域微服务映射

| V3.0 域 | 现有 Service（示例） | 估算文件数 |
|---------|---------------------|-----------|
| **tx-trade** 交易履约 | order_service, payment_service, settlement_service + **全新收银引擎** | ~40 现有 + ~60 新建 |
| **tx-menu** 商品菜单 | menu_ranker, dish_service, bom_service, recipe_service, dish_rd_* | ~35 |
| **tx-member** 会员CDP | marketing_agent_service, private_domain_*, rfm_*, loyalty_* | ~45 |
| **tx-supply** 供应链 | inventory_service, supplier_*, procurement_*, waste_guard_* | ~40 |
| **tx-finance** 财务结算 | fct_service, fct_advanced_*, financial_impact_*, monthly_report_* | ~30 |
| **tx-org** 组织运营 | employee_*, schedule_*, labor_*, shift_*, turnover_*, hr_* | ~50 |
| **tx-analytics** 经营分析 | store_health_*, narrative_engine, scenario_matcher, case_story_*, kpi_* | ~35 |
| **tx-agent** Agent OS | agent_service, decision_*, behavior_score_*, all Agent packages | ~60 |

---

## 五、迁移策略建议

### 5.1 策略选择：渐进式迁移（推荐）

**不推荐大爆炸重写**。363K Python + 93K TypeScript + 8800 测试是巨大资产，重写风险极高。

**推荐：Strangler Fig 模式** — 新建 tunxiang-os 项目，按域逐步从 tunxiang 迁移模块，通过 Gateway 路由切换。

### 5.2 四阶段迁移路线

#### Phase M1：基础设施 + 共享层（W1-4）

```
目标：搭建新项目骨架，所有域可以开始独立开发
```

- [ ] 初始化 tunxiang-os monorepo（pnpm workspace + Python multi-project）
- [ ] 迁移 shared/ontology/（从 models/ 提取 Pydantic 基类 + 6 大核心实体）
- [ ] 搭建 shared/db-migrations/（保留历史迁移，新增 RLS 基础迁移）
- [ ] 迁移 shared/adapters/（10 个 POS 适配器原样搬入）
- [ ] 搭建 services/gateway/（FastAPI + 路由代理，初期直接转发到旧单体）
- [ ] 搭建 Docker Compose 开发环境（PG + Redis + 新旧服务并行）
- [ ] 配置 Tailscale 开发网络

#### Phase M2：优先域迁移 — tx-trade + tx-agent（W5-16）

```
目标：交易引擎可收银 + Agent 双层推理可运行
```

**tx-trade（全新 + 部分迁移）**
- [ ] 设计交易引擎核心模型（Order/Payment/Settlement/Refund）
- [ ] 实现收银流程（开单→加菜→结算→打印）
- [ ] 迁移现有 order_service 的分析能力
- [ ] 对接安卓 POS JS Bridge 打印/钱箱/扫码

**tx-agent（迁移为主）**
- [ ] 合并 31 个 Agent 为 9 Skill Agent + 1 Master Agent
- [ ] 实现三条硬约束校验中间件
- [ ] 实现 AgentDecisionLog 决策留痕
- [ ] 搭建边缘推理调用链路（预留 Core ML 接口）

**edge/mac-station（新建）**
- [ ] FastAPI 门店本地服务骨架
- [ ] 本地 PostgreSQL 副本 schema
- [ ] 基础离线 API（迁移 edge_node_service.py 逻辑）

**apps/android-shell（新建）**
- [ ] Kotlin 项目初始化
- [ ] WebView 壳层 + TXBridge JS Bridge
- [ ] 商米打印/秤/钱箱 SDK 集成

#### Phase M3：核心域并行迁移（W17-32）

```
目标：6 个核心域独立运行，前端按终端拆分
```

- [ ] tx-menu：迁移菜品/BOM/配方相关 service
- [ ] tx-member：迁移会员/私域/营销相关 service
- [ ] tx-supply：迁移库存/采购/供应商相关 service
- [ ] tx-finance：迁移财务/FCT/报表相关 service
- [ ] tx-org：迁移组织/排班/人力/HR相关 service
- [ ] tx-analytics：迁移分析/健康度/叙事引擎相关 service

**前端拆分**
- [ ] apps/web-pos/：收银 + 点餐核心页面（Tailwind 重写）
- [ ] apps/web-kds/：KDS 出餐屏（Tailwind 重写）
- [ ] apps/web-crew/：服务员 PWA（Tailwind 重写）
- [ ] apps/web-admin/：总部管理后台（Tailwind 重写）

**edge 补全**
- [ ] edge/coreml-bridge/：Swift HTTP Server + 首批 3 个 ML 模型
- [ ] edge/sync-engine/：本地 PG ↔ 云端 PG 增量同步

#### Phase M4：全域覆盖 + 旧系统退役（W33-52）

```
目标：新系统全量替换，旧单体下线
```

- [ ] Gateway 路由全部切换到新域服务
- [ ] 旧 apps/api-gateway 下线
- [ ] 旧 apps/web 下线
- [ ] iPad 壳层（可选）
- [ ] 微信小程序
- [ ] 生产部署：新店上线 ≤ 半天交付流程
- [ ] 50+ 客户扩展准备

---

## 六、关键风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 交易引擎从零开发 | 最大工作量，且涉及资金安全 | Phase M2 优先攻坚，参考美团/品智 POS 协议设计 |
| 前端 Tailwind 重写 | 179 页面工作量巨大 | 考虑保留 Ant Design 先做功能迁移，后续逐步替换样式 |
| Agent 合并丢失能力 | 31→10 可能遗漏边缘场景 | 建立 Agent 能力矩阵，合并前逐个对账 |
| 双 PG 同步一致性 | 冲突解决复杂 | sync-engine 用 logical replication + 冲突日志 |
| RLS 全量改造 | 160 个模型 + 161 个迁移 | 分批改造，按域优先级排序 |
| 安卓外设兼容 | 商米以外的 POS 机型 | Phase 1 锁定商米 T2/V2，后续再扩展 |

---

## 七、工作量估算

| 阶段 | 周期 | 主要工作 | 新建/迁移比 |
|------|------|---------|------------|
| M1 基础设施 | 4 周 | 项目骨架 + 共享层 | 70% 新建 / 30% 迁移 |
| M2 交易+Agent | 12 周 | 收银引擎 + Agent 重组 + 安卓壳层 | 60% 新建 / 40% 迁移 |
| M3 核心域并行 | 16 周 | 6 域迁移 + 前端拆分 + 边缘补全 | 30% 新建 / 70% 迁移 |
| M4 全域覆盖 | 20 周 | 收尾 + 退役 + 小程序 + iPad | 50% 新建 / 50% 迁移 |
| **合计** | **52 周** | | **约 50% 可复用现有代码** |

---

## 八、建议立即行动项

1. **确认是否保留 Ant Design**：Tailwind 重写 179 页面是最大的"非必要"工作量。如果优先级是功能上线而非视觉统一，建议 M2/M3 阶段保留 Ant Design，M4 再逐步替换。

2. **确认 Celery vs Redis Streams**：现有 Celery 生态成熟（Beat 调度、任务监控），迁移到 Redis Streams 需要自建调度。建议保留 Celery，除非有明确的性能瓶颈。

3. **确认 Neo4j/Qdrant 去留**：V3.0 方案未提及向量 DB 和图 DB，但现有代码依赖 Qdrant (RAG) 和 Neo4j (Ontology)。需要明确是否保留。

4. **建立 Agent 能力矩阵**：在合并 31→10 之前，需要完整梳理每个 Agent 的能力清单，确保无遗漏。

5. **新建 tunxiang-os 仓库**：与现有 tunxiang 仓库并行，通过 Gateway 渐进切换。
