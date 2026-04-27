# 屯象OS 宴会/团餐/会议餐 全场景升级迭代开发计划

> 版本: v1.0 | 日期: 2026-04-25
> 市场定位: 3.6万亿团餐市场唯一全流程AI餐饮SaaS

---

## 一、战略背景

### 市场空白确认
- **主流厂商(美团/哗啦啦/客如云/奥琦玮/天财商龙)**: 均无宴会全流程产品线
- **专业系统(51宴会/木棉花)**: 功能有限、技术落后、非连锁场景
- **团餐市场**: 2026年预计3.6万亿，集中度仅6.7%，数字化率极低
- **AI+宴会**: 完全未被触及的蓝海

### 屯象OS已有能力复用率评估: ~80%

| 已有能力 | 复用方式 |
|----------|----------|
| 桌台管理(7模块/40+端点) | 扩展宴会桌组、厅房档期 |
| 预订系统(7状态机+定金) | 直接复用，增加宴会类型字段 |
| 楼层布局引擎(画布+WebSocket) | 增加宴会模式布局模板 |
| 包间规则(低消+容量+时段) | 扩展宴会厅专属规则 |
| 统一商品中心(Product+BOM) | 宴会套餐=商品组合+BOM分解 |
| KDS生产集成(v223) | 扩展宴会排产调度 |
| tx-supply供应链 | 宴会订单→精准采购计划 |
| SOP时间轴引擎(15分钟节拍) | 宴会执行SOP模板 |
| 卡券内核+多方结算 | 宴会结算(定金抵扣+分项) |
| 微信/支付宝V3 | 直接复用 |
| tx-expense合同台账(v241) | 扩展宴会电子合同 |
| 企业团餐B2B(v226, 5表) | 直接扩展为宴会CRM |
| 私域6大模块 | 宴会客户复购+转介绍 |
| 14个AI Agent | 扩展宴会AI大脑 |
| tx-civic合规 | 宴会食安追溯 |

---

## 二、全业务流程闭环设计

```
┌─────────────────────────────────────────────────────────────────────┐
│                    宴会全生命周期 (8个阶段)                           │
├─────────┬──────────┬──────────┬──────────┬──────────┬──────────────┤
│ ① 线索  │ ② 报价   │ ③ 签约   │ ④ 筹备   │ ⑤ 执行   │ ⑥ 结算     │
│ 获取    │ 方案     │ 定金     │ 排产     │ 当日     │ 售后       │
├─────────┼──────────┼──────────┼──────────┼──────────┼──────────────┤
│宴会CRM  │智能报价  │电子合同  │厨房排产  │宴会SOP   │多方结算    │
│线索录入  │套餐模板  │条款模板  │原料分解  │迎宾流程  │定金抵扣    │
│跟进提醒  │按人数配菜│变更留痕  │产能规划  │上菜节奏  │加菜/酒水   │
│客资保护  │智能定价  │定金收取  │采购备货  │VIP服务   │B2B月结    │
│转化漏斗  │多档方案  │违约条款  │多场并行  │实时调度  │发票开具    │
│         │         │         │厅房排布  │异常处理  │复购营销    │
├─────────┼──────────┼──────────┼──────────┼──────────┼──────────────┤
│ 复用:   │ 复用:    │ 复用:    │ 复用:    │ 复用:    │ 复用:      │
│v226团餐 │商品中心  │tx-expense│KDS+供应链│SOP引擎   │卡券内核    │
│私域CRM  │BOM配方  │合同台账  │批次库存  │IM推送   │多方结算    │
│会员画像 │动态定价  │费控审批  │采购计划  │WebSocket│支付V3     │
└─────────┴──────────┴──────────┴──────────┴──────────┴──────────────┘
         │                                                │
         └────────── ⑦ AI宴会大脑 (贯穿全流程) ───────────┘
                     │
         ⑧ 数据驾驶舱 (宴会经营看板)
```

---

## 三、技术架构决策

### 3.1 微服务归属

不新建微服务，按职责归入现有服务：

| 模块 | 归属微服务 | 理由 |
|------|-----------|------|
| 宴会CRM(线索/跟进/漏斗) | **tx-trade** (:8001) | 扩展v226 enterprise_meal体系 |
| 报价/套餐/合同 | **tx-trade** (:8001) | 复用商品中心+预订系统 |
| 厅房档期/桌组管理 | **tx-trade** (:8001) | 扩展现有桌台管理 |
| 宴会排产引擎 | **tx-trade** (:8001) | 扩展KDS生产集成 |
| 宴会采购联动 | **tx-supply** (:8003) | 复用采购计划+批次库存 |
| 宴会结算 | **tx-trade** (:8001) | 扩展多方结算引擎 |
| 宴会执行SOP | **tx-agent** (:8008) | 扩展SOP时间轴引擎 |
| AI宴会大脑 | **tx-agent** (:8008) | 扩展Chief Agent编排 |
| 宴会合规(食安) | **tx-civic** (:8013) | 复用追溯+明厨亮灶 |
| 宴会费控(差旅报销) | **tx-expense** (:8015) | 复用合同台账+审批 |

### 3.2 数据模型设计原则

- 所有新表继承 `TenantBase`，自动具备 RLS 租户隔离
- 金额字段统一用 `_fen`（分），Integer 类型
- 状态机统一用 `String(20)` + Enum 类
- JSON 配置字段用于灵活扩展（如菜单定制选项）
- 外键关联现有表（stores/products/orders/reservations）

### 3.3 事件驱动串联

```
banquet.lead.created        → CRM自动分配销售
banquet.quote.confirmed     → 生成合同草稿
banquet.contract.signed     → 触发采购计划+厅房锁定
banquet.deposit.paid        → 确认档期+通知厨房
banquet.menu.finalized      → BOM分解→原料需求→采购单
banquet.day.t_minus_1       → 备货检查+人员排班确认
banquet.execution.started   → 启动宴会SOP时间轴
banquet.execution.completed → 生成结算单
banquet.settled             → 触发售后SOP(评价+复购)
```

---

## 四、分Phase开发计划

---

### Phase 1: 宴会CRM + 智能报价 + 厅房档期

> 目标: 打通"线索→报价→锁定厅房"前端闭环

#### 迁移链: v305-v309 (5个迁移, ~12张新表)

**v305: 宴会线索与客资管理**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_leads` | lead_no, store_id, customer_name, phone, company, event_type(wedding/birthday/business/tour_group/conference/annual_party), event_date, guest_count_est, budget_per_table_fen, source_channel, assigned_sales_id, status(new/following/quoted/contracted/lost), priority, follow_up_at, lost_reason, referral_lead_id | 宴会线索 |
| `banquet_lead_follow_ups` | lead_id, sales_id, follow_type(phone/visit/wechat/demo), content, next_action, next_follow_at | 跟进记录 |
| `banquet_lead_transfers` | lead_id, from_employee_id, to_employee_id, reason, transferred_at | 客资转移(离职继承) |

**v306: 宴会套餐与智能报价**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_menu_templates` | name, event_type, tier(economy/standard/premium/luxury), per_table_price_fen, dish_count, dishes_json(product_id+quantity+course_order), min_tables, includes_drinks, includes_decoration, is_customizable | 套餐模板 |
| `banquet_quotes` | lead_id, quote_no, template_id, table_count, guest_count, menu_json(定制后), venue_fee_fen, decoration_fee_fen, service_fee_fen, drink_fee_fen, total_fen, discount_fen, final_fen, valid_until, status(draft/sent/accepted/expired/rejected), version | 报价单(支持多版本) |
| `banquet_quote_items` | quote_id, item_type(dish/drink/decoration/service/venue/other), product_id, name, quantity, unit_price_fen, subtotal_fen, note | 报价明细 |

**v307: 厅房档期管理**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_venues` | store_id, venue_name, venue_type(hall/private_room/outdoor/roof), floor, max_tables, max_guests, min_tables, base_fee_fen, decoration_options_json, facilities_json(投影/音响/LED), photos_json, is_active | 宴会厅/场地 |
| `banquet_venue_bookings` | venue_id, banquet_id, date, time_slot(lunch/dinner/full_day), status(held/confirmed/released), held_until, confirmed_at, notes | 厅房档期(防撞档) |

**v308: 宴会桌组管理**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_table_groups` | banquet_id, venue_id, group_name, table_ids_json, layout_snapshot_json, total_seats, status(planned/set_up/in_use/cleared) | 宴会桌组(一键管理N桌) |

**v309: 宴会主单**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquets` | banquet_no, lead_id, quote_id, store_id, venue_id, event_type, event_name, event_date, time_slot, host_name, host_phone, guest_count, table_count, contract_id, menu_json, special_requests, status(draft/confirmed/preparing/in_progress/completed/cancelled/settled), total_amount_fen, deposit_amount_fen, deposit_paid, deposit_paid_at, balance_fen | 宴会主单(贯穿全流程) |
| `banquet_status_logs` | banquet_id, from_status, to_status, operator_id, reason, created_at | 状态变更日志 |

#### Service层 (~4个新Service)

| 服务 | 核心方法 | 行数估算 |
|------|---------|---------|
| `banquet_crm_service.py` | create_lead / assign_sales / follow_up / transfer_lead / conversion_funnel / lost_analysis | ~600行 |
| `banquet_quote_service.py` | generate_quote(from_template) / customize_menu / calculate_pricing / compare_quotes / send_to_customer | ~500行 |
| `banquet_venue_service.py` | check_availability / hold_venue(24h) / confirm_booking / release / calendar_view / conflict_detect | ~400行 |
| `banquet_service.py` (扩展已有) | create_banquet / update_status / link_contract / link_deposit / get_timeline | ~500行 |

#### API端点 (~35个)

```
/api/v1/banquet/leads/*           — 线索CRUD+分配+跟进+转移+漏斗 (10)
/api/v1/banquet/templates/*       — 套餐模板CRUD+按类型查询 (5)
/api/v1/banquet/quotes/*          — 报价生成+定制+对比+发送 (8)
/api/v1/banquet/venues/*          — 厅房CRUD+档期日历+冲突检测 (7)
/api/v1/banquet/orders/*          — 宴会主单CRUD+状态流转+时间线 (5)
```

#### Phase 1 产出统计

| 指标 | 数量 |
|------|------|
| 新迁移 | 5个 (v305-v309) |
| 新表 | 12张 (全部RLS) |
| 新Service | 4个 |
| 新API端点 | ~35个 |
| 预估代码量 | ~4,000行 |

---

### Phase 2: 宴会排产 + 采购联动 + 电子合同

> 目标: 打通"签约→备货→厨房就绪"后端闭环

#### 迁移链: v310-v314 (5个迁移, ~10张新表)

**v310: 宴会合同管理**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_contracts` | banquet_id, contract_no, template_id, parties_json(甲方/乙方), terms_json(菜单/场地/服务/违约), total_fen, deposit_ratio, deposit_fen, payment_schedule_json, signed_at, signed_by, status(draft/pending_sign/signed/amended/terminated), amendment_count | 宴会合同(扩展tx-expense合同) |
| `banquet_contract_amendments` | contract_id, amendment_no, changes_json(变更项), reason, approved_by, approved_at | 合同变更记录 |

**v311: 宴会排产引擎**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_production_plans` | banquet_id, plan_date, kitchen_id, status(planned/confirmed/in_progress/completed), total_dishes, total_servings, prep_start_time, service_start_time, course_timeline_json(凉菜→热菜→主食→甜品 出菜时序), staff_required_json(厨师/帮厨/传菜) | 排产主计划 |
| `banquet_production_tasks` | plan_id, course_no, dish_id, dish_name, quantity, prep_time_min, cook_time_min, station_id, assigned_chef_id, status(pending/prepping/cooking/plated/served), started_at, completed_at | 排产任务(对接KDS) |

**v312: 宴会原料分解**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_material_requirements` | banquet_id, plan_id, product_id(原料), required_qty, unit, unit_cost_fen, total_cost_fen, source(inventory/purchase), inventory_reserved, purchase_order_id, status(calculated/reserved/purchased/received) | 原料需求(BOM分解) |
| `banquet_purchase_orders` | banquet_id, po_no, supplier_id, items_json, total_fen, required_by, status(draft/submitted/confirmed/received/partial), linked_supply_order_id | 宴会专用采购单(对接tx-supply) |

**v313: 产能管理**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `kitchen_capacity_slots` | store_id, date, time_slot, max_dishes_per_hour, max_concurrent_banquets, current_load, available_capacity, staff_on_duty_json | 厨房产能时段表 |
| `banquet_capacity_conflicts` | date, store_id, slot, conflict_type(overload/staff_shortage/ingredient_shortage), severity(warning/critical), resolution, resolved_by | 产能冲突记录 |

**v314: 多场宴会并行调度**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_day_schedule` | store_id, date, banquets_json(当日所有宴会), venue_allocation_json, staff_allocation_json, timeline_json, status(planned/confirmed/executing/completed) | 当日宴会总调度 |

#### Service层 (~5个新Service)

| 服务 | 核心方法 | 行数估算 |
|------|---------|---------|
| `banquet_contract_service.py` | generate_from_quote / sign / amend / terminate / payment_schedule | ~500行 |
| `banquet_production_service.py` | generate_plan(from_menu) / assign_tasks / track_progress / course_timeline | ~800行 |
| `banquet_material_service.py` | bom_decompose(menu→ingredients) / check_inventory / generate_purchase / reserve_stock | ~600行 |
| `banquet_capacity_service.py` | check_capacity / detect_conflicts / suggest_reschedule / staff_requirement | ~500行 |
| `banquet_scheduler_service.py` | daily_schedule / multi_banquet_optimize / venue_turnaround / resource_balance | ~600行 |

#### API端点 (~30个)

```
/api/v1/banquet/contracts/*       — 合同生成+签署+变更+付款计划 (7)
/api/v1/banquet/production/*      — 排产计划+任务+进度+时序 (8)
/api/v1/banquet/materials/*       — 原料分解+库存核查+采购联动 (6)
/api/v1/banquet/capacity/*        — 产能查询+冲突检测+建议 (4)
/api/v1/banquet/schedule/*        — 日调度+多场并行+资源平衡 (5)
```

#### Phase 2 产出统计

| 指标 | 数量 |
|------|------|
| 新迁移 | 5个 (v310-v314) |
| 新表 | 10张 (全部RLS) |
| 新Service | 5个 |
| 新API端点 | ~30个 |
| 预估代码量 | ~5,000行 |

---

### Phase 3: 宴会执行 + 结算 + 售后

> 目标: 打通"当日执行→结算→复购"最后一公里

#### 迁移链: v315-v318 (4个迁移, ~8张新表)

**v315: 宴会执行SOP**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_execution_plans` | banquet_id, sop_template_id, checkpoints_json(迎宾/开场/冷菜/热菜/主食/甜品/致辞/结束), assigned_staff_json(迎宾员/司仪/服务员/传菜员), status(planned/executing/completed) | 宴会执行计划(对接SOP引擎) |
| `banquet_execution_logs` | plan_id, checkpoint_id, checkpoint_name, scheduled_time, actual_time, delay_min, executor_id, status(pending/in_progress/completed/skipped/escalated), issue_note | 执行日志(每个节点) |

**v316: 宴会现场管理**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_live_orders` | banquet_id, order_type(add_dish/add_drink/special_request/cancel), items_json, amount_fen, requested_by, approved_by, status(pending/approved/rejected/fulfilled) | 现场加菜/加酒水/特殊需求 |
| `banquet_guest_check_ins` | banquet_id, table_no, guest_name, check_in_time, vip_flag, dietary_notes, seat_assignment | 宾客签到(可选) |

**v317: 宴会结算**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_settlements` | banquet_id, contract_amount_fen, deposit_paid_fen, live_order_amount_fen(加菜/酒水), service_fee_fen, venue_fee_fen, decoration_fee_fen, discount_fen, total_fen, balance_due_fen, payment_method, settled_at, settled_by, invoice_status, invoice_no | 宴会结算单 |
| `banquet_settlement_items` | settlement_id, item_type, item_name, quantity, unit_price_fen, subtotal_fen, source(contract/live_order/fee) | 结算明细 |

**v318: 宴会售后与复购**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_feedbacks` | banquet_id, customer_id, overall_score(1-5), food_score, service_score, venue_score, comments, improvement_suggestions, submitted_at | 宴会评价 |
| `banquet_referrals` | referrer_banquet_id, referred_lead_id, referrer_reward_type, referrer_reward_value_fen, status(pending/converted/rewarded) | 转介绍追踪 |

#### Service层 (~4个新Service)

| 服务 | 核心方法 | 行数估算 |
|------|---------|---------|
| `banquet_execution_service.py` | start_execution / checkpoint_complete / handle_delay / escalate / generate_from_sop_template | ~600行 |
| `banquet_live_order_service.py` | request_add_dish / approve / fulfill / notify_kitchen(→KDS) | ~300行 |
| `banquet_settlement_service.py` | generate_settlement / apply_deposit / add_live_charges / finalize / generate_invoice / b2b_monthly_reconcile | ~600行 |
| `banquet_aftercare_service.py` | send_feedback_request / trigger_referral_program / schedule_anniversary_reminder / create_reorder_lead | ~400行 |

#### 事件联动（对接已有系统）

```python
# 宴会执行→KDS
banquet.course.ready_to_serve → kds_production_service.create_tickets()

# 宴会结算→卡券内核
banquet.settled → coupon_kernel_service.issue_coupon(复购券)

# 宴会售后→客户触达SOP
banquet.feedback.collected → customer_journey_service.enroll(宴会复购旅程)

# 宴会转介绍→CRM
banquet.referral.converted → banquet_crm_service.create_lead(referral_source)

# 宴会合规→tx-civic
banquet.execution.started → traceability_service.log_batch_usage()
```

#### API端点 (~25个)

```
/api/v1/banquet/execution/*       — 执行启动+节点打卡+延迟处理 (6)
/api/v1/banquet/live-orders/*     — 现场加菜/酒水+审批+通知厨房 (5)
/api/v1/banquet/settlements/*     — 结算生成+明细+发票+B2B对账 (7)
/api/v1/banquet/feedbacks/*       — 评价收集+分析 (3)
/api/v1/banquet/referrals/*       — 转介绍+奖励+追踪 (4)
```

#### Phase 3 产出统计

| 指标 | 数量 |
|------|------|
| 新迁移 | 4个 (v315-v318) |
| 新表 | 8张 (全部RLS) |
| 新Service | 4个 |
| 新API端点 | ~25个 |
| 预估代码量 | ~3,500行 |

---

### Phase 4: AI宴会大脑 + 经营驾驶舱

> 目标: 用AI让宴会业务从"人驱动"变"AI驱动"

#### 迁移链: v319-v320 (2个迁移, ~4张新表)

**v319: AI决策日志**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_ai_decisions` | banquet_id, agent_type, decision_type(pricing/menu/capacity/scheduling/marketing), input_context_json, recommendation_json, confidence, accepted, operator_feedback | AI决策记录 |
| `banquet_demand_forecasts` | store_id, month, event_type, predicted_count, predicted_revenue_fen, actual_count, actual_revenue_fen, accuracy | 需求预测 |

**v320: 经营看板**

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| `banquet_kpi_snapshots` | store_id, period(daily/weekly/monthly), date, leads_count, conversion_rate, bookings_count, revenue_fen, avg_per_table_fen, avg_guest_count, top_event_type, venue_utilization_rate, customer_satisfaction_avg, repeat_rate | KPI快照 |
| `banquet_competitive_benchmarks` | store_id, period, metric_name, store_value, brand_avg, brand_best, rank, percentile | 跨店对标 |

#### AI Agent (~3个)

| Agent | 职责 | 行数估算 |
|-------|------|---------|
| `banquet_pricing_agent.py` | 智能报价(历史数据+季节+竞对+成本→最优价格), 套餐推荐(客户画像→匹配模板), 利润预测 | ~500行 |
| `banquet_operations_agent.py` | 排产优化(多场并行最优排布), 产能预警(T-3/T-1自动检查), 采购建议(历史损耗率→精准采购量), 人员排班建议 | ~600行 |
| `banquet_growth_agent.py` | 需求预测(按月/按类型), 复购提醒(周年/节庆自动触发), 转介绍激励优化, 流失预警(高价值客户N天未询价) | ~500行 |

#### API端点 (~15个)

```
/api/v1/banquet/ai/pricing/*      — 智能报价+套餐推荐+利润预测 (4)
/api/v1/banquet/ai/operations/*   — 排产优化+产能预警+采购建议 (4)
/api/v1/banquet/ai/growth/*       — 需求预测+复购提醒+流失预警 (4)
/api/v1/banquet/dashboard/*       — KPI看板+对标排名+趋势分析 (3)
```

#### Phase 4 产出统计

| 指标 | 数量 |
|------|------|
| 新迁移 | 2个 (v319-v320) |
| 新表 | 4张 (全部RLS) |
| 新AI Agent | 3个 |
| 新API端点 | ~15个 |
| 预估代码量 | ~2,500行 |

---

## 五、总产出汇总

| 指标 | Phase 1 | Phase 2 | Phase 3 | Phase 4 | **合计** |
|------|---------|---------|---------|---------|---------|
| 迁移 | 5 | 5 | 4 | 2 | **16** |
| 新表 | 12 | 10 | 8 | 4 | **34** |
| Service | 4 | 5 | 4 | 3(Agent) | **16** |
| API端点 | 35 | 30 | 25 | 15 | **105** |
| 代码量 | 4,000 | 5,000 | 3,500 | 2,500 | **~15,000行** |

### 升级后屯象OS总量

| 指标 | 当前 | 升级后 |
|------|------|--------|
| 迁移版本 | v304 | v320 |
| 数据表 | ~200+ | ~234+ |
| API端点 | ~2,153 | ~2,258 |
| AI Agent | 14个 | 17个 |
| 微服务 | 15个 | 15个(不新增) |

---

## 六、预设宴会SOP模板（3套）

### 模板1: 婚宴SOP (标准20桌)

| 时间节点 | 任务 | 责任人 | 检查项 |
|---------|------|--------|--------|
| T-7天 | 菜单终确认 + 原料采购单下发 | 宴会经理 | 过敏原核查 |
| T-3天 | 生鲜食材到货验收 | 厨师长 | 冷链温度记录 |
| T-1天 | 厅房布置 + 设备检查 | 前厅主管 | 音响/投影/灯光 |
| T-1天 | 干货/调料备料完成 | 厨房组长 | BOM清单逐项 |
| 当日-2h | 迎宾台搭建 + 签到准备 | 迎宾员 | 桌牌/引导牌 |
| 当日-1h | 冷菜摆盘 + 酒水到位 | 传菜组 | 每桌核对 |
| 当日+0 | 迎宾 + 宾客引座 | 全员 | VIP优先 |
| 开席+5min | 冷菜上桌(8道) | 传菜员 | 每桌齐上 |
| 开席+20min | 热菜第一轮(4道) | 厨房→传菜 | 出菜间隔5min |
| 开席+40min | 热菜第二轮(4道) | 厨房→传菜 | 观察进度调节 |
| 开席+60min | 主食 + 汤 | 厨房→传菜 | — |
| 开席+70min | 甜品 + 水果 | 厨房→传菜 | — |
| 结束后 | 结算 + 评价收集 | 宴会经理 | 现场加菜核对 |
| T+1天 | 感谢短信 + 照片发送 | 客服 | 私域入群引导 |
| T+7天 | 满意度回访 | 客服 | 转介绍激励 |

### 模板2: 旅游团餐SOP (标准5桌/50人)

| 时间节点 | 任务 | 责任人 |
|---------|------|--------|
| 接单时 | 确认人数/餐标/到店时间/忌口 | 前台 |
| T-1天 | 按餐标配菜 + 备料 | 厨师长 |
| 到店前30min | 桌位摆设 + 茶水 | 服务员 |
| 到店 | 导游对接 + 快速上冷菜 | 前厅主管 |
| 到店+5min | 热菜连续上(限时40min内完成) | 厨房全力出 |
| 离店 | 与旅行社对账签字 | 收银/经理 |
| 月末 | B2B月结 + 发票 | 财务 |

### 模板3: 会议餐SOP (茶歇+工作餐)

| 时间节点 | 任务 | 责任人 |
|---------|------|--------|
| 接单时 | 确认会议时长/茶歇轮次/工作餐标准 | 前台 |
| T-1天 | 茶歇物料采购(咖啡/茶/点心/水果) | 采购 |
| 会前1h | 茶歇台搭建 | 服务员 |
| 会中 | 每2小时补充茶歇 + 清理 | 服务员 |
| 午餐时 | 工作餐准时送达(盒餐/自助/围桌) | 厨房→传菜 |
| 会后 | 结算 + 场地恢复 | 前厅 |

---

## 七、屯象OS差异化壁垒（竞品无法复制）

| 维度 | 屯象OS | 主流竞品 | 壁垒深度 |
|------|--------|---------|---------|
| **AI排产** | 宴会菜单→BOM分解→产能规划→多场并行优化 | 无 | ★★★★★ |
| **全栈数据闭环** | 宴会订单自动驱动采购/库存/排班/财务 | 手工衔接 | ★★★★★ |
| **多方结算** | 定金+加菜+酒水+服务费+B2B月结+发票 | 仅收银 | ★★★★ |
| **合规内建** | 宴会食材自动追溯+明厨亮灶+食安报告 | 无 | ★★★★★ |
| **私域复购** | 宴会→评价→SOP→复购→转介绍 自动化 | 无 | ★★★★ |
| **17个AI Agent** | 报价/排产/增长 + 已有14个Agent联动 | 无 | ★★★★★ |
| **费控集成** | 会议餐/团建差旅自动关联费控审批 | 无 | ★★★★ |

---

## 八、风险与约束

| 风险 | 应对策略 |
|------|---------|
| 单人开发周期长 | 按Phase严格分期，每Phase独立可用 |
| 宴会场景多样(婚/寿/商/旅/会) | 模板化+JSON配置灵活扩展，不硬编码 |
| 与现有桌台系统耦合 | 宴会桌组通过table_ids_json软关联，不改现有表结构 |
| 排产引擎复杂度高 | Phase 2先做单场排产，Phase 4再做AI多场优化 |
| 前端工作量大 | 后端API先行，前端按需逐步开发 |
| 密钥/凭证安全 | 遵循现有规范：环境变量/KMS，不硬编码 |
