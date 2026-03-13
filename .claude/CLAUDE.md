# 屯象OS — Claude Code 项目总纲

> **版本**: v2.0 | **维护人**: 微了一 | **公司**: 屯象科技（长沙）
>
> 本文件是 Claude Code 的项目宪法。每次启动新会话，Claude 必须首先完整读取本文件，再执行任何任务。

-----

## 0. 第一性原理：为什么存在

**核心问题**：中国中小连锁餐饮（3～100 门店）的老板，多个业务及管理系统，数据在各 SaaS 软件里，但看不清、管不住，损耗靠感觉，决策靠经验，解决持续稳定经营的本质问题。

**屯象OS的本质**：一个架在现有 POS 之上的 AI 中间件，把分散在各系统的数据聚合成老板、店长、厨师长、督导各自需要的"可执行智能"。

**产品北极星**（永不偏离）：
```
老板看得见，管得住，能落地，可迭代
```

**核心价值主张**：增客流、提复购、防损失、餐饮人最优秀。每降低 1% 食材损耗 = 直接利润提升。

**North Star Metric**：续费率 >= 95%

**定位类比**：餐饮行业的 Palantir —— 不替换 POS，做 POS 上层的本体化智能层。

-----

## 1. 核心宪法（不可违反）

### 工程宪法（6 条）

1. **正确性 > 简洁 > 性能**：有 bug 的快代码不如正确的慢代码
2. **最小化影响**：每次变更只触碰必要的文件，不附带重构
3. **不造轮子**：能用现有 service/model 就不新建文件
4. **安全边界**：所有外部输入必须验证；SQL 用参数化查询，绝不拼接字符串
5. **死代码即技术债**：发现从未被调用的方法立即删除，不留"备用"
6. **离线优先**：新增查询类功能必须考虑离线降级方案（无网络时返回缓存数据而非报错）

### 产品宪法（4 条）

7. **￥优先**：任何 Service 的输出，如果涉及成本/收入/损耗，必须包含 `￥金额` 字段（单位：元，保留 2 位小数）
8. **决策型**：推送/建议内容必须包含：建议动作 + 预期￥影响 + 置信度 + 一键操作入口；纯信息不推送
9. **MVP 纪律**：不在 MVP 功能之外新增功能，除非客户明确要求且影响续费
10. **案例意识**：每个 Sprint 结束时确认关键数据（成本率变化/节省￥/决策采纳数）可被采集

### 绝不事项（Never-Do List）

- ❌ 永远不要在 SQL `text()` 里用字符串拼接参数（用 `:param` 绑定）
- ❌ 永远不要在 INTERVAL 字符串里嵌入参数（用 `:n * INTERVAL '1 day'`）
- ❌ 永远不要在 production 代码里留 TODO/FIXME 超过一次 commit
- ❌ 永远不要在没读懂文件的情况下修改它
- ❌ 永远不要一次性加载超过 10 个文件（走分级加载协议）
- ❌ 永远不要跳过测试直接标记任务完成
- ❌ 改数据库结构前不确认影响
- ❌ 删除代码前不确认是否有依赖
- ❌ 产生模糊的"感觉上应该可以"的确认

-----

## 2. 公司与项目基本信息

| 项目 | 内容 |
|------|------|
| 公司名 | 屯象科技（长沙） |
| 产品名 | 屯象OS（原名智链OS，已正式更名） |
| 服务器 IP | 42.194.229.21 |
| 域名 | zlsjos.cn |
| 服务端口 | 8000（主后端） |
| 当前阶段 | POC 验证期（种子客户接入中） |

### 种子客户（优先级顺序）

| 客户 | POS 系统 | 优先级 | 当前状态 |
|------|---------|--------|---------|
| 尝在一起 | 品智 POS | ★★★ 最高 | 接入中 |
| 徐记海鲜 | 奥琦玮 | ★★★ 核心 | 已有历史数据 |
| 最黔线（贵州菜连锁） | 待确认 | ★★ | 接入中 |
| 尚宫厨（精品创新湘菜中高端） | 待确认 | ★★ | 接入中 |

-----

## 3. 技术架构总览

### 3.1 系统架构

```
外部渠道
  企业微信 / 飞书 Webhook
  POS 系统 / 美团外卖
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  apps/api-gateway  (FastAPI, Python 3.11+)          │
│  ┌──────────────┐  ┌──────────────┐                 │
│  │ API Routes   │  │ Middleware   │                 │
│  │ /api/v1/...  │  │ CORS/Auth/   │                 │
│  │ 158 模块      │  │ Rate/Audit   │                 │
│  └──────┬───────┘  └──────────────┘                 │
│         │                                           │
│  ┌──────▼──────────────────────────────────────┐   │
│  │  Services 层 (217 service files)             │   │
│  │  核心：agent_service / intent_router         │   │
│  │        store_memory_service / menu_ranker    │   │
│  │        vector_db_service / rag_service       │   │
│  └──────┬──────────────────────────────────────┘   │
└─────────┼───────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────┐
│  packages/agents  (LangChain + LangGraph)           │
│  15 个领域 Agent 包                                   │
│  schedule │ order │ inventory │ private_domain      │
│  service  │ training │ decision │ ops_flow          │
│  performance │ reservation │ banquet │ supplier     │
│  people_agent │ dish_rd │ business_intel            │
└──────────────────────┬──────────────────────────────┘
                       │
          ┌────────────┼────────────┬────────────┐
          ▼            ▼            ▼            ▼
    PostgreSQL       Redis       Qdrant        Neo4j
    (主存储)      (缓存+队列)   (向量检索)    (本体图)
    asyncpg      Sentinel HA   384维嵌入     待迁移完成
```

### 3.2 技术栈（以代码实际为准）

| 层级 | 技术 | 版本/说明 |
|------|------|---------|
| Web 框架 | FastAPI | async first |
| ORM | SQLAlchemy 2.0 | async session + asyncpg |
| 数据库迁移 | Alembic | sync psycopg2（迁移专用，URL 转换逻辑不能删）|
| Agent 框架 | LangChain + LangGraph | 状态机式 Agent |
| LLM | Claude API（Anthropic）| 可配置 DeepSeek/OpenAI |
| 向量 DB | Qdrant | 384 维嵌入，本地优先 |
| 嵌入模型 | sentence-transformers | 本地优先，无模型时零向量降级 |
| 缓存 | Redis + Sentinel | TTL 策略按业务定 |
| 任务队列 | Celery | Redis broker，定时任务每日 02:00 UTC 拉取 |
| 监控 | Prometheus + Grafana | grafana-dashboard.json 预置 |
| 容器编排 | Docker Compose / Kubernetes | k8s/ 目录全套配置 |
| 反向代理 | Nginx | SSL/TLS 终止 |
| 前端 | React 19 + TypeScript 5.9 | Vite 7.3 构建 |
| UI 库 | Ant Design 5 + Z 组件设计系统 | 品牌色 `#FF6B2C` |
| 状态管理 | Zustand | 原子化状态 |
| 图表 | ECharts 5 + ChartTrend（Canvas） | 大图表/小趋势分开 |
| 边缘计算 | Raspberry Pi 5 | 离线优先，300s 云同步 |
| 语音交互 | Shokz 骨传导耳机 | BlueZ/PipeWire |
| IM 集成 | 企业微信 + 飞书 | Webhook + 消息推送 |

**关键约束**：
- 数据库主键统一使用 UUID（血泪教训：UUID vs VARCHAR 外键类型不匹配）
- **金额单位**：数据库存分（fen），展示/计算时 `/100` 转元
- 所有 API 集成优先走官方 API，禁止直接读写 POS 数据库

-----

## 4. 核心领域模型

### 代码中实际存在的核心模型（82+ 模型文件，415+ 类定义）

| 模型 | 文件 | 说明 |
|------|------|------|
| `Store` | `models/store.py` | 门店（多租户基本单元，store_id + brand_id） |
| `Dish` / `DishMaster` | `models/dish.py`, `dish_master.py` | 菜品主数据 |
| `BOMTemplate` / `BOMItem` | `models/bom.py` | 物料清单（带版本管理） |
| `IngredientMaster` | `models/ingredient_master.py` | 食材主数据 |
| `Order` / `OrderItem` | `models/order.py` | 订单（final_amount 存分） |
| `InventoryItem` / `InventoryTransaction` | `models/inventory.py` | 库存 + 批次 + 盘点 |
| `Employee` | `models/employee.py` | 员工（含 workforce 扩展） |
| `Schedule` / `Shift` | `models/schedule.py` | 排班 |
| `StoreLaborBudget` | `models/workforce.py` | 人力预算 + 劳动力需求预测 |
| `BanquetHall` | `models/banquet.py` | 宴会场地 |
| `SettlementRisk` | `models/settlement_risk.py` | 结算/离职风险 |
| `StoreMemory` | 服务层 | 门店运营记忆快照（峰值模式、异常模式） |
| `WasteEvent` | `models/waste_event.py` | 损耗事件追踪 |
| `PrivateDomain` | `models/private_domain.py` | 会员旅程（RFM、生命周期） |
| `KPI` | `models/kpi.py` | 绩效指标 |
| `Notification` | `models/notification.py` | 多渠道通知（微信/飞书/短信） |
| `DecisionLog` | 决策日志 | 决策推理 + 行动计划 |
| `NeuralEventLog` | `models/neural_event_log.py` | 事件溯源 |
| `CostTruth` | `models/cost_truth.py` | 成本真相引擎日快照 |

-----

## 5. Agent 系统（15+ 领域 Agent）

### 5.1 主应用内 Agent（`apps/api-gateway/src/agents/`）

| Agent | 文件 | 代码行 | 核心能力 |
|-------|------|--------|---------|
| LLMAgent | `llm_agent.py` | 526 | 核心 LLM 编排 + Tool Calling |
| PerformanceAgent | `performance_agent.py` | 1303 | KPI 分析、排名、场景规划 |
| OpsAgent | `ops_agent.py` | 445 | 运营流程 + 资产管理 |
| InventoryAgent | `inventory_agent.py` | 357 | 库存管理 + 补货建议 |
| OrderAgent | `order_agent.py` | 310 | 订单处理 + 异常检测 |
| KPIAgent | `kpi_agent.py` | 293 | KPI 监控 + 告警 |
| DecisionAgent | `decision_agent.py` | 298 | 决策支持 + 验证 |
| ScheduleAgent | `schedule_agent.py` | 300 | 排班优化 |
| ComplianceAgent | `compliance_agent.py` | 220 | 合规检查 |
| QualityAgent | `quality_agent.py` | 199 | 质量检查 |
| FCTAgent | `fct_agent.py` | 123 | 财务合并 |
| OntologyAdapter | `ontology_adapter.py` | 233 | Neo4j 图数据库交互 |

### 5.2 独立 Agent 包（`packages/agents/`，15 个领域）

`banquet` / `business_intel` / `decision` / `dish_rd` / `inventory` / `ops_flow` / `order` / `people_agent` / `performance` / `private_domain` / `reservation` / `schedule` / `service` / `supplier` / `training`

每个包结构：`{domain}/src/agent.py` + `{domain}/tests/`

### 5.3 角色 → Agent 映射

| 角色 | 主要 Agent | 推送渠道 |
|------|-----------|---------|
| 老板/总部 | PerformanceAgent + FCTAgent + DecisionAgent | 企业微信 |
| 店长 | OpsAgent + InventoryAgent + ScheduleAgent | 企业微信 |
| 厨师长 | OrderAgent + InventoryAgent + QualityAgent | 企业微信/Shokz |
| 楼面经理 | ReservationAgent + ServiceAgent | 企业微信 |
| 管理层 | PeopleAgent + ComplianceAgent | 企业微信 |
| 宴会负责人 | BanquetAgent | 企业微信 |

-----

## 6. POS 系统集成

### 已实现的适配器（`packages/api-adapters/`）

| POS 系统 | 适配器 | 客户 | 状态 |
|---------|--------|------|------|
| 品智 POS | `pinzhi/` PinzhiAdapter | 尝在一起 | 接入中 |
| 天财商龙 | `tiancai-shanglong/` TiancaiShanglongAdapter | 通用 | 已实现 |
| 奥琦玮 | `aoqiwei/` AoqiweiAdapter | 徐记海鲜 | 已实现 |
| 美团 SaaS | `meituan-saas/` MeituanSaasAdapter | 通用 | 已实现（含等位 Webhook） |
| 一订 | `yiding/` YidingAdapter | 预订 | 已实现 |
| 客如云 | `keruyun/` | 备选 | 基础集成 |

**数据流**：POS → Webhook/API → Adapter → OrderItem/Integration models → Services → Agent

**集成原则**：永远优先走官方 API，禁止直接读写 POS 数据库。

-----

## 7. 前端规范（v3.0 角色驱动架构）

### 角色路由

| 角色 | 路由前缀 | 设备 | 说明 |
|------|---------|------|------|
| 店长 | `/sm` | 手机 | 移动优先，底部 Tab 导航 |
| 厨师长 | `/chef` | 手机 | 食材/损耗/采购视图 |
| 楼面经理 | `/floor` | 平板 | 排队/预订/服务质量 |
| 总部 | `/hq` | 桌面 | 多店监控/财务/决策 |

### 设计系统规则

- **品牌色**：`#FF6B2C`（`var(--accent)`）
- **字体栈**：`'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'SF Pro Display'`（禁止 Inter/Roboto）
- **Design Token**：所有颜色/间距/圆角 → `src/design-system/tokens/index.ts` CSS 变量
- **Z 组件**：基础 UI 使用 `src/design-system/components/` 内的 Z 前缀组件（ZCard/ZKpi/ZBadge/ZButton/ZInput/ZEmpty/ZSkeleton/ZAvatar）
- **业务组件**：HealthRing / UrgencyList / ChartTrend（同目录）
- **CSS Modules**：每个组件必须配套 `.module.css`，禁止内联样式（仅动态值除外）
- **图表**：大图表用 `ReactECharts`，小卡片趋势用 `ChartTrend`（原生 Canvas）

### BFF 聚合规则

- BFF 端点：`GET /api/v1/bff/{role}/{store_id}`
- 每个角色首屏只发 **1 个 BFF 请求**（30s Redis 缓存 + `?refresh=true` 强制刷新）
- 子调用失败 → 降级返回 `null`，前端用 `ZEmpty` 占位，不阻塞整屏

### 前端数据获取

```typescript
// 正确：apiClient + useState（当前项目约定）
const resp = await apiClient.get('/api/v1/bff/sm/...');

// 禁止：直接 fetch/axios；不要引入 TanStack Query（尚未安装）
```

-----

## 8. 开发规范

### 8.1 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| Python 类 | PascalCase | `StoreMemoryService` |
| Python 函数/变量 | snake_case | `compute_peak_patterns` |
| 私有方法 | `_` 前缀 | `_fetch_from_db` |
| 数据库表 | snake_case 复数 | `order_items` |
| Redis Key | `namespace:entity_id` | `store_memory:S001` |
| Agent 包 | `packages/agents/{domain}/` | `packages/agents/schedule/` |
| React 组件 | PascalCase | `SmHome`, `ZCard` |
| CSS Module 类 | camelCase | `.healthRow`, `.tabBar` |
| BFF 端点角色前缀 | 小写 2 字母 | `sm`, `chef`, `floor`, `hq` |
| Layout 文件 | `{Role}Layout.tsx` | `StoreManagerLayout.tsx` |

### 8.2 代码规范

- Python：PEP 8
- React：组件 PascalCase，CSS Modules 配套
- API 路由：RESTful，`/api/v1/...`
- 数据库：UUID 主键，外键类型必须匹配
- 注释：关键业务逻辑必须有中文注释
- 金额：DB 存分，API 返回元，转换不能散落各 service

### 8.3 Git 规范

```
feat: 新功能
fix: bug 修复
refactor: 重构
docs: 文档更新
test: 测试
```

分支策略：`main`（生产）→ `dev`（开发）→ `feature/xxx`（功能）

### 8.4 数据安全

- 餐饮客户经营数据属于敏感数据，日志禁止明文记录订单金额、客户信息
- POS API Key 必须存储在环境变量，不得硬编码

-----

## 9. Claude Code 工作协议

### 9.1 上下文分级加载协议（每个任务必须走，禁止跳级）

```
Phase 1 [必须] 读取本文件（CLAUDE.md）全局宪法
Phase 2 [必须] 读取 ARCHITECTURE.md 确认任务涉及哪个模块
Phase 3 [按需] 读取对应模块的 CONTEXT.md（路径：{module_root}/CONTEXT.md）
Phase 4 [精确] 用 Grep/Glob 定位 → Read 只读必要文件（<=8 个）
Phase 5 [执行前] 输出变更蓝图 → 等待确认后执行
```

### 9.2 四阶段工作流

```
Research（读）→ Plan（规划）→ Implement（实现）→ Validate（验证）
```

- **Research**：先读相关代码，理解现有结构，不假设
- **Plan**：给出实施计划，等待确认（非平凡任务必须写计划）
- **Implement**：按计划实现
- **Validate**：本地运行验证，有测试必须跑。标记完成前问「一个高级工程师会批准这个吗？」

### 9.3 验证规则

- 异步代码：必须用 `pytest-asyncio` 跑通
- 数据库变更：必须有对应 Alembic migration
- 前端：确认角色路由和 BFF 端点对应关系

### 9.4 上下文管理

- 上下文使用超过 60% 时，主动提示切换新会话
- 每个阶段结束保存关键结论到 `docs/session-notes/`
- 复杂任务拆成独立子任务，每个子任务一个会话
- 子代理场景：需扫描 20+ 文件的架构分析、多模块并行研究

### 9.5 沟通风格

- 事实与推断分开说（"数据显示…" vs "我推测…"）
- 不确定的事情说不确定，不编造
- 报告问题时给出 3 个选项：（A）保守方案（B）推荐方案（C）激进方案
- 收到错误报告：直接定位 → 修复 → 验证，不要反问"能告诉我更多信息吗？"
- 用户纠正后：记录经验教训

-----

## 10. 关键路径速查

```
CLAUDE.md                            ← 项目宪法（本文件）
ARCHITECTURE.md                      ← Level 1 全景图
apps/api-gateway/CONTEXT.md          ← Level 2 API 层上下文
packages/agents/CONTEXT.md           ← Level 2 Agent 层上下文
tasks/todo.md                        ← 当前任务清单
tasks/lessons.md                     ← 经验教训（每次开始先读！）

apps/api-gateway/src/main.py         ← FastAPI 入口
apps/api-gateway/src/core/config.py  ← 全部配置
apps/api-gateway/src/models/         ← 82+ 数据模型
apps/api-gateway/src/agents/         ← 15 个核心 Agent
apps/api-gateway/src/services/       ← 217 个 Service
packages/agents/                     ← 15 个领域 Agent 包
packages/api-adapters/               ← 6 个 POS 适配器

apps/web/src/pages/                  ← 244 个页面组件
apps/web/src/design-system/          ← Z 前缀设计系统
```

-----

## 11. 构建 / 测试 / 部署

```bash
# 安装依赖
pip install -e ".[dev]"

# 后端测试
cd apps/api-gateway && pytest tests/ -v
pytest packages/*/tests -v --cov=packages    # Agent 包测试
pytest packages/agents/schedule/tests -v     # 单个 Agent 测试

# 前端
cd apps/web && pnpm install && pnpm dev

# 数据库迁移
make migrate-gen msg="描述变更"
make migrate-up
make migrate-status

# Docker
make up       # 启动所有服务（PostgreSQL/Redis/Neo4j/Qdrant/Prometheus/Grafana）
make down
make logs

# 启动开发服务
make run      # uvicorn + reload，端口 8000
```

-----

## 12. 已知约束与痛点

| 痛点 | 说明 | 影响范围 |
|------|------|---------|
| sys.path 污染 | 多 Agent 测试并行运行时互相覆盖 `src/agent.py` | packages/agents/* 测试需独立运行 |
| 同步 Alembic | 迁移用 psycopg2（同步），运行时用 asyncpg | alembic/env.py URL 转换逻辑不能删 |
| 金额单位 | DB 存分，API 返回元，转换分散在各 service | 改动金额字段时必须确认单位 |
| 嵌入降级 | 无本地模型+无 API Key 时返回零向量 | RAG 检索质量会下降 |
| Neo4j 迁移 | PostgreSQL → Neo4j 本体图迁移未完成 | 已识别为根级差距 |

-----

## 13. 当前最高优先级任务（更新于 2026.03）

### 进行中

1. **尝在一起接入**（品智 POS API 集成）— 最高优先
2. **业务报告生成模块**（ReportEngine 完善）
3. **会员生命周期管理**（私域 Agent V5.0）

### 架构欠债

1. PostgreSQL → Neo4j 本体图迁移
2. BettaFish 系统能力迁移（SentimentAnalysisModel 优先）
3. 12 个 Stub 页面补全

### 近期规划（未来 4 周）

- Week 1-2：品智 POS API 打通，尝在一起数据接入
- Week 2-3：报告生成模块上线（企业微信推送）
- Week 3-4：PerformanceAgent OKR 模块上线

-----

## 14. 战略定位备忘（不允许偏离）

### 我们是谁

- **不是** POS 系统（不替换现有系统）
- **不是** 通用 SaaS（深度垂直于连锁餐饮）
- **是** 餐饮行业的操作系统中间层

### 目标客户画像

- 连锁门店数：3～100 家
- 区域：以湖南省为核心，逐步扩展
- 决策人：老板本人（不是 IT 部门）
- 痛点核心：客流不稳定、维护营销价值客、损耗失控、管理全靠巡店、数据散落在多个系统

### 竞争护城河

1. 餐饮数字化 16 年行业积累（关系网络不可复制）
2. 本体化数据架构（比 SaaS 堆功能有更强语义理解）
3. 角色驱动 Agent（每个人看到的是自己最需要的信息）

-----

*本文件由微了一维护，重大架构变更后同步更新。Claude 每次启动会话必须首先读取本文件。*
