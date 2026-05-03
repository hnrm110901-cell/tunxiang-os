# 屯象OS × 微信生态 — 三阶段升级迭代开发计划

> 版本：V1.0 | 日期：2026-05-03 | 基线仓库：tunxiang-os  
> 关联文档：`docs/wechat-ecosystem-catering-solution.md`

---

## 总体策略

**微信生态 = 流量入口 + 支付通道 + 私域阵地 + AI能力**。屯象OS已具备微信支付V3、小程序C端、企业微信基础对接三大核心能力。三阶段目标是从"能用"到"好用"再到"智能"，使微信生态成为屯象OS的获客引擎和用户触点中枢。

### 交付节奏原则

| 原则 | 说明 |
|------|------|
| **与五月差距关闭计划并行** | Phase 1 与 `may-gap-closure-plan-2026-05.md` 并行执行，不阻塞上线 |
| **每阶段可单独上线** | 每个 Phase 完成后可独立灰度，不依赖于下一阶段 |
| **外设不变** | 不改变现有安卓POS外设架构，新功能通过 Mac mini 本地API和微信API扩展 |
| **Tier 1 路径不改** | 不修改 cashier_engine.py 的支付补偿Saga、不修改RLS策略 |
| **后向兼容** | 新对接代码通过 feature flags 控制，不影响现有商户 |

### 三阶段总览

```
Phase 1 (2026 Q2 当前-06-30):  基础能力增强
  ├── 微信支付能力升级（摇优惠/商家名片/投放计划）
  ├── 小程序扫码点餐体验完善（多商户定制+AI推荐）
  ├── UnionID 全渠道打通（存量会员关联+跨品牌识别）
  └── 企业微信私域基建（渠道活码+自动标签+群发）
      交付目标: P0 微信链路全闭环

Phase 2 (2026 Q3 07-01~09-30):  AI + 私域深度运营
  ├── 企微会话存档 + AI 客诉识别
  ├── AI 营销五步闭环（人群→权益→内容→触达→复盘）
  ├── 微信支付投放计划API深度集成
  ├── 视频号小程序交易组件对接
  └── 微信 AI 智能体（Q3 上线）适配准备
      交付目标: 私域运营自动化率 > 80%

Phase 3 (2026 Q4 10-01~12-31):  全链路智能生态
  ├── 微企付 B2B 供应链付款
  ├── 腾讯地图旺店 + 搜一搜品牌区
  ├── 微信 AI 智能体 Function Calling 正式对接
  ├── 视频号直播+KOC 分销数据闭环
  └── 全域数据智能分析（微信触点 ROI 归因）
      交付目标: 微信侧获客 ROI 可量化，全链路可归因
```

---

## Phase 1：基础能力增强（2026 Q2）

### 总览

| 工作流 | 服务/应用 | 工作量(人日) | 并行？ |
|--------|----------|------------|--------|
| WP-1 微信支付能力升级 | tx-trade, tx-pay, tx-growth | 8 | ←→ |
| MP-1 小程序体验完善 | miniapp-customer-v2, tx-menu, tx-agent | 12 | ←→ |
| MU-1 UnionID全渠道打通 | tx-member, gateway | 5 | ←→ |
| WC-1 企业微信私域基建 | tx-growth, gateway | 10 | ←→ |
| **数据层迁移 v384-v387** | shared/db-migrations | 3 | 依赖以上 |
| **测试与验收** | 全栈 | 5 | 串行 |

**总计：~43 人日（含缓冲）**

---

### WP-1：微信支付能力升级（8 人日）

#### WP-1.1 摇优惠/附近优惠对接

**现状**：微信支付V3核心收银已对接（JSAPI/Native/H5/退款/回调），但营销类API未接入。

**目标**：顾客支付后参与"摇一摇"领优惠券，券在屯象POS核销。

**改动文件**：

```
新增:
  services/tx-growth/src/api/wechat_pay_promotion_routes.py    # 支付营销路由
  services/tx-growth/src/services/wechat_pay_promotion_service.py  # 营销服务
  shared/integrations/wechat_pay_promotion.py                   # 营销API封装
  
修改:
  services/tx-trade/src/api/wechat_pay_routes.py                # 支付回调中触发摇优惠
  shared/integrations/wechat_pay.py                              # 补充Native URL生成
  .env.example                                                   # 新增营销API配置项
```

**核心逻辑**：

```python
# shared/integrations/wechat_pay_promotion.py
class WechatPayPromotionService:
    """
    微信支付营销类API封装（摇优惠/商家名片/投放计划）
    API文档: pay.weixin.qq.com/wiki/doc/apiv3/apis/chapter9_1_1.shtml
    """
    
    async def shake_coupon(self, openid: str, store_id: str, 
                           amount_fen: int) -> ShakeResult:
        """支付后触发摇一摇"""
        ...
    
    async def merchant_card(self, merchant_code: str) -> MerchantCard:
        """商家名片配置"""
        ...

async def trade_callback_handler(...):
    """在 tx-trade 支付回调中旁路触发摇优惠"""
    # 原有支付逻辑不变
    # 旁路触发摇优惠（不阻塞主流程）
    asyncio.create_task(
        promotion_service.shake_coupon(
            openid=openid,
            store_id=store_id,
            amount_fen=request.amount_fen
        )
    )
```

#### WP-1.2 商家名片 + 商品券配置

**改动文件**：

```
修改:
  services/gateway/src/wecom_routes.py           # 补充商家名片路由
  services/tx-growth/src/services/coupon_service.py  # 商品券类型支持
  apps/web-admin/src/pages/marketing/CouponManage/  # 新增"微信商品券"配置界面
```

**验收标准**：
- 支付完成后商户可配置"摇优惠"活动，领券率 > 30%
- 商家名片在支付后页面正常展示，可跳转小程序
- 商品券可在POS端核销（通过原有coupon_engine_routes.py）

---

### MP-1：小程序体验完善（12 人日）

#### MP-1.1 多商户定制化改造

**现状**：`apps/miniapp-customer-v2/`（Taro版）已具备通用点餐能力，但缺少商户定制化。

**目标**：支持不同商户的品牌色/Logo/首页banner/菜品分类定制。

**改动文件**：

```
修改:
  apps/miniapp-customer-v2/src/app.tsx               # 加载商户配置
  apps/miniapp-customer-v2/src/api/menu.ts            # 获取商户主题配置
  apps/miniapp-customer-v2/src/pages/index/index.tsx  # 首页根据配置渲染
  apps/miniapp-customer-v2/src/pages/menu/index.tsx   # 菜单页定制
  apps/miniapp-customer-v2/src/components/DishCard/DishCard.tsx  # 菜品卡片显示
  
  services/tx-menu/src/api/menu_display_routes.py     # 新增商户主题配置接口
  services/tx-menu/src/models/merchant_theme.py        # 商户主题模型（新增迁移）
```

**商户主题配置数据结构**：

```python
@dataclass
class MerchantThemeConfig:
    merchant_code: str
    brand_color_primary: str      # "#E8381A"
    brand_color_secondary: str    # "#FFB800"
    logo_url: str
    homepage_banners: list[str]   # banner图URL列表
    dish_card_style: str          # "card" | "list" | "image"
    feature_flags: dict           # {enable_ai_recommend: bool, ...}
```

#### MP-1.2 AI菜品推荐接入

**现状**：`tx-agent/ai_waiter.py` 和 `tx-brain` 已有AI推荐能力，但小程序未接入。

**目标**：小程序首页显示AI推荐菜品（基于会员画像+季节+天气+热销榜）。

**改动文件**：

```
修改:
  apps/miniapp-customer-v2/src/pages/index/index.tsx    # 添加AI推荐区域
  apps/miniapp-customer-v2/src/components/AiRecommend/AiRecommend.tsx  # 推荐组件升级
  apps/miniapp-customer-v2/src/api/menu.ts               # 新增推荐接口调用
  
  services/tx-menu/src/api/menu_recommendation_routes.py  # 新增AI推荐接口
  services/tx-brain/src/agents/menu_optimizer.py          # 补充实时推荐方法
```

**API设计**：

```
GET /api/v1/menu/recommendations?member_id={id}&store_id={id}&limit=6
Response:
{
  "recommendations": [
    {
      "dish_id": "...",
      "name": "招牌水煮鱼",
      "reason": "您上次吃过，好评如潮",
      "image_url": "...",
      "price_fen": 8800
    }
  ],
  "reasoning_brief": "基于历史订单+会员等级+时令推荐"
}
```

#### MP-1.3 小程序性能与体验优化

**目标**：首屏加载 < 2s，页面切换 < 500ms。

**改动文件**：

```
修改:
  apps/miniapp-customer-v2/src/app.tsx              # 分包策略优化
  apps/miniapp-customer-v2/src/utils/performance.ts  # 性能监控增强
  apps/miniapp-customer-v2/src/hooks/useLocation.ts  # 位置获取缓存
  apps/miniapp-customer-v2/src/api/trade.ts          # API响应缓存
```

**技术方案**：
- 使用微信云开发 CDN 缓存菜单图片
- 分包加载（主包 < 2MB，分包按业务域拆分）
- 预加载高频页面（首页→菜单页预渲染）
- 接口响应缓存（localStorage，TTL 3分钟）

---

### MU-1：UnionID 全渠道打通（5 人日）

#### MU-1.1 存量会员 UnionID 关联

**现状**：`shared/ontology/src/entities.py` 中 Customer 实体已有 `wechat_openid`、`wechat_unionid` 字段，但存量会员的 UnionID 尚未补全。

**目标**：为存量小程序用户补全 UnionID，实现微信生态内跨应用统一身份。

**改动文件**：

```
修改:
  services/tx-member/src/services/identity_resolver.py  # 补充UnionID补全逻辑
  services/tx-member/src/api/golden_id_routes.py        # 新增UnionID批量补全接口
  services/tx-member/src/workers/identity_resolution_worker.py  # 后台补全worker
```

**核心逻辑**：

```python
class IdentityResolver:
    async def backfill_union_id(self, tenant_id: str):
        """为已登录但缺少 union_id 的存量会员补全"""
        # 1. 查询所有有 wechat_openid 但无 wechat_unionid 的会员
        # 2. 调用微信API: GET /sns/userinfo?access_token=TOKEN&openid=OPENID
        #    → 返回 union_id
        # 3. 更新 Customer 表
        # 4. 记录到事件总线: MEMBER.UNION_ID_LINKED
```

#### MU-1.2 跨品牌 UnionID 识别

**目标**：同一集团下多品牌商户，同一微信用户自动识别为同一 Golden ID。

**改动文件**：

```
修改:
  services/tx-member/src/api/cross_brand_member_routes.py  # 跨品牌会员识别增强
  services/tx-member/src/services/profile360.py           # 360画像支持多品牌聚合
```

**验收标准**：
- 存量会员 UnionID 补全率 > 90%（运行 worker 后）
- 相同 UnionID 在不同品牌下自动关联为同一 Golden ID
- 同一用户跨品牌消费积分打通

---

### WC-1：企业微信私域基建（10 人日）

#### WC-1.1 渠道活码 + 自动标签

**现状**：`services/gateway/src/wecom_contact.py` 已有企微联系人基础能力。

**目标**：顾客通过不同渠道（海报/桌码/公众号菜单）添加企微时，自动打标签、自动回复、自动拉群。

**改动文件**：

```
新增:
  services/tx-growth/src/api/wecom_channel_code_routes.py    # 渠道活码路由
  services/tx-growth/src/services/wecom_channel_code_service.py  # 渠道活码服务
  services/tx-growth/src/services/wecom_auto_tag_service.py     # 自动标签服务

修改:
  services/gateway/src/wecom_contact.py              # 联系人与标签对接
  services/tx-member/src/models/wecom_contact.py     # 企微联系人模型
  shared/db-migrations/versions/v384_wecom_channel_code.py  # 渠道活码表
  
  apps/web-admin/src/pages/marketing/WecomChannel/   # 渠道活码配置页面
```

**渠道活码数据模型**：

```python
class WecomChannelCode(Base):
    """企微渠道活码"""
    id: UUID
    merchant_code: str
    channel_name: str        # "海报-店门口-2026Q2" | "公众号菜单" | "桌码-06号桌"
    qrcode_url: str          # 企微联系⼈二维码URL
    auto_tags: list[str]     # 自动打标签 ["新客", "扫码引流"]
    auto_reply: str          # 自动回复文案
    group_id: UUID | None    # 自动拉群ID
    scan_count: int = 0      # 扫码次数
    created_at: datetime
```

#### WC-1.2 企业微信标签同步

**目标**：屯象OS的会员标签（RFM分层/菜品偏好/消费能力）自动同步到企业微信侧。

**改动文件**：

```
修改:
  services/tx-member/src/services/rfm_outreach.py          # 标签同步触发
  services/tx-growth/src/api/wecom_scrm_agent_routes.py    # SCRM标签同步路由
  services/gateway/src/wecom_contact.py                    # 标签写入企微API
```

**核心逻辑**：

```
会员标签变更（tx-member）
  → 事件总线 MEMBER.TAG_UPDATED
    → asyncio.create_task(sync_to_wecom())
      → GET /cgi-bin/externalcontact/get_corp_tag_list
      → POST /cgi-bin/externalcontact/mark_tag
```

#### WC-1.3 基于标签的群发

**目标**：运营人员在屯象后台选择人群标签 → AI生成文案 → 一键企微群发。

**改动文件**：

```
修改:
  services/tx-growth/src/api/wecom_scrm_agent_routes.py    # 群发路由增强
  services/tx-growth/src/services/wecom_channel_code_service.py  # 群发服务
  
  apps/web-admin/src/pages/marketing/WecomMass/            # 群发管理页面
```

**验收标准**：
- 渠道活码创建后扫码可自动打标签+自动回复
- 会员标签变更后30秒内同步到企微
- 群发任务可在屯象后台创建、审批、执行、追踪
- 群发送达率 > 95%（T+1确认）

---

### Phase 1 数据层迁移

#### 新增迁移文件

```
shared/db-migrations/versions/v384_wecom_channel_code.py   # 渠道活码表
shared/db-migrations/versions/v385_merchant_theme.py        # 商户主题配置表
shared/db-migrations/versions/v386_wechat_promotion.py      # 微信营销活动配置表
shared/db-migrations/versions/v387_events_composite_idx.py  # 事件表复合索引优化
```

### Phase 1 测试计划

| 测试域 | 用例数 | 重点覆盖 |
|--------|-------|---------|
| WP-1 支付营销 | 8 | 摇优惠领券→核销全流程、回调幂等 |
| MP-1 小程序 | 10 | 多商户主题渲染、AI推荐接口、分包加载 |
| MU-1 UnionID | 6 | 存量补全、跨品牌识别、Golden ID去重 |
| WC-1 企微 | 10 | 渠道活码扫码→打标签→拉群全链路 |

---

## Phase 2：AI + 私域深度运营（2026 Q3）

### 总览

| 工作流 | 服务/应用 | 工作量(人日) | 依赖 |
|--------|----------|------------|------|
| WS-1 企微会话存档+AI客诉 | tx-agent, gateway | 15 | Phase 1 WC-1 |
| AM-1 AI营销五步闭环 | tx-agent, tx-growth | 20 | Phase 1 MP-1, MU-1 |
| WP-2 投放计划深度集成 | tx-growth, tx-trade | 8 | Phase 1 WP-1 |
| VC-1 视频号交易组件 | tx-trade, web-hub | 10 | — |
| WA-1 微信AI智能体适配准备 | gateway, miniapp-customer | 8 | — |
| **测试与集成** | 全栈 | 10 | — |

**总计：~71 人日（含缓冲）**

---

### WS-1：企微会话存档 + AI 客诉识别（15 人日）

#### WS-1.1 会话存档基础接入

**目标**：企微会话消息实时同步到屯象OS事件总线，作为AI分析数据源。

**改动文件**：

```
新增:
  services/gateway/src/wecom_session_archive.py          # 会话存档接收服务
  services/gateway/src/api/wecom_session_callback.py     # 回调接收路由
  services/gateway/src/services/wecom_decrypt_service.py  # 消息解密(RSA)
  services/tx-agent/src/workers/wecom_session_consumer.py # 会话消息消费者

修改:
  shared/events/src/event_types.py                       # 新增 WECOM 事件类型
  .env.example                                            # 新增企微会话存档配置
```

**事件类型新增**：

```python
class WecomEventType(str, Enum):
    """企微事件类型"""
    SESSION_MSG_RECEIVED = "WECOM.SESSION_MSG_RECEIVED"        # 会话消息接收
    CUSTOMER_SERVICE_QUERY = "WECOM.CUSTOMER_SERVICE_QUERY"    # 客服咨询
    COMPLAINT_IDENTIFIED = "WECOM.COMPLAINT_IDENTIFIED"        # 客诉识别
    SENTIMENT_ANOMALY = "WECOM.SENTIMENT_ANOMALY"             # 情绪异常
```

#### WS-1.2 AI 客诉识别引擎

**目标**：AI自动识别企微对话中的客诉内容，实时预警店长，自动生成改善建议。

**改动文件**：

```
新增:
  services/tx-agent/src/skills/complaint_identifier.py    # 客诉识别Skill Agent
  services/tx-agent/src/services/complaint_escalation.py  # 客诉升级服务

修改:
  services/tx-agent/src/skills/smart_customer_service.py  # 智能客服增强
  services/tx-brain/src/agents/customer_service.py        # 客服Agent扩展
```

**识别流程**：

```
企微会话 → 事件总线 → tx-agent 消费者
  → 客诉识别Agent:
    1. NLU分类: 口味抱怨 | 出餐慢 | 服务态度 | 价格不满 | 环境投诉
    2. 情感分析: 消极/中性/积极 + 强度评分(0-1)
    3. 紧急分级: P0(紧急)·P1(需跟进)·P2(一般)
    4. 自动回复建议: 按类型生成回复模板
  → 事件总线 WECOM.COMPLAINT_IDENTIFIED
    → 店长企微通知(紧急P0: 立即推送; P1: 日报汇总)
    → 记录到 tx-analytics 客诉看板
```

**验收标准**：
- 客诉识别准确率 > 85%（基于标注数据集评估）
- P0 客诉从识别到店长通知 < 60秒
- 自动回复建议采纳率 > 60%
- 每周客诉趋势分析报告自动生成

---

### AM-1：AI 营销五步闭环（20 人日）

#### AM-1.1 人群洞察 Agent 增强

**目标**：AI自动分析会员行为，输出目标人群包+推荐策略。

**改动文件**：

```
修改:
  services/tx-agent/src/skills/member_insight.py          # 人群洞察Agent
  services/tx-agent/src/skills/rfm_outreach.py            # RFM触达Agent
  services/tx-agent/src/skills/dormant_recall.py          # 沉睡唤醒Agent
  services/tx-member/src/api/segmentation_routes.py       # 人群细分API增强
  services/tx-brain/src/agents/member_insight.py          # 云端推理增强
```

#### AM-1.2 权益自动化设计

**目标**：AI根据人群特征智能推荐权益方案（券/次卡/礼品卡）。

**改动文件**：

```
修改:
  services/tx-growth/src/api/coupon_routes.py             # 优惠券API增强
  services/tx-growth/src/api/promotion_rules_v3_routes.py # 促销规则V3
  services/tx-growth/src/api/stamp_card_routes.py         # 阶梯次卡
  services/tx-agent/src/skills/private_ops.py             # 私域运营Agent-权益推荐
```

#### AM-1.3 AI 内容生成 + 全渠道触达

**目标**：AI生成营销文案（企微/订阅消息/公众号），多渠道自动触达。

**改动文件**：

```
新增:
  services/tx-brain/src/services/marketing_content_gen.py  # 营销内容生成服务
  
修改:
  services/tx-growth/src/api/wecom_scrm_agent_routes.py    # 企微SCRM触达增强
  shared/integrations/wechat_subscribe.py                  # 订阅消息补充营销模板
  shared/integrations/wechat_marketing.py                  # 公众号模板消息增强
  services/tx-agent/src/skills/content_generation.py       # 内容生成Agent
```

#### AM-1.4 全链路 ROI 归因

**目标**：从曝光→领券→到店→核销→复购，完整归因链路。

**改动文件**：

```
修改:
  services/tx-analytics/src/api/attribution_routes.py      # 归因分析
  services/tx-growth/src/api/attribution_routes.py         # 增长归因
  services/tx-analytics/src/api/experiment_routes.py       # AB实验增强
```

**验收标准**：
- 人群洞察Agent输出的目标人群转化率比随机提升 > 50%
- AI生成的营销文案打开率 > 人工文案（AB测试验证）
- 全链路归因可追溯：从曝光到核销的每一步可查
- 营销活动ROI自动计算，误差 < 5%

---

### WP-2：微信支付投放计划深度集成（8 人日）

#### WP-2.1 投放计划管理

**目标**：在屯象后台创建/管理微信支付"投放计划"（商品券/商家券/支付券）。

**改动文件**：

```
修改:
  services/tx-growth/src/api/wechat_pay_promotion_routes.py  # 投放计划路由
  services/tx-growth/src/services/wechat_pay_promotion_service.py  # 投放服务
  apps/web-admin/src/pages/marketing/CouponManage/           # 投放计划配置页
```

#### WP-2.2 投放效果分析

**目标**：投放曝光→领券→核销全链路数据回传到屯象分析平台。

**改动文件**：

```
修改:
  services/tx-analytics/src/api/campaign_routes.py         # 活动分析
  services/tx-analytics/src/reports/attribution_report/    # 归因报告
```

**验收标准**：
- 投放计划可在屯象后台一站式创建（选券→定人群→设预算→投放下单）
- 投放效果T+1回传（曝光量/领券量/核销率/新客率）
- 与AI营销闭环联动：AI圈选人群→自动创建投放→效果回传归因

---

### VC-1：视频号小程序交易组件对接（10 人日）

#### VC-1.1 视频号小店接入

**目标**：视频号直播挂载屯象小程序商品，用户可跳转小程序下单。

**改动文件**：

```
新增:
  services/gateway/src/api/channels_ec_routes.py          # 视频号电商回调路由
  
修改:
  services/tx-trade/src/api/webhook_routes.py              # 视频号订单同步
  services/tx-trade/src/services/channel_adapter.py        # 渠道适配器-视频号
  shared/events/src/event_types.py                         # 新增CHANNEL事件类型
  .env.example                                              # 视频号小店配置
```

#### VC-1.2 直播组件集成

**目标**：小程序内嵌视频号直播组件，直播时可直接下单。

**改动文件**：

```
修改:
  apps/miniapp-customer-v2/src/pages/index/index.tsx      # 首页直播入口
  apps/miniapp-customer-v2/src/components/VideoPlayer/VideoPlayer.tsx  # 直播组件
```

**验收标准**：
- 视频号直播时可挂载屯象小程序商品
- 用户下单后订单进入 tx-trade 统一订单中心
- 视频号订单同步到屯象POS可核销

---

### WA-1：微信 AI 智能体适配准备（8 人日）

**背景**：微信计划2026年Q3全量上线AI智能体（对话式入口调用小程序），屯象需要提前将小程序核心功能暴露为 Function Calling 格式。

**改动文件**：

```
新增:
  docs/wechat-ai-agent-adapter-plan.md                    # 适配设计方案
  
修改:
  services/gateway/src/external_sdk.py                    # 新增AI智能体SDK
  apps/miniapp-customer-v2/utils/api.js                   # 小程序API支持语义参数
  
列出所有需暴露的Function:
  1. 查询菜单: query_menu(store_id, dish_name, category)
  2. 提交订单: create_order(store_id, dishes[], preference)
  3. 查询订单状态: query_order(order_id)
  4. 查询会员信息: query_member(openid)
  5. 优惠查询: query_coupons(openid, store_id)
  6. 桌位预订: book_table(store_id, time, guests)
```

**验收标准**：
- 小程序核心功能可被语义参数调用（不依赖精确UI点击）
- 所有Function有完整的OpenAPI Schema描述
- 支持自然语言→参数的映射（如"帮我点上次的水煮鱼"→解析dish_id和历史记录）

---

### Phase 2 数据层迁移

```
shared/db-migrations/versions/v388_wecom_session_archive.py     # 企微会话存档表
shared/db-migrations/versions/v389_marketing_campaign_v2.py     # 营销活动V2表
shared/db-migrations/versions/v390_channels_ec_sync.py          # 视频号商品同步表
shared/db-migrations/versions/v391_attribution_tracking.py      # 归因追踪表
```

### Phase 2 测试计划

| 测试域 | 用例数 | 重点覆盖 |
|--------|-------|---------|
| WS-1 会话存档 | 15 | 消息解密、客诉识别准确率>85%、P0紧急推送 |
| AM-1 AI营销 | 20 | 人群圈定→权益→内容→触达→归因全链路 |
| WP-2 投放计划 | 8 | 创建→执行→效果回传→归因 |
| VC-1 视频号 | 6 | 订单同步、核销、退款 |
| WA-1 AI智能体 | 8 | Function Calling语义解析、参数映射 |

---

## Phase 3：全链路智能生态（2026 Q4）

### 总览

| 工作流 | 服务/应用 | 工作量(人日) |
|--------|----------|------------|
| B2B-1 微企付B2B供应链付款 | tx-supply, tx-finance | 10 |
| TM-1 腾讯地图旺店 | web-hub, tx-menu | 6 |
| SS-1 搜一搜品牌区 | web-hub | 3 |
| WA-2 微信AI智能体正式对接 | gateway, miniapp-customer, tx-agent | 12 |
| VI-1 视频号直播+KOC分销数据闭环 | tx-growth, tx-analytics | 8 |
| DA-1 全域数据智能分析 | tx-analytics, tx-brain | 10 |
| **测试与集成** | 全栈 | 10 |

**总计：~59 人日（含缓冲）**

---

### B2B-1：微企付B2B供应链付款（10 人日）

**目标**：连锁总部向供应商付款时，通过微企付完成B2B支付，实现业财一体。

**改动文件**：

```
新增:
  shared/integrations/weiqifu_pay.py                      # 微企付SDK
  
修改:
  services/tx-supply/src/api/purchase_order_routes.py     # 采购单付款集成
  services/tx-finance/src/api/settlement_routes.py        # 结算单对接
  services/tx-finance/src/services/fund_settlement.py     # 资金结算-微企付通道
  .env.example                                             # 新增微企付配置
```

**验收标准**：
- 采购单可直接通过微企付付款（单笔最高100万）
- 多主体分账（集团→品牌→门店维度）
- 付款流水自动对账，与tx-finance凭证匹配

---

### TM-1：腾讯地图旺店对接（6 人日）

**目标**：屯象商户菜品/门店信息同步到腾讯地图"旺店"，获取日超1亿的"附近商家"搜索流量。

**改动文件**：

```
新增:
  services/web-hub/src/integrations/tencent_map_wangdian.py  # 地图旺店同步服务

修改:
  services/tx-menu/src/api/menu_display_routes.py            # 菜品数据导出接口
  services/tx-menu/src/api/dish_routes.py                    # 推荐菜接口
  apps/web-admin/src/pages/settings/StoreListing/           # 地图旺店配置页
```

**验收标准**：
- 屯象商户菜品数据自动同步到腾讯地图旺店（T+1）
- 用户可在腾讯地图直接查看菜品/推荐菜/AI问答
- 旺店订位/预订可直接跳转屯象小程序

---

### WA-2：微信AI智能体正式对接（12 人日）

**目标**：微信AI智能体全量上线后，完成Function Calling正式对接，支持对话式点餐。

**改动文件**：

```
新增:
  services/gateway/src/api/wechat_ai_agent_routes.py       # AI智能体回调路由
  
修改:
  services/gateway/src/external_sdk.py                     # AI智能体SDK增强
  services/tx-agent/src/skills/ai_waiter.py                # AI点餐Agent-智能体模式
  apps/miniapp-customer-v2/src/hooks/useAuth.ts            # 智能体鉴权
  apps/miniapp-customer-v2/src/api/trade.ts                # 语义参数API
```

**验收标准**：
- 用户可通过微信对话完成点餐：查询菜单→下单→支付→查询状态
- 自然语言理解准确率 > 90%（基于测试集）
- 智能体调用小程序API延迟 < 2s

---

### Phase 3 数据层迁移

```
shared/db-migrations/versions/v392_weiqifu_payments.py       # 微企付付款记录
shared/db-migrations/versions/v393_store_listing_sync.py     # 门店曝光同步表
shared/db-migrations/versions/v394_ai_agent_session.py       # AI智能体对话记录
shared/db-migrations/versions/v395_unified_attribution.py    # 全域归因分析表
```

### Phase 3 测试计划

| 测试域 | 用例数 | 重点覆盖 |
|--------|-------|---------|
| B2B-1 微企付 | 8 | 采购付款、多主体分账、自动对账 |
| TM-1 地图旺店 | 6 | 菜品同步、AI问答回复、订位跳转 |
| WA-2 AI智能体 | 12 | 对话式点餐全流程、NLU准确率 |
| VI-1 视频号KOC | 6 | 分销追踪、佣金结算、ROI归因 |
| DA-1 全域分析 | 8 | 微信触点ROI归因、多渠道对比 |

---

## 四、风险矩阵

| # | 风险 | 影响 | 概率 | 应对 | 阶段 |
|---|------|------|------|------|------|
| R1 | 微信API政策变更（如摇优惠规则调整） | 高 | 中 | 微信网关抽象层，业务代码不直接调微信API | P1 |
| R2 | 视频号本地生活战略摇摆 | 中 | 高 | 优先做内容分发，不做交易闭环重度依赖 | P2 |
| R3 | 微信AI智能体上线延迟或政策限制 | 高 | 中 | Function Calling提前准备但不依赖，备选H5方案 | P2/P3 |
| R4 | 企微会话存档合规风险（用户授权不足） | 高 | 低 | 用户知情同意+加密存储+严格权限控制 | P2 |
| R5 | 五月差距关闭与P1并行资源冲突 | 中 | 中 | P1非阻塞项延至五月交付后进行 | P1 |
| R6 | 小程序分包超限（主包>2MB） | 中 | 低 | 严格分包策略，图片资源使用CDN | P1 |
| R7 | AI营销效果不达预期（转化率提升<50%） | 中 | 中 | AB实验先验证，达到阈值后全量 | P2 |
| R8 | 微信支付费率变动影响毛利 | 低 | 低 | 预留多元支付通道（云闪付/数币） | P3 |

---

## 五、依赖关系图

```
Phase 1:
  WP-1 (微信支付升级) ───┐
  MP-1 (小程序体验) ─────┼──┐
  MU-1 (UnionID打通) ────┼──┼──┐
  WC-1 (企微私域基建) ───┘  │  │
                           │  │
Phase 2:                   │  │
  WS-1 (会话存档+AI客诉) ───╯  │
  AM-1 (AI营销五步闭环) ──────╯
  WP-2 (投放计划深度) ─── WP-1
  VC-1 (视频号交易) ──── MP-1
  WA-1 (AI智能体准备) ── MU-1+MP-1

Phase 3:
  B2B-1 (微企付) ────── WC-1
  TM-1 (地图旺店) ───── MU-1
  WA-2 (AI智能体正式) ── WA-1+AM-1
  VI-1 (视频号KOC) ──── VC-1+WP-2
  DA-1 (全域分析) ───── AM-1+所有
```

---

## 六、交付路线图（甘特图风格）

```
Q2 2026                        Q3 2026                           Q4 2026
│                              │                                │
WP-1 ████████                  │                                │
MP-1 ████████████              │                                │
MU-1 █████                     │                                │
WC-1 ██████████                │                                │
数据层 ███                      │                                │
测试  █████                     │                                │
│                              │                                │
WS-1            ███████████████                                │
AM-1            ████████████████████                            │
WP-2            ████████                                       │
VC-1            ██████████                                     │
WA-1            ████████                                       │
测试             ██████████                                     │
│                              │                                │
B2B-1                                        ██████████        │
TM-1                                         ██████            │
WA-2                                         ████████████      │
VI-1                                         ████████          │
DA-1                                         ██████████        │
测试                                          ██████████        │
```

---

## 七、代码交付清单汇总

### 新增文件（按阶段）

```
Phase 1:
  shared/integrations/wechat_pay_promotion.py
  services/tx-growth/src/api/wechat_pay_promotion_routes.py
  services/tx-growth/src/api/wecom_channel_code_routes.py
  services/tx-growth/src/services/wecom_channel_code_service.py
  services/tx-growth/src/services/wecom_auto_tag_service.py
  shared/db-migrations/versions/v384_wecom_channel_code.py
  shared/db-migrations/versions/v385_merchant_theme.py
  shared/db-migrations/versions/v386_wechat_promotion.py
  shared/db-migrations/versions/v387_events_composite_idx.py

Phase 2:
  services/gateway/src/wecom_session_archive.py
  services/gateway/src/api/wecom_session_callback.py
  services/gateway/src/services/wecom_decrypt_service.py
  services/tx-agent/src/workers/wecom_session_consumer.py
  services/tx-agent/src/skills/complaint_identifier.py
  services/tx-agent/src/services/complaint_escalation.py
  services/tx-brain/src/services/marketing_content_gen.py
  services/gateway/src/api/channels_ec_routes.py
  docs/wechat-ai-agent-adapter-plan.md
  shared/db-migrations/versions/v388_wecom_session_archive.py
  shared/db-migrations/versions/v389_marketing_campaign_v2.py
  shared/db-migrations/versions/v390_channels_ec_sync.py
  shared/db-migrations/versions/v391_attribution_tracking.py

Phase 3:
  shared/integrations/weiqifu_pay.py
  services/web-hub/src/integrations/tencent_map_wangdian.py
  services/gateway/src/api/wechat_ai_agent_routes.py
  shared/db-migrations/versions/v392_weiqifu_payments.py
  shared/db-migrations/versions/v393_store_listing_sync.py
  shared/db-migrations/versions/v394_ai_agent_session.py
  shared/db-migrations/versions/v395_unified_attribution.py
```

### 修改文件（按服务统计）

```
service/gateway/        → 9 文件 (wecom_*.py, external_sdk.py, .env.example)
service/tx-trade/       → 3 文件 (wechat_pay_routes.py, webhook_routes.py)
service/tx-pay/         → 1 文件 (wechat.py)
service/tx-growth/      → 8 文件 (wecom_scrm_agent_routes.py, coupon_service.py, 等)
service/tx-member/      → 4 文件 (identity_resolver.py, golden_id_routes.py, profile360.py)
service/tx-agent/       → 9 文件 (member_insight.py, rfm_outreach.py, content_generation.py, 等)
service/tx-menu/        → 3 文件 (menu_display_routes.py, menu_recommendation_routes.py)
service/tx-brain/       → 3 文件 (menu_optimizer.py, customer_service.py)
service/tx-supply/      → 1 文件 (purchase_order_routes.py)
service/tx-finance/     → 2 文件 (settlement_routes.py, fund_settlement.py)
service/tx-analytics/   → 5 文件 (attribution_routes.py, campaign_routes.py, 等)
service/web-hub/        → 1 文件 (tencent_map_wangdian.py)
apps/miniapp-customer-v2/ → 8 文件 (app.tsx, menu.ts, index.tsx, 多组件)
apps/web-admin/         → 4 页面 (CouponManage/, WecomChannel/, WecomMass/, StoreListing/)
apps/web-hub/           → 1 集成文件
```

---

## 八、与五月差距关闭计划的协同

```
五月计划 (may-gap-closure-plan-2026-05.md)   微信三阶段计划
──────────────────────────────              ──────────────
Week 1 (05-01~05-07): 数据质量标准化           WP-1 启动(设计阶段)
Week 2 (05-08~05-14): AI分析深化               WP-1 开发 + MU-1 启动
Week 3 (05-15~05-21): 压测与演示监控            WP-1 完成 + MP-1 启动
Week 4 (05-22~05-31): 上线交付                  MP-1 开发 + WC-1 启动
06-01~06-30: 交付后迭代                        MP-1+WC-1 完成 + 测试
```

**并行策略**：
- 五月前两周：微信团队与数据团队并行工作，WP-1设计评审
- 五月后两周：五月交付压力下降后，微信接入开发逐步推进
- 六月：全速推进Phase 1剩余工作，完成测试后在czyz灰度上线

---

## 九、验收标准与 KPI

### Phase 1 验收门禁

| 检查点 | 标准 | 验收方式 |
|--------|------|---------|
| 摇优惠全流程 | 支付→摇一摇→领券→到店核销 → 100% 可用 | E2E测试 + 手动验证 |
| 小程序首屏加载 | < 2s (3G网络) | Lighthouse 评分 |
| UnionID补全率 | > 90% | sql 查询 |
| 渠道活码 | 扫码→自动标签→入群→30s内完成 | E2E测试 |
| 多商户定制 | 3商户主题各自正确渲染 | 截图对比 |
| 迁移脚本 | v384-v387 全部可回滚 | pytest migration test |

### Phase 2 验收门禁

| 检查点 | 标准 | 验收方式 |
|--------|------|---------|
| 客诉识别准确率 | > 85% | 标注集评估 |
| AI营销转化率 | AI组 > 人工组(提升 > 50%) | AB实验 |
| 会话存档延迟 | 消息→入库 < 10s | 监控告警 |
| 投放计划ROI | 自动计算误差 < 5% | 人工复核 |
| 视频号订单 | 订单→POS核销全流程 | E2E测试 |

### Phase 3 验收门禁

| 检查点 | 标准 | 验收方式 |
|--------|------|---------|
| 微企付付款 | 采购单→付款→对账全流程 | E2E测试 |
| 地图旺店同步 | T+1数据一致 | 数据对比 |
| AI智能体 | 对话式点餐成功率 > 90% | 测试集评估 |
| 全域归因 | 微信触点ROI可量化 | 报告验证 |

---

> 本计划基于屯象OS仓库（v383迁移基线）和微信开放平台2026年Q2最新API文档编写。  
> 执行过程中如发现微信API变更或政策调整，及时更新本文件并在DEVLOG.md记录。
