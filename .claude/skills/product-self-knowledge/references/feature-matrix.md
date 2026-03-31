# 屯象OS 功能矩阵

> 数据截止：2026-03-31 | 基于代码库深度扫描

## 后端服务

| 服务 | 代码行数 | 完成度 | 核心能力 |
|------|---------|--------|---------|
| **tx-trade** | ~26,000 | ✅ 完整 | 订单CRUD、支付网关(mock)、退款、挂账、多渠道统一 |
| **tx-agent** | ~22,000 | ✅ 完整 | Master Agent编排、40+ Skill Agent、决策留痕、三条硬约束 |
| **tx-supply** | ~17,000 | ✅ 完整 | 采购、入库、出库、盘点、供应商管理、中央厨房 |
| **tx-analytics** | ~11,000 | ✅ 完整 | 经营分析、报表引擎、PDF生成、多维度对比 |
| **tx-org** | ~10,000 | ✅ 完整 | 组织架构、员工管理、排班、RBAC权限 |
| **tx-ops** | ~10,000 | ✅ 完整 | 巡店、设备管理、工单、门店运营 |
| **tx-brain** | ~8,000 | ✅ 完整 | AI推理引擎、模型路由(ModelRouter)、多模型支持 |
| **tx-menu** | ~5,000 | ✅ 完整 | 菜品CRUD、BOM配方、定价策略、四象限分析 |
| **gateway** | ~5,000 | ✅ 完整 | API网关、认证鉴权、限流、路由 |
| **tx-intel** | ~5,000 | ✅ 完整 | 商业智能、竞品分析、市场洞察 |
| **tx-growth** | ~4,000 | ⚠️ 部分 | 私域运营、营销活动、优惠券（部分功能待完善） |
| **tx-member** | ~3,200 | ✅ 完整 | 会员CDP、Golden ID、RFM分层、生命周期、144个DB操作 |
| **tx-finance** | ~1,600 | ⚠️ 部分 | 服务层完整(store_pnl 460行+finance_analytics 615行)，**15个API路由未接线** |
| **mcp-server** | ~2,500 | ✅ 完整 | Model Context Protocol服务 |
| **tunxiang-api** | ~3,000 | ✅ 完整 | 统一对外API |

## 前端应用

| 应用 | 技术栈 | 完成度 | 核心页面 |
|------|--------|--------|---------|
| **web-pos** | React 18 + TS + TXTouch | ✅ 完整 | Toast风格点餐、购物车、结算、桌台管理 |
| **web-admin** | React 18 + TS + Ant Design 5 | ✅ 完整 | 菜品管理、库存仪表板、R365风格库存-财务联动 |
| **web-kds** | React 18 + TS + TXTouch | ✅ 完整 | Toast风格KDS网格、工单时间色、滑动完成 |
| **web-crew** | React 18 + TS + TXTouch | ⚠️ 部分 | 服务员PWA基础框架 |
| **web-reception** | React 18 + TS | ✅ 完整 | 预订管理、AI洞察面板、座位优化 |
| **web-hub** | React 18 + TS | ⚠️ 部分 | 门店管理中心 |
| **web-forge** | React 18 + TS | ⚠️ 部分 | 开发工具/配置 |
| **miniapp-customer** | uni-app + Vue 3 + TS | ⚠️ 部分 | 微信小程序（抖音待开发） |
| **android-pos** | Kotlin | ⚠️ 框架 | 安卓POS壳层 |
| **android-shell** | Kotlin | ⚠️ 框架 | WebView + JS Bridge 定义 |
| **ios-shell** | Swift | ⚠️ 框架 | iPad WKWebView 壳层 |

## 边缘计算

| 模块 | 代码行数 | 完成度 | 说明 |
|------|---------|--------|------|
| **mac-station** | ~4,158 | ✅ 完整 | 门店本地API + vision/voice/KDS |
| **sync-engine** | ~123 | ❌ 骨架 | 仅有框架代码，增量同步逻辑未实现 |
| **coreml-bridge** | 规范定义 | ⚠️ 接口定义 | Swift HTTP Server接口已定义 |

## Ontology层

| 模块 | 状态 | 说明 |
|------|------|------|
| 6大核心实体 | ✅ 完整 | Customer/Dish/Store/Order/Ingredient/Employee Pydantic V2模型 |
| 对象注册表 | ✅ 完整 | OMS等价物，Object/Link/Action/Function注册 |
| 约束检查器 | ✅ 完整 | 三条硬约束自动校验框架 |
| 决策留痕 | ✅ 完整 | AgentDecisionLog + 全链路记录 |

## Agent系统

| Agent | 优先级 | 状态 | 运行位置 |
|-------|--------|------|---------|
| 折扣守护 | P0 | ✅ 完整 | 边缘+云端 |
| 智能排菜 | P0 | ✅ 完整 | 云端 |
| 出餐调度 | P1 | ✅ 完整 | 边缘 |
| 会员洞察 | P1 | ✅ 完整 | 云端 |
| 库存预警 | P1 | ✅ 完整 | 边缘+云端 |
| 财务稽核 | P1 | ⚠️ 部分 | 云端 |
| 巡店质检 | P2 | ✅ 完整 | 云端 |
| 智能客服 | P2 | ⚠️ 部分 | 云端 |
| 私域运营 | P2 | ⚠️ 部分 | 云端 |
| 预订智能(No-Show预测) | P1 | ✅ 完整 | 云端 |
| 智能排座 | P1 | ✅ 完整 | 云端 |
| 对话式预订 | P2 | ✅ 完整 | 云端 |

## 已知关键缺口

| 缺口 | 严重度 | 说明 |
|------|--------|------|
| 支付SDK真实集成 | P0 | 3个mock方法需替换为收钱吧/微信/支付宝SDK |
| tx-finance API路由 | P0 | 15个路由未接线到服务层 |
| sync-engine | P0 | 仅123行骨架，增量同步未实现 |
| 加盟商模块 | P1 | franchise子模块缺失 |
| 抖音小程序 | P2 | 仅微信，抖音待开发 |
