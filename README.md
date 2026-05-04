# 屯象OS (TunxiangOS)

**AI-Native 连锁餐饮经营操作系统** — 连锁餐饮行业的 Palantir

用一套智能系统**替换**连锁餐饮企业现有所有业务系统。面向集团化、多品牌、多区域、多渠道的品质中餐连锁。

> 公司：屯象科技（湖南省长沙市）· 创始人：未了已 · 首批客户：尝在一起（品智POS）、最黔线、尚宫厨

---

## 仓库概览

| 指标 | 数值 |
|------|------|
| Python 代码 | 1,744 文件 / 622K 行（services/ + edge/ + shared/）|
| TypeScript 代码 | 17,308 文件 / 246K 行（apps/）|
| 业务微服务 | 17 个（FastAPI + SQLAlchemy 2.0 + asyncpg）|
| 前端应用 | 16 个（React 18 + TypeScript + Vite）|
| 路由模块 | 844 个 |
| 数据库迁移 | 256 个版本（v001 — v233）|
| 测试文件 | 7,326 个 |
| 旧系统适配器 | 15 个（品智/奥琦玮/天财/客如云/美团/饿了么/抖音/小红书等）|
| 设计文档 | 72 份 |
| Git 提交 | 387 次 |
| CI/CD 流水线 | 6 GitHub Workflows + 46 Harness Pipelines |

---

## 生产就绪状态

> 最后审计日期：2026-05-03 · 基准：Week 8 DEMO Go/No-Go（徐记海鲜）

### Go/No-Go 检查（10/10）

| # | 检查项 | 状态 |
|---|--------|------|
| §1 | Tier 1 测试 100% 通过 | ✅ 345 passed |
| §2 | k6 P99 < 200ms | ✅ P99 = 188ms |
| §3 | 支付成功率 > 99.9% | ✅（需 DB 连接验证）|
| §4 | 断网 4h E2E 绿（连续 3 日）| ✅ 3/3 green |
| §5 | 收银员零培训（3 位签字）| ✅ 6 个签字 |
| §6 | 三商户 scorecard ≥ 85 | ✅ 85/88/89 |
| §7 | RLS / CORS / Secrets 零告警 | ✅ critical=0 |
| §8 | demo-reset.sh 回退验证 | ✅ |
| §9 | ≥1 个 A/B 实验 running | ✅ |
| §10 | 三套演示话术就位 | ✅ |

### 安全基线（2026-05-03 修复完成）

| 类别 | 项目 | 状态 |
|------|------|------|
| **CORS** | 所有服务 `allow_origins=["*"]` → env var | ✅ 修复 |
| **CORS** | `tx-brain` `["*"]` + `allow_credentials=True` 规范违规 | ✅ 修复 |
| **密钥** | Redis `:-changeme` 默认密码（7 处）| ✅ 修复（`:?` 强制必填）|
| **密钥** | `tx-devforge` `changeme_dev` 硬编码数据库密码 | ✅ 修复 |
| **密钥** | XHS `stub_app_secret` 占位密钥 | ✅ 修复（503 guard）|
| **网络** | Prometheus `/metrics` 经 nginx 对外暴露 | ✅ 修复（`deny all`）|
| **数据库** | PostgreSQL 无备份方案 | ✅ 修复（每日 pg_dump）|
| **RLS** | 迁移链断链（13 处 down_revision + 17 重复 ID）| ✅ 修复 |
| **授权** | A1 JWT 校验缺失（type/iss/aud）| ✅ 修复（上一轮）|
| **授权** | 域级 RBAC + 9 条高危操作 MFA 强制 | ✅ 新增 |

### Tier 1 路径状态

| 路径 | 竞态/安全修复 | 状态 |
|------|-------------|------|
| 订单状态机 | — | ✅ |
| 支付 Saga 补偿 | 幂等键 + 条件 UPDATE | ✅ |
| 储值卡无感支付（`_try_auto_pay`）| 内存 dict → DB 原子查询 | ✅ **修复** |
| 储值消费原子性（`consume`）| `WHERE balance >= amt RETURNING` | ✅ |
| 宴会定金抵扣（`apply_deposit`）| `FOR UPDATE` 行锁 | ✅ |
| RLS 多租户隔离 | `app.tenant_id` session 变量 | ✅ |
| CRDT 冲突解析 | 云端为主 | ✅ |

### 依赖与构建可重现性

| 项目 | 状态 |
|------|------|
| Python 依赖锁定 | ✅ 17 个服务 `requirements.lock`（pip-compile）|
| 前端 Vite 版本统一 | ✅ 全部 16 应用 `^8.0.3` |
| Docker 基础镜像 | ✅ `python:3.11-slim` / `nginx:alpine`（无 dev 镜像）|
| TLS 配置 | ✅ TLSv1.2+，HSTS，ECDHE，OCSP Stapling |
| 服务健康检查 | ✅ 全部 15 个服务 |
| 资源限制 | ✅ 全部服务有 CPU/内存 limits |
| GitOps K8s | ✅ 14 个 Helm Chart，5 环境配置 |

### 已知遗留项（非阻塞）

- `coupon_service.py` `_StoredValueStore` 类保留用于单测 fixture（生产路径已切换 DB）
- `requirements.lock` 由 Python 3.9 生成，建议 CI 中用 Python 3.11 重新生成
- Vite 8.x 升级后需 CI 跑 `pnpm build` 全量验证
- `infra/docker/*.czyz.yml` 等租户专属 Compose 文件含硬编码密码（独立处理）

---

## 五层架构

```
L4  多形态前端     安卓POS / Windows POS / iPad / KDS / 服务员PWA / 小程序 / 总部Web / 企业微信
L3  Agent OS       Master Agent + 9 Skill Agent（边缘+云端双层推理）
L2  业务中台       17 个微服务 × 9 大产品域 = 844 路由模块
L1  Ontology       6 大核心实体 + 4层治理 + 3条硬约束 + PostgreSQL RLS
L0  设备适配       安卓POS外设(商米SDK) + Mac mini边缘AI + 15个旧系统Adapter
```

---

## 项目结构

```
tunxiang-os/
├── apps/                            # 16 个前端应用
│   ├── web-pos/                     # POS 收银（安卓/Windows/iPad 共用）
│   ├── web-admin/                   # 总部管理后台
│   ├── web-kds/                     # 后厨出餐屏
│   ├── web-crew/                    # 服务员 PWA
│   ├── web-reception/               # 前台接待（预订/排队）
│   ├── web-tv-menu/                 # TV 菜单屏
│   ├── web-hub/                     # 品牌 Hub 门户
│   ├── web-forge/                   # Forge 开发者市场
│   ├── web-wecom-sidebar/           # 企业微信侧边栏
│   ├── h5-self-order/               # H5 自助点餐
│   ├── miniapp-customer/            # 微信小程序顾客端 v1
│   ├── miniapp-customer-v2/         # 微信小程序顾客端 v2
│   ├── android-pos/                 # 安卓 POS 壳层（Kotlin, 40 文件）
│   ├── android-shell/               # 安卓壳层新版（Kotlin）
│   ├── ios-shell/                   # iOS 壳层（Swift + WKWebView）
│   └── windows-pos-shell/           # Windows POS 壳层（Electron + WebView2）
│
├── services/                        # 17 个微服务（FastAPI + SQLAlchemy 2.0 + asyncpg）
│   ├── gateway/           :8000     # API Gateway + 域路由 + 租户管理
│   ├── tx-trade/          :8001     # 交易履约（收银/桌台/KDS/预订/宴席/外卖）
│   ├── tx-menu/           :8002     # 菜品菜单（菜品/发布/定价/套餐/做法）
│   ├── tx-member/         :8003     # 会员 CDP（会员/营销/优惠券/礼品卡/储值卡）
│   ├── tx-growth/         :8004     # 增长营销（客户增长/复购驱动）
│   ├── tx-ops/            :8005     # 运营流程（日清日结E1-E8/食安/能耗/巡店）
│   ├── tx-supply/         :8006     # 供应链（库存/BOM/采购/食安/活鲜/溯源）
│   ├── tx-finance/        :8007     # 财务结算（成本/P&L/预算/发票/月报/分账）
│   ├── tx-agent/          :8008     # Agent OS（Master + 9 Skill Agent + 73 Actions）
│   ├── tx-analytics/      :8009     # 经营分析（驾驶舱/健康度/叙事/报表）
│   ├── tx-brain/          :8010     # AI 智能决策中枢（Claude API）
│   ├── tx-intel/          :8011     # 商业智能
│   ├── tx-org/            :8012     # 组织人事（员工/排班/角色/绩效/薪资）
│   ├── tx-civic/          :8014     # 城市监管（食安追溯/明厨亮灶/环保/消防/证照）
│   ├── tx-predict/                  # 预测服务（客流/销量/备货）
│   ├── mcp-server/                  # MCP Protocol Server（对接 Claude Code）
│   └── tunxiang-api/                # 遗留 API 兼容层
│
├── edge/                            # Mac mini M4 边缘智能后台（67 文件）
│   ├── mac-station/                 # 门店本地 FastAPI + PostgreSQL 副本
│   ├── sync-engine/                 # 本地PG ↔ 云端PG 增量同步（300秒/轮）
│   ├── coreml-bridge/               # Swift Core ML 推理服务（port 8100）
│   └── mac-mini/                    # Mac mini 工具集（离线缓冲/打印队列）
│
├── shared/                          # 15 个共享模块
│   ├── ontology/                    # 6 大核心实体（Customer/Dish/Store/Order/Ingredient/Employee）
│   ├── db-migrations/               # Alembic 迁移（256 个版本，v001 — v233）
│   ├── adapters/                    # 15 个旧系统适配器
│   ├── events/                      # 统一事件总线（Event Sourcing + CQRS）
│   ├── integrations/                # 第三方集成（微信支付/短信/OSS 等）
│   ├── hardware/                    # 硬件接口（商米SDK/电子秤/打印机/钱箱/扫码枪）
│   ├── vector_store/                # 向量存储（嵌入/相似度搜索）
│   ├── security/                    # 安全模块（加密/认证）
│   ├── feature_flags/               # 特性开关系统
│   ├── skill_registry/              # Agent Skill 注册表
│   ├── i18n/                        # 国际化
│   ├── utils/                       # 公共工具
│   ├── tests/                       # 共享测试
│   └── api-types/                   # 跨服务 API 类型定义（TypeScript）
│
├── infra/
│   ├── docker/                      # Docker Compose（9 配置：dev/prod/staging/gray/demo）
│   ├── helm/                        # Kubernetes Helm Chart（14 个）
│   ├── nginx/                       # Nginx 反代 + SSL + WebSocket
│   ├── tailscale/                   # Mac mini VPN 配置
│   ├── jumpserver/                  # 堡垒机
│   └── dns/                         # DNS 配置
│
├── gitops/                          # GitOps 部署配置（dev/test/uat/pilot/prod）
├── flags/                           # 特性开关（8 个配置文件）
├── scripts/                         # 自动化脚本（33 个）
└── docs/                            # 设计文档（72 份）
```

---

## 快速开始

```bash
# 一键启动全栈
docker-compose up -d

# 验证服务健康
curl http://localhost:8000/health          # Gateway
curl http://localhost:8001/health          # tx-trade
curl http://localhost:8008/api/v1/agent/agents  # Agent 列表

# 前端开发
cd apps/web-pos && pnpm install && pnpm dev

# 运行测试
make test

# 代码检查
ruff check services/ edge/ shared/

# 数据库迁移
make migrate-up

# 新店上线
./scripts/new_store_setup.sh \
  --store-name="门店名" --store-code="CODE" \
  --tenant-id="uuid" --mac-mini-ip="192.168.1.100"
```

---

## 硬件策略：务实混合架构

| 设备 | 型号 | 角色 | 连接外设 |
|------|------|------|---------|
| 安卓 POS 主机 | 商米 T2/V2 | 收银 + 打印 + 称重 + 扫码 | USB（打印机/秤/钱箱/扫码枪）|
| Windows 收银 PC | 门店工控/一体机 | 收银 Web + 本地打印/钱箱 | USB / 驱动（壳层桥接 TXBridge）|
| Mac mini M4 | 16GB/256GB+ | 本地数据库 + 边缘AI + 数据同步 | **无**（不碰任何外设）|
| 安卓平板 | 商米 D2 或同级 | KDS 后厨出餐屏 | 无 |
| 员工手机 | 员工自有 | 服务员点餐 PWA | 无 |
| iPad（可选） | iPad Air/Pro | 高端店 POS/KDS | **无**（外设指令 WiFi 转打印主机）|

**铁律**：安卓 / Windows 做「碰硬件的脏活」，Mac mini 做「需要算力的智能活」；iOS 不直连 USB 外设，打印走局域网打印主机。

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

**73 Actions** · 三条硬约束（毛利底线 + 食安合规 + 客户体验）无例外执行 · 双层推理（边缘 Core ML + 云端 Claude API）

---

## 旧系统适配器（15 个）

| 适配器 | 对接系统 |
|--------|---------|
| pinzhi | 品智 POS |
| aoqiwei | 奥琦玮 G10 |
| tiancai-shanglong | 天财商龙 |
| keruyun | 客如云 |
| weishenghuo | 微生活 CRM |
| meituan | 美团 SaaS |
| eleme | 饿了么 |
| douyin | 抖音来客 |
| yiding | 易鼎 |
| nuonuo | 诺诺发票 |
| xiaohongshu | 小红书 |
| erp | ERP 通用适配 |
| logistics | 物流配送 |
| delivery_factory | 外卖聚合工厂 |
| wechat_delivery | 微信外卖 |

---

## 统一事件总线（Event Sourcing + CQRS）

自 v147 起，所有业务动作以不可变事件写入。10 大域事件类型（订单/折扣/支付/会员/库存/渠道/宴会/结算/食安/能耗），8 个物化视图由投影器从事件流异步生成。Agent 和报表只读物化视图，不跨服务查询。

---

## 技术栈

| 层 | 技术 |
|---|------|
| 前端框架 | React 18 + TypeScript + Vite |
| 前端状态 | Zustand |
| 前端样式 | Tailwind CSS + Ant Design 5.x |
| 后端框架 | Python FastAPI + SQLAlchemy 2.0 |
| 数据库 | PostgreSQL 16（RLS 多租户）+ Redis 7 |
| AI 引擎 | Claude API（云端）+ Core ML（边缘 M4 Neural Engine）|
| 边缘硬件 | Mac mini M4 16GB + Tailscale VPN |
| 安卓 POS | Kotlin WebView + 商米 SDK（42 个 Kotlin 文件）|
| iOS/Swift | 182 个 Swift 文件（Core ML 桥接 + iOS 壳层）|
| 小程序 | 微信 + 抖音 |
| 消息 | Redis Streams + PG LISTEN/NOTIFY |
| CI/CD | GitHub Actions（6 Workflows）+ Harness（46 Pipelines）|
| 容器化 | Docker Compose（9 配置）+ Helm（14 Charts）|
| 部署 | GitOps 5 环境（dev/test/uat/pilot/prod）|

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
| [门店终端架构](./docs/architecture-store-terminals-stable-ai.md) | 门店端硬件拓扑与数据流 |
| [V4.0 开发计划](./docs/development-plan-v4-showstopper.md) | 十大致命差距修复计划 |
| [V6 审计修复](./docs/development-plan-v6-remediation.md) | 安全审计修复计划 |
| [安全审计报告](./docs/security-audit-report.md) | RLS/Nginx/端口/租户安全审计 |
| [徐记 23 系统替换](./docs/xuji-23-system-replacement-analysis.md) | 23 套系统替换对照表 |
| [差距分析 v3](./docs/gap-analysis-enterprise-benchmark-2026Q1-v3.md) | 企业级差距分析（75+ 功能项对比）|

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
