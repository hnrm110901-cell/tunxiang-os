# FLIPOS 差距补齐开发计划（2026-Q2 · Sprint 1-6）

> **背景**：对标 FLIPOS 产品功能，屯象OS 在前厅营销玩法和第三方平台对接方面存在 8 项差距。
> 本计划按 `小红书对接 > 拼团 > 集点卡 > 线上商城` 优先级排列，预计 4-6 周完成核心功能。
> 直播带货和商户互通列入 Q2 后期探索。
>
> **约束**：所有新代码遵守 CLAUDE.md 审计修复期规范 — 禁止 broad except、必须 tenant_id + RLS、模型调用走 ModelRouter。

---

## 一、总览甘特图

```
Week  1 ──── 2 ──── 3 ──── 4 ──── 5 ──── 6
      ├─────────────────┤
      │  P1: 小红书对接  │
      │   (2.5 周)       │
      ├───────┤
      │P2:拼团│
      │(1.5周)│
              ├──────┤
              │P3:集 │
              │点卡   │
              │(1周)  │
                     ├──────────────────┤
                     │  P4: 线上商城     │
                     │   (2-3 周)        │
```

**总工作量**：~7-8 人周（可并行压缩至 5-6 周）

---

## 二、P1：小红书平台对接（2.5 周 · 高优先）

### 2.1 为什么最优先

- 小红书是 2025-2026 年餐饮行业**获客增长最快的渠道**
- FLIPOS 是小红书官方服务商，已有核销互通
- 屯象OS 当前仅有枚举+文案级别的骨架代码，零实际对接
- 对接后直接提升"外卖/全渠道"维度评分（当前 62 → 目标 72+）

### 2.2 功能范围

| # | 功能 | 优先级 | 说明 |
|---|------|--------|------|
| 1 | 团购券核销 | P0 | 小红书团购券 → POS 扫码核销 → 自动对账 |
| 2 | 门店 POI 同步 | P0 | 门店信息/菜品/价格同步到小红书 |
| 3 | 评论监控集成 | P1 | 小红书笔记/评论 → tx-intel 评论分析引擎 |
| 4 | 达人探店管理 | P2 | 达人邀约/探店任务/效果追踪（Q2后期） |

### 2.3 技术方案

#### 新建文件

```
shared/adapters/xiaohongshu/
├── src/
│   ├── __init__.py
│   ├── xhs_client.py              # HTTP 客户端（OAuth2 + 签名）
│   ├── xhs_coupon_adapter.py      # 团购券核销适配器
│   ├── xhs_poi_sync.py            # 门店 POI 同步
│   └── xhs_review_crawler.py      # 评论采集（走开放平台 API）
├── tests/
│   ├── test_xhs_coupon.py
│   └── test_xhs_poi_sync.py
└── README.md

services/tx-trade/src/services/delivery_adapters/
└── xhs_adapter.py                 # 小红书团购核销适配器（继承 BaseDeliveryAdapter）
```

#### 修改文件

| 文件 | 改动 |
|------|------|
| `services/tx-trade/src/api/platform_coupon_routes.py` | 新增 `/api/v1/platform-coupons/xhs/verify` 核销端点 |
| `services/tx-trade/src/services/coupon_platform_service.py` | 注册 xhs 平台，实现核销逻辑 |
| `services/tx-trade/src/api/webhook_routes.py` | 新增 `/webhook/xhs` 接收小红书回调 |
| `services/tx-intel/src/services/consumer_insight.py` | 接入小红书评论数据源 |
| `shared/adapters/base/src/types/enums.py` | 新增 `XIAOHONGSHU = "xiaohongshu"` 平台枚举 |

#### DB 迁移

```
shared/db-migrations/versions/v100_xiaohongshu_integration.py
```

新建表：
- `xhs_poi_mappings` — 门店与小红书 POI 的绑定关系
- `xhs_coupon_verifications` — 核销记录（含小红书券码/金额/门店/时间）

#### 关键接口设计

```python
# POST /api/v1/platform-coupons/xhs/verify
class XHSVerifyRequest(BaseModel):
    coupon_code: str       # 小红书团购券码
    store_id: str          # 核销门店
    order_id: str          # 关联订单

# POST /webhook/xhs
# 接收小红书回调：订单状态变更、退款通知

# POST /api/v1/xhs/poi/sync
class XHSPOISyncRequest(BaseModel):
    store_id: str          # 屯象门店ID
    xhs_poi_id: str        # 小红书POI ID
```

### 2.4 里程碑

| 天 | 交付 |
|----|------|
| D1-D3 | `xhs_client.py` 完成（OAuth2 授权 + API 签名 + 基础请求封装） |
| D4-D6 | 团购券核销链路跑通（扫码 → 验证 → 核销 → 记账） |
| D7-D9 | POI 同步 + Webhook 回调 |
| D10-D12 | 评论采集 + tx-intel 集成 + 前端总部后台页面 |
| D13 | 测试用例（≥6 个）+ 文档 |

---

## 三、P2：拼团功能（1.5 周 · 中优先）

### 3.1 功能范围

| # | 功能 | 说明 |
|---|------|------|
| 1 | 创建拼团活动 | 商家后台配置拼团商品/人数/价格/时间 |
| 2 | 发起拼团 | 顾客下单发起拼团，生成拼团链接 |
| 3 | 参与拼团 | 其他顾客通过链接/小程序参团 |
| 4 | 拼团成功/失败 | 满员自动成团，超时自动退款 |
| 5 | 拼团数据分析 | 成团率/参团转化/拉新效果 |

### 3.2 技术方案

#### 新建文件

```
services/tx-growth/src/campaigns/group_buy.py        # 拼团活动执行器（遵循 campaigns/ 模板模式）

services/tx-trade/src/services/group_buy_service.py   # 拼团订单管理
services/tx-trade/src/api/group_buy_routes.py         # 拼团 API（6个端点）
services/tx-trade/src/tests/test_group_buy.py         # 测试

apps/miniapp-customer/pages/group-buy/                # 小程序拼团页面
├── group-buy.js
├── group-buy.wxml
├── group-buy.wxss
└── group-buy.json
```

#### DB 迁移

```
shared/db-migrations/versions/v101_group_buy.py
```

新建表：
- `group_buy_activities` — 拼团活动配置（商品/目标人数/拼团价/原价/时限/状态）
- `group_buy_teams` — 拼团团队（发起人/当前人数/目标人数/状态/过期时间）
- `group_buy_members` — 拼团成员（用户/订单/加入时间/支付状态）

#### 关键接口

```python
# POST   /api/v1/group-buy/activities           创建拼团活动
# GET    /api/v1/group-buy/activities           活动列表
# POST   /api/v1/group-buy/teams                发起拼团
# POST   /api/v1/group-buy/teams/{id}/join      参与拼团
# GET    /api/v1/group-buy/teams/{id}           拼团详情
# POST   /api/v1/group-buy/teams/{id}/check     检查成团/超时处理
```

#### campaigns 模板（遵循现有 22 种活动类型的模式）

```python
# services/tx-growth/src/campaigns/group_buy.py
CONFIG_SCHEMA = {
    "type": "object",
    "required": ["name", "product_id", "group_size", "group_price_fen"],
    "properties": {
        "name": {"type": "string"},
        "product_id": {"type": "string"},
        "group_size": {"type": "integer", "minimum": 2, "maximum": 20},
        "group_price_fen": {"type": "integer"},
        "original_price_fen": {"type": "integer"},
        "time_limit_minutes": {"type": "integer", "default": 1440},
        "max_teams": {"type": "integer", "default": 100},
    },
}

async def execute(customer_id, config, trigger_event, tenant_id, db=None):
    """拼团成团后执行奖励"""
    ...
```

#### CampaignEngine 注册

在 `campaign_engine.py` 的 `CAMPAIGN_TYPES` 列表新增 `"group_buy"`（当前 22 种 → 23 种）。

### 3.3 里程碑

| 天 | 交付 |
|----|------|
| D1-D2 | DB 迁移 + group_buy_service.py 核心逻辑（发起/参团/成团/超时） |
| D3-D4 | API 路由 + campaigns/group_buy.py 执行器 |
| D5-D6 | 小程序拼团页面 + 总部后台拼团活动管理 |
| D7 | 定时任务（超时未成团自动退款） + 测试（≥4 个） |

---

## 四、P3：集点卡（1 周 · 中优先）

### 4.1 功能范围

| # | 功能 | 说明 |
|---|------|------|
| 1 | 创建集点卡活动 | 配置集满N次送X（如：集5杯送1杯） |
| 2 | 消费打卡 | 每次消费自动/手动盖章 |
| 3 | 兑换奖励 | 集满后自动发放奖励券/免费商品 |
| 4 | 集点进度查询 | 小程序查看当前集点进度 |
| 5 | 活动数据统计 | 参与人数/完成率/复购带动 |

### 4.2 技术方案

#### 新建文件

```
services/tx-growth/src/campaigns/stamp_card.py        # 集点卡活动执行器

services/tx-member/src/services/stamp_card_service.py  # 集点卡业务逻辑
services/tx-member/src/api/stamp_card_routes.py        # 集点卡 API（5个端点）
services/tx-member/src/tests/test_stamp_card.py        # 测试

apps/miniapp-customer/pages/stamp-card/                # 小程序集点卡页面
├── stamp-card.js
├── stamp-card.wxml
├── stamp-card.wxss
└── stamp-card.json
```

#### DB 迁移

```
shared/db-migrations/versions/v102_stamp_card.py
```

新建表：
- `stamp_card_templates` — 集点卡模板（名称/目标次数/奖励配置/有效期/门店范围）
- `stamp_card_instances` — 用户集点卡实例（用户ID/当前印章数/状态/过期时间）
- `stamp_card_stamps` — 盖章记录（关联订单/盖章时间/门店）

#### 关键接口

```python
# POST   /api/v1/stamp-cards/templates          创建集点卡模板
# GET    /api/v1/stamp-cards/templates          模板列表
# POST   /api/v1/stamp-cards/stamp              盖章（消费后调用）
# GET    /api/v1/stamp-cards/my                 我的集点卡（小程序）
# POST   /api/v1/stamp-cards/{id}/redeem        集满兑换
```

#### 与订单系统集成

在 `tx-trade` 的订单完成事件中，自动触发集点卡盖章：

```python
# 订单完成 → 发布事件 → tx-member stamp_card_service.auto_stamp()
# 检查用户是否有进行中的集点卡活动 → 自动盖章 → 集满则发放奖励
```

### 4.3 里程碑

| 天 | 交付 |
|----|------|
| D1 | DB 迁移 + stamp_card_service.py |
| D2 | API 路由 + campaigns/stamp_card.py |
| D3 | 订单事件集成（自动盖章） + 小程序页面 |
| D4 | 总部后台管理页面 + 测试（≥3 个） |

---

## 五、P4：线上商城完善（2-3 周 · 中优先）

### 5.1 现状分析

`retail_mall.py` 已有 **475 行**代码，包括：
- ✅ 商品列表/详情/搜索（SQL 查询已写好）
- ✅ 订单创建/支付/取消/退款逻辑
- ✅ 收货地址校验
- ✅ 物流状态更新
- ✅ 订单状态机（8 个状态）

**缺失：**
- 🔴 DB 迁移脚本（`retail_products` / `retail_orders` / `retail_order_items` 表未建）
- 🔴 路由未注册到 `main.py`（代码存在但未启用）
- 🔴 小程序商城页面
- 🔴 物流对接（快递100/菜鸟）
- 🔴 商品管理后台

### 5.2 功能范围

| # | 功能 | 优先级 | 说明 |
|---|------|--------|------|
| 1 | DB 表创建 + 路由注册 | P0 | 激活已有代码 |
| 2 | 商品管理后台 | P0 | 总部后台 — 商品 CRUD/上下架/分类管理 |
| 3 | 小程序商城页面 | P0 | 商品列表/详情/购物车/下单/我的订单 |
| 4 | 物流集成 | P1 | 快递100 API 对接（物流轨迹查询） |
| 5 | 营销联动 | P2 | 优惠券可用于商城订单 |

### 5.3 技术方案

#### DB 迁移

```
shared/db-migrations/versions/v103_retail_mall.py
```

新建表（retail_mall.py 中 SQL 已引用但未建的表）：
- `retail_products` — 商品表（名称/分类/价格/图片/库存/状态/排序）
- `retail_orders` — 零售订单（用户/地址/金额/支付/物流/状态）
- `retail_order_items` — 订单商品行项
- `retail_cart_items` — 购物车

#### 修改文件

| 文件 | 改动 |
|------|------|
| `services/tx-trade/src/main.py` | 注册 retail_mall_routes |
| `services/tx-trade/src/api/retail_mall_routes.py` | 补全路由（当前为骨架） |
| `apps/web-admin/src/App.tsx` | 新增商城管理路由 |

#### 新建文件

```
apps/miniapp-customer/pages/mall/
├── mall-home.js/wxml/wxss/json          # 商城首页
├── product-detail.js/wxml/wxss/json      # 商品详情
├── cart.js/wxml/wxss/json                # 购物车
├── checkout.js/wxml/wxss/json            # 结算页
└── my-orders.js/wxml/wxss/json           # 我的订单

apps/web-admin/src/pages/hq/mall/
├── ProductListPage.tsx                    # 商品列表管理
├── ProductEditPage.tsx                    # 商品编辑
└── MallOrdersPage.tsx                     # 商城订单管理

shared/adapters/logistics/
├── src/
│   ├── kuaidi100_client.py               # 快递100 API 客户端
│   └── logistics_tracker.py              # 物流轨迹查询
└── tests/
    └── test_kuaidi100.py
```

### 5.4 里程碑

| 天 | 交付 |
|----|------|
| D1-D2 | DB 迁移 + 路由注册 + 激活已有代码 |
| D3-D5 | 总部后台商品管理（CRUD/上下架/分类） |
| D6-D8 | 小程序商城页面（首页/详情/购物车/下单） |
| D9-D10 | 快递100物流集成 |
| D11-D12 | 购物车 + 优惠券联动 + 测试（≥5 个） |

---

## 六、Q2 后期探索（不阻塞主线）

### 6.1 直播带货（探索期 · 4-6 周）

| 阶段 | 内容 | 说明 |
|------|------|------|
| 调研 | 抖音直播/微信视频号直播 SDK | 确定 API 能力边界 |
| MVP | 直播间商品挂载 + 实时订单推送 | 复用 tx-trade 订单系统 |
| 完善 | 直播数据看板 + 达人管理 | 接入 tx-analytics |

**技术路径**：优先走微信视频号（与小程序同生态），抖音直播作为第二阶段。
复用已有的 `douyin_adapter.py` 架构，新建 `livestream_adapter.py`。

### 6.2 商户互通/跨品牌联动（探索期 · 3-4 周）

FLIPOS 的"商户互通"是一个 **平台级功能**（需要多个品牌共同参与），与屯象OS 的单品牌/集团模式有本质差异。

**替代方案**：
- 屯象已有 `v042_cross_brand_member.py` 跨品牌会员体系
- 可在此基础上扩展"集团内品牌联动"（如：A 品牌消费积分可在 B 品牌使用）
- 不必复制 FLIPOS 的"打卡路线"游戏化玩法（与屯象定位不匹配）

| 阶段 | 内容 |
|------|------|
| Phase 1 | 跨品牌积分互通（基于 v042 扩展） |
| Phase 2 | 跨品牌优惠券互认 |
| Phase 3 | 集团联合营销活动模板 |

---

## 七、前端页面清单（总部后台 web-admin）

| 页面 | 路由 | 所属 Sprint |
|------|------|------------|
| 小红书对接设置 | `/hq/channels/xiaohongshu` | P1 |
| 小红书核销记录 | `/hq/channels/xiaohongshu/verifications` | P1 |
| 小红书评论监控 | `/hq/market-intel/xhs-reviews` | P1 |
| 拼团活动管理 | `/hq/growth/group-buy` | P2 |
| 拼团数据分析 | `/hq/growth/group-buy/analytics` | P2 |
| 集点卡管理 | `/hq/growth/stamp-cards` | P3 |
| 商城商品管理 | `/hq/mall/products` | P4 |
| 商城订单管理 | `/hq/mall/orders` | P4 |

---

## 八、DB 迁移汇总

| 版本 | 内容 | 依赖 |
|------|------|------|
| v100 | 小红书 POI 映射 + 核销记录 | v099 |
| v101 | 拼团活动 + 团队 + 成员 | v100 |
| v102 | 集点卡模板 + 实例 + 盖章记录 | v101 |
| v103 | 零售商品 + 订单 + 购物车 | v102 |

所有表强制包含 `tenant_id` + RLS 策略（使用 `app.tenant_id`）。

---

## 九、测试要求

| 模块 | 最低测试用例数 | 重点测试场景 |
|------|--------------|-------------|
| 小红书核销 | 6 | 正常核销/重复核销/过期券/退款回调 |
| 拼团 | 4 | 发起/满员成团/超时退款/并发参团 |
| 集点卡 | 3 | 自动盖章/集满兑换/过期处理 |
| 线上商城 | 5 | 下单/支付/发货/退款/库存扣减 |

---

## 十、风险与依赖

| 风险 | 影响 | 缓解 |
|------|------|------|
| 小红书开放平台审核周期 | P1 可能延迟 | 先用沙箱环境开发，并行申请资质 |
| 拼团并发竞态 | 超卖/超员 | 使用 `SELECT ... FOR UPDATE` 行锁 |
| 商城物流对接 | P4 延迟 | 快递100是标准 API，风险低 |
| 集点卡与订单事件耦合 | 事件丢失 | 使用 Redis Streams + 幂等消费 |

---

## 十一、完成后评分预估

| 维度 | 当前 | 完成后 | 说明 |
|------|------|--------|------|
| 外卖/全渠道 | 62 | **72** | 小红书+商城补齐 |
| 会员营销 | 83 | **88** | 拼团+集点卡+礼品卡DB化 |
| **加权总分** | **78** | **82** | 超越天财商龙(78)、客如云(75) |

结合 V3 剩余致命差距修复（中央厨房DB化/菜单模板DB化/资金分账，另需 6-10 周），
**全部完成后预计达到 85+ 分，在所有维度超越或持平竞品。**
