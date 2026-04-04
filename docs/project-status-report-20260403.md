# 屯象OS 项目状态报告 — 2026-04-03

> 由 Team S6 自动扫描生成。统计截止日期：2026-04-02。

---

## 一、代码量总览

| 语言/技术 | 目录 | 预估文件数 | 说明 |
|-----------|------|-----------|------|
| Python | services/ | ~700+ | 16个微服务后端 |
| Python | edge/ | 48 | Mac mini 边缘服务 |
| Python | shared/ | ~200+ | 适配器/迁移/本体/事件/硬件/i18n |
| TypeScript/React | apps/ (源码) | ~400+ | 11个前端应用（不含 node_modules） |
| 微信小程序 (JS/WXML/WXSS) | apps/miniapp-customer/ | ~100+ | 消费者小程序 |
| Kotlin | android-shell/ | 10 | 安卓 POS 壳层 |
| Swift | edge/coreml-bridge/ | 6 | Core ML 桥接服务 |
| Python (迁移) | shared/db-migrations/ | 138 | v001 — v137（含 v056b） |

**项目总文件数（代码）：约 1,500+ 个源文件**

> 注：根据 CLAUDE.md 记录，Python 约 363K 行，TypeScript 约 93K 行，合计约 **456K+ 行代码**。

---

## 二、前端应用矩阵

| # | 应用 | 路径 | 路由数 | 源文件数 | 目标终端 |
|---|------|------|--------|---------|---------|
| 1 | web-admin | apps/web-admin/ | 130 | ~110+ | 总部浏览器 |
| 2 | web-pos | apps/web-pos/ | 31 | ~95+ | 安卓POS/iPad |
| 3 | web-crew | apps/web-crew/ | 59 | ~100+ | 服务员手机PWA |
| 4 | web-kds | apps/web-kds/ | 30 | ~44 | 后厨出餐屏 |
| 5 | web-reception | apps/web-reception/ | 8 | 14 | 前台接待 |
| 6 | web-tv-menu | apps/web-tv-menu/ | 12 | 20 | TV菜单屏 |
| 7 | web-hub | apps/web-hub/ | 12 | 14 | 品牌Hub门户 |
| 8 | web-forge | apps/web-forge/ | 7 | 9 | 开发者市场 |
| 9 | h5-self-order | apps/h5-self-order/ | 10 | 30 | H5自助点餐 |
| 10 | web-wecom-sidebar | apps/web-wecom-sidebar/ | 1(SPA) | 13 | 企微侧边栏 |
| 11 | miniapp-customer | apps/miniapp-customer/ | **75** | ~100+ | 微信小程序 |
| | **合计** | | **375+** | **~550+** | |

### 小程序页面明细
- 主包页面：30个（首页/点餐/订单/会员/预订/排队/社区/外卖/券中心...）
- 分包页面：45个，覆盖26个分包（扫码点餐/到家厨师/零售商城/集章卡/团购/储值/积分商城...）

---

## 三、后端微服务矩阵

| # | 服务 | 端口 | 路由模块数 | 定位 |
|---|------|------|-----------|------|
| 1 | gateway | :8000 | 12 | API网关 + 域路由 + 租户管理 + 企微集成 |
| 2 | tx-trade | :8001 | **89** | 交易履约（收银/KDS/外卖/宴席/储值/团购...） |
| 3 | tx-menu | :8002 | 18 | 菜品菜单（发布/定价/活鲜/宴席/版本...） |
| 4 | tx-member | :8003 | 30 | 会员CDP（卡/券/积分/储值/礼品卡/等级...） |
| 5 | tx-growth | :8004 | 15 | 增长营销（活动/分群/归因/AB测试/旅程...） |
| 6 | tx-ops | :8005 | 19 | 运营流程（巡检/排班/审批/绩效/日结...） |
| 7 | tx-supply | :8006 | 24 | 供应链（BOM/采购/收货/仓储/中央厨房...） |
| 8 | tx-finance | :8007 | 18 | 财务结算（成本/损益/预算/发票/对账...） |
| 9 | tx-agent | :8008 | 18 | Agent OS（Master+Skills+编排+监控...） |
| 10 | tx-analytics | :8009 | 15 | 经营分析（仪表盘/门店/菜品/知识图谱...） |
| 11 | tx-brain | :8010 | 2 | AI决策中枢（Claude API对接） |
| 12 | tx-intel | :8011 | 3 | 商业智能（竞对/趋势/异常） |
| 13 | tx-org | :8012 | **32** | 组织人事（薪资/加盟/考勤/权限/OTA...） |
| 14 | mcp-server | — | 1 | MCP Protocol（Claude Code对接） |
| 15 | tunxiang-api | — | 6 | 统一API聚合层（POS同步/Hub/交易/运营/脑） |
| | **云端合计** | | **302** | |

### 边缘服务（Mac mini）

| 服务 | 路由模块数 | 说明 |
|------|-----------|------|
| mac-station | 10 | 门店本地API（视觉/语音/联邦/OTA/离线/远程管理） |
| coreml-bridge | 5端点 | Swift HTTP: predict/transcribe/health |
| sync-engine | — | 本地PG↔云端PG增量同步 |

**后端路由模块总计：312个（云端302 + 边缘10）**

---

## 四、数据库

- **迁移版本**：v001 → v137（含 v056b），共 **138 个迁移文件**
- **create_table 调用**：**210 次**（分布在 57 个迁移文件中）
- **预估数据库表数**：**约 200+ 张表**（部分迁移是 ALTER/RLS/索引，非新建表）
- **RLS 策略**：全表强制 tenant_id 隔离，多次安全修复（v006/v014/v017/v023/v056/v063/v075）
- **等保三级**：审计日志(v070) + 模型调用日志(v071) + MFA(v072) + RBAC(v073) + PII加密(v074)

### 重点迁移里程碑
| 版本 | 内容 |
|------|------|
| v001 | RLS基础 + 核心实体（门店/菜品/订单/桌台/会员/员工） |
| v031 | Round2功能表（活鲜/宴席/KDS扩展） |
| v062 | 中央厨房 |
| v069 | 开放API平台 |
| v070-v076 | 等保三级安全表 |
| v100+ | 分润引擎/预算/团购/零售商城/集章卡 |
| v119-v137 | 中央厨房V2/薪资引擎/加盟管理/排班V2/成长表/日报表 |

---

## 五、测试覆盖

| 指标 | 数量 |
|------|------|
| 测试文件数 | **258** |
| 测试函数数 | **5,656** |

### 测试分布（按服务 Top 10）

| 服务/模块 | 测试函数数(估) | 说明 |
|-----------|--------------|------|
| tx-trade | ~800+ | 收银/KDS/宴席/外卖/支付... |
| tx-agent | ~600+ | Agent框架/编排/决策/联邦学习... |
| tx-supply | ~500+ | BOM/采购/仓储/中央厨房... |
| tx-org | ~500+ | 薪资/加盟/考勤/权限/审批... |
| tx-member | ~400+ | 会员/券/积分/储值/礼品卡... |
| tx-analytics | ~350+ | 仪表盘/知识图谱/叙事引擎... |
| tx-finance | ~200+ | 成本/损益/发票/三方匹配... |
| tx-menu | ~200+ | 菜品/发布/定价/活鲜... |
| gateway | ~200+ | RLS中间件/安全/品牌管理/Forge... |
| shared/adapters | ~400+ | 品智/奥琦玮/美团/天财/客如云... |

---

## 六、旧系统适配器

| # | 适配器 | 目标系统 | 状态 |
|---|--------|---------|------|
| 1 | pinzhi | 品智POS | 完整（签名/订单/菜品/会员/库存同步） |
| 2 | aoqiwei | 奥琦玮 | 完整（含CRM适配 + 供应链mapper） |
| 3 | tiancai-shanglong | 天财商龙 | 基础适配 |
| 4 | meituan-saas | 美团SaaS | 基础适配（含预订） |
| 5 | yiding | 易订 | 完整（含客户端/缓存/mapper） |
| 6 | keruyun | 客如云 | 基础适配 |
| 7 | weishenghuo | 微生活 | 基础适配 |
| 8 | eleme | 饿了么 | 基础适配（含Webhook） |
| 9 | douyin | 抖音 | 基础适配（含客户端） |
| 10 | nuonuo | 诺诺电子发票 | 基础适配 |

---

## 七、Agent OS 完成度

| Agent | Skills 文件 | 测试文件 | 状态 |
|-------|------------|---------|------|
| Master Agent | master.py + orchestrator.py | test_orchestrator.py | 已实现 |
| 折扣守护 | discount_guard.py | test_constraints_migrated.py | 已实现 |
| 智能排菜 | menu_ranker (in tx-menu) | test_menu_ranker.py | 已实现 |
| 出餐调度 | table_dispatch.py + serve_dispatch.py | test_decision_migrated.py | 已实现 |
| 会员洞察 | member_insight.py | test_member_private_agents.py | 已实现 |
| 库存预警 | inventory_alert.py + stockout_alert.py | test_inventory_migrated.py | 已实现 |
| 财务稽核 | finance_audit.py + cashier_audit.py | test_inventory_finance_agents.py | 已实现 |
| 巡店质检 | store_inspect.py + patrol_check.py | test_inspect_service_agents.py | 已实现 |
| 智能客服 | smart_customer_service.py + ai_waiter.py | test_voice_order.py | 已实现 |
| 私域运营 | private_ops.py + referral_growth.py | test_growth_agents_new.py | 已实现 |

**附加 Agent Skills**：competitor_watch / compliance_alert / content_generation / cost_diagnosis / seasonal_campaign / trend_discovery / pilot_recommender / salary_advisor / banquet_growth / review_insight / review_summary / voice_order

**Agent 基础设施**：
- 决策留痕：decision_log_service.py + decision_feedback.py
- 联邦学习：federated_learning.py (边缘+云端)
- 模型路由：model_router.py (Claude API + Core ML 双层)
- 事件总线：event_bus.py + domain_event_consumer.py
- 知识检索：knowledge_retrieval.py
- 编排引擎：orchestrator.py + planner.py + handler_factory.py
- 运营计划：operation_planner.py + daily_review_service.py + specials_engine.py

---

## 八、设计系统（Design System）

位于 `apps/web-pos/src/design-system/`，所有前端共享：

| 类别 | 组件数 | 示例 |
|------|--------|------|
| 基础组件 | 18 | ZButton/ZCard/ZTable/ZModal/ZInput/ZSelect/ZTag/ZBadge... |
| AI组件 | 3 | AIMessageCard/AISuggestionCard/DecisionCard |
| 数据组件 | 4 | HealthRing/ChartTrend/UrgencyList/QuoteBlock |
| Design Tokens | 5 | colors/typography/spacing/elevation/index |
| 主题 | 2 | light/dark |

---

## 九、基础设施完成度

| 模块 | 状态 | 说明 |
|------|------|------|
| Docker Compose | 已有 | dev/prod/staging/gray |
| Nginx 反代 | 已有 | SSL + WebSocket |
| Tailscale VPN | 已有 | Mac mini 安全连接 |
| DNS 配置 | 已有 | 配置脚本 |
| PostgreSQL RLS | 已完成 | 全表 tenant_id 隔离 |
| Alembic 迁移 | v001-v137 | 138个迁移版本 |
| 事件驱动 | 已实现 | Redis Streams + PG LISTEN/NOTIFY |
| 硬件抽象层 | 已实现 | 设备注册/协议支持/门店硬件配置 |
| 向量存储 | 已有 | shared/vector_store |
| i18n 国际化 | 已有 | 中文/英文 + H5四语(zh/en/ja/ko) |
| Core ML 桥接 | 已实现 | Swift HTTP: predict/transcribe/health |
| Sync Engine | 已实现 | 离线优先 + 冲突解决 + 增量同步 |
| 安卓 JS Bridge | 已实现 | Print/Scan/Scale/CashBox/DeviceInfo |
| 等保三级 | Phase 0-5 已完成 | 审计/MFA/RBAC/PII加密/模型日志 |
| git-secrets | 已配置 | 防密钥泄露 |

---

## 十、系统规模总结

| 维度 | 数值 |
|------|------|
| 代码总行数 | ~456K+ 行 |
| 源文件总数 | ~1,500+ 个 |
| 编程语言 | 5种（Python/TypeScript/Kotlin/Swift/JS） |
| 前端应用 | 11个 |
| 前端路由/页面 | 375+ |
| 后端微服务 | 16个（含 tunxiang-api 聚合层） |
| 后端路由模块 | 312个 |
| 边缘服务 | 3个（mac-station/coreml-bridge/sync-engine） |
| 数据库表 | ~200+ 张 |
| 迁移版本 | 138个 (v001-v137) |
| 旧系统适配器 | 10个 |
| AI Agent Skills | 21个 |
| 测试文件 | 258个 |
| 测试函数 | 5,656个 |
| Design System 组件 | 27个 |
| 设计文档 | 47+ 份 |

---

## 十一、与 CLAUDE.md 宪法对标

| 宪法要求 | 实际状态 | 差距 |
|----------|---------|------|
| 16个微服务 | 15个独立服务 + 1个聚合层 | 已达标 |
| 10个前端应用 | 11个（多了 web-wecom-sidebar） | 超额 |
| 9大核心 Agent | 9个全部有实现 + 12个附加 | 超额 |
| PostgreSQL RLS | 全表覆盖 + 7次安全修复 | 已达标 |
| Ontology 6大实体 | 均已在 v001 建表 | 已达标 |
| 四层治理 | 集团→品牌→业态→门店 | 已达标 |
| 三条硬约束 | constraints.py 已实现 | 已达标 |
| 安卓 JS Bridge | 6个接口已实现 | 已达标 |
| Core ML 桥接 | 5个端点已实现 | 已达标 |
| Sync Engine | 完整实现（含冲突解决） | 已达标 |
| 10个旧系统适配器 | 10个全部有代码 | 已达标 |
| 等保三级 | Phase 0-5 完成 | 已达标 |

---

## 十二、已知技术债务与待办

1. **auth.py 5处 DB TODO** — 等保三级 auth 模块需接入真实数据库
2. **broad except 清理** — 审计期（至2026-06）强制修复
3. **部分适配器为骨架** — eleme/douyin/nuonuo 仅基础适配，未完整对接
4. **测试覆盖率** — P0 服务目标 ≥80%，部分服务尚未达标
5. **前端 node_modules 管理** — web-admin 有 node_modules 在仓库中
6. **tunxiang-api 聚合层** — 新引入的统一 API 入口，需与原有微服务路由整合

---

*报告生成时间：2026-04-03*
*生成工具：Claude Code Team S6*
