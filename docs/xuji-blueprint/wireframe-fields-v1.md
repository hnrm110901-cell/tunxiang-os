下面直接给你定版稿。





# **《屯象OS × 徐记海鲜 6个P0核心页面低保真线框说明 + 字段明细 V1》**





这 6 个 P0 页面，不是“先把界面做全”，而是围绕徐记样板 Year 1 最该先证明的四个必赢点来定：**折扣守护、订单/菜品毛利穿透、桌台/出餐效率看板、财务稽核初版**；同时先跑通交易最小闭环：**点单、收银、打印、KDS、券核销、称重菜改价**。这和你现有方案里的 P0 优先级、八大产品域、六大核心实体，以及三条硬约束是一致的。   



我下面按 6 个页面逐页给你：



1. 页面定位
2. 低保真线框说明
3. 区块字段明细
4. 主交互与状态
5. 权限与异常点





------





# **一、P0 核心页面范围**





建议这 6 个页面定为：



1. 桌台/包厢总览页
2. 开台点单页
3. 收银结账台
4. KDS 出餐总看板
5. 日清日结巡航页
6. 总部经营驾驶舱





原因很明确：这 6 页刚好覆盖“门店现场交易、后厨出餐、门店执行、总部穿透”四条主链，也是屯象OS与通用 SaaS 拉开差异的最短路径。徐记海鲜这种高复杂直营正餐集团，关键不在功能多少，而在能否处理复杂交易、桌台包厢、称重活鲜、损耗、总部整改闭环。  



------





# **1）桌台/包厢总览页**







## **1.1 页面定位**





门店交易前台的第一核心页。

负责实时桌态、包厢调度、入座开台、转台并台、翻台监控。

它承接的是交易履约域中的“预订迎宾、桌台包厢、服务员移动作业”等能力，也是 Store 实体里“桌台拓扑、档口、人效、翻台诊断”的前台表达。  





## **1.2 低保真线框说明**



```
┌──────────────────────────────────────────────┐
│ 顶部栏：门店/楼层/区域/班次/时间/网络/同步/用户   │
├──────────────────────────────────────────────┤
│ 筛选栏：区域 | 散台/包厢 | 状态 | 服务员 | 搜索桌号 │
├──────────────────────────────────────────────┤
│ 左侧主画布：桌台地图 / 包厢卡片                    │
│ [A01 空台] [A02 预留] [A03 用餐中] [VIP1 包厢]    │
│ [B01 待清台] [B02 待结账] [B03 锁台] [VIP2 预订]  │
├───────────────────────┬──────────────────────┤
│ 底部统计条              │ 右侧详情抽屉           │
│ 空台数/在店桌数/待结账数 │ 桌台基本信息           │
│ 预订数/翻台率/超时桌次   │ 当前订单/人数/时长     │
│                         │ 快捷动作：开台/转台等  │
└───────────────────────┴──────────────────────┘
```



## **1.3 区块字段明细**







### **A. 顶部栏字段**





- store_id 门店ID
- store_name 门店名称
- business_date 营业日期
- shift_code 班次
- current_time 当前时间
- network_status 网络状态
- sync_status 同步状态
- user_id 当前用户
- user_role 当前角色







### **B. 筛选栏字段**





- floor_id 楼层
- zone_id 区域
- table_type 桌台类型：散台/包厢
- table_status 桌台状态
- waiter_id 服务员
- table_keyword 桌号/包厢名搜索







### **C. 桌台卡片字段**





- table_id
- table_code
- table_name
- capacity
- min_spend 包厢低消
- status
- reservation_flag
- reservation_time
- current_order_id
- guest_count
- service_staff
- open_time
- dining_duration_min
- dish_progress
- pending_checkout_flag
- abnormal_flag
- vip_flag







### **D. 右侧详情抽屉字段**





- table_id
- table_name
- current_status
- current_customer_name
- current_customer_tag
- guest_count
- assigned_waiter
- open_timestamp
- expected_turnover_time
- current_amount
- pending_dishes_count
- urge_count
- complaint_count
- remark
- action_permissions







### **E. 底部统计字段**





- empty_table_count
- occupied_table_count
- reserved_table_count
- pending_checkout_count
- waiting_cleanup_count
- turnover_rate
- overdue_table_count







## **1.4 主交互与状态**





主状态建议固定为：



- 空台
- 已预留
- 待入座
- 用餐中
- 待结账
- 待清台
- 锁台
- 维修/停用





主操作：



- 开台
- 分配桌台
- 转台
- 并台
- 拆台
- 锁台
- 清台
- 查看订单







## **1.5 权限与异常点**





- 服务员可查看本人桌台，可发起转台申请
- 店长可强制转台、锁台、修改桌态
- 包厢冲突时必须给出替代推荐
- 若桌台关联订单存在未结账，不允许直接清台
- 出餐超时桌台卡片需红点提醒，强化“客户体验上限”这条硬约束。 





------





# **2）开台点单页**







## **2.1 页面定位**





门店交易最核心页面。

负责点菜、加菜、退菜、称重菜、赠菜、折扣、催菜、拆单。

它直接承接 Order、Dish、Ingredient 三类实体关系，以及交易履约域、商品与菜单域、财务与结算域的交汇点。  





## **2.2 低保真线框说明**



```
┌──────────────────────────────────────────────┐
│ 订单头：桌号/包厢/人数/服务员/客户标签/开台时长     │
├───────────────┬──────────────────────────────┤
│ 左：菜品分类树  │ 中：菜品列表区                  │
│ 冷菜/热菜/海鲜  │ 菜品卡：图/名/价/标签/沽清状态   │
│ 酒水/主食/套餐  │ 搜索/推荐/最近点/招牌/高毛利     │
├───────────────┴──────────────┬───────────────┤
│ 底部快捷规格栏/做法/口味/备注     │ 右：订单购物车区      │
│                                  │ 已选菜/数量/称重/小计 │
│                                  │ 已下单/未下单分层     │
├─────────────────────────────────┴───────────────┤
│ 底部操作：发送后厨 | 加菜 | 退菜 | 赠菜 | 折扣 | 结账 │
└──────────────────────────────────────────────┘
```



## **2.3 区块字段明细**







### **A. 订单头字段**





- order_id
- order_no
- table_id
- table_name
- room_flag
- guest_count
- waiter_id
- waiter_name
- customer_id
- customer_name
- customer_level
- customer_tag
- open_time
- dining_duration_min
- order_status







### **B. 菜品分类字段**





- category_id
- category_name
- category_sort
- parent_category_id







### **C. 菜品卡字段**





- dish_id
- dish_name
- dish_code
- dish_image
- dish_price
- current_price
- pricing_mode 固定价/时价/称重
- recommended_flag
- signature_flag
- high_margin_flag
- stock_status
- sold_out_flag
- estimated_wait_time
- station_id
- taste_options
- cook_method_options







### **D. 订单行字段**





- order_item_id
- dish_id
- dish_name
- quantity
- unit
- weight_value
- weight_unit
- unit_price
- line_amount
- taste_value
- cook_method
- remark
- sent_to_kds_flag
- served_flag
- gift_flag
- return_flag
- discount_flag
- approval_status







### **E. 折扣区字段**





- discount_type 整单/单品/券/协议价
- discount_value
- discount_amount
- gross_margin_before
- gross_margin_after
- margin_alert_flag
- approver_id
- approval_reason
- approval_result







### **F. 退菜字段**





- return_reason_code
- return_reason_name
- return_qty
- return_amount
- return_operator_id
- return_approval_required
- return_approval_status







### **G. 时价称重字段**





- weight_input
- weight_price
- processing_method
- estimated_cost
- estimated_margin
- pricing_confirm_user







## **2.4 主交互与状态**





主流程：



- 选桌开台
- 选菜加入订单
- 规格/口味/做法确认
- 发送后厨
- 加菜/退菜/催菜
- 折扣/挂账前预览
- 跳转结账





订单状态建议：



- 草稿
- 已下单
- 制作中
- 部分上菜
- 已上齐
- 待结账
- 已结账







## **2.5 权限与异常点**





- 时价称重必须记录重量、单价、加工方式
- 毛利跌破阈值时禁止直接提交折扣，这是三条硬约束之一。 
- 沽清菜禁止下单，改为推荐替代菜
- 已出餐退菜默认需店长审批
- 高峰期若档口负载过高，可展示预计出餐时长，呼应出餐调度 Agent。 





------





# **3）收银结账台**







## **3.1 页面定位**





交易闭环最后一公里。

负责账单确认、券核销、储值/权益抵扣、企业挂账、混合支付、退款反结账。

它直接对应财务与结算域中的账单、支付、券核销、企业账户、收银交接、对账稽核。 





## **3.2 低保真线框说明**



```
┌──────────────────────────────────────────────┐
│ 结账头：订单号/桌号/客户/服务员/开台时长/应收金额   │
├───────────────────────┬──────────────────────┤
│ 左：账单明细区          │ 右：支付与抵扣区       │
│ 菜品明细                │ 支付方式               │
│ 服务费/包厢费           │ 现金/扫码/银行卡       │
│ 折扣/券/抹零            │ 储值/权益/挂账         │
│ 应收/已收/待收          │ 混合支付明细           │
├───────────────────────┴──────────────────────┤
│ 底部操作：试算 | 核销券 | 企业挂账 | 确认收款 | 打印 │
└──────────────────────────────────────────────┘
```



## **3.3 区块字段明细**







### **A. 结账头字段**





- order_id
- order_no
- table_name
- customer_id
- customer_name
- member_level
- waiter_name
- open_time
- payable_amount
- paid_amount
- remaining_amount







### **B. 账单明细字段**





- bill_item_id
- bill_item_type 菜品/服务费/包厢费/折扣/券/抹零
- item_name
- qty
- amount
- tax_flag
- remark







### **C. 支付字段**





- payment_method
- payment_channel
- payment_amount
- payment_status
- payment_reference_no
- cash_received
- change_amount







### **D. 券与权益字段**





- coupon_id
- coupon_name
- coupon_type
- coupon_threshold
- coupon_discount_amount
- coupon_conflict_flag
- stored_value_balance
- benefit_package_id
- benefit_deduction_amount







### **E. 企业挂账字段**





- corporate_account_id
- corporate_name
- credit_limit
- used_credit_amount
- available_credit_amount
- authorized_signer
- signer_id
- corporate_price_rule
- hang_account_approval_flag







### **F. 打印与票据字段**





- receipt_type
- print_times
- invoice_required_flag
- tax_device_status







## **3.4 主交互与状态**





- 试算
- 核销券
- 储值抵扣
- 企业挂账
- 混合支付
- 确认收款
- 小票打印
- 退款/反结账





支付状态建议：



- 待支付
- 部分支付
- 已支付
- 挂账中
- 已退款
- 反结账中







## **3.5 权限与异常点**





- 券冲突必须即时拦截
- 企业挂账超额度禁止结账
- 反结账仅店长以上
- 收款异常需写入交班差异池，便于财务稽核 Agent 后续处理。 
- 税控与银联刷卡要走安卓生态，符合你现有混合架构假设。 





------





# **4）KDS 出餐总看板**







## **4.1 页面定位**





后厨档口执行核心页。

负责待制作、制作中、异常卡单、加急、重做、缺料、超时。

它是交易履约域里的 KDS 出餐能力，也是出餐调度 Agent 的主要落点。  





## **4.2 低保真线框说明**



```
┌──────────────────────────────────────────────┐
│ 顶部栏：档口/时段/总票数/超时数/缺料数/同步状态     │
├──────────────────┬──────────────────┬────────┤
│ 左：待制作队列     │ 中：制作中队列     │ 右：异常队列 │
│ 桌号/菜品/下单时间  │ 开始时间/剩余预测   │ 超时/缺料/重做 │
│ 数量/口味/优先级    │ 档口/厨师          │ 原因/处理动作  │
├──────────────────────────────────────────────┤
│ 底部快捷操作：开始 | 完成 | 加急 | 缺料 | 重做 | 备注 │
└──────────────────────────────────────────────┘
```



## **4.3 区块字段明细**







### **A. 顶部汇总字段**





- station_id
- station_name
- service_period
- total_ticket_count
- pending_ticket_count
- in_progress_ticket_count
- overtime_ticket_count
- stockout_ticket_count
- sync_status







### **B. 任务卡字段**





- ticket_id
- order_id
- table_name
- dish_id
- dish_name
- qty
- taste_value
- remark
- priority_level
- created_time
- start_time
- expected_finish_time
- elapsed_time
- station_name
- chef_name
- status







### **C. 异常字段**





- abnormal_type 超时/缺料/重做/阻塞
- abnormal_reason
- reported_by
- reported_time
- frontdesk_notified_flag
- replacement_suggestion_flag







### **D. 操作日志字段**





- action_name
- operator_id
- operation_time
- operation_result







## **4.4 主交互与状态**





任务状态建议：



- 待制作
- 制作中
- 已完成
- 已上菜
- 超时
- 缺料阻塞
- 重做中





主操作：



- 接单开始
- 出餐完成
- 标记加急
- 上报缺料
- 发起重做







## **4.5 权限与异常点**





- 厨师长可重排优先级
- 普通档口只可操作所属票据
- 超时票据自动进入异常列
- 缺料必须同步前厅，不可只在后厨关闭
- 页面要尽量少输入，符合安卓平板/KDS 使用环境，也与你的硬件路线一致。 





------





# **5）日清日结巡航页**







## **5.1 页面定位**





店长/值班经理的营业执行页。

负责从开店准备、营业巡航、高峰值守，到闭店盘点、异常转任务。

它对应组织与运营协同域中的巡店整改、工单，以及门店日清日结管理目标。 





## **5.2 低保真线框说明**



```
┌──────────────────────────────────────────────┐
│ 巡航头：门店/班次/当前阶段/完成率/异常数/责任人      │
├───────────────────────┬──────────────────────┤
│ 左：流程节点时间轴      │ 右：当前节点详情区       │
│ 开店准备                │ 检查项列表               │
│ 营业巡航                │ 填报结果/图片/备注       │
│ 高峰值守                │ 转异常/指派整改          │
│ 闭店盘点                │ 提交确认                 │
├───────────────────────┴──────────────────────┤
│ 底部：异常汇总 | 待整改 | 历史记录 | 店长签字         │
└──────────────────────────────────────────────┘
```



## **5.3 区块字段明细**







### **A. 巡航头字段**





- store_id
- store_name
- shift_code
- current_stage
- stage_progress
- abnormal_count
- duty_manager_id
- duty_manager_name







### **B. 流程节点字段**





- node_id
- node_name
- node_type
- planned_start_time
- planned_end_time
- actual_start_time
- actual_end_time
- node_status
- responsible_role







### **C. 检查项字段**





- check_item_id
- check_item_name
- check_item_type
- check_result
- check_score
- photo_required_flag
- photo_urls
- remark
- operator_id
- checked_time







### **D. 异常转任务字段**





- issue_id
- issue_type
- issue_level
- issue_desc
- assignee_id
- deadline_time
- follow_status
- escalation_flag







### **E. 盘点与闭店字段**





- inventory_task_id
- inventory_category
- theoretical_qty
- actual_qty
- variance_qty
- variance_amount
- closing_confirm_flag
- manager_sign_flag







## **5.4 主交互与状态**





节点状态建议：



- 未开始
- 进行中
- 已完成
- 异常待处理
- 已闭环





主操作：



- 填写检查结果
- 上传图片
- 转异常
- 指派整改
- 提交节点
- 店长签字







## **5.5 权限与异常点**





- 店员可填报，店长可审核
- 区域经理可查看、追踪整改
- 高峰节点到时未完成需提醒
- 关键异常可升级区域
- 这页本质上把“看见问题”变成“有人处理”，呼应你路线图里“发现问题—触发动作—跟踪执行—复盘”的闭环能力。 





------





# **6）总部经营驾驶舱**







## **6.1 页面定位**





总部/区域管理入口。

负责发现异常门店、异常菜品、损耗问题、整改进度。

它对应经营分析与决策域中的驾驶舱、门店分析、菜品分析、财务分析、库存成本、预警复盘。 





## **6.2 低保真线框说明**



```
┌──────────────────────────────────────────────┐
│ 顶部筛选：日期/品牌/区域/门店类型/午晚市/指标口径    │
├──────────────────────────────────────────────┤
│ 第一行：核心指标卡                             │
│ 营收 | 翻台率 | 毛利率 | 损耗率 | 客诉率 | 闭环率   │
├───────────────────────┬──────────────────────┤
│ 第二行左：排行榜         │ 第二行右：异常榜        │
│ 门店排行/区域排行        │ 折扣异常/损耗异常/超时  │
├───────────────────────┴──────────────────────┤
│ 第三行：整改与预警区                           │
│ 待处理预警 | 高风险门店 | 未闭环门店 | 责任人       │
├──────────────────────────────────────────────┤
│ 底部：趋势图/下钻入口/门店详情跳转              │
└──────────────────────────────────────────────┘
```



## **6.3 区块字段明细**







### **A. 顶部筛选字段**





- brand_id
- region_id
- store_id
- store_type
- business_date_range
- service_period
- metric_caliber







### **B. 核心指标字段**





- revenue_amount
- revenue_yoy
- turnover_rate
- gross_margin_rate
- loss_rate
- complaint_rate
- rectification_close_rate







### **C. 排行字段**





- rank_type
- rank_target_id
- rank_target_name
- rank_metric_name
- rank_metric_value
- rank_trend
- rank_tag







### **D. 异常字段**





- alert_id
- alert_type
- alert_level
- store_name
- region_name
- related_metric
- responsible_person
- deadline_time
- close_status







### **E. 整改字段**





- task_id
- issue_type
- issue_source
- assignee_name
- created_time
- due_time
- task_status
- review_result







## **6.4 主交互与状态**





主操作：



- 指标下钻
- 查看门店详情
- 跳转整改任务
- 查看异常列表
- 按区域筛选







## **6.5 权限与异常点**





- 区域经理默认只看本区域
- 总部运营看全部品牌/区域
- 高风险门店必须显示责任人和截止时间
- 首页不放过细流水，先放“哪里有问题”，符合你对“先讲结果，不先讲技术”的对外表达原则。 





------





# **二、6页共用字段规范建议**





为了后面做表结构、DTO、埋点和权限，我建议你把这几类字段统一：





## **2.1 通用审计字段**





- id
- created_at
- updated_at
- created_by
- updated_by
- tenant_id
- brand_id
- store_id
- is_deleted







## **2.2 状态字段统一规范**





- status
- sub_status
- abnormal_flag
- approval_status
- sync_status







## **2.3 人员字段统一规范**





- operator_id
- operator_name
- responsible_id
- responsible_name
- approver_id
- approver_name







## **2.4 金额字段统一规范**





- original_amount
- discount_amount
- payable_amount
- paid_amount
- refund_amount
- margin_amount
- margin_rate





这会让后续交易、财务、分析、Agent 都更容易共用同一语义层，也更贴合六大核心实体的统一本体设计。 



------





# **三、6页对应的接口分组建议**





为了后面前后端好接，我建议先这样分：



- 桌台/包厢总览页 → table-service
- 开台点单页 → order-service
- 收银结账台 → cashier-service
- KDS 出餐总看板 → kds-service
- 日清日结巡航页 → ops-service
- 总部经营驾驶舱 → analytics-service





这样也和你“云端后台 + 门店本地 FastAPI + React 多端”的技术栈更吻合。 



------





# **四、最终定版建议**





这份 V1 不是视觉稿，而是你后面所有产出的“结构母版”：



- 可以直接往下做 Figma 低保真
- 可以直接拆 React 页面骨架
- 可以直接倒推接口字段
- 可以直接做权限矩阵
- 可以直接做门店试点培训





最关键的是，这 6 页已经把屯象OS × 徐记海鲜最重要的样板价值钉住了：



- 桌台经营
- 点单与称重
- 收银与挂账
- KDS 出餐调度
- 日清日结执行
- 总部异常穿透





下一步最适合继续往下做的是：

**《屯象OS × 徐记海鲜 6个P0核心页面 React 组件拆分清单 + Props 字段定义 V1》**