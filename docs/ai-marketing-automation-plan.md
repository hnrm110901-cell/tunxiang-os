# 屯象OS AI营销自动化 — 产品开发计划 V1.0

> 撰写日期：2026-04-11 | 负责人：屯象科技产品团队
> 本文档描述屯象OS营销自动化模块的完整建设路径，面向连锁餐饮品牌"增长飞轮"场景。

---

## 一、战略定位

**核心命题**：让连锁餐饮每一条营销动作都有数据闭环，每一笔广告花费都能溯源到ROI。

屯象OS定位"连锁餐饮行业的Palantir"，营销自动化是其中不可或缺的增长引擎。相比传统餐饮系统的"发券→核销"单一链路，屯象OS营销自动化要建立：

```
流量获取（抖音/美团/私域）
    → 用户识别（Golden ID）
        → 旅程编排（个性化触达）
            → 内容生成（AIGC）
                → 核销归因（多触点）
                    → 策略优化（闭环）
```

**差异化竞争点**：
- AI驱动内容生成，比传统系统快10倍出稿
- 全渠道统一归因，打通美团/抖音/私域数据孤岛
- Agent实时决策，折扣符合三条硬约束（毛利/食安/体验）
- 边缘推理（Mac mini M4），离线场景下营销策略继续生效

---

## 二、现状盘点（已有基础）

### tx-growth 服务（:8004）已覆盖
- **24种活动类型**：满减、折扣、买赠、换购、组合、拼团、秒杀等
- **旅程引擎**（journey_engine）：多节点、多条件触发的用户旅程编排
- **渠道引擎**（channel_engine）：支持短信/微信小程序订阅消息/应用内推送
- **内容引擎**（content_engine）：基础模板管理、变量替换
- **A/B测试框架**：流量分桶、效果对比
- **营销归因**（attribution）：末次触点归因（last-touch）

### shared/integrations 已接入
- `wechat_subscribe.py`：微信小程序订阅消息（4种模板）
- `sms_service.py`：短信（阿里云/腾讯云双通道）
- `wechat_pay.py`：微信支付（JSAPI/Native/H5）
- `notification_dispatcher.py`：统一通知调度器

### tx-agent 服务（:8008）已有
- **私域运营Agent**（P2优先级）：已定义Skill框架
- **内容生成Skill**：基于Claude API的文案生成能力

---

## 三、差距分析 & 新增模块

| 差距维度 | 现状 | 目标 | 新增模块 |
|----------|------|------|----------|
| 渠道覆盖 | 微信小程序+短信 | 公众号+企微+美团+饿了么+抖音 | wechat_marketing / meituan_marketing / douyin_marketing |
| 内容生产 | 人工填模板 | Claude驱动AIGC批量生产 | ContentHub（tx-growth扩展） |
| 广告数据 | 无 | 美团/抖音广告花费+ROI数据接入 | 渠道数据聚合层 |
| 归因模型 | 末次触点 | 多触点归因（线性/时间衰减/数据驱动） | attribution_v2 |
| 竞品监控 | 无 | 周边竞品价格/活动抓取+对比 | competitor_monitor |
| Agent决策 | P2占位 | 实时营销Agent，通过三条硬约束 | MarketingAgent升级 |

---

## 四、分层实现路线图（3 Phase）

### Phase 1 — 渠道全面接入（Q2 2026，第1-6周）

**Week 1-2：微信公众号模板消息 + 企业微信群发**

目标：打通公众号触达链路，支持企微客户群批量运营

交付物：
- `shared/integrations/wechat_marketing.py`
  - `WeChatOAService`：公众号模板消息（send_template_msg）
  - `WeComService`：企微客户消息（send_text_to_customer / send_miniprogram_to_customer / batch_send_to_tag）
- tx-growth新增API：`POST /api/v1/marketing/oa-template/send`
- Mock模式：WX_OA_APPID未配置时自动降级，不影响开发联调

验收标准：
- 单条模板消息发送成功率 ≥ 99%（非Mock模式）
- access_token缓存命中率 ≥ 95%（2小时TTL，提前5分钟刷新）
- 覆盖测试 ≥ 3个用例

**Week 3-4：美团/饿了么营销API**

目标：在屯象OS内直接创建/管理美团优惠券和促销活动，无需登录美团商家后台

交付物：
- `shared/integrations/meituan_marketing.py`
  - `MeituanMarketingAdapter`：优惠券创建/促销管理/广告数据/归因数据
- tx-growth新增API：`POST /api/v1/marketing/meituan/coupon`
- HMAC-SHA256签名实现（美团开放平台标准）

验收标准：
- Mock模式返回结构与真实API一致（便于前端联调）
- 签名算法通过美团开放平台签名校验工具验证
- 优惠券创建接口端到端测试 ≥ 3个用例

**Week 5-6：抖音本地生活API + 微信广告**

目标：接入抖音POI活动、直播间订单同步、广告ROI数据

交付物：
- `shared/integrations/douyin_marketing.py`
  - `DouyinMarketingAdapter`：POI活动/内容效果/广告ROI/直播订单同步/客流归因
- OAuth2 access_token管理（抖音开放平台）

验收标准：
- 直播订单同步延迟 ≤ 5分钟
- 广告ROI数据拉取覆盖测试 ≥ 3个用例

---

### Phase 2 — AIGC内容中枢（Q2 2026，第7-10周）

**Week 7-8：Claude API驱动ContentHub**

目标：AI批量生成营销文案、朋友圈素材、公众号图文，效率提升10倍

架构设计：
```
ContentHub（tx-growth）
    ├── 内容需求输入（渠道/活动类型/菜品/目标用户画像）
    ├── Claude API 调用（claude-3-5-sonnet，streaming）
    ├── 内容审核（敏感词过滤 + 品牌规范校验）
    ├── ai_content_cache（PostgreSQL缓存，避免重复生成）
    └── 内容分发（公众号/企微/短信/小程序）
```

数据库新增表（见第七节）：
- `ai_content_cache`：AIGC生成内容缓存，按(prompt_hash, channel)唯一索引

API新增：
- `POST /api/v1/content/generate`：输入营销场景，输出多渠道文案
- `POST /api/v1/content/batch-generate`：批量生成（异步任务）
- `GET /api/v1/content/cache/{content_id}`：获取缓存内容

验收标准：
- 单条文案生成 ≤ 8秒（P95）
- 缓存命中时响应 ≤ 100ms
- 内容审核覆盖率100%（所有生成内容必须过审）

**Week 9-10：AI营销编排Agent**

目标：MarketingAgent从P2升级为可用状态，支持自动化营销决策

Agent能力升级：
```python
# MarketingAgent 决策流程
1. 读取门店经营数据（物化视图 mv_store_pnl / mv_member_clv）
2. 识别营销机会（如：某菜品毛利高但销量低 → 适合做买赠活动）
3. 通过三条硬约束校验（毛利底线 / 食安合规 / 客户体验）
4. 生成营销方案（活动类型 + 目标人群 + 渠道组合 + 预算）
5. ContentHub生成文案
6. 提交审批（人工确认后自动投放）
7. 投放后持续监控ROI → 超预算自动暂停
```

必须记录 AgentDecisionLog（含 constraints_check 字段），无例外。

---

### Phase 3 — 品效闭环（Q3 2026，第11-16周）

**Week 11-12：多触点归因模型升级**

目标：从末次触点归因升级为数据驱动归因（Data-Driven Attribution）

实现方案：
- 新增 `marketing_touch_log` 表（见第七节），记录每次营销触达
- 归因算法支持：末次触点（默认）/ 首次触点 / 线性归因 / 时间衰减归因
- 归因窗口可配置：1天/7天/30天
- 归因结果写入 `mv_channel_margin` 物化视图

**Week 13-14：经营驾驶舱营销模块**

目标：tx-analytics新增营销ROI看板，与经营P&L打通

新增分析维度：
- 渠道ROI对比（美团 vs 抖音 vs 私域 vs 大众点评）
- 会员营销效果（RFM分层 × 活动类型 × 转化率）
- AIGC内容效果追踪（文案A/B测试 × 转化归因）
- 广告花费趋势（日/周/月）

**Week 15-16：竞品监控 + 动态策略调整**

目标：自动感知周边竞品价格变动，动态调整营销策略

实现方案：
- 数据来源：大众点评/美团商家端公开数据（合规爬取）
- 监控维度：竞品菜单价格 / 促销活动 / 评分变化
- 触发规则：竞品降价超过阈值 → Agent自动生成应对方案 → 人工确认后执行
- 频率：每日一次全量对比，每小时增量监控

---

## 五、技术架构图

```
┌─────────────────────────────────────────────────────────┐
│                    营销触达渠道层                          │
│  微信公众号  企业微信  美团商家  饿了么  抖音本地生活  短信  │
│  (WeChatOA) (WeCom) (Meituan) (Eleme) (Douyin) (SMS)  │
└──────────────────────┬──────────────────────────────────┘
                       │ shared/integrations/*
┌──────────────────────▼──────────────────────────────────┐
│                  tx-growth 营销中台                        │
│  旅程引擎  内容引擎(AIGC)  活动引擎  归因引擎  A/B测试      │
│  journey  ContentHub   campaign  attribution  ab_test  │
└──────┬───────────────┬──────────────────────────────────┘
       │               │
┌──────▼──────┐ ┌──────▼──────────────────────────────────┐
│  tx-agent   │ │          tx-analytics 数据层               │
│ Marketing   │ │  mv_member_clv  mv_channel_margin         │
│   Agent     │ │  mv_store_pnl   marketing_touch_log       │
│ (Claude API)│ │  ai_content_cache                        │
└─────────────┘ └─────────────────────────────────────────┘
```

---

## 六、API设计规范

所有营销API遵循屯象OS统一规范：

```
请求头：
  X-Tenant-ID: {uuid}        # 租户隔离（必须）
  Authorization: Bearer {jwt} # 身份验证

响应格式：
  { "ok": true, "data": {}, "error": null }

分页：
  GET /api/v1/marketing/campaigns?page=1&size=20
  返回：{ "items": [...], "total": 100, "page": 1, "size": 20 }
```

**新增API清单（Phase 1-2）**：

```
# 公众号/企微
POST /api/v1/marketing/oa-template/send          # 发送公众号模板消息
POST /api/v1/marketing/wecom/customer-msg        # 企微客户消息
POST /api/v1/marketing/wecom/batch-tag-send      # 企微标签群发

# 美团营销
POST /api/v1/marketing/meituan/coupon            # 创建美团优惠券
GET  /api/v1/marketing/meituan/promotions        # 获取促销列表
PUT  /api/v1/marketing/meituan/promotion/{id}    # 更新促销配置
GET  /api/v1/marketing/meituan/ad-spend          # 广告花费数据
GET  /api/v1/marketing/meituan/attribution       # 订单归因数据

# 抖音营销
POST /api/v1/marketing/douyin/poi-activity       # 创建POI活动
GET  /api/v1/marketing/douyin/content-performance # 内容效果数据
GET  /api/v1/marketing/douyin/ad-roi             # 广告ROI
POST /api/v1/marketing/douyin/sync-live-orders   # 同步直播订单
GET  /api/v1/marketing/douyin/store-traffic      # 到店客流归因

# AIGC内容
POST /api/v1/content/generate                    # AI生成营销文案
POST /api/v1/content/batch-generate              # 批量生成（异步）
GET  /api/v1/content/cache/{content_id}          # 获取缓存内容

# 归因分析
GET  /api/v1/marketing/attribution/channel       # 渠道归因汇总
GET  /api/v1/marketing/attribution/touch-path    # 用户触点路径
```

---

## 七、数据库新增表设计

```sql
-- 渠道账号配置（一个租户可有多个渠道账号）
CREATE TABLE marketing_channel_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    channel         VARCHAR(32) NOT NULL,   -- wechat_oa / wecom / meituan / douyin / eleme
    account_name    VARCHAR(128) NOT NULL,
    credentials     JSONB NOT NULL,         -- 加密存储，密钥由KMS管理
    store_ids       UUID[],                 -- 关联门店（NULL=全品牌）
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    is_deleted      BOOLEAN DEFAULT FALSE,
    UNIQUE(tenant_id, channel, account_name)
);

-- RLS策略
ALTER TABLE marketing_channel_accounts ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON marketing_channel_accounts
    USING (tenant_id = current_setting('app.tenant_id')::UUID);

-- AIGC内容缓存
CREATE TABLE ai_content_cache (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    prompt_hash     VARCHAR(64) NOT NULL,   -- SHA256(prompt)
    channel         VARCHAR(32) NOT NULL,   -- 目标渠道
    content_type    VARCHAR(32) NOT NULL,   -- 文案/图文/短视频脚本
    generated_text  TEXT NOT NULL,
    model_version   VARCHAR(64),            -- claude-3-5-sonnet-20241022等
    generation_params JSONB,
    hit_count       INTEGER DEFAULT 0,
    expires_at      TIMESTAMPTZ,            -- NULL=永不过期
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    is_deleted      BOOLEAN DEFAULT FALSE,
    UNIQUE(tenant_id, prompt_hash, channel)
);

ALTER TABLE ai_content_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON ai_content_cache
    USING (tenant_id = current_setting('app.tenant_id')::UUID);

-- 营销触达记录（多触点归因核心数据）
CREATE TABLE marketing_touch_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    customer_id     UUID NOT NULL,          -- Golden Customer ID
    store_id        UUID,
    channel         VARCHAR(32) NOT NULL,   -- 触达渠道
    campaign_id     UUID,                   -- 关联活动ID
    content_id      UUID,                   -- 关联内容ID
    touch_type      VARCHAR(32) NOT NULL,   -- impression/click/conversion
    touch_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    order_id        UUID,                   -- 若为conversion，关联订单ID
    revenue_fen     BIGINT DEFAULT 0,       -- 带来的GMV（分）
    attribution_weight NUMERIC(5,4),        -- 归因权重（0-1）
    metadata        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    is_deleted      BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_touch_log_customer ON marketing_touch_log(tenant_id, customer_id, touch_at DESC);
CREATE INDEX idx_touch_log_campaign ON marketing_touch_log(tenant_id, campaign_id, touch_at DESC);
CREATE INDEX idx_touch_log_order ON marketing_touch_log(tenant_id, order_id) WHERE order_id IS NOT NULL;

ALTER TABLE marketing_touch_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON marketing_touch_log
    USING (tenant_id = current_setting('app.tenant_id')::UUID);
```

---

## 八、关键指标 & 验收标准

### Phase 1 验收指标

| 指标 | 目标值 | 测量方式 |
|------|--------|----------|
| 公众号模板消息发送成功率 | ≥ 99% | 7天滑动窗口 |
| 美团优惠券创建成功率 | ≥ 98% | 生产环境监控 |
| 抖音直播订单同步延迟 | ≤ 5分钟 | P95延迟 |
| access_token缓存命中率 | ≥ 95% | 缓存层指标 |
| Mock模式降级可用 | 100% | 无env var时正常返回mock数据 |

### Phase 2 验收指标

| 指标 | 目标值 | 测量方式 |
|------|--------|----------|
| AI文案生成耗时（P95） | ≤ 8秒 | APM监控 |
| 内容缓存命中响应时间 | ≤ 100ms | APM监控 |
| Agent决策留痕覆盖率 | 100% | AgentDecisionLog审计 |
| 三条硬约束通过率 | 100% | 强制校验，无法绕过 |

### Phase 3 验收指标

| 指标 | 目标值 | 测量方式 |
|------|--------|----------|
| 多触点归因覆盖率 | ≥ 80% | 已归因订单/总订单 |
| 渠道ROI看板数据刷新 | ≤ 1小时 | 物化视图刷新周期 |
| 竞品监控覆盖范围 | ≥ 门店5公里内TOP5竞品 | 人工抽样验证 |

---

## 九、风险与合规

### 微信营销合规
- **公众号模板消息**：仅在用户产生交互行为后48小时内发送服务通知，禁止用于纯营销推广
- **企微外部联系人消息**：需用户添加企微账号，单日发送频率 ≤ 4条/客户
- **不超发原则**：同一用户同一活动的触达次数，在 `marketing_touch_log` 中检查后决定是否发送
- **退订机制**：所有营销消息必须提供退订入口，退订状态写入 Customer 实体

### 数据隐私
- **脱敏原则**：日志中手机号/openid脱敏（已在各Adapter中实现）
- **最小必要原则**：不采集超过营销目的所需的用户数据
- **credentials加密**：`marketing_channel_accounts.credentials` 字段使用应用层加密存储
- **数据留存**：`marketing_touch_log` 保留90天，超期自动归档或删除

### Agent决策合规
- 所有营销Agent决策必须通过三条硬约束校验
  1. **毛利底线**：活动折扣后单笔毛利不低于设定阈值
  2. **食安合规**：促销菜品不含临期/过期食材（查 `mv_safety_compliance`）
  3. **客户体验**：大促时段不触发可能导致超时的菜品组合
- `AgentDecisionLog.constraints_check` 必须记录三条约束的校验结果

### 第三方平台合规
- 美团开放平台：遵守《美团商家数据使用规范》，不爬取竞品数据
- 抖音开放平台：遵守《抖音开放平台开发者协议》
- 竞品监控仅使用公开展示数据，不调用任何非授权接口

---

## 十、团队分工 & 里程碑

### 人员配置
| 角色 | 人数 | 职责 |
|------|------|------|
| 后端工程师 | 2 | shared/integrations适配器开发 + tx-growth API扩展 |
| AI工程师 | 1 | ContentHub + MarketingAgent开发 |
| 数据工程师 | 1 | 归因模型 + 物化视图 + 驾驶舱 |
| 产品经理 | 1 | 需求评审 + 验收 + 合规把关 |

### 里程碑

```
2026-04-18  Phase 1 Week 1-2  微信公众号+企微适配器完成，Mock测试通过
2026-04-25  Phase 1 Week 3-4  美团营销适配器完成，签名验证通过
2026-05-02  Phase 1 Week 5-6  抖音营销适配器完成，直播订单同步联调完成
2026-05-09  Phase 1 验收      三个适配器全部接入tx-growth，集成测试通过
2026-05-16  Phase 2 Week 7-8  ContentHub上线，AI文案生成P95 ≤ 8秒
2026-05-23  Phase 2 Week 9-10 MarketingAgent升级完成，Agent决策留痕100%
2026-05-30  Phase 2 验收      尝在一起试点，营销文案生产效率提升验证
2026-06-13  Phase 3 Week 11-12 多触点归因上线，touch_log数据回填
2026-06-27  Phase 3 Week 13-14 营销ROI看板上线
2026-07-11  Phase 3 Week 15-16 竞品监控上线（尚宫厨试点）
2026-07-18  全量验收           三个首批客户全部覆盖，ROI看板数据对齐
```

### 关键依赖
- 微信开放平台账号（由客户品牌方提供公众号/企微）
- 美团商家开放平台API权限申请（需3-5个工作日审核）
- 抖音本地生活服务商资质（需提前申请）
- Claude API配额（tx-brain/ModelRouter统一管理，禁止直接调用）
