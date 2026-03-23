# 屯象OS (TunxiangOS) V3.0

**AI-Native 连锁餐饮经营操作系统**

用一套智能系统替换连锁餐饮企业现有所有业务系统，定位"连锁餐饮行业的 Palantir"。

## 架构

```
L4  多形态前端     安卓POS / iPad / KDS / 服务员PWA / 小程序 / 总部Web
L3  Agent OS       Master Agent + 9 Skill Agent（边缘+云端双层推理）
L2  业务中台       8 域微服务（交易/菜品/会员/供应链/财务/组织/分析/Agent）
L1  Ontology       6 大核心实体 + PostgreSQL RLS 多租户隔离
L0  设备适配       安卓POS外设(商米SDK) + Mac mini边缘AI + 旧系统Adapter
```

## 硬件策略：务实混合架构

| 设备 | 角色 | 外设 |
|------|------|------|
| 安卓 POS (商米 T2/V2) | 收银 + 打印 + 称重 + 扫码 | USB 连接 |
| Mac mini M4 | 本地数据库 + 边缘AI + 数据同步 | **无**（不碰外设）|
| iPad (可选) | 高端店 POS/KDS 升级 | **无**（WiFi转发到安卓）|

## 快速开始

```bash
# 一键启动全栈
docker-compose up -d

# 验证服务
curl http://localhost:8000/health   # Gateway
curl http://localhost:8001/health   # tx-trade
curl http://localhost:8008/api/v1/agent/agents  # 9 Agent 列表

# 前端开发
cd apps/web-pos && pnpm install && pnpm dev

# 运行测试
make test
```

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

**73/73 actions 全部实现** · 三条硬约束（毛利底线+食安合规+客户体验）无例外执行

## 项目结构

```
tunxiang-os/
├── apps/
│   ├── web-pos/           React POS 收银（5 页面）
│   ├── web-admin/         React 总部后台（3 页面）
│   ├── web-kds/           React KDS 出餐屏
│   ├── web-crew/          React 服务员 PWA（离线可用）
│   ├── android-shell/     Kotlin WebView + TXBridge JS Bridge
│   ├── ios-shell/         Swift WKWebView iPad 壳层
│   └── miniapp-customer/  微信小程序顾客端
├── services/
│   ├── gateway/           FastAPI API Gateway + 域路由代理
│   ├── tx-trade/          收银引擎（开单/结算/支付/打印）
│   ├── tx-menu/           菜品管理（BOM/四象限/定价）
│   ├── tx-member/         会员 CDP（Golden ID/RFM/旅程）
│   ├── tx-supply/         供应链（库存/采购/损耗）
│   ├── tx-finance/        财务（FCT/成本率/月报）
│   ├── tx-org/            组织（员工/排班/考勤/绩效）
│   ├── tx-analytics/      分析（健康度/叙事/KPI/BFF）
│   └── tx-agent/          Agent OS（Master + 9 Skill）
├── edge/
│   ├── mac-station/       Mac mini 本地 API + WebSocket
│   ├── sync-engine/       本地PG ↔ 云端PG 增量同步
│   └── coreml-bridge/     Swift Core ML 推理服务
├── shared/
│   ├── ontology/          6 大核心实体 + RLS 基类
│   ├── db-migrations/     Alembic 迁移
│   └── adapters/          10 个 POS 适配器
└── infra/                 Docker + Nginx + Tailscale
```

## V3.2+ 新增功能

### 品智 POS 借鉴与适配
- **品智 Adapter** — 完整的品智 POS 数据适配器（订单/菜品/会员/库存同步）
- **签名验证** — 品智 API 签名校验模块
- **10 大 Adapter 体系** — 品智/奥琦玮/天财商龙/美团SaaS/易鼎/客如云/微生活/饿了么/抖音/诺诺

### HR 模块（tx-org 扩展）
- **薪资引擎** — 多薪资项库 + 五险一金 + 绩效提成自动计算
- **请假审批** — 多级审批流 + 假期余额管理
- **门店调动** — 跨门店人员调配 + 历史记录
- **人效分析** — 人时营收比 + 工时利用率 + 排班优化建议
- **角色层级** — 集团/区域/门店三级权限体系
- **薪资项库** — 可配置薪资项模板 + 批量套用

### Repository 模式
- **tx-analytics Repository** — 健康度/叙事/KPI 数据访问层抽象
- **tx-menu Repository** — 菜品/发布方案 Repository 封装
- **tx-member Repository** — 会员/营销方案 Repository 封装
- **tx-supply Repository** — 库存/采购/损耗 Repository 封装

### Adapter / SDK 扩展
- **统一适配器基类** — BaseAdapter + AdapterRegistry + 类型映射
- **标准化数据类型** — 订单/菜品/会员/库存/桌台/供应商/预订统一类型
- **饿了么 Webhook** — 饿了么订单实时回调适配
- **抖音外卖适配** — 抖音来客订单同步

### 运营流程
- **日清日结 E1-E8** — 开店/巡航/异常/交班/闭店/日结/复盘/整改八节点
- **工作流引擎** — 通用节点状态机 + 检查项管理
- **快速开店（Clone）** — 标杆门店配置一键克隆到新店

### 交易增强
- **预订排队入座** — 预订状态机 + 排队叫号 + 最优桌台分配
- **桌台状态机** — 休眠检测 + 超时提醒 + 自动释放
- **ESC/POS 高级打印** — 外卖单/交班报表/预结单/二维码/厨房标签
- **营销方案引擎** — 7种方案类型 + 互斥规则 + 优先级执行

### 基础设施
- **Nginx 完善** — WebSocket 代理/miniapp API/静态缓存/Gzip/Rate Limiting/CORS
- **SSL 自动续期** — Let's Encrypt certbot + cron 定时续期

## 测试

```
173+ tests passing
├── tx-trade:      26 (收银全流程 + ESC/POS + 支付)
├── tx-agent:      76 (9 Agent + 约束 + Memory Bus + Master)
├── tx-analytics:  40 (健康度 + 叙事引擎)
├── tx-supply:     21 (损耗监控)
├── tx-ops:        20+ (日清日结+快速开店+工作流)
├── tx-org:        30+ (薪资/请假/调动/人效/角色)
├── tx-member:     20+ (营销引擎+API)
├── adapters:      15+ (品智/奥琦玮/天财等)
├── integration:   10 (跨域全链路)
└── e2e:            5 (端到端场景)
```

## 部署

```bash
# 开发环境
docker-compose up -d

# 生产环境
docker-compose -f docker-compose.prod.yml up -d

# 新店上线（≤半天）
./scripts/new_store_setup.sh \
  --store-name="门店名" --store-code="CODE" \
  --tenant-id="uuid" --mac-mini-ip="192.168.1.100"
```

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18 + TypeScript + Ant Design + Zustand |
| 后端 | Python FastAPI + SQLAlchemy 2.0 + asyncpg |
| 数据库 | PostgreSQL 16 (RLS) + Redis 7 |
| AI | Claude API (云端) + Core ML (边缘) |
| 安卓 | Kotlin + WebView + 商米 SDK |
| iOS | Swift + WKWebView |
| 边缘 | Mac mini M4 + Tailscale VPN |
| CI/CD | GitHub Actions |

---

屯象科技 · 未了已 · 2026
