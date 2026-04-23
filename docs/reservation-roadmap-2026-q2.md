# 屯象OS 预订业务与 AI 智能体规划 · 2026-Q2 路线图

> 文档日期：2026-04-23
> 对标对象：天财商龙《食尚订产品介绍 2025.11.19》
> 对齐规范：CLAUDE.md §3/§9/§15/§17/§18
> Tier 分级：混合（T1 零容忍 / T2 高标准 / T3 常规）

---

## 0. 文档目的

把天财商龙 SaaS"食尚订"的预订能力矩阵拆成 7 大能力类，对齐屯象OS 现有实现，输出：
1. **差距矩阵** — 可追踪、可验收。
2. **业务流程总体蓝图** — 覆盖公域流量 → 预订聚合 → 宴会全流程 → 客户生命周期闭环。
3. **AI 智能体规划** — 3 个新 Agent + 3 个增强 Agent（对齐 CLAUDE.md §9 双层推理）。
4. **落地路线图** — 3 个 Sprint / 6 周、Tier 验收门槛、徐记海鲜 DEMO 验收口径。

---

## 1. 食尚订核心能力矩阵（7 大类）

| # | 能力域 | 关键特性（PPTX §4-§6 汇总） |
|---|--------|---------|
| A | **多渠道预订聚合** | 美团 / 大众点评 / 高德 / 百度 / 微信公众号+小程序 / 智能预订电话 / App / 平板 / PC 统一收单 |
| B | **智能预订电话 Pro** | 来电弹屏、通话录音、核餐回拨、打印通知单、随客确认 |
| C | **预订台业务** | 预点菜（常规/临时/宴会套餐/专用/做法分组）、订金线上线下收退、前台核销、邀请函 |
| D | **宴会全流程** | 商机 → 洽谈 → 电子合同 → EO 工单分发 → 订金 → 排菜 → 执行 → 分席结账 → 回访 → 二次营销 |
| E | **CRM 联动** | 卡型 / 余额 / 积分 / 累计消费 / 标签 / 菜品喜好 / 忌口 / 评价 双向同步 |
| F | **目标管理** | 年 / 月 / 员工销售目标（金额 / 单数 / 单均 / 桌均 / 人均 / 新客）追踪达成 |
| G | **任务管理** | 10 类任务：商机跟进、宴会流程、餐后回访、生日 / 纪念日、沉睡唤醒、新客、核餐、临时 |
| H | **运营分析** | 客户活跃 / 沉睡 / 流失 / 无订单 四象限；销售经理资源分布；客户资料完整度考核；撤单分析；翻台 / 上座率；宴会来源 / 商机转化率 |
| I | **集团监控** | 集团预订台统一录入 + 集团监控台实时可视 |

---

## 2. 屯象OS 预订侧现状盘点

| 层 | 现状 | 位置 |
|---|------|------|
| **预订 API** | ✅ booking_api / booking_prep / booking_webhook (美团/点评/微信) / customer_booking | `services/tx-trade/src/api/` |
| **宴会 API** | ✅ 6 个路由（routes/advanced/deposit/payment/order/kds） | `services/tx-trade/src/api/` |
| **前端预订** | ✅ web-reception BookingPanel + web-pos ReservationPage + web-admin BanquetBoard/Template/Manage | `apps/` |
| **Agent** | ✅ banquet_growth（宴会）、dormant_recall（沉睡） | `services/tx-agent/src/agents/skills/` |
| **会员 CDP** | ✅ 33 路由（rfm / lifecycle / golden_id / customer_depth / tag） | `services/tx-member/` |
| **Webhook 聚合** | ✅ 美团 / 大众点评 / 微信已对接 HMAC 验签 + WS 推送 | `booking_webhook_routes.py` |
| **事件总线** | ✅ v147/v148（events + 8 物化视图） | `shared/events/` |

---

## 3. 关键差距矩阵（Tier 分级）

| 差距项 | 现状 | Tier | 优先级 | 说明 |
|--------|------|------|--------|------|
| **AI 预订电话 / 来电弹屏 / 通话录音 / 核餐回拨** | ❌ 无（calling_screen 仅叫号屏） | T1 | P0 | 连锁餐饮 60% 预订来自电话，徐记海鲜刚需 |
| **电子邀请函 + 短信带券 + 随客确认** | ❌ 无 | T2 | P0 | 宴会获客闭环缺失 |
| **销售经理年 / 月 / 个人目标 + 进度追踪** | ❌ 无 | T2 | P0 | org 服务只有员工薪资，缺销售目标维度 |
| **统一任务引擎（10 类任务）** | ⚠️ 分散在各 skill，缺统一任务表 | T2 | P0 | 任务闭环是销售管理核心抓手 |
| **高德 / 百度地图预订聚合** | ❌ 无 | T2 | P1 | 公域流量入口缺失 |
| **客户资料完整度评分** | ❌ 无 | T3 | P1 | 8 字段加权：姓名 20% / 手机 20% / 生日 15% / 纪念日 10% / 单位 10% / 喜好 10% / 忌口 10% / 服务要求 5% |
| **客户状态机（活跃 / 沉睡 / 流失 / 无订单）四象限** | ⚠️ dormant 只分"沉睡"，缺统一四象限 + 4 流量 | T2 | P0 | 所有客户分析的基础 |
| **宴会商机漏斗（全部商机 → 商机阶段 → 订单阶段 → 失效）+ 转化率** | ⚠️ banquet_growth 有骨架，无 DB 模型 | T1 | P0 | 宴会是高客单核心收入 |
| **集团监控台（多店预订实时流）** | ⚠️ web-admin 有宴会大盘，缺预订实时流 | T3 | P2 | 中大型连锁必需 |
| **运营报表（预订周期/餐段/桌型/人均/撤单/预点餐/接通质量）** | ⚠️ booking_api 有基础，缺分析面板 | T3 | P1 | 对齐食尚订 12 张运营图 |
| **宴会电子合同 + EO 工单 + 自动 / 人工审核流** | ⚠️ 有 deposit/payment，缺合同 / EO 多级审批 | T1 | P1 | 婚宴强合规 |

---

## 4. 预订业务流程总体蓝图

```
┌─────────────────────────────────────────────────────────────┐
│  公域流量入口                                                 │
│  美团 / 点评 / 高德 / 百度 / 抖音                             │
│  微信小程序 / 公众号  销售经理 App / 平板 / PC                │
│  电话（AI 接线员 Pro）  线下到店  邀请函 H5                   │
└────────────────────┬────────────────────────────────────────┘
                     ↓ 统一 Webhook + 去重
┌─────────────────────────────────────────────────────────────┐
│  L1 预订聚合层  tx-trade/reservation_aggregator              │
│  • Golden Customer 识别（手机号 / 微信 OpenID / 卡号）         │
│  • 撞单检测 → 先到先得排队                                    │
│  • 渠道归因 channel_attribution                              │
└────────────────────┬────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────┐
│  L2 预订类型路由                                              │
│  普通预订 → 桌台锁定 → 预点菜                                  │
│  宴会预订 → 档期锁定 → 商机转单                                │
│  商机/线索 → 销售跟进任务 → 到期不跟进 → 升级                   │
└─────────────────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────┐
│  L3 宴会特殊流  banquet_lifecycle                            │
│  商机 → 洽谈 → 电子合同 → EO 工单分发 → 订金 → 排菜          │
│       （分部门：厨房/前厅/客房/财务/营销）                    │
│  执行 → 分席结账 → 客户回访 → 二次营销                         │
└─────────────────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────┐
│  L4 任务引擎  task_engine（新）                               │
│  • 10 类任务自动生成：核餐 T-2h / 生日 T-7d / 纪念日 /         │
│    沉睡唤醒 / 新客 48h 回访 / 餐后 D+1 回访 /                  │
│    宴会 6 阶段 / 商机 / 核餐 / 临时                            │
│  • 到期升级：销售未跟 → 店长 → 区经                            │
│  • 完成率计入销售 KPI                                          │
└─────────────────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────┐
│  L5 客户状态机  customer_lifecycle_fsm                       │
│  无订单 → 新客 → 活跃 → 沉睡 → 流失 → 挽回 / 召回 → 活跃     │
│  • 状态事件写入 shared/events v147                            │
│  • 物化视图 mv_customer_lifecycle 支撑 4 象限客户分析          │
└─────────────────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────┐
│  L6 Agent 智能层（预订相关 6 个）                              │
│  reservation_concierge（新） / banquet_growth（增强） /       │
│  dormant_recall（增强） / sales_coach（新） /                 │
│  banquet_contract_agent（新） / member_insight（增强）        │
└─────────────────────────────────────────────────────────────┘
```

### 4.1 Golden Customer 识别优先级（撞单处理）
1. 会员卡号 > 2. 手机号 > 3. 微信 OpenID > 4. 身份证尾号后 4 位 + 姓名
5. 命中多条 → 用 `member_golden_id.merge_candidates()` 触发人工确认

### 4.2 多渠道归因公式
```
attribution_weight = {
    "first_touch":  0.3,   # 首次接触
    "last_touch":   0.5,   # 末次预订落地渠道
    "assisted":     0.2    # 期间其他渠道触达
}
```

---

## 5. AI 智能体规划

### 5.1 🆕 Agent ① `reservation_concierge` — AI 预订礼宾员

| 项 | 内容 |
|---|---|
| 优先级 | P0 |
| 运行位置 | 云端 + 边缘（Whisper via coreml-bridge:8100） |
| 对标 | 食尚订"智能预订电话 Pro + 来电弹屏 + 会员透视镜" |
| 硬约束 | 毛利底线（套餐推荐不破底价）+ 客户体验（排队 SLA） |

**Actions**：
| Action | 输入 | 输出 |
|---|---|---|
| `identify_caller` | 来电号码 | Golden Customer 画像卡（VIP 等级 / 历史偏好 / 忌口 / 上次消费 / 沉睡状态） |
| `suggest_slot` | 日期 + 人数 + 偏好房型 | 可用时段 / 桌型 / 套餐推荐 |
| `detect_collision` | 多渠道预订流 | 合并单 + 优先渠道裁决 |
| `send_invitation` | 预订成功事件 | H5 邀请函 + 短信 + 券码 |
| `confirm_arrival` | T-2h 触发 | 自动外呼 / 短信 → 客户确认到店 / 改期 / 取消 |

**边缘推理**：`/predict/caller-identify` + `/transcribe` 在 Mac mini Core ML 本地执行，延迟 < 500ms。

### 5.2 🆕 Agent ② `sales_coach` — 销售经理教练

| 项 | 内容 |
|---|---|
| 优先级 | P1 |
| 运行位置 | 云端 |
| 对标 | 食尚订"目标管理 + 任务管理 + 销售业绩分析" |
| 硬约束 | 无（纯策略层）；决策必须写 AgentDecisionLog |

**Actions**：
| Action | 逻辑 |
|---|---|
| `decompose_target` | 年目标 → 月目标 → 周目标 → 每日触发任务清单 |
| `dispatch_daily_tasks` | 按客户状态机 + 日历自动派发 10 类任务 |
| `diagnose_gap` | 偏离 > 15% → 推送"该打几个电话 / 该维护哪些客户"建议 |
| `coach_action` | 根据业绩诊断生成个性化建议（主攻沉睡 vs 新客 vs 高值） |
| `audit_coverage` | 检测资源分布（沉睡占比 > 40% 告警）+ 未维护 VIP 自动报警 |
| `score_profile_completeness` | 8 字段加权评分 + < 50% 每日生成补录任务 |

### 5.3 🆕 Agent ③ `banquet_contract_agent` — 宴会合同管家

| 项 | 内容 |
|---|---|
| 优先级 | P1 |
| 运行位置 | 云端 |
| 对标 | 食尚订"电子合同 + EO 工单 + 自动 / 人工审核流" |
| 硬约束 | 食安合规（套餐食材批次绑定）+ 毛利底线 |

**Actions**：
| Action | 逻辑 |
|---|---|
| `generate_contract` | 按宴会类型 + 桌数 + 套餐 + 订金比例自动产出 PDF + 电子签 |
| `split_eo` | 一份合同 → 拆至厨房 / 前厅 / 采购 / 营销 / 财务 5 条工单 |
| `route_approval` | 简单宴会自动过；金额 > 10W 或婚宴 → 店长审；> 50W → 区经审 |
| `lock_schedule` | 先到先得（谁先交订金锁档期）+ 候补队列 |
| `progress_reminder` | T-7d / T-3d / T-1d / T-2h 四级推送各部门 |

### 5.4 🔧 增强 Agent ④ `banquet_growth`
新增 action：
- `lead_funnel_analytics`：全部商机 → 商机阶段 → 订单阶段 → 失效，按销售经理维度
- `source_attribution`：预订台 / 老客推荐 / 婚礼纪 / 点评 / 内部 5 渠道转化率

### 5.5 🔧 增强 Agent ⑤ `dormant_recall`
现状 3 级（轻 / 中 / 深）扩展为 **4 象限**：无订单 / 活跃 / 沉睡 / 流失
新增月度 4 流量：新增沉睡 / 新增流失 / 唤醒沉睡 / 挽回流失
消费事件写入 `shared/events` 触发状态机跃迁。

### 5.6 🔧 增强 Agent ⑥ `member_insight`
新增 action：`profile_completeness_score`（姓名 20% / 手机 20% / 生日 15% / 纪念日 10% / 单位 10% / 喜好 10% / 忌口 10% / 服务要求 5%），按销售经理维度输出考核表。

---

## 6. 落地路线图（3 Sprint / 6 周）

### Sprint R1（2 周）— 数据与状态机底座（T1 零容忍）

| 任务 | 交付 | 位置 |
|------|------|------|
| 客户状态机 FSM + Event Sourcing | 4 象限 + 4 流量 + 物化视图 `mv_customer_lifecycle` | `shared/events/` + `shared/db-migrations/` v264 ✅ |
| 任务引擎表 + API | `tasks` 表（10 类型） + `task_dispatch_service` | `services/tx-org/` v265 ✅ |
| 销售目标表 + API | `sales_targets` + `sales_progress` + 员工-目标-完成率 | `services/tx-org/` v266 ✅ |
| 宴会商机漏斗模型 | `banquet_leads` + 转化事件 + `mv_banquet_funnel` | `services/tx-trade/` v267 ✅ |

> 2026-04-23 实装进度：v230-v233 规划值因 v263 已占用顺延为 v264-v267，4 Track 已全部完成 39/39 Tier 1 测试。详见 `docs/reservation-r1-contracts.md`。

**Tier 1 测试门槛**：
- 200 桌并发下客户状态机无冲突
- 商机状态流转幂等
- 订金 Saga 无半状态
- 合同 PDF 生成 P99 < 3s

### Sprint R2（2 周）— Agent 实装（T2 高标准）

| 任务 | 交付 |
|------|------|
| `reservation_concierge` Agent | 5 actions + Whisper 桥接 + 来电弹屏 WS 推送 |
| `sales_coach` Agent | 6 actions + 每日定时任务派发 |
| `banquet_contract_agent` Agent | 5 actions + PDF 合同模板 + 电子签对接 |
| 前端 — 来电弹屏面板 | `web-pos/src/pages/CallerPopupPanel.tsx` + WS 订阅 |
| 前端 — 销售经理 PWA | `web-crew` 增加 `SalesTargetTab` + `TaskListTab` |

### Sprint R3（2 周）— 分析与灰度（T3 常规）

| 任务 | 交付 |
|------|------|
| 12 图运营报表 | `web-admin/src/pages/ReservationAnalyticsPage.tsx`（对齐食尚订图表） |
| 客户资料完整度考核 | 销售经理排名表 + 每日补录任务 |
| 集团监控台 | `web-admin/src/pages/hq/HqReservationMonitor.tsx` 实时流 |
| 高德 / 百度地图预订聚合 | 2 个 webhook + 签名验签 |
| 徐记海鲜 DEMO 灰度 | `demo-xuji-seafood.sql` 跑通 6 大 Agent |

---

## 7. 架构最小侵入原则

1. **不新建服务**：能力落在 tx-trade（预订 / 宴会）+ tx-agent（智能体）+ tx-org（目标 / 任务）+ tx-member（客户状态机）。
2. **事件总线强制接入**（对齐 CLAUDE.md §15）：7 类新事件走 `shared/events/src/emitter.py`
   - `RESERVATION.CREATED / CANCELLED / NO_SHOW / CONFIRMED`
   - `BANQUET.LEAD_CREATED / CONTRACT_SIGNED / EO_DISPATCHED`
   - `TASK.DISPATCHED / COMPLETED / ESCALATED`
   - `SALES_TARGET.SET / PROGRESS_UPDATED`
   - `CUSTOMER.STATE_CHANGED`（四象限跃迁）
3. **Agent 决策留痕**（对齐 CLAUDE.md §9）：3 个新 Agent 每次执行必须写 `AgentDecisionLog`（决策理由 / 置信度 / 三条硬约束校验结果）。
4. **Ontology 不改**（对齐 CLAUDE.md §18 冻结规则）：所有新实体（task / sales_target / banquet_lead / contract）归入 Order/Customer/Employee 的扩展关系表。

---

## 8. 验收门槛（对齐 CLAUDE.md §22）

| 指标 | 门槛 | 适用范围 |
|---|---|---|
| 预订聚合去重率 | > 99.9% | T1 |
| 宴会订金 Saga 无半状态 | 100% | T1 |
| 客户状态机 200 并发无冲突 | 100% | T1 |
| 销售任务派发延迟 | < 5s | T2 |
| 合同生成 P99 | < 3s | T2 |
| 运营 12 图全量加载 | < 2s | T3 |
| 徐记海鲜 DEMO 收银员无培训可用 | 现场用户测试通过 | 全体 |

---

## 9. 遗留与风险

- **电子签第三方选型未定**：e 签宝 / 法大大 / 腾讯电子签，需法务确认
- **AI 外呼牌照**：运营商合作或第三方外呼平台（讯飞 / 阿里云）未选型
- **核餐外呼合规**：需用户授权文案 + 开关
- **高德 / 百度地图商家入驻**：需运营账号准入
- **集团监控台并发规模**：100 店 × 200 桌 = 20K 活跃桌台订阅，WS 扩容方案待定

---

## 10. 下一步

- [ ] 本文档评审（创始人 + 徐记海鲜 PM）
- [ ] Sprint R1 任务分派（按 CLAUDE.md §17 Tier 分级，T1 任务先 TDD）
- [ ] DEMO 环境 `demo-xuji-seafood.sql` 补 200 个客户画像 + 50 条宴会商机样本
- [ ] 独立验证会话（对齐 CLAUDE.md §19）：R1 完成后开新会话从徐记海鲜收银员视角 review
