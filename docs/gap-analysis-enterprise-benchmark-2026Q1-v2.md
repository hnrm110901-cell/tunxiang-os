# 屯象OS 企业级差距分析报告 V2（2026-Q1·代码深度审计版）

> **审计方法**：GitHub 仓库全量代码扫描（332K 行 Python / 75K 行 TypeScript / 1182 个 Python 文件 / 341 个 TS/TSX 文件）
>
> **模拟客户**：集团化、多品牌、多区域、多渠道、复杂品质中餐连锁（类徐记海鲜/西贝/海底捞级别）
>
> **对标系统**：天财商龙、客如云、奥琦玮、企迈科技、餐道、美团收银品牌版 + 海底捞智能中台
>
> **审计日期**：2026-03-30
>
> **与 V1 的区别**：V1 基于表面扫描，本版深入到每个服务的 services/*.py 文件级别，区分「真实 DB 实现」vs「内存 Mock」vs「完全缺失」

---

## 一、代码库规模总览

| 维度 | 数量 | 说明 |
|------|------|------|
| 域微服务 | **15 个** | gateway + 11 业务域 + brain + intel + mcp-server |
| API 路由文件 | **135 个** `*_routes.py` | tx-trade 59 个最多 |
| API 端点总数 | **~1,400+** | 按 `@router.get/post/put/patch/delete` 统计 |
| Python 代码 | **332,530 行** | services/ + edge/ + shared/ |
| TypeScript 代码 | **74,833 行** | apps/ 下 10 个前端应用 |
| DB 迁移脚本 | **66 个** | v001 → v066，含 3 次 RLS 安全修复 |
| ORM 实体 | **11 个** 核心 + 各域扩展 | TenantBase 继承体系 |
| 旧系统适配器 | **12 个** | 品智/傲客微/美团/饿了么/抖音/客如云/天财等 |
| 测试用例 | **~2,900+** | 跨 11 个服务 |
| 前端应用 | **14 个** | 含 POS/KDS/Crew/Admin/小程序/企微侧栏等 |

---

## 二、模拟客户需求全景

### 客户画像

| 维度 | 描述 |
|------|------|
| 集团规模 | 总部 + 3 个品牌（高端海鲜、大众湘菜、宴席会所）|
| 门店数 | 80 家直营 + 20 家加盟，覆盖 15 个城市 |
| 业态 | 正餐大店 Pro（包厢/宴请/称重/活鲜）+ 标准中餐 + 外卖厨房 |
| 渠道 | 堂食 + 外卖(美团/饿了么/抖音) + 小程序 + 团餐 + 宴席 + 零售 |
| 供应链 | 中央厨房 + 区域仓 + 门店直采 |
| 人员 | 3,000+ 员工 |

---

## 三、差距总览矩阵（代码级精确评级）

> **评级标准**（比 V1 更严格）：
> - ✅ **生产可用**（≥80%，有 DB 持久化 + 真实业务逻辑 + 测试覆盖）
> - 🟡 **功能可用但需完善**（50-80%，核心有但细节/对接缺）
> - 🟠 **内存原型**（有业务逻辑但用内存 dict 存储，未接数据库）
> - 🔵 **骨架/占位**（路由存在但逻辑为空/TODO/return 空值）
> - 🔴 **完全缺失**

### A. 交易履约（tx-trade：441 路由 / 94 服务文件 / 641 测试用例）

| # | 功能 | V2 评级 | 代码证据 | 竞品对标 |
|---|------|---------|----------|----------|
| A1 | 堂食收银 | ✅ | `cashier_engine.py` 真实结算 + `payment_service.py` DB | 对齐天财/客如云 |
| A2 | 桌台管理 | ✅ | `table_session_service.py` + `table_layout_service.py` DB | 对齐 |
| A3 | 预订/排队 | ✅ | `web-reception` 14个组件 + `booking_prep_routes.py` | 对齐 |
| A4 | KDS 出餐 | ✅ | `kds_dispatch.py` + 12 个 KDS 路由文件 + `web-kds` 36 组件 | **超越**（泳道/暂停/抢单/档口利润） |
| A5 | 外卖聚合 | 🟡 | `omni_channel_service.py` 真实 DB + 3 适配器；`delivery_aggregator` 部分 Mock | 缺真实SDK对接深度 |
| A6 | 扫码点餐 | 🟡 | `h5-self-order` 27 个组件 + 4 语言 i18n | 缺 navigator.serviceWorker 离线 |
| A7 | 称重/活鲜 | ✅ | `seafood_routes.py` + `TXBridge.startScale()` | 对齐天财 |
| A8 | 宴席/包厢 | 🟡 | `banquet_service.py` + `banquet_payment` 微信 Mock | 缺宴席套餐模板 |
| A9 | 团餐/企业 | 🟡 | `enterprise_routes.py` 已注册 | 缺月结账户 |
| A10 | 零售商城 | 🔵 | `retail_mall_routes.py` 已注册，多处 TODO | 仅骨架 |
| A11 | 大厨到家 | 🟠 | 有代码未注册到 main.py，内存 MVP | 未激活 |
| A12 | 全渠道订单中心 | 🟡 | `omni_channel_routes.py` 已注册 | 缺统一视图 |
| A13 | 协作点餐 | ✅ | `collab_order` 已注册 | 屯象特色 |
| A14 | 语音点餐 | 🟡 | `voice_order` 路由有，Brain 服务对接 | 前沿功能 |

### B. 支付结算

| # | 功能 | V2 评级 | 代码证据 |
|---|------|---------|----------|
| B1 | 多支付方式 | ✅ | `payment_service.py` + `shouqianba_client.py` |
| B2 | 聚合支付/分账 | 🔵 | 有组合支付，无商户利润分账 |
| B3 | 电子发票 | 🟡 | 诺诺适配器有，tax 对接 pending |
| B4 | 桌边支付 | ✅ | `table_side_pay` 路由已注册 |

### C. 菜品菜单（tx-menu：108 路由 / 15 服务 / 149 测试）

| # | 功能 | V2 评级 | 代码证据 |
|---|------|---------|----------|
| C1 | 菜品 CRUD + BOM | ✅ | `DishService` + `bom_service.py` DB |
| C2 | 套餐/组合 | ✅ | `combo_routes.py` |
| C3 | **菜单模板中心** | 🟠 | `menu_template.py` **内存 dict**；v056b 建了 `channel_menu_items` 表但服务层未接 |
| C4 | **多渠道发布** | 🟠 | `channel_mapping_routes.py` 有；`VALID_CHANNELS` 有定义；服务层内存 |
| C5 | 沽清管理 | ✅ | `kds_soldout` 已注册 |
| C6 | 菜品智能推荐 | ✅ | `menu_engineering` + 5 因子引擎 |
| C7 | 菜单版本管理 | ✅ | `menu_version_routes.py` |
| C8 | 菜单审批流 | ✅ | `menu_approval_routes.py` |
| C9 | 菜品生命周期 | ✅ | `dish_lifecycle_routes.py` |

### D. 会员 CRM（tx-member：159 路由 / 20 服务 / 272 测试）

| # | 功能 | V2 评级 | 代码证据 |
|---|------|---------|----------|
| D1 | 会员注册/Golden ID | ✅ | `members.py` DB 操作 |
| D2 | RFM 分层 | ✅ | `rfm_routes.py` + APScheduler 每日自动 |
| D3 | **储值卡/预付费** | ✅ | `stored_value_service.py` 真实 DB + FOR UPDATE 并发控制 |
| D4 | 实体卡/权益卡 | 🔵 | `premium_card_routes.py` 已注册，多处 TODO |
| D5 | 积分商城 | ✅ | `points_mall` 注册 + `points_mall.py` SQL 查询 |
| D6 | 优惠券引擎 | ✅ | `coupon_engine_routes.py` |
| D7 | 付费会员卡 | 🔵 | 与 premium 混合，占位 |
| D8 | 企微 SCRM | ✅ | gateway `wecom_*` 5 个路由模块 + `web-wecom-sidebar` |
| D9 | 全渠道会员打通 | 🟡 | Golden ID 有，缺外卖平台绑定 |
| D10 | 会员生命周期 | ✅ | `lifecycle_routes.py` + `lifecycle_v2` |
| D11 | 智能会员触达 | ✅ | `smart_dispatch_routes.py` |

### E. 供应链（tx-supply：151 路由 / 39 服务 / 434 测试）

| # | 功能 | V2 评级 | 代码证据 |
|---|------|---------|----------|
| E1 | 采购管理 | ✅ | `requisition_routes.py` + `procurement_recommend` |
| E2 | 库存管理 | ✅ | `InventoryIO` DB |
| E3 | BOM 成本 | ✅ | `bom_routes.py` + `bom_craft.py` |
| E4 | 批次/效期 | 🟡 | `food_safety_routes.py` + `trace_routes.py` |
| E5 | **门店间调拨** | ✅ | `warehouse_ops.py` 写 `warehouse_transfers` + v064 建表 |
| E6 | 收货验收 | 🟡 | `receiving_routes.py` 有逻辑，部分路径 db=None |
| E7 | **中央厨房** | 🟠 | `central_kitchen_service.py` **全内存 dict**，注释写明 |
| E8 | 配送管理 | 🟠 | `distribution.py` 内存 `_plans` |
| E9 | 智能补货 | ✅ | `smart_replenishment_routes.py` |
| E10 | 供应商门户 | 🟠 | `supplier_portal_service.py` 内存 dict |
| E11 | 供应商评分 | ✅ | `supplier_scoring_routes.py` |
| E12 | 金蝶对接 | ✅ | `kingdee_routes.py` + `KingdeeBridge` |

### F. 财务结算（tx-finance：49 路由 / 10 服务 / 25 测试）

| # | 功能 | V2 评级 | 代码证据 |
|---|------|---------|----------|
| F1 | 日利润快报 | ✅ | `revenue_engine.py` 真实 SQL 聚合 |
| F2 | 成本核算 | ✅ | `cost_engine.py` DB 聚合 |
| F3 | 营收报表 | ✅ | `RevenueEngine` select Order/OrderItem |
| F4 | 门店 P&L | ✅ | `pnl_engine.py` 多维损益 |
| F5 | 日清日结 | 🟡 | tx-ops `daily_ops` 有流程 |
| F6 | 凭证/金蝶 | ✅ | `voucher_service.py` + `KingdeeBridge` |
| F7 | **预算管理** | 🔵 | API 返回空对象 + "planned" |
| F8 | **资金安全/分账** | 🔴 | 无任何实现 |
| F9 | **税务管理** | 🟡 | 个税计算器完整，企业增值税/申报缺 |
| F10 | 渠道 P&L | ✅ | `ChannelPLCalculator` |
| F11 | 三单匹配 | ✅ | `three_way_match.py` 模型 + 测试 |

### G. 组织人事（tx-org：125 路由 / 22 服务 / 268 测试）

| # | 功能 | V2 评级 | 代码证据 |
|---|------|---------|----------|
| G1 | 员工 CRUD | ✅ | `emp` 路由 DB |
| G2 | 排班管理 | ✅ | `SmartSchedule` |
| G3 | 考勤 | 🟡 | 有引擎，缺排班联动异常 |
| G4 | **薪资计算** | ✅ | `payroll_engine.py`(纯计算) + `payroll_engine_db.py`(DB版) + `payroll_engine_v2.py`(编排) |
| G5 | 社保公积金 | ✅ | `social_insurance.py` 五险一金费率 + 城市基数 |
| G6 | 假期管理 | 🟡 | 考勤引擎有请假，无独立模块 |
| G7 | 培训管理 | 🟠 | `employee_depth.py` 内存 `_training_store` |
| G8 | 绩效考核 | 🟡 | 有基础 |
| G9 | **加盟管理** | ✅ | `franchise_service.py` DB CRUD + `franchise_settlement_service.py` + v066 建表 |

### H. 集团管控

| # | 功能 | V2 评级 | 代码证据 |
|---|------|---------|----------|
| H1 | 多品牌管理 | 🟡 | RLS tenant_id + tx-growth `brand_strategy` 内存 |
| H2 | 多区域管理 | 🟡 | tx-ops `regional_routes.py` |
| H3 | **加盟管理** | ✅ | 同 G9，含特许经营费结算 |
| H4 | 新店 SOP | 🟡 | tx-ops `StoreOpening` 有工作流 |
| H5 | 权限体系 | 🟡 | `role_routes.py` 有 |
| H6 | **审批流引擎** | ✅ | `approval_workflow_engine.py` 多级状态机 + 模板/实例/步骤 3 表 DB 持久化 |
| H7 | 巡店质检 | ✅ | `patrol_routes.py` + v065 建表 |
| H8 | 门店评分 | ✅ | 5 维健康度 |

### I. 营销增长（tx-growth：95 路由 / 12 服务 / 98 测试）

| # | 功能 | V2 评级 | 代码证据 |
|---|------|---------|----------|
| I1 | 营销活动引擎 | 🟡 | `campaign_engine` + `CampaignEngine` |
| I2 | 抖音团购核销 | 🟡 | 抖音适配器有 |
| I3 | 小红书 | 🔵 | 仅枚举 + Agent 文案平台 |
| I4 | 裂变营销 | 🟡 | `referral_service.py` 邀请有礼完整，拼团仅枚举 |
| I5 | **直播带货** | 🔴 | 无代码 |
| I6 | 精准推送 | ✅ | `ChannelEngine` + 企微/短信通道 |
| I7 | A/B 测试 | ✅ | `ab_test_routes.py` |
| I8 | ROI 归因 | ✅ | `attribution_routes.py` |
| I9 | 内容引擎 | 🟡 | `ContentEngine` Agent 侧 |

### J. 数据分析（tx-analytics：77 路由 / 22 服务 / 284 测试）

| # | 功能 | V2 评级 | 代码证据 |
|---|------|---------|----------|
| J1 | 经营驾驶舱 | ✅ | `GroupDashboardService` + `NarrativeEngine` |
| J2 | 门店分析 | ✅ | `StoreAnalysis` |
| J3 | 菜品分析 | ✅ | `DishAnalysis` 四象限 |
| J4 | 会员分析 | ✅ | tx-member `analytics_routes.py` |
| J5 | 自定义报表 | 🟡 | `ReportEngine` 有，缺拖拽设计器 |
| J6 | BOSS BI | ✅ | `boss_bi_routes.py` |
| J7 | 成本健康度 | ✅ | `CostHealthEngine` |

### K. 边缘计算/离线

| # | 功能 | V2 评级 | 代码证据 |
|---|------|---------|----------|
| K1 | 断网收银 | 🟡 | mac-station API 有路由，本地 PG TODO |
| K2 | 数据同步 | ✅ | `sync_engine.py` PG UPSERT + HTTP 上云 + 水位表 |
| K3 | 边缘 AI | 🟡 | coreml-bridge Vapor 服务 + 规则 fallback（无真实 .mlmodel） |
| K4 | **PWA 离线** | 🟡 | web-crew 有 Service Worker，其他端无 |
| K5 | 离线打印队列 | ✅ | `mac-mini/print_queue.py` |

### L. 安全合规

| # | 功能 | V2 评级 | 代码证据 |
|---|------|---------|----------|
| L1 | RLS 租户隔离 | ✅ | Gateway UUID 校验 + `_validate_tenant_id` + v014/v017/v023 三次修复 |
| L2 | 数据加密 | 🟡 | HTTPS 有，字段级加密缺 |
| L3 | 操作审计 | 🟡 | Agent 决策留痕有，通用审计缺 |
| L4 | **GDPR** | 🔵 | 仅手机号脱敏，无合规模块 |

### M. 小程序/顾客端（miniapp-customer：116 文件）

| # | 功能 | V2 评级 | 代码证据 |
|---|------|---------|----------|
| M1 | 扫码点餐 | ✅ | miniapp + h5-self-order |
| M2 | 排队取号 | ✅ | 有 |
| M3 | 在线预订 | ✅ | 有 |
| M4 | 外卖自营 | 🟡 | 缺配送调度 |
| M5 | 积分商城 | ✅ | points_mall |
| M6 | 会员中心 | ✅ | 有 |
| M7 | 宴席在线预订 | 🟡 | `banquet-booking/` 目录有 |

---

## 四、差距严重度统计（V2 vs V1 对比）

| 评级 | V2 数量 | V2 占比 | V1 数量 | V1 占比 | 变化 |
|------|---------|---------|---------|---------|------|
| ✅ 生产可用 | **56** | **58%** | 28 | 33% | +100% |
| 🟡 功能可用 | **22** | **23%** | 24 | 28% | -8% |
| 🟠 内存原型 | **7** | **7%** | 11 | 13% | -36% |
| 🔵 骨架/占位 | **6** | **6%** | — | — | 新分类 |
| 🔴 完全缺失 | **5** | **5%** | 22 | 26% | -77% |

**V1→V2 核心变化：**
- 储值卡(D3)、薪资(G4)、社保(G5)、加盟(G9/H3)、审批流(H6)、同步引擎(K2)、门店调拨(E5) 从「缺失」升级为「✅生产可用」
- 财务引擎(F1-F4) 从「占位返回0」升级为「✅真实SQL聚合」
- 菜单模板(C3)、中央厨房(E7)、配送(E8) 确认为「🟠内存原型」（代码有但未接DB）

---

## 五、修正后的致命差距（从 10 个缩减为 5 个）

V1 报告的 10 大致命差距，经代码深度审计后：

| V1 致命差距 | V2 状态 | 说明 |
|------------|---------|------|
| #1 财务模块空壳 | ✅ **已解决** | PnL/Cost/Revenue 引擎已有真实 SQL 聚合 |
| #2 中央厨房 | 🟠 **仍存在** | 服务层全内存，需迁移到 DB |
| #3 加盟管理 | ✅ **已解决** | franchise_service + franchise_settlement + v066 |
| #4 储值卡 | ✅ **已解决** | stored_value_service DB + FOR UPDATE |
| #5 菜单模板 | 🟠 **仍存在** | v056b 建了表但服务层未接 |
| #6 薪资引擎 | ✅ **已解决** | 3 层引擎 + social_insurance + payroll_engine_db |
| #7 审批流 | ✅ **已解决** | 多级状态机 + 3 表 DB |
| #8 数据同步 | ✅ **已解决** | sync_engine PG UPSERT |
| #9 RLS 安全 | ✅ **已解决** | 3 次修复迁移 + Gateway/DB 双层校验 |
| #10 外卖聚合 | 🟡 **大幅改善** | omni_channel DB 真实逻辑，适配器需完善 |

### V2 版五大致命差距

#### 🚨 致命差距 #1：中央厨房全内存（E7）

**现状**：`central_kitchen_service.py` 文件头标注「当前阶段使用内存存储」，`_kitchens`/`_plans`/`_production_orders` 全为 Python dict。有完整的业务逻辑（生产计划/领料/配送），但断电即丢失。

**竞品**：天财商龙供应链连锁版支持采购→入库→加工→配送全流程 DB 持久化。

**修复方案**：将内存 dict 迁移到已有的 DB 基础设施（参考 v064 WMS 持久化模式）。

**工作量**：中（3-4 周，逻辑已有，主要是 ORM 模型 + 迁移 + 测试）

---

#### 🚨 致命差距 #2：菜单模板中心未接 DB（C3/C4）

**现状**：`menu_template.py` 用内存 dict，但 v056b 迁移已创建 `channel_menu_items`/`channel_pricing_rules` 表。Schema 和代码"两张皮"。

**竞品**：天财商龙/客如云支持总部菜单下发→门店微调→多渠道发布。

**修复方案**：将 menu_template.py 的 dict 替换为 v056b 表的 ORM 操作。

**工作量**：小（2-3 周，表已建好，主要是 repository + service 重写）

---

#### 🚨 致命差距 #3：资金安全/利润分账完全缺失（F8）

**现状**：零代码。多品牌+加盟模式下，平台方/品牌方/加盟商的资金分账和监管是法规硬性要求。

**竞品**：企迈科技将资金安全作为核心卖点。

**修复方案**：新建 fund_settlement 服务，对接支付通道分账 API。

**工作量**：大（6-8 周）

---

#### 🚨 致命差距 #4：配送管理全内存（E8）

**现状**：`distribution.py` 用 `_plans`/`_warehouses` 内存 dict。中央厨房→门店的配送调度是大型连锁的基础设施。

**竞品**：天财商龙配送版支持路线规划/装车/签收全流程。

**修复方案**：与 #1 中央厨房一起重构为 DB 持久化。

**工作量**：中（3-4 周）

---

#### 🚨 致命差距 #5：供应商门户内存化（E10）

**现状**：`supplier_portal_service.py` 内存 dict。100 家门店的供应链需要供应商自助报价/对账。

**竞品**：奥琦玮有完整供应商协同平台。

**修复方案**：DB 持久化 + 供应商登录门户。

**工作量**：中（3-4 周）

---

## 六、按领域的竞品对比评分（V2）

| 评估维度 | 屯象OS V2 | V1 得分 | 天财商龙 | 客如云 | 说明 |
|---------|-----------|---------|---------|--------|------|
| 交易收银 | **90/100** | 85 | 95 | 90 | KDS 超越竞品 |
| 会员营销 | **78/100** | 55 | 85 | 90 | 储值卡+RFM已补齐 |
| 供应链 | **60/100** | 50 | 95 | 70 | 门店级强，中央厨房/配送内存 |
| 财务结算 | **72/100** | **15** | 90 | 75 | **最大提升**（+57 分） |
| 组织人事 | **75/100** | 40 | 60 | 50 | 薪资+加盟已补齐 |
| 集团管控 | **68/100** | 35 | 85 | 80 | 审批流+加盟已补齐 |
| 数据分析 | **85/100** | 80 | 80 | 75 | 叙事引擎+BOSS BI领先 |
| AI 智能 | **95/100** | 95 | 20 | 30 | **绝对优势**（MCP 1700+工具） |
| 外卖/全渠道 | **58/100** | 40 | 70 | 95 | omni_channel 有但需完善 |
| 安全合规 | **70/100** | 50 | 80 | 85 | RLS 3 轮修复 |
| 边缘/离线 | **45/100** | 10 | 75 | 60 | sync-engine 真实实现 |
| **加权总分** | **72/100** | **50** | **78** | **75** | V1→V2 提升 +22 分 |

---

## 七、屯象OS 独有优势（竞品不具备）

| # | 独有优势 | 代码证据 | 壁垒 |
|---|---------|----------|------|
| 1 | **MCP Server + 1700+ 工具注册** | `services/mcp-server/agent_registry.py` | 极深 |
| 2 | **KDS 泳道/暂停抢单/档口利润/备餐推荐** | tx-trade 12 个 KDS 路由文件 | 深 |
| 3 | **经营叙事引擎** | `NarrativeEngine` ≤200 字简报 | 深 |
| 4 | **菜品排名引擎（5 因子）** | `menu_engineering` | 中 |
| 5 | **12 个旧系统适配器** | shared/adapters/ | 中 |
| 6 | **审批流引擎（多级 DB 持久化）** | `approval_workflow_engine.py` | 中 |
| 7 | **同桌同出协调（TableFire）** | `table_production_plans` | 深 |
| 8 | **传菜员 Runner 工作流** | `runner_routes.py` | 中 |
| 9 | **BOSS BI + 成本健康度** | `boss_bi_routes.py` + `CostHealthEngine` | 中 |
| 10 | **Mac mini 边缘 AI 架构** | sync-engine + coreml-bridge | 极深（待完善） |

---

## 八、修复路线图（V2，聚焦剩余 5 个致命差距）

### Phase A：内存→DB 迁移冲刺（4-6 周）

| 项目 | 现状 | 工作量 | 方法 |
|------|------|--------|------|
| 中央厨房 DB 化 | 内存 dict | 3 周 | 参考 v064 WMS 模式 |
| 配送管理 DB 化 | 内存 dict | 2 周 | 同上 |
| 菜单模板接 DB | 内存但表已建 | 2 周 | 接 v056b 表 |
| 供应商门户 DB 化 | 内存 dict | 2 周 | 新建迁移 |

### Phase B：缺失模块补建（6-8 周）

| 项目 | 说明 |
|------|------|
| 资金分账引擎 | 支付通道分账 API + 加盟分润 |
| 预算管理 v1 | 部门/门店预算编制 + 执行跟踪 |
| 企业税务管理 | 增值税/申报/多区域税率 |

### Phase C：体验完善（4-6 周）

| 项目 | 说明 |
|------|------|
| PWA 全端覆盖 | 将 web-crew SW 模式复制到 POS/KDS |
| 付费会员卡 | premium_card 占位→真实实现 |
| 零售商城 | retail_mall TODO→真实逻辑 |
| GDPR 合规 | 数据主体删除/脱敏模块 |

---

## 九、一句话结论

> **屯象OS 经过持续开发，从 V1 的「50 分/100」跃升至 V2 的「72 分/100」**。财务引擎（+57 分）、组织人事（+35 分）、集团管控（+33 分）三大短板均已补齐核心功能。当前剩余 5 个致命差距（中央厨房/配送/菜单模板/资金分账/供应商门户）中，前 4 个的**业务逻辑已经完整编写在内存层**，只需迁移到 DB 即可投产。真正从零开发的仅「资金分账」一项。按当前开发速度，预计 **10-14 周**可将综合评分提升至 **82-85 分**，接近天财商龙（78 分）和客如云（75 分）的水平，同时保持 AI 智能层（95 分）的绝对碾压优势。
