下面直接给你定版稿。





# **《屯象OS × 徐记海鲜 页面清单 + 路由规划 V1》**





这版不是简单把 IA 再展开一层，而是要直接服务三件事：

第一，指导前端工程拆分；

第二，指导后端接口与权限边界；

第三，指导徐记海鲜样板店的分阶段上线。



我会按你当前的实际技术形态来设计：**一套 React Web App 多端运行**，终端包括安卓 POS、安卓 KDS、服务员手机 PWA、总部 Web，以及可选的 iPad 壳层；同时项目结构里已经拆出 web-pos / web-kds / web-crew / web-admin / miniapp-customer 等应用，因此页面与路由应按“应用边界 + 角色边界 + 经营闭环”来规划，而不是做成一套巨型后台。  



另外，这版路由规划会继续围绕你最该先证明的四个结果来收敛：**少亏折扣、少亏损耗、更快出餐与翻台、总部看清门店**，并优先覆盖 Year 1 要先打透的交易最小闭环、主数据治理、折扣守护、桌台/出餐效率看板与财务稽核初版。  



------





## **一、页面规划总原则**







### **1）按应用拆，而不是按全部功能堆在一个后台**





建议正式拆成 6 个前端应用：



- web-pos：门店交易前台
- web-kds：后厨出餐前台
- web-crew：店员/店长移动端 PWA
- web-admin：总部/区域/配置后台
- miniapp-customer：顾客端小程序
- shell：安卓 POS / iPad 壳层承载，不承载业务页面





这和你现有项目结构、终端形态、外设桥接方式是一致的。  





### **2）路由分三层**





每个应用都建议按三层路由组织：



- 一级：业务域
- 二级：页面
- 三级：详情页 / 抽屉页 / 子工作流







### **3）先做“高频闭环页面”，再做“完整管理页面”**





Phase 1 你已经明确要先跑通安卓 POS + Mac mini 并行运行、折扣守护和交易 MVP，因此页面优先级必须严格偏向：开台、点菜、出餐、结账、交班、巡航、复盘，而不是先做大而全后台。 



------





# **二、前端应用总表**







## **A. web-pos（门店交易前台）**





面向：迎宾、服务员、收银、店长

运行：安卓 POS WebView / iPad WKWebView 可选 / 浏览器兼容 





## **B. web-kds（后厨出餐前台）**





面向：档口、厨师长、传菜

运行：安卓 KDS 平板 / 浏览器 





## **C. web-crew（店员移动端）**





面向：服务员、迎宾、店长、巡店人员

运行：PWA / 手机浏览器 





## **D. web-admin（总部管理后台）**





面向：总部运营、区域经理、财务、商品、供应链、配置管理员

运行：Chrome / Safari 浏览器 





## **E. miniapp-customer（顾客端）**





面向：顾客、企业订餐客户

运行：微信 / 抖音小程序 



------





# **三、页面清单 + 路由规划 V1**





下面按应用给你出可直接给前端、产品、后端对齐的版本。



------





# **1. web-pos 页面清单 + 路由规划**





这是徐记海鲜样板项目的核心应用。它要覆盖你文档里 Year 1 的“交易最小闭环”：**点单、收银、打印、KDS、券核销、称重菜改价**。 





## **1.1 一级路由结构**



```
/pos
  /dashboard
  /reservations
  /floor
  /orders
  /cashier
  /handover
  /exceptions
  /settings-lite
```



------





## **1.2 页面清单**







### **/pos/dashboard**

###  **门店工作台**





用途：POS 默认首页，按角色显示待办与营业快照。

核心卡片：



- 待到店预订
- 当前桌台占用
- 待出餐超时
- 待结账单
- 折扣异常提醒





这是为了把“少亏折扣、快出餐、快翻台”直接前置到首页。 





### **/pos/reservations**

###  **预订台账**





二级子页：



- /pos/reservations/list 预订列表
- /pos/reservations/new 新建预订
- /pos/reservations/:id 预订详情
- /pos/reservations/:id/edit 修改预订
- /pos/reservations/queue 排队叫号





对应预订、排号、到店签到、候位跟进链路。





### **/pos/floor**

###  **桌台与包厢总览**





二级子页：



- /pos/floor/map 桌台地图
- /pos/floor/rooms 包厢总览
- /pos/floor/:tableId 桌台详情
- /pos/floor/:tableId/seat 入座开台
- /pos/floor/:tableId/transfer 转台并台拆台
- /pos/floor/:tableId/cleanup 清台待客





这个页面是正餐区别于标准快餐 SaaS 的关键入口。





### **/pos/orders**

###  **点单与订单中心**





二级子页：



- /pos/orders/open 开台点单
- /pos/orders/:orderId 订单详情
- /pos/orders/:orderId/items 菜品明细
- /pos/orders/:orderId/weight 时价称重
- /pos/orders/:orderId/discount 折扣改价
- /pos/orders/:orderId/gift 赠菜补送
- /pos/orders/:orderId/return 退菜退单
- /pos/orders/:orderId/split 分单拆单并单
- /pos/orders/:orderId/urge 催菜起菜





这里要把称重菜改价、折扣守护、加退菜都嵌进订单详情，而不是散落到多个后台页面。文档里已把称重菜改价、折扣守护、订单/菜品毛利穿透列为早期关键点。  





### **/pos/cashier**

###  **收银与结算中心**





二级子页：



- /pos/cashier/pending 待结账单
- /pos/cashier/:orderId 收银台
- /pos/cashier/:orderId/pay 支付方式选择
- /pos/cashier/:orderId/coupon 券核销
- /pos/cashier/:orderId/member 会员/储值抵扣
- /pos/cashier/:orderId/corporate 企业挂账
- /pos/cashier/:orderId/refund 退款反结账
- /pos/cashier/:orderId/receipt 小票与票据





这块直接承接财务与结算域中的账单、支付、券核销、企业账户、收银交接。 





### **/pos/handover**

###  **收银交班**





二级子页：



- /pos/handover/current 当前班次
- /pos/handover/reconcile 班次对账
- /pos/handover/cash-diff 长短款登记
- /pos/handover/channel-check 支付渠道核对
- /pos/handover/submit 提交交班
- /pos/handover/history 交班记录







### **/pos/exceptions**

###  **异常中心**





二级子页：



- /pos/exceptions/discount 折扣异常
- /pos/exceptions/payment 收银异常
- /pos/exceptions/returns 退菜异常
- /pos/exceptions/stockout 缺料断货
- /pos/exceptions/service 客诉异常







### **/pos/settings-lite**

###  **轻配置**





仅门店级、低频、少量配置：



- 默认打印机
- 默认收银台
- 本班次参数
- 快捷菜设置
- 本店桌台视图偏好





------





## **1.3 web-pos 建议页面数量**





建议首版：



- P0 必做主页面 12 个
- 子工作流页面 28 个
- 合计约 40 个路由节点





这已经足够支撑徐记样板的交易 MVP，而不会过早膨胀。



------





# **2. web-kds 页面清单 + 路由规划**





KDS 是你证明“更快出餐与翻台”的关键，文档里已把出餐调度 Agent、KDS 智能排序、出餐时间预测、超时预警列为重点能力。 





## **2.1 一级路由结构**



```
/kds
  /board
  /stations
  /tickets
  /alerts
  /stats
```



## **2.2 页面清单**







### **/kds/board**

###  **出餐总看板**





- 全部出餐任务
- 超时预警
- 档口负载
- 加急任务
- 缺料卡单







### **/kds/stations**

###  **档口工作台**





- /kds/stations/:stationId 档口详情
- /kds/stations/:stationId/queue 档口队列
- /kds/stations/:stationId/history 档口历史







### **/kds/tickets**

###  **出餐任务单**





- /kds/tickets/:ticketId 任务详情
- /kds/tickets/:ticketId/start 开始制作
- /kds/tickets/:ticketId/done 出餐完成
- /kds/tickets/:ticketId/remake 重做返工
- /kds/tickets/:ticketId/block 缺料卡单







### **/kds/alerts**

###  **预警中心**





- 出餐超时
- 队列拥堵
- 重做异常
- 缺料异常







### **/kds/stats**

###  **当班统计**





- 档口出餐数
- 平均出餐时长
- 超时率
- 重做率





------





# **3. web-crew 页面清单 + 路由规划**





这个应用承接“服务员手机 PWA/浏览器访问”，适合移动轻操作、高频协同。 





## **3.1 一级路由结构**



```
/crew
  /home
  /tasks
  /service
  /daily
  /review
  /profile
```



## **3.2 页面清单**







### **/crew/home**

###  **我的工作台**





- 当班任务
- 当前服务桌
- 待催菜
- 待处理客诉
- 当班提醒







### **/crew/tasks**

###  **任务中心**





- /crew/tasks/today 今日任务
- /crew/tasks/:taskId 任务详情
- /crew/tasks/abnormal 异常任务
- /crew/tasks/history 历史任务





这里要承接 Agent 发现问题后的任务流转。文档里明确提出“发现问题，不只看报表，还要触发动作、跟踪执行、复盘”。 





### **/crew/service**

###  **服务动作**





- /crew/service/tables 我的桌台
- /crew/service/:tableId 桌台服务详情
- /crew/service/:tableId/order 快速加菜
- /crew/service/:tableId/urge 催菜
- /crew/service/:tableId/complaint 客诉登记
- /crew/service/:tableId/clear 清台确认







### **/crew/daily**

###  **日清日结**





- /crew/daily/opening 开店准备
- /crew/daily/cruise 营业巡航
- /crew/daily/peak 高峰值守
- /crew/daily/closing 闭店检查
- /crew/daily/inventory 盘点填报
- /crew/daily/handover 交班确认





这部分直接承接你当前正在推动的“开店—营业—闭店标准业务流程节点管理、日清日结”。 





### **/crew/review**

###  **复盘与整改**





- /crew/review/store 门店复盘
- /crew/review/issues 问题清单
- /crew/review/rectify/:id 整改详情
- /crew/review/compare 跨店对标







### **/crew/profile**

###  **我的**





- 我的班次
- 绩效简报
- 操作日志
- 培训任务





------





# **4. web-admin 页面清单 + 路由规划**





这是总部/区域/配置后台，建议严格按 6 大经营中心来组织，兼容你之前定的 IA。它还要承接八大业务域、64 个二级模块，以及总部 Web 不依赖 Apple 设备的使用方式。  





## **4.1 一级路由总览**



```
/admin
  /dashboard
  /trade
  /catalog
  /supply
  /operations
  /crm
  /analytics
  /org
  /agent
  /system
```



------





## **4.2 一级模块与核心二级路由**







### **/admin/dashboard**

###  **总部驾驶舱**





- /admin/dashboard/overview 今日总览
- /admin/dashboard/regions 区域总览
- /admin/dashboard/stores 门店排行
- /admin/dashboard/alerts 异常摘要
- /admin/dashboard/targets 目标达成
- /admin/dashboard/health 经营健康度







### **/admin/trade**

###  **交易经营**





- /admin/trade/reservations 预订分析
- /admin/trade/tables 桌台分析
- /admin/trade/orders 订单中心
- /admin/trade/cashier 收银结算
- /admin/trade/corporate 企业挂账
- /admin/trade/audit 稽核中心







### **/admin/catalog**

###  **商品与菜单**





- /admin/catalog/dishes 菜品档案
- /admin/catalog/menus 菜单模板
- /admin/catalog/bom BOM 配方
- /admin/catalog/process 工艺卡
- /admin/catalog/pricing 定价中心
- /admin/catalog/seasonal 季节菜单
- /admin/catalog/banquet 宴席套餐





这里直接对齐商品与菜单域中的菜品档案、菜单模板、定价发布、BOM、套餐宴席、沽清、菜品分析、AI 优化。 





### **/admin/supply**

###  **供应链与成本**





- /admin/supply/ingredients 原料主数据
- /admin/supply/inventory 库存批次
- /admin/supply/purchase 请购采购
- /admin/supply/receiving 收货验收
- /admin/supply/transfer 调拨中心
- /admin/supply/issue 领料扣料
- /admin/supply/count 盘点中心
- /admin/supply/loss 损耗归因
- /admin/supply/cost 成本核算
- /admin/supply/foodsafety 食安追溯





这与供应链与成本域的八个模块完全对应。 





### **/admin/operations**

###  **日清日结与运营协同**





- /admin/operations/opening 开店管理
- /admin/operations/cruise 营业巡航
- /admin/operations/peak 高峰值守
- /admin/operations/closing 闭店盘点
- /admin/operations/review 店长复盘
- /admin/operations/inspection 巡店整改
- /admin/operations/workorders 工单中心
- /admin/operations/templates SOP 模板





这里承接组织与运营协同域中的巡店整改、工单等能力。 





### **/admin/crm**

###  **客户经营**





- /admin/crm/customers 客户主档
- /admin/crm/golden-id 身份合并
- /admin/crm/members 会员等级
- /admin/crm/benefits 权益卡储值
- /admin/crm/cards 实体卡
- /admin/crm/coupons 活动券
- /admin/crm/scrm SCRM 触达
- /admin/crm/rfm RFM 洞察
- /admin/crm/ai AI 会员建议





对应会员与客户经营域的 8 个模块。 





### **/admin/analytics**

###  **经营分析**





- /admin/analytics/store 门店分析
- /admin/analytics/dish 菜品分析
- /admin/analytics/member 会员分析
- /admin/analytics/finance 财务分析
- /admin/analytics/cost 库存成本
- /admin/analytics/nlq 自然语言问数
- /admin/analytics/alerts 预警中心
- /admin/analytics/review 复盘中心





这与经营分析与决策域直接对应。 





### **/admin/org**

###  **组织与权限**





- /admin/org/structure 组织架构
- /admin/org/roles 角色权限
- /admin/org/onboarding 入驻激活
- /admin/org/performance 提成绩效
- /admin/org/service-fee 服务费规则
- /admin/org/checkout-template 结账模板







### **/admin/agent**

###  **Agent OS 与策略**





- /admin/agent/registry Agent 注册
- /admin/agent/orchestration 编排中心
- /admin/agent/rules 规则策略
- /admin/agent/models 模型服务
- /admin/agent/knowledge 知识库
- /admin/agent/tasks 任务联动
- /admin/agent/audit AI 审计
- /admin/agent/monitoring 监控告警





这与 Agent OS 与智能编排域完全对应。 





### **/admin/system**

###  **系统与接口**





- /admin/system/devices 门店与设备
- /admin/system/adapters Adapter 管理
- /admin/system/payments 支付渠道
- /admin/system/tax 税控票据
- /admin/system/sync 同步任务
- /admin/system/logs 审计与日志





这块要显式保留“旧系统替换能力”和 Adapter 管理，因为你要逐步接管 POS、会员、供应链、巡店、HR、OA 等旧系统。 



------





# **5. miniapp-customer 页面清单 + 路由规划**





你文档里已明确小程序主要承担：**顾客点餐、大厨到家、企业订餐**。 





## **5.1 一级路由结构**



```
/mp
  /home
  /booking
  /queue
  /order
  /member
  /coupons
  /corporate
  /profile
```



## **5.2 页面清单**







### **/mp/home**

###  **首页**





- 品牌首页
- 当前门店
- 推荐菜
- 活动信息
- 快捷入口







### **/mp/booking**

###  **预订**





- 新建预订
- 选择门店
- 选择包厢/人数
- 预订详情
- 我的预订







### **/mp/queue**

###  **排队**





- 在线取号
- 排队进度
- 到店提醒







### **/mp/order**

###  **点餐**





- 菜单浏览
- 菜品详情
- 购物车
- 提交订单
- 支付结果







### **/mp/member**

###  **会员中心**





- 会员等级
- 成长值
- 储值
- 权益包







### **/mp/coupons**

###  **券包**





- 我的券
- 券详情
- 使用记录







### **/mp/corporate**

###  **企业订餐**





- 企业账户
- 协议价
- 企业订单
- 月结记录







### **/mp/profile**

###  **我的**





- 个人资料
- 偏好与禁忌
- 消费记录
- 售后反馈





------





# **四、跨应用统一详情路由规范**





为了后续工程一致性，我建议统一详情页命名：



- 列表页：/xxx
- 新建页：/xxx/new
- 详情页：/xxx/:id
- 编辑页：/xxx/:id/edit
- 子动作页：/xxx/:id/action-name





例如：



- /admin/catalog/dishes/123
- /admin/catalog/dishes/123/edit
- /pos/orders/456/discount
- /kds/tickets/789/remake





这样前后端、测试、埋点、权限都更好对齐。



------





# **五、页面优先级分期建议**







## **P0：徐记样板首发必做**





聚焦交易最小闭环与四个必赢点。 



建议先上：



- web-pos：dashboard / floor / orders / cashier / handover
- web-kds：board / tickets / alerts
- web-crew：home / daily / tasks
- web-admin：dashboard / trade/orders / analytics/store / analytics/finance / agent/rules
- miniapp：booking / member / coupons







## **P1：形成总部穿透**





建议补：



- 商品与菜单
- 供应链与成本
- 巡店整改
- 客户分析
- 预警中心
- 复盘中心







## **P2：形成模板复制**





建议补：



- 企业客户
- SCRM 触达
- AI 会员
- NLP 问数
- 全量 Agent 配置
- 高级配置与多品牌能力





------





# **六、路由与权限矩阵建议**





建议在代码里把权限分成 5 层：



- store_clerk
- store_manager
- regional_manager
- hq_operator
- hq_admin





例如：



- /pos/cashier/:orderId/refund：store_manager 以上
- /admin/supply/cost：hq_operator 以上
- /admin/agent/models：hq_admin
- /admin/system/adapters：hq_admin
- /crew/daily/opening：store_clerk 可填报，store_manager 可审核





这和你文档里的角色权限、组织统一、RLS 多租户隔离是匹配的。 



------





# **七、建议的代码层目录映射**





为了让路由与工程结构一开始就稳，建议这样落：

```
apps/
  web-pos/src/pages/
    dashboard/
    reservations/
    floor/
    orders/
    cashier/
    handover/
    exceptions/

  web-kds/src/pages/
    board/
    stations/
    tickets/
    alerts/
    stats/

  web-crew/src/pages/
    home/
    tasks/
    service/
    daily/
    review/
    profile/

  web-admin/src/pages/
    dashboard/
    trade/
    catalog/
    supply/
    operations/
    crm/
    analytics/
    org/
    agent/
    system/

  miniapp-customer/src/pages/
    home/
    booking/
    queue/
    order/
    member/
    coupons/
    corporate/
    profile/
```

这能和你已有的 web-pos / web-kds / web-crew / web-admin / miniapp-customer 项目结构直接接上。 



------





# **八、最终定版建议**





这版《页面清单 + 路由规划 V1》核心不是“页面尽量多”，而是把屯象OS × 徐记海鲜真正拆成一套能落地开发、能分期实施、能逐步替换旧系统的前端地图。你现在最该先证明的是：



- POS 交易链跑通
- KDS 出餐链跑通
- 日清日结有人执行
- 总部能看到异常并下发整改





只要这四条跑通，徐记样板就会从“架构正确”变成“产品成立”。这也符合你三年路线里 Year 1 的目标：先把徐记样板店稳定上线，再沉淀第一版海鲜酒楼 Pro 模板。 



下一步最适合继续往下做的是：

**《屯象OS × 徐记海鲜 核心页面原型结构图 + 页面交互说明 V1》**