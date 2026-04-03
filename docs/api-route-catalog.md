# 屯象OS API路由清单

> 生成日期：2026-04-02
> 扫描范围：6个后端微服务 main.py + api/ 目录，4个前端 App.tsx

---

## tx-trade (:8001) — 交易履约微服务

共 **77 个 API 模块文件**（api/ + routers/），覆盖收银/桌台/KDS/预订/宴席/外卖/零售全链路。

| 路由前缀 / 文件 | 功能说明 |
|----------------|---------|
| `/api/v1/trade` → `orders.py` | 订单 CRUD + 支付 + 小票打印 |
| `/api/v1` → `cashier_api.py` | 收银核心（开台/点单/结算/折扣/权限校验）|
| `/api/v1/kds` → `kds_routes.py` | KDS 出餐调度（分单/队列/超时预警）|
| `handover_routes.py` | 交接班管理 |
| `table_routes.py` | 桌台管理（桌型/状态/布局）|
| `enterprise_routes.py` | 企业挂账 |
| `order_ext_routes.py` | 订单扩展（备注/特殊要求）|
| `coupon_routes.py` | 优惠券核销 |
| `platform_coupon_routes.py` | 平台券（美团/抖音）|
| `service_charge_routes.py` | 服务费管理 |
| `invoice_routes.py` | 电子发票（税控）|
| `payment_direct_routes.py` | 直接支付（微信/支付宝）|
| `webhook_routes.py` | 支付回调 Webhook |
| `printer_routes.py` | `/api/v1/printer` 打印执行 |
| `approval_routes.py` | 审批流（订单级）|
| `booking_api.py` | 预订管理 |
| `booking_webhook_routes.py` | 预订平台 Webhook + Mock 生成 |
| `kds_shortage_routes.py` | KDS 缺料上报 |
| `scan_order_routes.py` | 扫码点餐 |
| `order_ops_routes.py` | 订单操作（加菜/催菜/退单）|
| `shift_routes.py` | 班次管理 |
| `dish_practice_routes.py` | 菜品做法（加辣/去葱等）|
| `table_ops_routes.py` | 桌台操作（并台/换台/分单）|
| `banquet_routes.py` | 宴席管理 |
| `mobile_ops_routes.py` | 移动端运营 |
| `takeaway_routes.py` | 外卖管理 |
| `retail_mall_routes.py` | 零售商城 |
| `/api/v1/runner` → `runner_routes.py` | 传菜员工作站 |
| `/api/v1/expo` → `expo_routes.py` | 展览/快餐叫号 |
| `/api/v1/cook-time` → `cook_time_routes.py` | 出餐时间基线管理 |
| `/api/v1/shifts` → `shift_report_routes.py` | 班次报表 |
| `/api/v1/dispatch-rules` → `dispatch_rule_routes.py` | KDS 分单规则 |
| `/api/v1/dispatch-codes` → `dispatch_code_routes.py` | 菜品档口码 |
| `/api/v1/kds-call` → `kds_config_routes.py` | KDS 配置（叫号/档口）|
| `/api/v1/kitchen` → `kitchen_monitor_routes.py` | 厨房监控大屏 |
| `table_monitor_routes.py` | 桌台实时监控 |
| `/api/v1/booking-prep` → `booking_prep_routes.py` | 预订备餐视图 |
| `delivery_ops_routes.py` | 外卖接单操作 |
| `/api/v1` → `omni_channel_routes.py` | 全渠道（堂食/外卖/零售统一）|
| `banquet_payment_routes.py` | 宴席定金支付 |
| `collab_order_routes.py` | 多人协同扫码点餐 |
| `table_layout_routes.py` | 桌台布局实时编辑 |
| `kds_pause_grab_routes.py` | KDS 暂停/抢单 |
| `kds_soldout_routes.py` | KDS 沽清管理 |
| `kds_chef_stats_routes.py` | 厨师绩效计件统计 |
| `kds_swimlane_routes.py` | KDS 泳道模式（工序流水线）|
| `kds_prep_routes.py` | 预制量智能推荐 |
| `kds_station_profit_routes.py` | 档口毛利核算 |
| `discount_audit_routes.py` | 折扣审计日志 |
| `discount_engine_routes.py` | 折扣引擎（规则计算/叠加）|
| `service_bell_routes.py` | 服务铃呼叫 |
| `course_firing_routes.py` | 宴席同步出品（打节/控菜）|
| `seat_order_routes.py` | 座位点餐 |
| `manager_app_routes.py` | 店长移动端 |
| `crew_stats_routes.py` | 服务员绩效统计 |
| `allergen_routes.py` | 菜品过敏原管理 |
| `inventory_menu_routes.py` | 菜单-库存联动 |
| `supply_chain_mobile_routes.py` | 供应链移动端（收货/盘点）|
| `prediction_routes.py` | 出餐/客流预测 |
| `proactive_service_routes.py` | 主动服务推荐 |
| `crew_handover_router.py` | 服务员交接班 |
| `payment_router.py` (routers/) | 桌边支付 |
| `crew_schedule_router.py` (routers/) | 服务员排班 |
| `menu_engineering_router.py` (routers/) | 菜单工程分析（四象限）|
| `voice_order_router.py` (routers/) | 语音点餐 |
| `vision_router.py` (routers/) | 视觉识别（活鲜称重）|
| `patrol_router.py` (routers/) | 巡台自动签到 |
| `digital_menu_board_router.py` | 数字菜单屏 |
| `shift_summary_router.py` (routers/) | 班次汇总报表 |
| `sync_ingest_router.py` (routers/) | 离线同步数据摄入 |
| `delivery_panel_router.py` (routers/) | 外卖接单面板（完整实现）|
| `delivery_router.py` (routers/) | 外卖旧骨架（/webhook/ + /platforms）|
| `self_pay_router.py` (routers/) | 顾客自助买单 |
| `production_dept_routes.py` | 出品部门路由配置 |
| `template_editor_routes.py` | 打印模板编辑器 |
| `group_buy_routes.py` | 拼团功能 |
| `xhs_routes.py` | 小红书 POI 对接 |
| `split_payment_routes.py` | AA 分摊付款 |
| `chef_at_home_routes.py` | 大厨到家（可 feature flag 关闭）|
| `scan_pay_routes.py` | 扫码支付 |
| `stored_value_routes.py` | 储值卡消费 |
| `/api/v1/printers` → `printer_config_routes.py` | 打印机配置管理 |
| `/api/v1/waitlist` → `waitlist_routes.py` | 排队等位 |
| `delivery_orders_routes.py` | 外卖订单状态流转/取消/Mock |
| `kds_banquet_routes.py` | 徐记宴席同步出品（KDS 专用）|
| `print_template_routes.py` | 打印模板（活鲜/宴席/挂账）|
| `dish_dept_mapping_routes.py` | 菜品档口映射管理 |
| `GET /health` | 服务健康检查 |

---

## tx-menu (:8002) — 菜品菜单微服务

共 **20 个 API 模块文件**。

| 路由前缀 / 文件 | 功能说明 |
|----------------|---------|
| `/api/v1/menu` → `dishes.py` | 菜品 CRUD（创建/查询/分类）|
| `publish.py` | 菜单发布（门店生效）|
| `pricing_routes.py` | 多渠道定价管理 |
| `menu_routes.py` | 菜单中心（模板/版本/分组）|
| `practice_routes.py` | 菜品做法配置 |
| `combo_routes.py` | 套餐组合管理 |
| `menu_version_routes.py` | 菜单版本管理 |
| `/api/v1/dish-lifecycle` → `dish_lifecycle_routes.py` | 菜品生命周期（研发/上线/下线）|
| `/api/v1/menu/lifecycle/*` 等 → `dish_lifecycle_routes.lifecycle_router` | 生命周期状态机操作 |
| `channel_mapping_routes.py` | 菜品渠道映射（堂食/外卖/小程序）|
| `menu_approval_routes.py` | 菜单审批（集团下发审批）|
| `live_edit_routes.py` | 实时菜单编辑（门店微调）|
| `brand_publish_routes.py` | 品牌→门店三级发布体系 |
| `live_seafood_routes.py` | 徐记：活鲜海鲜管理（称重/条头/鱼缸）|
| `live_seafood_query_routes.py` | 徐记：活鲜查询（前端点单专用）|
| `banquet_menu_routes.py` | 徐记：宴席菜单（多档次/分节/场次）|
| `GET /health` | 服务健康检查 |

---

## tx-ops (:8005) — 日清日结操作层微服务

共 **15 个 API 模块文件**，实现 E1-E8 日清日结完整流程。

| 路由前缀 / 文件 | 功能说明 |
|----------------|---------|
| `/api/v1/ops` → `daily_ops.py` | 日清日结主流程（门店每日状态）|
| `store_clone.py` | 快速开店克隆 |
| `ops_routes.py` | 运营总览 |
| `review_routes.py` | 门店复盘 |
| `regional_routes.py` | 区域管理（多店巡检）|
| `peak_routes.py` | 高峰期监控与预警 |
| `dispatch_routes.py` | 任务分派 |
| `notification_routes.py` | 运营通知推送 |
| `shift_routes.py` | E1: 排班/换班管理 |
| `daily_summary_routes.py` | E2: 日总结汇总 |
| `issues_routes.py` | E3: 问题记录与跟进 |
| `inspection_routes.py` | E4: 巡检 SOP |
| `performance_routes.py` | E5: 绩效考核 |
| `daily_settlement_routes.py` | E6-E8: 日结/结算 |
| `approval_workflow_routes.py` | 审批工作流引擎 |
| `GET /health` | 服务健康检查 |

---

## tx-finance (:8007) — 财务结算微服务

共 **17 个 API 模块文件**，覆盖营收/成本/P&L/发票/预算/分润。

| 路由前缀 / 文件 | 功能说明 |
|----------------|---------|
| `/api/v1/finance` → `finance.py` | 财务结算核心（营收/P&L/凭证生成）|
| `analytics_routes.py` | 财务分析报表 |
| `/api/v1/costs` → `cost_routes.py` | 成本管理 V1 |
| `/api/v1/pl` → `pl_routes.py` | 损益表 V1 |
| `/api/v1/invoices` → `e_invoice_routes.py` | 电子发票（含诺诺对接）|
| `settlement_routes.py` | 渠道结算对账 |
| `erp_routes.py` | ERP 对接（金蝶/用友）|
| `/api/v1/reconciliation_*` → `reconciliation_routes.py` | 对账差异核查 |
| `revenue_aggregation_routes.py` | 营收汇总聚合 |
| `/api/v1/finance/costs` → `finance_cost_routes.py` | 财务成本分析 |
| `/api/v1/finance/pl` → `finance_pl_routes.py` | 财务损益分析 |
| `split_routes.py` | 分润规则与分账流水（/api/v1/finance/splits）|
| `/api/v1/finance/pnl` → `pnl_routes.py` | P&L 计算引擎（v117）|
| `/api/v1/finance/costs` → `cost_routes_v2.py` | 成本计算引擎 V2（v117）|
| `/api/v1/finance/revenue` → `revenue_routes.py` | 营收计算引擎（v117）|
| `/api/v1/finance/seafood-loss` → `seafood_loss_routes.py` | 活鲜损耗计算（v117）|
| `GET /health` | 服务健康检查 |

---

## tx-org (:8012) — 组织人事微服务

共 **35 个 API 模块文件**，覆盖员工/排班/薪资/考勤/绩效/加盟管理。

| 路由前缀 / 文件 | 功能说明 |
|----------------|---------|
| `/api/v1/org` → `employees.py` | 员工管理 CRUD |
| `schedule.py` | 排班管理 |
| `role_api.py` | 角色管理 |
| `transfers.py` | 员工调动 |
| `efficiency.py` | 人效分析 |
| `salary_items.py` | 薪资科目配置 |
| `payslip.py` | 工资条查询 |
| `employee_depth_routes.py` | 员工深度档案（技能/培训）|
| `admin_routes.py` | 管理员操作 |
| `/api/v1/org/payroll` → `payroll_routes.py` | 薪资引擎 V4（v121 表）|
| `/api/v1/payroll` → `payroll_router.py` | 薪资引擎 V2 |
| `/api/v1/approval-engine` → `approval_engine_routes.py` | 审批引擎 |
| `franchise_routes.py` | 加盟商管理 V1 |
| `franchise_router.py` | 加盟商管理 V2 |
| `/api/v1/approvals` → `approval_router.py` | 审批处理 |
| `/api/v1/patrol` → `patrol_routes.py` | 巡店质检 |
| `franchise_settlement_routes.py` | 加盟结算 |
| `permission_routes.py` | 权限检查 API（v075）|
| `permission_routes.role_limits_router` | 角色限制配置 CRUD（v075）|
| `attendance_routes.py` | 考勤打卡（v077）|
| `leave_routes.py` | 请假管理（v077）|
| `store_clone_routes.py` | 快速开店克隆（v078）|
| `device_routes.py` | 品牌级设备管理（v093）|
| `ota_routes.py` | OTA 版本管理（v094）|
| `compliance_routes.py` | 合规管理（等保三级）|
| `im_sync_routes.py` | IM 同步（企微/钉钉）|
| `performance_routes.py` | 绩效考核 |
| `payroll_engine_routes.py` | 薪资计算引擎 V3（v119 表）|
| `franchise_mgmt_routes.py` | 加盟管理完整版（v125 表）|
| `GET /health` | 服务健康检查 |

---

## tx-supply (:8006) — 供应链微服务

共 **22 个 API 模块文件**，覆盖库存/BOM/采购/食安/活鲜/溯源/中央厨房。

| 路由前缀 / 文件 | 功能说明 |
|----------------|---------|
| `/api/v1/supply` → `inventory.py` | 库存管理（入库/出库/盘点/效期/安全库存）|
| `bom_routes.py` | BOM 配方管理（标准用量/理论成本）|
| `deduction_routes.py` | 库存扣减（按 BOM 自动扣）|
| `receiving_routes.py` | 采购验收 V1 |
| `kingdee_routes.py` | 金蝶 ERP 库存同步 |
| `requisition_routes.py` | 采购申请/审批 |
| `dept_issue_routes.py` | 部门领料 |
| `warehouse_ops_routes.py` | 仓库操作（调拨/报损）|
| `period_close_routes.py` | 期末结存 |
| `craft_routes.py` | 工艺配方 |
| `distribution_routes.py` | 配送管理 |
| `food_safety_routes.py` | 食品安全（效期预警/追溯）|
| `seafood_routes.py` | 活鲜管理（鱼缸/称重/条头）|
| `trace_routes.py` | 食材溯源 |
| `central_kitchen_routes.py` | 中央厨房（生产计划/加工/配送）|
| `/api/v1/procurement` → `procurement_recommend_routes.py` | 智能采购推荐 |
| `/api/v1/smart-replenishment` → `smart_replenishment_routes.py` | 智能补货 |
| `delivery_route_routes.py` | 配送路线优化 |
| `supplier_scoring_routes.py` | 供应商评分 |
| `receiving_v2_routes.py` | 采购验收 V2 |
| `transfer_routes.py` | 库存调拨 |
| `ck_production_routes.py` | 中央厨房生产执行 |
| `ck_recipe_routes.py` | 中央厨房配方管理 |
| `GET /health` | 服务健康检查 |

---

## web-admin 前端路由（总部管理后台）

| 路径 | 组件 | 功能 |
|------|------|------|
| `/dashboard` | `DashboardPage` | 总部驾驶舱 |
| `/operations-dashboard` | `OperationsDashboardPage` | 运营综合仪表盘 |
| `/store-health` | `StoreHealthPage` | 门店健康度监控 |
| `/agents` | `AgentMonitorPage` | Agent 监控中心 |
| `/trade` | `TradePage` | 交易管理 |
| `/catalog` | `CatalogPage` | 商品目录 |
| `/supply` | `SupplyPage` | 供应链管理 |
| `/operations` | `OperationsPage` | 运营管理 |
| `/crm` | `CrmPage` | 会员 CRM |
| `/org` | `OrgPage` | 组织管理 |
| `/system` | `SystemPage` | 系统设置 |
| `/daily-plan` | `DailyPlanPage` | 每日计划 |
| `/hq/growth/dashboard` | `GrowthDashboardPage` | 增长驾驶舱 |
| `/hq/growth/segments` | `SegmentCenterPage` | 会员分群中心 |
| `/hq/growth/journeys` | `JourneyListPage` | 旅程列表 |
| `/hq/growth/journeys/:id` | `JourneyDetailPage` | 旅程详情 |
| `/hq/growth/journeys/:id/canvas` | `JourneyCanvasPage` | 旅程画布 |
| `/hq/growth/roi` | `ROIOverviewPage` | ROI 总览 |
| `/hq/growth/content` | `ContentCenterPage` | 内容中心 |
| `/hq/growth/offers` | `OfferCenterPage` | 优惠中心 |
| `/hq/growth/channels` | `ChannelCenterPage` | 渠道中心 |
| `/hq/growth/referral` | `ReferralCenterPage` | 裂变推广 |
| `/hq/growth/execution` | `StoreExecutionPage` | 门店执行 |
| `/hq/growth/group-buy` | `GroupBuyPage` | 拼团管理 |
| `/hq/growth/stamp-card` | `StampCardPage` | 集点卡管理 |
| `/hq/growth/xhs` | `XHSIntegrationPage` | 小红书对接 |
| `/hq/growth/retail-mall` | `RetailMallPage` | 零售商城 |
| `/hq/growth/journey-monitor` | `JourneyMonitorPage` | 旅程监控 |
| `/hq/growth/member-cards` | `MemberCardPage` | 会员卡管理 |
| `/hq/market-intel/dashboard` | `IntelDashboardPage` | 市场情报驾驶舱 |
| `/hq/market-intel/new-products` | `NewProductListPage` | 新品机会列表 |
| `/hq/market-intel/new-products/:id` | `NewProductOpportunityPage` | 新品机会详情 |
| `/hq/market-intel/competitors` | `CompetitorCenterPage` | 竞品中心 |
| `/hq/market-intel/competitors/:id` | `CompetitorDetailPage` | 竞品详情 |
| `/hq/market-intel/reviews` | `ReviewTopicPage` | 口碑话题分析 |
| `/hq/market-intel/reports` | `TrendReportPage` | 趋势报告 |
| `/hq/market-intel/trend-radar` | `TrendRadarPage` | 趋势雷达 |
| `/hq/market-intel/review-intel` | `ReviewIntelPage` | 评价智能分析 |
| `/hq/ops/dashboard` | `OpsDashboardPage` | 运营总部驾驶舱 |
| `/hq/ops/store-analysis` | `StoreAnalysisPage` | 门店分析 |
| `/hq/ops/dish-analysis` | `DishAnalysisPage` | 菜品分析 |
| `/hq/ops/approvals` | `ApprovalCenterPage` | 审批中心（旧）|
| `/hq/ops/review` | `ReviewCenterPage` | 复盘中心 |
| `/hq/ops/alerts` | `AlertCenterPage` | 预警中心 |
| `/hq/ops/settings` | `SettingsPage` | 运营设置 |
| `/hq/ops/peak-monitor` | `PeakMonitorPage` | 高峰期监控 |
| `/hq/ops/regional` | `RegionalPage` | 区域管理 |
| `/hq/ops/cruise` | `CruiseMonitorPage` | 巡店监控 |
| `/hq/ops/operation-plans` | `OperationPlanPage` | 运营计划 |
| `/hq/ops/event-bus-health` | `EventBusHealthPage` | 事件总线健康 |
| `/hq/ops/store-clone` | `StoreClonePage` | 快速开店克隆 |
| `/hq/ops/daily-review` | `DailyReviewPage` | 日复盘 |
| `/hq/ops/smart-specials` | `SmartSpecialsPage` | 智能特供 |
| `/hq/analytics/finance` | `FinanceAnalysisPage` | 财务分析 |
| `/hq/analytics/pl-report` | `PLReportPage` | 损益报告 |
| `/hq/analytics/member` | `MemberAnalysisPage` | 会员分析 |
| `/hq/analytics/multi-store` | `MultiStoreComparePage` | 多店对比 |
| `/hq/analytics/trend` | `TrendAnalysisPage` | 趋势分析 |
| `/hq/analytics/budget` | `BudgetTrackerPage` | 预算追踪 |
| `/hq/trade/delivery` | `DeliveryPage` | 外卖聚合 |
| `/hq/supply/inventory-intel` | `InventoryIntelPage` | 库存智能分析 |
| `/hq/supply/chain` | `SupplyChainPage` | 供应链管理 |
| `/hq/org/hr` | `HRDashboardPage` | HR 驾驶舱 |
| `/hq/banquet` | `BanquetBoardPage` | 宴席管理大屏 |
| `/receipt-editor` | `ReceiptEditorPage` | 小票模板编辑器 |
| `/receipt-editor/:templateId` | `ReceiptEditorPage` | 模板编辑（指定）|
| `/hq/menu/live-seafood` | `LiveSeafoodPage` | 活鲜菜单管理 |
| `/hq/trade/banquet-menu` | `BanquetMenuPage` | 宴席菜单管理 |
| `/hq/kds/dish-dept-mapping` | `DishDeptMappingPage` | 菜品档口映射 |
| `/menu-templates` | `MenuTemplatePage` | 菜单模板管理 |
| `/central-kitchen` | `CentralKitchenPage` | 中央厨房 |
| `/supply/bom` | `BomEditorPage` | BOM 配方编辑器 |
| `/payroll` | `PayrollPage` | 薪资管理 |
| `/approval-templates` | `ApprovalTemplatePage` | 审批模板管理 |
| `/approval-center` | `ApprovalCenterPageNew` | 审批中心（新）|
| `/payroll-manage` | `PayrollManagePage` | 薪资发放管理 |
| `/franchise-dashboard` | `FranchiseDashboardPage` | 加盟商驾驶舱 |

> 合计：**76 条前端路由**（含动态路由）

---

## web-crew 前端路由（服务员 PWA）

| 路径 | 组件 | 功能 |
|------|------|------|
| `/tables` | `TablesView` | 桌台总览（Tab 主页）|
| `/order` | `QuickOrderView` | 快速点餐（Tab 主页）|
| `/active` | `ActiveOrdersView` | 进行中订单（Tab 主页）|
| `/cruise` | `DailyCruisePage` | 巡台/巡航（Tab 主页）|
| `/delivery` | `DeliveryDashboardPage` | 外卖看板（Tab 主页）|
| `/review` | `ReviewPage` | 复盘（Tab 主页）|
| `/profile` | `ProfilePage` | 我的（Tab 主页）|
| `/open-table` | `OpenTablePage` | 开台 |
| `/order-full` | `OrderPage` | 完整点餐流程 |
| `/rush` | `RushPage` | 催菜 |
| `/table-ops` | `TableOpsPage` | 桌台操作（并/换/分）|
| `/member` | `MemberPage` | 会员查询 |
| `/complaint` | `ComplaintPage` | 投诉记录 |
| `/service-confirm` | `ServiceConfirmPage` | 服务确认 |
| `/peak-alert` | `PeakAlertPage` | 高峰预警 |
| `/order-status` | `OrderStatusPage` | 订单状态 |
| `/table-detail` | `TableDetailPage` | 桌台详情 |
| `/table-side-pay` | `TableSidePayPage` | 桌边支付 |
| `/table-map` | `TableMapView` | 桌位地图 |
| `/seat-split` | `SeatSplitPage` | 座位分单 |
| `/crew-stats` | `CrewStatsPage` | 服务员绩效 |
| `/manager-app` | `ManagerMobileApp` | 店长移动端 |
| `/receiving` | `ReceivingPage` | 验收收货 |
| `/stocktake` | `StocktakePage` | 盘点 |
| `/purchase-approval` | `PurchaseApprovalPage` | 采购审批 |
| `/route-optimize` | `RouteOptimizePage` | 配送路线优化 |
| `/handover` | `HandoverMobilePage` | 移动端交接班 |
| `/shift-schedule` | `ShiftSchedulePage` | 排班管理 |
| `/dish-recognize` | `DishRecognizePage` | 菜品识别（视觉 AI）|
| `/shift-summary` | `ShiftSummaryPage` | 班次汇总 |
| `/self-pay-link` | `SelfPayLinkPage` | 自助买单链接 |
| `/discount-request` | `DiscountRequestPage` | 折扣申请 |
| `/scan-pay` | `ScanPayPage` | 扫码支付 |
| `/stored-value-recharge` | `StoredValueRechargePage` | 储值卡充值 |
| `/printer-settings` | `PrinterSettingsPage` | 打印机设置 |
| `/waitlist` | `WaitlistPage` | 等位列表 |
| `/member-level-config` | `MemberLevelConfigPage` | 会员等级配置 |
| `/group-dashboard` | `GroupDashboardPage` | 集团视图 |
| `/store-detail` | `StoreDetailPage` | 门店详情 |
| `/live-seafood` | `LiveSeafoodOrderPage` | 活鲜点单 |
| `/reservations` | `ReservationInboxPage` | 预订收件箱 |
| `/daily-settlement` | `DailySettlementPage` | 日清日结（E1-E8）|
| `/shift-handover` | `ShiftHandoverPage` | 班次交接 |
| `/issue-report` | `IssueReportPage` | 问题上报 |
| `/member-lookup` | `MemberLookupPage` | 会员查询 |
| `/member-points` | `MemberPointsPage` | 会员积分 |
| `/member/:memberId/points` | `PointsTransactionPage` | 积分流水 |
| `/approvals` | `ApprovalPage` | 审批处理 |

> 合计：**48 条前端路由**（含 7 个底部 Tab 主页）

---

## web-kds 前端路由（后厨出餐屏）

| 路径 | 组件 | 功能 |
|------|------|------|
| `/board` | `KitchenBoard` | 档口任务看板（核心，默认页）|
| `/zone-board` | `ZoneKitchenBoard` | 包厢/大厅分区看板 |
| `/booking-prep` | `BookingPrepView` | 预订备餐视图 |
| `/dept` | `DeptSelector` | 档口选择 |
| `/timeout` | `TimeoutAlert` | 超时预警 |
| `/shortage` | `ShortageReport` | 缺料上报 |
| `/stats-panel` | `StatsPanel` | 出品统计面板 |
| `/remake` | `RemakeModal` | 重新出品 |
| `/runner` | `RunnerStation` | 传菜员工作站 |
| `/calling` | `CallingQueue` | 等叫队列 |
| `/swimlane` | `SwimLaneBoard` | 泳道模式（工序流水线）|
| `/manager` | `ManagerControlScreen` | 控菜大屏（厨师长视角）|
| `/chef-stats` | `ChefStatsPage` | 厨师绩效计件排行 |
| `/prep` | `PrepRecommendationPanel` | 预制量智能推荐 |
| `/station-profit` | `StationProfitPage` | 档口毛利核算 |
| `/calling-screen` | `CustomerCallingScreen` | 快餐顾客叫号屏 |
| `/menu-board` | `DigitalMenuBoardPage` | 数字菜单屏（大屏展示）|
| `/banquet-control` | `BanquetControlScreen` | 宴席控菜大屏（厨师长宴席同步出品）|
| `/board-legacy` | `KDSBoardPage` | 旧版看板（兼容保留）|
| `/history` | `HistoryPage` | 出品历史 |
| `/stats` | `StatsPage` | 统计报表 |
| `/config` | `KDSConfigPage` | 档口配置 |
| `/alerts` | `AlertsPage` | 预警列表 |

> 合计：**23 条前端路由**

---

## web-pos 前端路由（POS 收银）

| 路径 | 组件 | 功能 |
|------|------|------|
| `/dashboard` | `POSDashboardPage` | POS 驾驶舱（默认页）|
| `/tables` | `TableMapPage` | 桌位地图 |
| `/reservations` | `ReservationPage` | 预订管理 |
| `/open-table/:tableNo` | `OpenTablePage` | 开台 |
| `/cashier/:tableNo` | `CashierPage` | 收银操作 |
| `/order/:orderId` | `OrderPage` | 点单/加菜 |
| `/settle/:orderId` | `SettlePage` | 结账 |
| `/credit-pay/:orderId` | `CreditPayPage` | 挂账支付 |
| `/reverse-settle` | `ReverseSettlePage` | 反结算/退款 |
| `/split-pay/:orderId` | `SplitPayPage` | AA 分摊结账 |
| `/tax-invoice/:orderId` | `TaxInvoicePage` | 税务发票 |
| `/shift` | `ShiftPage` | 班次管理 |
| `/exceptions` | `ExceptionPage` | 异常处理 |
| `/queue` | `QueuePage` | 排队等位 |
| `/settings` | `POSSettingsPage` | POS 设置 |
| `/reports` | `POSReportsPage` | 报表查询 |
| `/handover` | `HandoverPage` | 交接班 |
| `/quick-cashier` | `QuickCashierPage` | 快速收银（快餐模式）|
| `/discount-audit` | `DiscountAuditPage` | 折扣审计 |
| `/live-menu` | `LiveMenuEditorPage` | 实时菜单编辑 |
| `/menu-engineering` | `MenuEngineeringPage` | 菜单工程分析 |
| `/menu-board-control` | `MenuBoardControlPage` | 菜单屏控制 |

> 合计：**22 条前端路由**（含动态参数路由）

---

## 统计汇总

| 服务/应用 | 模块/路由数 | 端口 | 版本 |
|-----------|-----------|------|------|
| tx-trade | 77 个 API 模块文件 | :8001 | v4.0.0 |
| tx-menu | 20 个 API 模块文件 | :8002 | v3.0.0 |
| tx-ops | 15 个 API 模块文件 | :8005 | v3.0.0 |
| tx-finance | 17 个 API 模块文件 | :8007 | v4.0.0 |
| tx-org | 35 个 API 模块文件 | :8012 | v3.0.0 |
| tx-supply | 24 个 API 模块文件 | :8006 | v3.0.0 |
| web-admin | 76 条前端路由 | - | React 18 |
| web-crew | 48 条前端路由 | - | React 18 |
| web-kds | 23 条前端路由 | - | React 18 |
| web-pos | 22 条前端路由 | - | React 18 |
| **合计** | **357+ API模块 + 169 前端路由** | - | - |
