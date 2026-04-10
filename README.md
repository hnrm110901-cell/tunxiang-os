# 屯象OS (TunxiangOS)

**AI-Native 连锁餐饮经营操作系统** — 连锁餐饮行业的 Palantir

用一套智能系统**替换**连锁餐饮企业现有所有业务系统。面向集团化、多品牌、多区域、多渠道的品质中餐连锁。

> 公司：屯象科技（湖南省长沙市）· 创始人：未了已 · 首批客户：尝在一起、最黔线、尚宫厨

---

## 五层架构

```
L4  多形态前端     安卓POS / Windows POS / iPad / KDS / 服务员PWA / 小程序 / 总部Web
L3  Agent OS       Master Agent + 9 Skill Agent（边缘+云端双层推理）
L2  业务中台       13 个微服务 × 8 大产品域 = 320+ 路由模块
L1  Ontology       6 大核心实体 + 4层治理 + 3条硬约束 + PostgreSQL RLS
L0  设备适配       安卓POS外设(商米SDK) + Mac mini边缘AI + 10个旧系统Adapter
```

---

## 门店端架构（硬件兼容 · 稳定交付 · AI）

门店侧采用 **一套 React Web 业务**（`web-pos` / `web-kds` / `web-crew` 等）+ **分平台薄壳**：Android **WebView + TXBridge（商米 SDK）**；Windows **WebView2/Electron 壳**（打印/钱箱等，与 TXBridge 语义对齐）；**iOS / 纯浏览器不直连 USB 小票机**，打印经局域网 **HTTP → 指定打印主机**（Windows 或固定安卓 POS）。**Mac mini** 承担本地库、同步与边缘轻量推理；**云端**承载集团 API 与重推理。**AI 智能体**只做建议/摘要等增强层，**毛利·食安·体验**等硬规则在微服务内确定性执行，失败可降级、不挡结账。

**详细设计**（终端映射、数据流、AI 分层、工程路径）：[`docs/architecture-store-terminals-stable-ai.md`](docs/architecture-store-terminals-stable-ai.md) · 分阶段落地参见 [`docs/development-plan-mixed-terminals-claude-2026Q2.md`](docs/development-plan-mixed-terminals-claude-2026Q2.md) · **Claude 执行方案 + 单商户布署 Runbook**：[`docs/claude-dev-execution-plan-merchant-deploy.md`](docs/claude-dev-execution-plan-merchant-deploy.md)

---

## 项目结构

```
tunxiang-os/
├── apps/                            # 16 个前端应用（React 18 + TypeScript + Vite）
│   ├── web-pos/                     # POS 收银（20+ 路由，安卓/Windows/iPad 共用）
│   ├── web-admin/                   # 总部管理后台（多域子页面）
│   ├── web-kds/                     # 后厨出餐屏（6 路由）
│   ├── web-crew/                    # 服务员 PWA（6 Tab + 全屏流）
│   ├── web-reception/               # 前台接待系统（预订/排队）
│   ├── web-tv-menu/                 # TV 菜单屏显示
│   ├── web-hub/                     # 品牌 Hub 门户
│   ├── web-forge/                   # Forge 开发者市场
│   ├── web-wecom-sidebar/           # 企业微信侧边栏
│   ├── h5-self-order/               # H5 自助点餐（多渠道）
│   ├── miniapp-customer/            # 微信小程序顾客端 v1（8 主包 + 7 分包）
│   ├── miniapp-customer-v2/         # 微信小程序顾客端 v2
│   ├── android-pos/                 # 安卓 POS 壳层（Kotlin + WebView + TXBridge）
│   ├── android-shell/               # 安卓壳层新版（Kotlin）
│   ├── ios-shell/                   # iOS 壳层（Swift + WKWebView）
│   └── windows-pos-shell/           # Windows POS 壳层（Electron + WebView2）
│
├── services/                        # 13 个业务微服务 + 2 个支撑服务（FastAPI + SQLAlchemy 2.0 + asyncpg）
│   ├── gateway/           port 8000 # API Gateway + 域路由 + 租户管理
│   ├── tx-trade/          port 8001 # 交易履约（90 路由文件：收银/桌台/KDS/预订/宴席/外卖）
│   ├── tx-menu/           port 8002 # 菜品菜单（20 路由文件：菜品/发布/定价/套餐/做法）
│   ├── tx-member/         port 8003 # 会员 CDP（33 路由文件：会员/营销/优惠券/礼品卡）
│   ├── tx-growth/         port 8004 # 增长营销（18 路由文件：客户增长/复购驱动）
│   ├── tx-ops/            port 8005 # 运营流程（15 路由文件：日清日结E1-E8/工作流）
│   ├── tx-supply/         port 8006 # 供应链（35 路由文件：库存/BOM/采购/食安/活鲜/溯源）
│   ├── tx-finance/        port 8007 # 财务结算（20 路由文件：成本/P&L/预算/发票/月报）
│   ├── tx-agent/          port 8008 # Agent OS（Master Agent + 9 Skill Agent + 73 Actions）
│   ├── tx-analytics/      port 8009 # 经营分析（28 路由文件：驾驶舱/健康度/叙事/报表）
│   ├── tx-brain/          port 8010 # AI 智能决策中枢（Claude API）
│   ├── tx-intel/          port 8011 # 商业智能（12 路由文件）
│   ├── tx-org/            port 8012 # 组织人事（45 路由文件：员工/排班/角色/绩效/薪资）
│   ├── mcp-server/                  # MCP Protocol Server（对接 Claude Code）
│   └── tunxiang-api/                # 遗留 API 兼容层
│
├── edge/                            # Mac mini M4 边缘智能后台
│   ├── mac-station/                 # 门店本地 FastAPI + PostgreSQL 副本
│   ├── sync-engine/                 # 本地PG ↔ 云端PG 增量同步（300秒/轮）
│   ├── coreml-bridge/               # Swift Core ML 推理服务（port 8100）
│   └── mac-mini/                    # Mac mini 工具集（离线缓冲/打印队列）
│
├── shared/
│   ├── ontology/                    # 6 大核心实体（Customer/Dish/Store/Order/Ingredient/Employee）
│   ├── db-migrations/               # Alembic 增量迁移（184 个版本，v001-v184）
│   ├── adapters/                    # 10 个旧系统适配器（品智/奥琦玮/天财/美团/饿了么/抖音等）
│   ├── events/                      # 统一事件总线（Event Sourcing + CQRS，v147/v148）
│   ├── hardware/                    # 硬件接口（商米SDK/电子秤/打印机/钱箱/扫码枪）
│   ├── vector_store/                # 向量存储（嵌入/相似度搜索）
│   ├── security/                    # 安全模块（加密/认证）
│   ├── feature_flags/               # 特性开关系统
│   ├── skill_registry/              # Agent Skill 注册表
│   └── api-types/                   # 跨服务 API 类型定义（TypeScript）
│
├── infra/
│   ├── docker/                      # Docker Compose（dev/prod/staging/gray/demo）
│   ├── helm/                        # Kubernetes Helm Chart（11 个）
│   ├── nginx/                       # Nginx 反代 + SSL + WebSocket
│   ├── tailscale/                   # Mac mini VPN 配置
│   ├── jumpserver/                  # 堡垒机配置
│   └── dns/                         # DNS 配置脚本
│
├── gitops/                          # GitOps 部署配置（dev/test/uat/pilot/prod）
├── flags/                           # 特性开关（trade/member/org/growth/agents/edge）
├── scripts/                         # 自动化脚本（34+ 个）
└── docs/                            # 详细设计文档（67 份，含门店端架构）
```

---

## 快速开始

```bash
# 一键启动全栈
docker-compose up -d

# 验证服务健康
curl http://localhost:8000/health          # Gateway
curl http://localhost:8001/health          # tx-trade
curl http://localhost:8008/api/v1/agent/agents  # 9 Agent 列表

# 前端开发
cd apps/web-pos && pnpm install && pnpm dev

# 运行所有测试
make test

# 代码检查
ruff check services/ edge/ shared/

# 数据库迁移
make migrate-up

# 新店上线（≤半天）
./scripts/new_store_setup.sh \
  --store-name="门店名" --store-code="CODE" \
  --tenant-id="uuid" --mac-mini-ip="192.168.1.100"
```

---

## 硬件策略：务实混合架构

| 设备 | 型号 | 角色 | 连接外设 |
|------|------|------|---------|
| 安卓 POS 主机 | 商米 T2/V2 | 收银 + 打印 + 称重 + 扫码 | USB（打印机/秤/钱箱/扫码枪）|
| Windows 收银 PC | 门店常见工控/一体机 | 收银 Web + 本地打印/钱箱（壳层实现 TXBridge 语义） | USB / 驱动（由 Windows 壳桥接）|
| Mac mini M4 | 16GB/256GB+ | 本地数据库 + 边缘AI + 数据同步 | **无**（不碰任何外设）|
| 安卓平板 | 商米 D2 或同级 | KDS 后厨出餐屏 | 无 |
| 员工手机 | 员工自有 | 服务员点餐 PWA | 无 |
| iPad（可选升级） | iPad Air/Pro | 高端店 POS/KDS | **无**（外设指令 WiFi 转打印主机）|

**铁律**：安卓 / Windows 做「碰硬件的脏活」，Mac mini 做「需要算力的智能活」；**iOS 不直连 USB 外设**，打印走局域网打印主机。完整拓扑见 [`docs/architecture-store-terminals-stable-ai.md`](docs/architecture-store-terminals-stable-ai.md)。

---

## 9 大 AI Agent

| # | Agent | 优先级 | 运行位置 | Actions |
|---|-------|--------|---------|---------|
| 1 | 折扣守护 | P0 | 边缘+云端 | 6 |
| 2 | 智能排菜 | P0 | 云端 | 8 |
| 3 | 出餐调度 | P1 | 边缘 | 7 |
| 4 | 会员洞察 | P1 | 云端 | 9 |
| 5 | 库存预警 | P1 | 边缘+云端 | 9 |
| 6 | 财务稽核 | P1 | 云端 | 7 |
| 7 | 巡店质检 | P2 | 云端 | 7 |
| 8 | 智能客服 | P2 | 云端 | 9 |
| 9 | 私域运营 | P2 | 云端 | 11 |

**73/73 Actions 全部实现** · 三条硬约束（毛利底线 + 食安合规 + 客户体验）无例外执行

---

## 业务域覆盖

### 已实现（可投入使用）

| 域 | 核心能力 | 实现度 |
|----|---------|--------|
| **交易履约** | 堂食收银/桌台管理/预订排队/KDS出餐/宴席/称重菜/扫码点餐 | 95% |
| **菜品菜单** | 菜品CRUD/BOM配方/套餐组合/四象限分析/5因子动态排名 | 90% |
| **会员CRM** | Golden ID/RFM分层/生命周期/优惠券引擎/营销活动 | 85% |
| **供应链** | 采购管理/库存管理/BOM成本/损耗监控/活鲜管理/溯源 | 80% |
| **组织人事** | 员工管理/排班/考勤/绩效/门店调动/角色权限 | 75% |
| **经营分析** | 经营驾驶舱/5维健康度/叙事引擎/跨店分析/报表引擎 | 85% |
| **Agent OS** | 9 大 Agent/决策留痕/Memory Bus/4时间点推送 | 100% |
| **运营流程** | 日清日结E1-E8/巡店SOP/快速开店/工作流引擎 | 70% |

### 待完善（V4.0 路线图）

| 域 | 待补齐内容 | 优先级 |
|----|-----------|--------|
| **财务结算** | 真实营收/成本/P&L计算引擎、凭证生成 | P0 |
| **储值卡** | 充值/消费/退款/赠送金/余额管理 | P0 |
| **数据同步** | sync-engine 核心逻辑、断网收银 | P0 |
| **外卖聚合** | 统一接单面板、自动接单、菜单同步 | P0 |
| **菜单中心** | 集团模板下发、多渠道独立定价发布 | P1 |
| **中央厨房** | 生产计划/加工/配送/门店签收 | P1 |
| **审批流** | 通用审批引擎、可视化配置 | P1 |
| **多品牌** | 品牌配置中心、品牌级数据隔离 | P1 |
| **加盟管理** | 加盟商管理/分润/独立登录 | P2 |
| **薪资引擎** | 多方案薪资计算/五险一金/个税 | P2 |

---

## V4.0 开发路线图

> 详见 `docs/development-plan-v4-showstopper.md`

```
Phase 0  ████           Week 1-2    安全止血（RLS漏洞修复 + 凭证清除）  ✅ 完成
Phase 1  ████████████   Week 3-14   财务引擎 + 储值卡 + 同步引擎 + 外卖聚合
Phase 2  ████████████   Week 15-26  菜单中心 + 中央厨房 + 审批流 + 多品牌管控
Phase 3  ████████████   Week 27-38  加盟管理 + 薪资引擎 + 营销增长工具
Phase 4  ████████████   Week 39-52  深化打磨 + 10个E2E场景 + V4.0 发布
```

### 十大致命差距修复进度

| # | 差距 | 状态 | 目标 Phase |
|---|------|------|-----------|
| 1 | 财务模块空壳 → 真实计算引擎 | ✅ 已修复（v117 财务计算引擎）| Phase 1 |
| 2 | 中央厨房 + 配送缺失 → 全链路实现 | ✅ 已修复（v119 中央厨房 + ck_production/ck_recipe）| Phase 2 |
| 3 | 加盟管理缺失 → 直营+加盟混合模式 | ✅ 已修复（v125 加盟管理五表 + franchise_mgmt_routes）| Phase 3 |
| 4 | 储值卡缺失 → 完整预付费体系 | ✅ 已修复（v107 储值卡 + stored_value_routes）| Phase 1 |
| 5 | 菜单模板缺失 → 集团下发+门店微调 | ✅ 已修复（v095 菜单模板 + brand_publish_routes）| Phase 2 |
| 6 | 薪资引擎缺失 → 多方案+五险一金 | ✅ 已修复（v120/v121/v124 薪资引擎三阶段）| Phase 3 |
| 7 | 审批流缺失 → 通用可配置审批引擎 | ✅ 已修复（v121 审批工作流 + approval_workflow_routes）| Phase 2 |
| 8 | 同步引擎骨架 → 真实增量同步 | ✅ 已修复（sync_ingest_router + edge/sync-engine）| Phase 1 |
| 9 | RLS 安全漏洞 → 修复+加固 | ✅ 已修复（v063 + v075 + v056 批量修复）| Phase 0 |
| 10 | 外卖聚合未集成 → 统一接单管理 | ✅ 已修复（delivery_panel_router + delivery_orders_routes）| Phase 1 |

### 目标指标

| 指标 | 当前（2026-04-07）| V4.0 目标 |
|------|------|----------|
| 测试文件 | ~420（Wave 0-2 新增）| ≥ 400 ✅ |
| 路由文件 | ~370（+50 Wave 0-2）| ~380 |
| 数据库迁移版本 | **v204**（v001-v204，含v200里程碑）| ~v220 |
| 综合竞争力 | **87/100**（🟡/🟠 差距清零）| ≥ 85/100 ✅ |
| AI 智能 | 95/100 | 95/100（保持领先）✅ |
| 财务能力 | **88/100**（税务+分账+电子发票）| 85/100 ✅ |
| 供应链深度 | **88/100**（供应商门户DB化）| 90/100 |
| 集团管控 | **85/100**（多品牌/多区域完成）| 85/100 ✅ |

**🟡/🟠 差距清零进度（2026-04-07）：**
- Wave 0（v193-v194）：✅ 营销活动DB化 / 宴席支付 / 全渠道订单中心 / 叙事分析
- Wave 1（v195-v201）：✅ 培训绩效 / 多渠道菜单 / 付费会员卡 / 供应商门户 / 抖音团购 / 多品牌 / 多区域 / 团餐 / 自配送 / PWA三端 / 电子发票 / Golden ID打通
- Wave 2（v202-v204）：✅ 断网收银 / 数据脱敏GDPR / 边缘AI出餐预测 / 语音稳定性 / 外卖聚合对账 / 增值税台账 / 聚合支付分账

---

## 竞争优势（竞品不具备）

| # | 独有能力 | 说明 |
|---|---------|------|
| 1 | 9 大 AI Agent + 73 Actions | 竞品最多有规则引擎，无 AI 决策 |
| 2 | 三条硬约束自动校验 | 毛利底线 + 食安合规 + 客户体验 |
| 3 | 经营叙事引擎 | 30 秒读懂今天生意（≤200 字自动简报）|
| 4 | 菜品 5 因子动态排名 | 趋势+毛利+库存+时段+退单 |
| 5 | Agent Memory Bus | 跨 Agent 协同决策 |
| 6 | Mac mini 边缘 AI | 断网也能推理（出餐预测/折扣检测）|
| 7 | Ontology 全链路溯源 | 一笔订单→食材→利润 完整因果链 |
| 8 | 旧系统 Adapter 渐进替换 | 10 个适配器，不必一刀切换 |

---

## 旧系统适配器（10 个）

| 适配器 | 对接系统 | 状态 |
|--------|---------|------|
| pinzhi | 品智 POS | ✅ 已实现（订单/菜品/会员/库存）|
| aoqiwei | 奥琦玮 G10 | ✅ 已实现 |
| tiancai-shanglong | 天财商龙 | ✅ 已实现 |
| keruyun | 客如云 | ✅ 已实现 |
| weishenghuo | 微生活 CRM | ✅ 已实现 |
| meituan-saas | 美团 SaaS | ✅ 已实现 |
| eleme | 饿了么 | ✅ 已实现 |
| douyin | 抖音来客 | ✅ 已实现 |
| yiding | 易鼎 | ✅ 已实现 |
| nuonuo | 诺诺发票 | ✅ 已实现 |

---

## 技术栈

| 层 | 技术 | 版本 |
|---|------|------|
| 前端框架 | React + TypeScript | 18.3.0 / 5.3 |
| 前端状态 | Zustand | 4.4 |
| 前端样式 | Tailwind CSS + Ant Design | 5.x / 5.12 |
| 前端构建 | Vite | 5.0 |
| 后端框架 | Python FastAPI + SQLAlchemy | 0.100+ / 2.0 |
| 数据库 | PostgreSQL 16（RLS 多租户）+ Redis 7 | - |
| AI 引擎 | Claude API（云端）+ Core ML（边缘）| - |
| 边缘硬件 | Mac mini M4 16GB + Tailscale VPN | - |
| 安卓 POS | Kotlin WebView + 商米 SDK | T2/V2 |
| 小程序 | 微信/抖音 | - |
| 消息队列 | Redis Streams + PG LISTEN/NOTIFY | - |
| CI/CD | GitHub Actions（9 服务 + 前端 + lint）| - |
| 容器化 | Docker Compose（dev/prod/gray/staging）| 3.8+ |

---

## 测试覆盖

```bash
make test                                    # 运行全部测试
cd services/tx-trade && pytest src/tests/ -v # 单个服务测试
ruff check services/ edge/ shared/          # Lint 检查
```

```
364 测试文件，覆盖全部微服务（Round107 全量扫描，100% 覆盖率）
├── tx-trade:      90 路由文件，对应测试全覆盖（收银/桌台/KDS/预订/宴席/外卖）
├── tx-org:        45 路由文件，对应测试全覆盖（排班/绩效/调动/角色/薪资）
├── tx-agent:      Master + 9 Skill Agent + 73 Actions（约束 + Memory Bus）
├── tx-analytics:  28 路由文件（健康度 + 叙事引擎 + 报表）
├── tx-supply:     35 路由文件（库存 + BOM + 采购 + 食安 + 活鲜）
├── tx-member:     33 路由文件（营销引擎 + 会员 CDP + 优惠券 + 礼品卡）
├── adapters:      10 个旧系统适配器（品智/奥琦玮/天财等）
└── edge:          mac-station + sync-engine + coreml-bridge
```

---

## 部署

```bash
docker-compose up -d                                      # 开发环境
docker-compose -f docker-compose.prod.yml up -d          # 生产环境
docker-compose -f docker-compose.gray.yml up -d          # 灰度环境
```

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [CLAUDE.md](./CLAUDE.md) | 项目宪法 V3.0（架构决策 + 编码规范）|
| [DEVLOG.md](./DEVLOG.md) | 每日开发进度日志 |
| [差距分析报告](./docs/gap-analysis-enterprise-benchmark-2026Q1-v3.md) | 企业级差距分析 v3（75+ 功能项对比）|
| [V4.0 开发计划](./docs/development-plan-v4-showstopper.md) | 十大致命差距修复计划（52 周）|
| [V6 审计修复](./docs/development-plan-v6-remediation.md) | 安全审计修复计划 |
| [安全审计报告](./docs/security-audit-report.md) | RLS/Nginx/端口/租户安全审计 |
| [徐记 23 系统替换](./docs/xuji-23-system-replacement-analysis.md) | 23 套系统替换对照表 |
| [域架构 V3](./docs/domain-architecture-v3.md) | 四平台域名与职责 |

---

## 目标客户

| 层级 | 客户类型 | 适配度 |
|------|---------|--------|
| **A 类** | 高复杂直营正餐集团（海鲜/酒楼/宴请/多品牌）| 核心目标 |
| **B 类** | 标准中式正餐连锁（5-30 家门店）| 第二波复制 |
| **C 类** | 精品小店 / 新品牌试点 | Lite 版 |

**首批客户**：尝在一起（品智 POS）、最黔线、尚宫厨
**标杆案例**：基于徐记海鲜 23 套系统替换方案设计

---

屯象科技 · 未了已 · 长沙 · 2026
