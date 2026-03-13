# 屯象OS 预订Agent 开发计划

> **版本**: v1.0 | **日期**: 2026-03-13
> **目标**: 整合易订PRO、客必得、宴荟佳、宴小猪四家竞品精华，构建餐饮行业最强AI预订Agent

---

## 一、四家竞品核心能力拆解

| 维度 | 易订PRO | 客必得 | 宴荟佳 | 宴小猪 |
|------|---------|--------|--------|--------|
| **定位** | 全渠道预订中台 | 客源管理+风控 | 婚礼堂数智化SaaS | 一站式宴会管理 |
| **最强能力** | 平台对接/渠道整合 | 客户资产风控 | 销控+履约闭环 | 综合业态+EO单 |
| **目标客群** | 酒店/高端餐饮 | 中大型餐厅/连锁 | 婚礼堂 | 宴会酒店/婚庆综合体 |
| **CRM深度** | 中（自动分类+标签） | 高（等级+风控+交接） | 高（轮转+竞对） | 中（跟进+提醒） |
| **宴会管理** | 有（档期+看板） | 弱 | 强（全链路） | 强（EO单+厅管理） |
| **数据分析** | 强（多维报表） | 中 | 强（趋势预测） | 中 |

### 从每家吸收的精华

| 来源 | 吸收能力 | 屯象Agent对应模块 |
|------|---------|------------------|
| **易订PRO** | 全渠道预订接单（美团/大众/抖音API对接）、桌位实时同步、存酒管理、自动化报表推送、退订率管理 | 渠道中台 + 报表引擎 |
| **客必得** | 客户资产风控（归属追踪+离职交接+流失预警）、客户等级自动识别、服务资源匹配、餐前-餐中-餐后闭环 | CRM风控 + 服务匹配 |
| **宴荟佳** | 7阶段销控漏斗（已有）、吉日等级设定、动态去化+变价配置、竞对分析、履约节点跟踪、客资三次轮转 | 宴会销控 + 履约管理 |
| **宴小猪** | EO单(Event Order)自动生成、宴会厅实景展示、演职人员资源调度、商家小程序、多业态管理 | EO执行 + 资源调度 |

---

## 二、屯象预订Agent 整体架构

```
                    ┌─────────────────────────────────────┐
                    │         屯象预订 Agent (AI层)         │
                    │  意图识别 · 智能推荐 · 自动跟进 · 预测  │
                    └──────────────┬──────────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          ▼                        ▼                        ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  渠道中台 (易订)   │  │  CRM风控 (客必得)  │  │  宴会引擎 (宴荟佳) │
│                  │  │                  │  │                  │
│ · 美团/大众对接    │  │ · 客户等级识别     │  │ · 7阶段销控漏斗   │
│ · 抖音/小红书     │  │ · 归属追踪        │  │ · 档期销控        │
│ · 企微/电话/到店  │  │ · 离职风控交接     │  │ · 吉日等级        │
│ · 桌位实时同步    │  │ · 流失预警        │  │ · 动态去化定价     │
│ · 退订率管理     │  │ · 服务资源匹配     │  │ · 竞对分析        │
└──────────────────┘  └──────────────────┘  └──────────────────┘
          │                        │                        │
          └────────────────────────┼────────────────────────┘
                                   ▼
                    ┌──────────────────────────┐
                    │    EO执行引擎 (宴小猪)      │
                    │                          │
                    │ · EO单自动生成             │
                    │ · 厅位实景展示              │
                    │ · 演职人员调度              │
                    │ · 履约节点追踪              │
                    │ · 合同/订单/回款管理         │
                    └──────────────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          ▼                        ▼                        ▼
    ┌───────────┐          ┌───────────┐          ┌───────────┐
    │ 易订API    │          │ POS系统    │          │ 企业微信   │
    │ Adapter   │          │ Adapters  │          │ Webhook   │
    │ (已有)    │          │ (已有)     │          │ (已有)    │
    └───────────┘          └───────────┘          └───────────┘
```

---

## 三、屯象AI加持 — 竞品没有的差异化

| AI能力 | 说明 | 对应竞品短板 |
|--------|------|------------|
| **智能档期推荐** | 基于历史数据预测最优档期+定价，告诉销售"这个日子报价¥X最合适" | 宴荟佳/宴小猪只有手动设定 |
| **客户意向预测** | 分析跟进记录，预测成交概率，标注"高意向/低意向" | 客必得只有静态等级 |
| **自动跟进话术** | AI生成个性化跟进话术，推送到企微 | 四家都是手动跟进 |
| **流失预警+挽回** | 识别沉睡客户，自动触发挽回营销（优惠券/专属邀约） | 客必得有预警但无自动挽回 |
| **最优厅位匹配** | 根据宴会规模/预算/偏好，AI推荐最优厅位+套餐组合 | 宴小猪只是展示 |
| **退订原因分析** | NLP分析退订原因，生成改进建议 | 易订有退订率但无原因分析 |
| **竞对情报** | 自动采集竞对报价/档期，辅助定价决策 | 宴荟佳有竞对分析但手动 |
| **EO单智能生成** | 根据宴会类型+客户偏好，AI预填80%的EO单内容 | 宴小猪是模板填写 |

---

## 四、数据模型扩展

### 4.1 新增模型

```python
# ── 渠道来源 (易订) ──
class ReservationChannel(Base):
    """预订渠道追踪"""
    id: str                          # CHN_xxx
    reservation_id: str (FK)         # 关联预订
    channel: Enum                    # MEITUAN/DIANPING/DOUYIN/WECHAT/PHONE/WALK_IN/REFERRAL
    external_order_id: str           # 外部平台订单号
    channel_commission_rate: Decimal  # 渠道佣金比例
    source_url: str                  # 来源链接
    utm_params: JSON                 # 营销追踪参数

# ── 客户风控 (客必得) ──
class CustomerOwnership(Base):
    """客户归属追踪（防止人走客走）"""
    id: str
    customer_id: str (FK)
    owner_employee_id: str (FK)      # 归属销售
    assigned_at: DateTime
    transferred_at: DateTime         # 交接时间
    transferred_from: str            # 前归属人
    transfer_reason: Enum            # RESIGNATION/REORG/MANUAL
    is_active: bool

class CustomerRiskAlert(Base):
    """客户流失预警"""
    id: str
    customer_id: str (FK)
    risk_level: Enum                 # HIGH/MEDIUM/LOW
    risk_type: Enum                  # DORMANT/DECLINING/COMPETITOR_LOST
    last_visit_days: int             # 距上次消费天数
    predicted_churn_probability: float
    suggested_action: str            # AI建议的挽回动作
    action_taken: bool
    action_result: str

# ── 宴会销控 (宴荟佳) ──
class BanquetDateConfig(Base):
    """档期吉日等级+定价"""
    id: str
    store_id: str (FK)
    date: Date
    day_type: Enum                   # AUSPICIOUS_S/AUSPICIOUS_A/AUSPICIOUS_B/NORMAL/OFF_PEAK
    base_price_multiplier: Decimal   # 价格系数 (如吉日1.3倍)
    is_locked: bool                  # 是否已被锁定
    locked_by_reservation_id: str
    notes: str

class BanquetCompetitor(Base):
    """竞对分析"""
    id: str
    store_id: str (FK)
    competitor_name: str             # 竞争酒店名
    competitor_price_range: str      # "¥2888-¥5888/桌"
    lost_deals_count: int            # 输给该竞对的单数
    common_lost_reasons: JSON        # ["价格高", "场地小"]
    last_updated: DateTime

class SalesFunnel(Base):
    """销售漏斗追踪"""
    id: str
    reservation_id: str (FK)
    stage: Enum                      # 复用已有 BanquetStage 7阶段
    entered_at: DateTime
    exited_at: DateTime
    duration_hours: int              # 在该阶段停留时长
    owner_employee_id: str           # 负责销售
    follow_up_count: int             # 跟进次数
    follow_up_notes: JSON            # 跟进记录列表
    conversion_probability: float    # AI预测转化率

# ── EO执行 (宴小猪) ──
class EventOrder(Base):
    """EO单（宴会执行单）"""
    id: str                          # EO_20260313_001
    reservation_id: str (FK)
    store_id: str (FK)

    # 基本信息
    event_type: Enum                 # WEDDING/BIRTHDAY/CORPORATE/FAMILY
    event_date: Date
    event_time: Time
    guest_count: int
    table_count: int

    # 厅位
    hall_id: str
    hall_layout: JSON                # 厅位摆台布局

    # 餐标
    menu_package: str                # 套餐名称
    price_per_table: int             # 每桌价格(分)
    total_amount: int                # 总金额(分)

    # 服务配置
    welcome_setup: JSON              # 迎宾布置要求
    stage_setup: JSON                # 舞台/LED要求
    flower_requirements: JSON        # 花艺要求
    audio_video: JSON                # 音响灯光要求
    special_requirements: str        # 特殊要求

    # 人员调度
    service_staff_count: int         # 服务人员数
    chef_notes: str                  # 厨房备注

    # 状态
    status: Enum                     # DRAFT/CONFIRMED/IN_PROGRESS/COMPLETED
    confirmed_by: str                # 客户确认人
    confirmed_at: DateTime

    # 时间线
    setup_start_time: Time           # 布场开始
    guest_arrival_time: Time         # 客人到场
    event_start_time: Time           # 宴会开始
    event_end_time: Time             # 宴会结束
    teardown_end_time: Time          # 撤场结束

class EventStaff(Base):
    """宴会演职人员调度"""
    id: str
    event_order_id: str (FK)
    role: Enum                       # MC/PHOTOGRAPHER/VIDEOGRAPHER/FLORIST/LIGHTING/DJ
    staff_name: str
    staff_phone: str
    company: str                     # 所属公司
    fee: int                         # 费用(分)
    confirmed: bool
    notes: str

class HallShowcase(Base):
    """宴会厅实景展示"""
    id: str
    store_id: str (FK)
    hall_name: str
    capacity_min: int
    capacity_max: int
    table_count_max: int
    area_sqm: Decimal                # 面积
    ceiling_height: Decimal          # 层高
    has_led_screen: bool
    has_stage: bool
    has_natural_light: bool
    images: JSON                     # 实景照片URL列表
    virtual_tour_url: str            # VR全景链接
    price_range: str                 # "¥2888-¥5888/桌"
    description: str
    features: JSON                   # 亮点标签
```

### 4.2 扩展已有模型

```python
# Reservation 模型扩展字段
class Reservation(Base):
    # ... 已有字段 ...

    # 新增: 渠道追踪 (易订)
    source_channel: str              # MEITUAN/DIANPING/DOUYIN/WECHAT/PHONE/WALK_IN
    external_order_id: str           # 外部平台订单号

    # 新增: 客户归属 (客必得)
    owner_employee_id: str           # 归属销售经理

    # 新增: 销控 (宴荟佳)
    conversion_probability: float    # AI预测成交率
    competitor_name: str             # 客户对比的竞对
    follow_up_deadline: DateTime     # 下次跟进截止时间

    # 新增: 存酒 (易订)
    wine_storage_id: str             # 关联存酒记录
```

---

## 五、开发阶段计划

### Phase 1: 渠道中台 + CRM风控（Week 1-3）

**目标**: 从易订PRO和客必得吸收核心能力

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 渠道来源模型 + migration | `models/reservation_channel.py` | 0.5d |
| 客户归属模型 + migration | `models/customer_ownership.py` | 0.5d |
| 客户流失预警模型 + migration | `models/customer_risk.py` | 0.5d |
| 渠道统计 Service | `services/channel_analytics_service.py` | 1d |
| 客户风控 Service | `services/customer_risk_service.py` | 1.5d |
| 客户归属/交接 API | `api/customer_ownership.py` | 1d |
| 渠道统计 API | `api/channel_analytics.py` | 0.5d |
| 流失预警定时任务 | `tasks/customer_risk_scan.py` | 1d |
| 易订Adapter升级（渠道字段） | `packages/api-adapters/yiding/` | 1d |
| 前端: 客户风控面板 | `pages/CustomerRiskPage.tsx` | 2d |
| 前端: 渠道分析仪表板 | `pages/ChannelAnalyticsPage.tsx` | 1.5d |
| **小计** | | **11d** |

**关键交付物**:
- 客户归属追踪 + 离职交接流程
- 流失预警（>30天未消费 = 高风险，AI建议挽回动作）
- 渠道来源统计（各渠道订单量/转化率/佣金成本）
- 退订率分析 + Top退订原因

### Phase 2: 宴会销控引擎（Week 4-6）

**目标**: 从宴荟佳吸收销控方法论

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 档期吉日配置模型 + migration | `models/banquet_date_config.py` | 0.5d |
| 竞对分析模型 + migration | `models/banquet_competitor.py` | 0.5d |
| 销售漏斗模型 + migration | `models/sales_funnel.py` | 0.5d |
| 销控定价 Service（动态去化+变价） | `services/banquet_pricing_service.py` | 2d |
| 销售漏斗 Service | `services/sales_funnel_service.py` | 1.5d |
| 竞对分析 Service | `services/competitor_analysis_service.py` | 1d |
| AI 转化率预测 | `services/conversion_predictor.py` | 2d |
| 销控 API 端点 | `api/banquet_sales.py` | 1d |
| 前端: 销控看板（日历视图） | `pages/BanquetSalesBoard.tsx` | 2.5d |
| 前端: 漏斗分析图表 | `components/SalesFunnelChart.tsx` | 1d |
| 前端: 竞对分析页 | `pages/CompetitorAnalysis.tsx` | 1d |
| **小计** | | **13.5d** |

**关键交付物**:
- 档期日历（吉日S/A/B等级标注，已售/可售/锁定状态）
- 动态定价（吉日涨价系数，淡季折扣，去化率<60%自动降价建议）
- 销售漏斗（LEAD→INTENT→ROOM_LOCK→SIGNED→...，各阶段转化率）
- 竞对输单分析（输给谁、为什么、多少次）
- AI成交概率预测（每条线索标注 85%/60%/30%）

### Phase 3: EO执行引擎（Week 7-9）

**目标**: 从宴小猪吸收EO单和资源调度能力

| 任务 | 文件 | 工作量 |
|------|------|--------|
| EO单模型 + migration | `models/event_order.py` | 1d |
| 演职人员模型 + migration | `models/event_staff.py` | 0.5d |
| 厅位展示模型 + migration | `models/hall_showcase.py` | 0.5d |
| EO单 Service | `services/event_order_service.py` | 2d |
| AI EO单自动生成 | `services/eo_generator_service.py` | 2d |
| 人员调度 Service | `services/event_staff_service.py` | 1d |
| 履约节点追踪 Service | `services/fulfillment_tracker_service.py` | 1.5d |
| EO/人员/厅位 API | `api/event_orders.py` | 1.5d |
| 前端: EO单详情页 | `pages/EventOrderPage.tsx` | 2d |
| 前端: 宴会厅展示页 | `pages/HallShowcasePage.tsx` | 1.5d |
| 前端: 人员调度面板 | `pages/EventStaffPage.tsx` | 1.5d |
| 前端: 履约时间线组件 | `components/FulfillmentTimeline.tsx` | 1d |
| EO单PDF导出 | `services/eo_pdf_export.py` | 1d |
| **小计** | | **16d** |

**关键交付物**:
- EO单自动生成（AI根据宴会类型+客户偏好预填80%内容）
- EO单PDF导出打印（厨房/服务/布场三联单）
- 宴会厅线上展示（照片+VR+参数+价格）
- 演职人员库+调度（司仪/摄影/花艺/灯光）
- 履约时间线（布场→迎宾→开席→撤场，节点打卡）

### Phase 4: AI Agent 整合 + 智能升级（Week 10-12）

**目标**: 用AI串联所有能力，实现屯象独有差异化

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 升级 ReservationAgent | `packages/agents/reservation/src/agent.py` | 3d |
| 智能跟进话术生成 | `services/follow_up_copilot.py` | 2d |
| 智能档期+定价推荐 | `services/smart_pricing_service.py` | 2d |
| 客户意向预测模型 | `services/intent_predictor.py` | 2d |
| 退订原因NLP分析 | `services/cancellation_analyzer.py` | 1d |
| 自动跟进触发器（企微推送） | `services/auto_follow_up.py` | 1.5d |
| AI报表自动推送（日报/周报） | `services/reservation_report_push.py` | 1.5d |
| 前端: AI助手面板 | `components/ReservationAIPanel.tsx` | 2d |
| 前端: 智能定价建议卡片 | `components/PricingSuggestion.tsx` | 1d |
| 集成测试 + E2E | `tests/` | 2d |
| **小计** | | **18d** |

**关键交付物**:
- AI跟进话术（"张总您好，上次咨询的3月18日档期还有最后2个厅..."）
- 智能定价（"3月18日黄道吉日，建议报价¥3888/桌，去化率已达70%"）
- 意向预测（"客户李女士 成交概率85%，建议今天跟进"）
- 退订原因分析（"本月退订Top3: 价格偏高42%、档期冲突28%、选了竞对20%"）
- 自动日报推送到企微（"今日新增线索12条，成交3单¥86,400，明日6场宴会"）

---

## 六、总工期与里程碑

| 阶段 | 周期 | 核心交付 | 来源 |
|------|------|---------|------|
| Phase 1 | Week 1-3 | 渠道中台 + CRM风控 | 易订 + 客必得 |
| Phase 2 | Week 4-6 | 宴会销控引擎 | 宴荟佳 |
| Phase 3 | Week 7-9 | EO执行引擎 | 宴小猪 |
| Phase 4 | Week 10-12 | AI Agent整合 | 屯象独有 |
| **总计** | **12周 / 58.5人天** | | |

---

## 七、与现有代码的关系

### 已有 → 复用

| 现有资产 | 路径 | 复用方式 |
|---------|------|---------|
| ReservationAgent | `packages/agents/reservation/src/agent.py` | Phase 4 升级扩展 |
| YiDing Adapter | `packages/api-adapters/yiding/` | Phase 1 增加渠道字段 |
| Reservation Model | `models/reservation.py` | 新增字段扩展 |
| BanquetLifecycle | `models/banquet_lifecycle.py` | Phase 2 销控漏斗复用7阶段 |
| ReservationService | `services/reservation_service.py` | 各Phase增加方法 |
| Reservation API | `api/reservations.py` | 各Phase增加端点 |
| UnifiedReservation | `yiding/src/types.py` | 统一数据格式基础 |

### 新建文件清单（约28个）

**后端 Models (6)**:
1. `models/reservation_channel.py`
2. `models/customer_ownership.py`
3. `models/customer_risk.py`
4. `models/banquet_date_config.py`
5. `models/event_order.py`
6. `models/hall_showcase.py`

**后端 Services (12)**:
1. `services/channel_analytics_service.py`
2. `services/customer_risk_service.py`
3. `services/banquet_pricing_service.py`
4. `services/sales_funnel_service.py`
5. `services/competitor_analysis_service.py`
6. `services/conversion_predictor.py`
7. `services/event_order_service.py`
8. `services/eo_generator_service.py`
9. `services/event_staff_service.py`
10. `services/fulfillment_tracker_service.py`
11. `services/follow_up_copilot.py`
12. `services/smart_pricing_service.py`

**后端 API (4)**:
1. `api/customer_ownership.py`
2. `api/channel_analytics.py`
3. `api/banquet_sales.py`
4. `api/event_orders.py`

**前端 Pages (6)**:
1. `pages/CustomerRiskPage.tsx`
2. `pages/ChannelAnalyticsPage.tsx`
3. `pages/BanquetSalesBoard.tsx`
4. `pages/EventOrderPage.tsx`
5. `pages/HallShowcasePage.tsx`
6. `pages/EventStaffPage.tsx`

---

## 八、对客户的价值（用于销售话术）

### 对比四家竞品的价值主张

> **"一个Agent顶四套系统，还有AI加持"**

| 客户痛点 | 竞品方案 | 屯象方案 | ¥影响 |
|---------|---------|---------|------|
| 多平台订单散落 | 易订PRO ¥6800/年 | 渠道中台自动聚合 | 减少丢单，月增¥5000+ |
| 销售离职带走客户 | 客必得 ¥4800/年 | CRM风控+自动交接 | 防止客户流失¥10万+/年 |
| 宴会报价凭感觉 | 宴荟佳 ¥8800/年 | AI动态定价+去化建议 | 客单价提升10-15% |
| EO单手写出错 | 宴小猪 ¥3600/年 | AI自动生成EO单 | 减少执行差错，省2h/单 |
| **四套系统总成本** | **¥24,000/年** | **屯象OS包含** | **额外节省¥24,000** |

### 对种子客户的适用性

| 客户 | 预订场景 | 核心需求 |
|------|---------|---------|
| **尝在一起** | 日常订座为主 | 渠道中台 + 退订率管理 |
| **徐记海鲜** | 高端宴请+商务 | CRM风控 + 客户等级匹配 |
| **最黔线** | 家庭聚餐+宴会 | 档期管理 + EO单 |
| **尚宫厨** | 高端宴会为主 | 全流程：销控+EO+履约 |
