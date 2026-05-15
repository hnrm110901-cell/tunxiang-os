# tx-trade Router 路由分类盘点

**Created:** 2026-05-15 (W2 Foundation 轨)
**SoT:** 战略开发计划 2026-05-12 §3 W2 任务 + 举措 1 服务收敛 W9-W11 拆分讨论输入
**Status:** v1 ground-truth, 不含拆分决策 (留架构守门会)

## 0. 文档目的与边界

- **目的:** 为举措 1 "服务收敛 24→17" 提供 tx-trade 内部路由分布事实，识别业态/职责跨界候选
- **不在范围:** 不做拆分决策 / 不改源码 / 不评估技术债优先级
- **使用方:** 架构守门会 (W2.5) / 创始人战略评估 / 后续 service-merge PR 起草

## 1. 现状摘要 (2026-05-15)

| 维度 | 数量 | 备注 |
|---|---:|---|
| router 文件 | **163** | `services/tx-trade/src/{api,routers}/*.py` 去掉 `__init__` |
| `include_router` 调用 | **149** | `main.py` 显式 + Sprint E batch_mount 延迟 4 个 |
| router 文件总行数 | **60,737** | 含 docstring / schema / endpoint 实现 |
| service 文件 | 152 | `services/tx-trade/src/services/*.py` |
| service 总行数 | 71,840 | |
| model 文件 | 44 | `services/tx-trade/src/models/*.py` |

**信号:** 单一 microservice 内 163 路由 + 60K LOC，是 tx-trade 单点风险（W8 demo 全靠它）+ 举措 1 服务收敛的首要拆分对象。

## 2. 分类法 (4 类)

按"业务边界 + 拆分必要性"分类：

| 类别 | 定义 | 拆分性 |
|---|---|---|
| **交易内核** | 订单生命周期 + 桌台 + 收银 + 支付 + 折扣 + 结算 + 退款 + 离线同步 (Tier 1 资金路径) | **不可拆** — Tier 1 主路径必须保持单服务事务边界 |
| **履约** | KDS + 出餐 + 配送 + 打印 + 制作辅助 (vision/voice/expo) | **可考虑拆出** tx-fulfillment 独立服务 |
| **渠道** | 外部平台对接 + Omni + 预订 + 自助/扫码 + 评价 + Webhook | **可考虑拆出** tx-channel 或并入 gateway 边缘 |
| **业态扩展** | 业态特异 (宴席/美食广场/自助点餐/快餐/上门厨师/企业餐/早市/零售/存酒) + 员工/管理 + 跨界辅助 | **重度拆分候选** — 宴席/食广场/kiosk 各自可独立 |

**分类规则:**
- 按 `prefix` + `tag` + 业务语义判断
- 不按文件名前缀（部分文件名误导，如 `crew_*` 其实跨内核/管理边界）
- 边界模糊条目单列 §7

## 3. 类别 1: 交易内核 (Trade Core)

**~36 routers / ~12,000+ lines (~20% 文件数 / ~20% LOC)**

| Router | Lines | Prefix | 备注 |
|---|---:|---|---|
| quick_cashier_routes | 1603 | /api/v1/quick-cashier | 快收银主路径 |
| cashier_api | 886 | /api/v1 | 主收银 (cashier tag) |
| offline_sync_routes | 800 | /api/v1 | 离线同步 (Tier 1: 断网 4h 无数据丢失) |
| dining_session_routes | 579 | /api/v1/dining-sessions | 堂食会话 |
| discount_engine_routes | 634 | /api/v1/discount | 折扣引擎 |
| minimum_consumption_routes | 513 | /api/v1/minimum-consumption | 最低消费 |
| stored_value_routes | 487 | /api/v1 | 储值 (Tier 1 资金) |
| table_card_api | 478 | /api/v1/tables | 桌台卡片 |
| billing_rules_routes | 457 | /api/v1 | 计费规则 |
| table_utilization_routes | 441 | /api/v1/table-utilization | 翻台率 (跨履约边界) |
| table_period_config_routes | 390 | /api/v1/table-period-configs | 时段配置 |
| orders | 387 | /api/v1/trade | 订单主 (trade tag) |
| table_merge_preset_routes | 379 | /api/v1/table-presets | 拼桌 |
| split_payment_routes | 344 | /api/v1/orders | 分单支付 |
| shift_report_routes | 303 | /api/v1/shifts | 班次报表 |
| payment_direct_routes | 286 | /api/v1/payment-direct | 直接支付 |
| table_routes | 262 | /api/v1/tables | 桌台 |
| scan_pay_routes | 262 | /api/v1/payments | 扫码支付 |
| self_pay_router | 254 | /api/v1 | self-pay tag |
| coupon_routes | 238 | /api/v1/trade/coupon | 优惠券 |
| settle_retry | 236 | /api/v1 | 结算重试 (Tier 1: 支付 Saga) |
| order_ops_routes | 224 | /api/v1/orders | 订单操作 |
| wechat_pay_routes | 218 | /api/v1/trade/payment/wechat | 微信支付 |
| refund_routes | 215 | /api/v1/trade/refunds | 退款 |
| table_layout_routes | 210 | /api/v1/tables | 桌台布局 |
| discount_audit_routes | 182 | /api/v1/discount | 折扣审计 |
| platform_coupon_routes | 170 | /api/v1/trade/platform-coupon | 平台券 |
| payment_router | 170 | /api/v1 | table-side-pay |
| handover_routes | 170 | /api/v1 | 交班 |
| seat_order_routes | 162 | /api/v1/orders | 座位下单 |
| shift_routes | 160 | /api/v1/shifts | 班次 |
| order_ext_routes | 156 | /api/v1/trade/orders | 订单扩展 |
| service_charge_routes | 145 | /api/v1/service-charge | 服务费 |
| invoice_routes | 132 | /api/v1/invoices | 发票 (Tier 1: 金税四期) |
| course_firing_routes | 130 | /api/v1/orders | 起菜 (跨履约边界) |
| table_monitor_routes | 115 | /api/v1/table-monitor | 桌台监控 |
| table_ops_routes | 68 | /api/v1 | table-ops |

**拆分性结论:** 不可拆。Tier 1 资金路径 (cashier/payment/discount/refund/stored-value/invoice/settle-retry) + 桌台状态机 + 订单生命周期必须保持单事务边界，且与 `services/{cashier_engine,order_service,payment_saga_service}.py` 强耦合。

## 4. 类别 2: 履约 (Fulfillment)

**~45 routers / ~15,000+ lines (~28% 文件数 / ~25% LOC)**

### 4.1 KDS 系列 (18 routers, ~3,200 lines)

| Router | Lines | Prefix |
|---|---:|---|
| kds_routes | 635 | /api/v1/kds |
| kds_banquet_routes | 521 | /api/v1/kds (宴席特化) |
| kds_analytics_routes | 297 | /api/v1/kds-analytics |
| kds_delta_routes | 296 | /api/v1/kds |
| kds_by_session_routes | 279 | /api/v1/kds/sessions |
| kds_piecework_routes | 225 | /api/v1/kds-piecework |
| kds_config_routes | 217 | /api/v1/kds-config |
| kds_rules_routes | 173 | /api/v1/kds-rules |
| kds_display_rules_routes | 167 | /api/v1/kds |
| scan_analytics_routes | 165 | /api/v1/kds (tag 是 kds-analytics) |
| kds_display_config_routes | 135 | /api/v1/kds-display |
| kds_shortage_routes | 112 | /api/v1/kds/shortage |
| kds_swimlane_routes | 104 | /api/v1/kds/swimlane |
| kds_soldout_routes | 83 | /api/v1/kds/soldout |
| kds_pause_grab_routes | 83 | /api/v1/kds/tickets |
| kds_chef_stats_routes | 67 | /api/v1/kds/chef-stats |
| kds_station_profit_routes | 63 | /api/v1/kds/station-profit |
| kds_prep_routes | 45 | /api/v1/kds/prep |

### 4.2 配送系列 (13 routers, ~6,000+ lines)

| Router | Lines | Prefix |
|---|---:|---|
| self_delivery_routes | 782 | /api/v1/trade/delivery |
| delivery_panel_router | 720 | /api/v1/delivery |
| delivery_ops_routes | 672 | /api/v1/delivery |
| delivery_dispatch_routes | 592 | /api/v1/delivery/self |
| delivery_router | 556 | /api/v1/delivery |
| aggregator_reconcile_routes | 556 | /api/v1/trade/aggregator-reconcile |
| dish_publish_routes | 523 | /api/v1/trade/delivery/publish |
| delivery_orders_routes | 515 | /api/v1/delivery |
| dispute_routes | 511 | /api/v1/trade/delivery/disputes |
| delivery_platform_sync_routes | 500 | /api/v1/delivery/platform-sync |
| delivery_aggregator_routes | 403 | /api/v1/trade/aggregator |
| dispatch_rule_routes | 395 | /api/v1/dispatch-rules |
| canonical_delivery_routes | 379 | /api/v1/trade/delivery/canonical |
| dispatch_code_routes | 229 | /api/v1/dispatch-codes |
| delivery_dispute_routes | 187 | /api/v1/delivery/disputes |

### 4.3 打印系列 (4 routers, ~1,800 lines)

| Router | Lines | Prefix |
|---|---:|---|
| printer_config_routes | 618 | /api/v1/printers |
| print_manager_routes | 581 | /api/v1/print |
| print_template_routes | 394 | /api/v1/print |
| printer_routes | 196 | /api/v1/printer |

### 4.4 制作/出餐辅助 (14 routers, ~3,800 lines)

| Router | Lines | Prefix |
|---|---:|---|
| dish_dept_mapping_routes | 555 | /api/v1/kds |
| service_call_routes | 470 | /api/v1/service-calls |
| kitchen_monitor_routes | 453 | /api/v1/kitchen-monitor |
| production_dept_routes | 432 | /api/v1/production-depts |
| digital_menu_board_router | 373 | /api/v1/menu |
| cook_time_routes | 323 | /api/v1/cook-time |
| expo_routes | 312 | /api/v1/expo (传菜) |
| calling_screen_routes | 281 | (叫号屏) |
| voice_order_router | 237 | /api/v1/voice (AI 辅助，跨 tx-brain) |
| tv_menu_routes | 209 | /api/v1/tv-menu |
| vision_router | 196 | /api/v1/vision (AI 辅助，跨 tx-brain) |
| runner_routes | 147 | /api/v1/runner |
| service_bell_routes | 126 | /api/v1/service-bell |

**拆分性结论:** 可考虑拆出 **tx-fulfillment** 独立服务承接 KDS + 配送 + 打印 + 制作辅助。前提：与 cashier_engine 的事件契约 (order_confirmed → kds_dispatch) 必须先在 Outbox 上稳定 (举措 3 真 Outbox 前置)。

## 5. 类别 3: 渠道 (Channel)

**~26 routers / ~12,000+ lines (~16% 文件数 / ~20% LOC)**

### 5.1 Omni 多渠道核心 (4 routers, ~2,700 lines)

| Router | Lines | Prefix |
|---|---:|---|
| omni_sync_routes | 1035 | /api/v1/omni |
| omni_channel_routes | 715 | /api/v1 |
| sync_ingest_router | 684 | /api/v1/sync (edge-sync) |
| omni_order_center_routes | 271 | /api/v1/trade/omni-orders |

### 5.2 预订/邀请/排队 (8 routers, ~3,800 lines)

| Router | Lines | Prefix |
|---|---:|---|
| waitlist_routes | 876 | /api/v1/waitlist |
| booking_api | 775 | /api/v1 |
| booking_webhook_routes | 653 | /api/v1/booking |
| customer_booking_routes | 516 | (no prefix) |
| reservation_config_routes | 449 | /api/v1/reservation |
| invitation_routes | 303 | /api/v1/invitations (电子邀请函) |
| reservation_invitation_routes | 250 | /api/v1/reservation-invitations |
| booking_prep_routes | 113 | /api/v1/booking-prep |
| call_center_routes | 204 | (无 prefix) — 预订电话集成 / 客户回拨 |

### 5.3 自助/扫码入口 (5 routers, ~1,700 lines)

| Router | Lines | Prefix |
|---|---:|---|
| scan_order_routes | 492 | /api/v1/scan-order |
| self_pickup_routes | 335 | /api/v1/self-pickup |
| scan_order_api | 323 | /api/v1/scan-order (**与 scan_order_routes 重复候选**, 见 §8) |
| takeaway_routes | 301 | /api/v1/takeaway |
| self_order_routes | 212 | /api/v1/self-order |

### 5.4 平台对接/合作 (9 routers, ~3,800 lines)

| Router | Lines | Prefix |
|---|---:|---|
| douyin_voucher_routes | 826 | /api/v1/trade/douyin-voucher |
| collab_order_routes | 558 | /api/v1/collab-order |
| webhook_routes | 512 | /api/v1/webhook |
| xiaohongshu_routes | 515 | (deferred batch_mount, 见 §8) |
| review_routes | 471 | /api/v1/trade/reviews |
| xhs_routes | 271 | (与 xiaohongshu_routes 重复候选, 见 §8) |
| channel_dispute_routes | 196 | /api/v1/channels/disputes |
| channel_canonical_routes | 188 | /api/v1/channels/canonical |
| group_buy_routes | 188 | /api/v1/group-buy |
| group_order_routes | 172 | /api/v1/trade/group-orders |

**拆分性结论:** 可考虑拆出 **tx-channel** 或并入 gateway 边缘 (与举措 2 Gateway 瘦身联动)。但 omni_sync 1035 行 + edge sync_ingest 684 行 与 cashier 强事件耦合，拆分前需先稳定事件契约。

## 6. 类别 4: 业态扩展 (Vertical Specialization)

**~56 routers / ~18,000+ lines (~34% 文件数 / ~30% LOC) — 最大候选拆出**

### 6.1 宴席 banquet 系列 (20 routers, ~6,000+ lines)

| Router | Lines | Prefix |
|---|---:|---|
| banquet_order_routes | 1127 | /api/v1/trade/banquet (含支付) |
| banquet_kds_routes | 471 | /api/v1/banquet/kds (KDS 宴席特化) |
| banquet_deposit_routes | 458 | /api/v1/banquet/deposits |
| banquet_advanced_routes | 452 | /api/v1/banquet |
| banquet_payment_routes | 419 | /api/v1/banquet (含支付) |
| banquet_routes | 396 | /api/v1/banquets |
| banquet_contract_routes | 395 | /api/v1/banquet-contracts |
| banquet_lead_routes | 337 | /api/v1/banquet-leads |
| banquet_quote_routes | 298 | /api/v1/banquet/quotes |
| banquet_venue_routes | 272 | /api/v1/banquet/venues |
| banquet_order_v2_routes | 266 | /api/v1/banquet/orders |
| banquet_ai_routes | 144 | /api/v1/banquet/ai |
| banquet_production_routes | 134 | /api/v1/banquet/production |
| banquet_aftercare_routes | 120 | /api/v1/banquet/aftercare |
| banquet_material_routes | 117 | /api/v1/banquet/materials |
| banquet_schedule_routes | 103 | /api/v1/banquet/schedule |
| banquet_live_order_routes | 96 | /api/v1/banquet/live-orders |
| banquet_capacity_routes | 95 | /api/v1/banquet/capacity |
| banquet_execution_routes | 92 | /api/v1/banquet/eecution (**typo 候选, 见 §8**) |
| banquet_settlement_routes | 74 | /api/v1/banquet/settlements |

### 6.2 业态特异 (10 routers, ~6,000+ lines)

| Router | Lines | Prefix |
|---|---:|---|
| food_court_routes | 1442 | /api/v1/food-courts (智慧商街多商户) |
| kiosk_routes | 1155 | /api/v1/kiosk (自助点餐机) |
| wine_storage_routes | 980 | /api/v1/wine-storage (存酒 Tier 1) |
| market_session_routes | 607 | /api/v1/market-sessions (早市/夜市) |
| corporate_order_routes | 562 | /api/v1/trade/corporate (企业团餐) |
| fastfood_routes | 532 | /api/v1/fastfood |
| chef_at_home_routes | 307 | /api/v1/chef-at-home (上门厨师) |
| enterprise_meal_routes | 282 | /api/v1/trade/enterprise |
| enterprise_routes | 271 | /api/v1/enterprise |
| retail_mall_routes | 226 | /api/v1/retail |

### 6.3 员工/管理 (跨 tx-org 边界候选, 9 routers, ~3,300 lines)

| Router | Lines | Prefix |
|---|---:|---|
| mobile_ops_routes | 931 | /api/v1/mobile (店员手机端) |
| store_management_routes | 625 | (门店+桌台配置) |
| crew_stats_routes | 325 | /api/v1/crew/stats |
| crew_schedule_router | 320 | (排班) |
| manager_app_routes | 302 | /api/v1/manager |
| shift_summary_router | 226 | (班次汇总, 跨内核) |
| patrol_router | 182 | (巡台签到, 跨履约) |
| proactive_service_routes | 169 | (三约束聚合, 跨 tx-brain) |
| crew_handover_router | 140 | /api/v1/crew |

### 6.4 特殊辅助 (8 routers, ~2,200 lines)

| Router | Lines | Prefix |
|---|---:|---|
| template_editor_routes | 1349 | /api/v1/receipt-templates (小票模板) |
| training_mode_routes | 334 | /api/v1/training-mode |
| menu_engineering_router | 231 | (BCG 矩阵, 跨 tx-analytics) |
| prediction_routes | 219 | /api/v1/predict (跨 tx-brain) |
| inventory_menu_routes | 171 | /api/v1/inventory (跨 tx-supply) |
| allergen_routes | 164 | (过敏原) |
| approval_routes | 161 | /api/v1/approvals |
| dish_practice_routes | 106 | /api/v1 |
| supply_chain_mobile_routes | 212 | /api/v1/supply (**明显跨 tx-supply**, 见 §7) |

**拆分性结论:** 重度候选。宴席 (20 routers ~6K LOC) / 美食广场 (1442) / kiosk (1155) / 存酒 (980 Tier 1) 各可独立微服务或合并为 tx-vertical。员工/管理 (~3.3K LOC) 应回归 tx-org。

## 7. 边界模糊 routers (拆分时需创始人裁决)

| Router | 当前归属 | 跨界候选 | 备注 |
|---|---|---|---|
| `vision_router` (196) | 履约 | tx-brain | AI 视觉识别本应 brain |
| `voice_order_router` (237) | 履约 | tx-brain | 语音点菜本应 brain |
| `prediction_routes` (219) | 业态/辅助 | tx-brain | 销量预测明确跨界 |
| `proactive_service_routes` (169) | 业态/员工 | tx-brain | 三约束聚合本应 brain |
| `menu_engineering_router` (231) | 业态/辅助 | tx-analytics | BCG 矩阵分析跨经营分析 |
| `inventory_menu_routes` (171) | 业态/辅助 | tx-supply | 库存联动菜单跨供应链 |
| `crew_*` (5 routers ~1,150) | 业态/员工 | tx-org | 员工排班/巡台/交接班 |
| `store_management_routes` (625) | 业态/员工 | tx-org | 门店+桌台配置 (桌台留内核, 门店出 tx-org) |
| `manager_app_routes` (302) | 业态/员工 | tx-org | 店长 KPI 跨多域 |
| `mobile_ops_routes` (931) | 业态/员工 | tx-org | 店员手机端含订单操作 |
| `template_editor_routes` (1349) | 业态/辅助 | tx-org / 独立 | 小票模板是配置类，可独立 |
| `printer_*` (4 routers ~1,800) | 履约 | tx-org / 边缘 | 打印配置 + 实际打印拆开 |
| `course_firing_routes` (130) | 内核 | 履约 | 起菜紧贴订单状态机，但 KDS 流转下游 |
| `supply_chain_mobile_routes` (212) | 业态/辅助 | tx-supply | 供应链移动端明显应归 tx-supply |
| `call_center_routes` (204) | 渠道/预订 | tx-org / 独立 | 呼叫中心可独立服务 |
| `table_utilization_routes` (441) | 内核 | tx-analytics | 翻台率是分析维度 |

## 8. 重复 / 命名漂移 / 候选 dead routers

| 项 | 状态 | 建议 |
|---|---|---|
| `xhs_routes` (271) vs `xiaohongshu_routes` (515) | `xhs_routes` 显式注册 / `xiaohongshu_routes` 通过 Sprint E `batch_mount` 延迟注册 (`# E3 #93`) | 落 follow-up issue 确认是否两套并存，统一收敛到 `xiaohongshu_routes` |
| `scan_order_routes` (492) vs `scan_order_api` (323) | 双注册 `scan_order_router` + `scan_order_ext_router` | 文件命名漂移 (一个 `_routes` 一个 `_api`)，可能 deliberate 分层但需 doc 化 |
| `banquet_execution_routes` prefix `banquet/eecution` | **typo** (`eecution` 缺 `x`) | follow-up issue: 修 typo 但属 breaking change，需调用方同步 |

## 9. 数字汇总 (4 类 + 跨界候选)

| 类别 | Router 数 | Lines 估计 | 占文件数 % | 占 LOC % |
|---|---:|---:|---:|---:|
| 交易内核 | 37 | ~12,500 | 23% | ~21% |
| 履约 | 50 | ~15,200 | 31% | ~25% |
| 渠道 | 28 | ~12,200 | 17% | ~20% |
| 业态扩展 | 48 | ~17,800 | 29% | ~29% |
| **合计** | **163** | **~57,700** | 100% | ~95% |

（剩余 ~5% LOC 含 docstring / blank / `__init__` 等）

**业态扩展 30% LOC 是最大拆分潜力点。**

## 10. 不做的事 (本 doc 边界)

- ❌ 不给出"拆 X 服务"的具体方案 (留架构守门会 + 创始人裁决)
- ❌ 不修任何 router/service 代码
- ❌ 不评估各 router 的健康度 / 测试覆盖 (silent failure 治理见 #663)
- ❌ 不重命名 / 不合并任何重复候选 (留单独 follow-up PR)

## 11. 后续行动 (落地建议)

| 项 | 推荐路径 | 时机 |
|---|---|---|
| 架构守门会 v1 (W2.5) | 用本 doc 4 类 + §7 跨界候选作为评估输入 | W2 周五 |
| 举措 1 服务收敛 W9-W11 拆分讨论 | 用本 doc §3-§6 LOC 估计 + §9 占比作为决策依据 | W9 启动 |
| 维护本 doc | 每月对照 `grep -c include_router main.py` + 文件数，drift > 10% 触发重新分类 | 月初 |
| 重复 / typo follow-up | 落 issues, 不在本 doc 修 | 本周内 |
| 跨界 routers 归位 PR | 单独 PR / service, 每次只动一组 | 举措 1 启动后 |

## 12. 参考

- 战略 SoT: `/Users/lichun/Desktop/屯象OS餐饮行业知识库/屯象OS 架构与代码升级优化战略开发计划2026-05-12.md` §3 W2 / 举措 1
- W1 服务健康度 baseline: `docs/service-health/2026-W20.md`
- 服务冻结令 (CLAUDE.md 19 服务): `CLAUDE.md`
- main.py 注册表: `services/tx-trade/src/main.py` (149 include_router + Sprint E batch_mount)
