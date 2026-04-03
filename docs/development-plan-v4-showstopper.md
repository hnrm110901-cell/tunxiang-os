# 屯象OS V4.0 十大致命差距修复 — 开发计划

> 基于 2026-Q1 企业级差距分析报告，针对阻碍集团级客户签约的 10 个 Showstopper 制定
>
> 基线：V3.2.0（10 服务 + 73 Agent Actions + 13 迁移脚本 + 158 测试文件）
>
> 目标：修复后综合竞争力从 50 分提升至 75+ 分，可支撑 80 店 + 3 品牌 + 中央厨房的集团级客户

---

## 总览：5 个 Phase，52 周

```
Phase 0  ████           Week 1-2    安全止血（RLS漏洞 + 凭证清除）
Phase 1  ████████████   Week 3-14   财务引擎 + 储值卡 + 同步引擎 + 外卖聚合
Phase 2  ████████████   Week 15-26  菜单中心 + 中央厨房 + 审批流 + 多品牌管控
Phase 3  ████████████   Week 27-38  加盟管理 + 薪资引擎 + 营销增长
Phase 4  ████████████   Week 39-52  深化打磨 + 全链路集成测试 + V4.0 发布
```

### 每 Phase 硬门禁

| 节点 | 门禁条件 | 不通过则 |
|------|---------|---------|
| Phase 0 完成 | RLS CRITICAL-001/002 修复 + git 凭证清除 | 禁止继续开发 |
| Phase 1 完成 | tx-finance 日利润计算准确率 ≥ 95% + sync-engine 可同步 3 张核心表 | 不进入 Phase 2 |
| Phase 2 完成 | 菜单模板可从总部下发到 5 家模拟门店 + 审批流支持 ≥ 3 种审批类型 | 不进入 Phase 3 |
| Phase 3 完成 | 加盟商可独立登录管理 + 薪资计算通过 20 个测试用例 | 不进入 Phase 4 |
| V4.0 发布 | 10 个 E2E 场景全通过 + `make test` ≥ 500 tests | 不打 tag |

---

## Phase 0：安全止血（Week 1-2）🚨

> **致命差距 #9：RLS 安全漏洞未修复**
>
> 不修复 = 不可上线，品牌间数据互相泄露

### 0.1 修复 RLS CRITICAL-001：session 变量名不一致 [3天]

**问题**：RLS Policy 使用 `app.current_store_id`，但应用设的是 `app.current_tenant`。

**执行步骤**：

```
- [ ] 扫描所有迁移脚本中的 RLS Policy，统一 session 变量名为 `app.tenant_id`
- [ ] 修改 init-rls.sql 中的 set_tenant_id 函数
- [ ] 修改所有 Python 服务中 set session variable 的调用点
- [ ] 编写迁移脚本 v014_rls_session_variable_unify.py
- [ ] 测试：≥ 5 个（跨租户不可访问 + 同租户可访问 + 空 tenant 拒绝）
```

### 0.2 修复 RLS CRITICAL-002：NULL 绕过漏洞 [2天]

**问题**：`current_setting(...) IS NULL` 条件导致未设 tenant 时全表可见。

**执行步骤**：

```
- [ ] 所有 RLS Policy 改为：tenant_id = current_setting('app.tenant_id')::uuid（去掉 IS NULL 分支）
- [ ] 中间件层强制校验 X-Tenant-ID header，缺失则 403
- [ ] Gateway 层拦截无 tenant_id 的请求
- [ ] 编写迁移脚本 v015_rls_null_bypass_fix.py
- [ ] 测试：≥ 3 个（无 tenant 请求返回 403 + Policy 拒绝无 tenant 查询）
```

### 0.3 git 历史凭证清除 [1天]

```
- [ ] 用 git-filter-repo 清除 config/merchants/*.env 历史
- [ ] 清除 scripts/probe_pinzhi_v2.py 中硬编码 Token
- [ ] 配置 git-secrets 防止再次提交
- [ ] .gitignore 添加 config/merchants/.env*
```

### 0.4 关键路径 broad except 收窄 [2天]

```
- [ ] 修复 celery_tasks.py 中 1 处静默 except（加 exc_info=True）
- [ ] 收窄 tx-trade 收银链路中的 45 处 except Exception 为具体异常
- [ ] 收窄 gateway 认证链路中的 except Exception
```

**Phase 0 验收**：RLS 跨租户测试全通过 + git 历史无凭证 + ruff S110 检查通过

---

## Phase 1：财务 + 储值卡 + 同步 + 外卖（Week 3-14）💰

### Sprint 1.1：财务引擎 v1（Week 3-6）

> **致命差距 #1：财务模块是空壳**
>
> 解决"今天赚了多少钱"这个最基本的问题

#### 1.1.1 营收计算引擎 [Week 3]

```
- [ ] 新建 tx-finance/src/services/revenue_engine.py
      - 从 orders + payments 表实时聚合营收
      - 按支付方式分类（现金/微信/支付宝/银联/储值卡/外卖平台）
      - 按渠道分类（堂食/外卖/小程序/团餐）
      - 金额全部用分（int），展示层转元
- [ ] 新建 tx-finance/src/services/cost_engine.py
      - 从 order_items + ingredients 关联计算食材成本
      - BOM 展开计算理论成本
      - 支持实际成本 vs 理论成本对比
- [ ] 新建 tx-finance/src/repositories/finance_repo.py
      - 日粒度/周粒度/月粒度聚合查询
      - 门店/品牌/集团三级聚合
- [ ] 测试：≥ 10 个
```

#### 1.1.2 利润计算 + P&L [Week 4]

```
- [ ] 新建 tx-finance/src/services/pnl_engine.py
      - 门店级损益表：营收 - 食材成本 - 人工成本 - 租金 - 水电 = 利润
      - 毛利率 / 净利率 / 人效比 自动计算
      - 按日/周/月/季/年出表
- [ ] 重写 finance.py 中 daily-profit 端点（替换占位返回）
      - 调用 revenue_engine + cost_engine 真实计算
- [ ] 重写 cost-rate 端点（真实计算成本率 + 趋势）
- [ ] 重写 cost-rate/ranking 端点（跨店排名）
- [ ] 测试：≥ 8 个（含边界：空数据/跨时区/退款扣减）
```

#### 1.1.3 FCT 报表 + 预算 [Week 5]

```
- [ ] 重写 fct/report 端点 — 7 种报表类型真实数据
      - period_summary: 期间汇总
      - aggregate: 聚合报表
      - trend: 趋势分析
      - by_entity: 按实体（门店/品牌）
      - by_region: 按区域
      - comparison: 同比/环比
      - plan_vs_actual: 预算 vs 实际
- [ ] 重写 budget 端点 — 预算录入 + 执行率计算
- [ ] 重写 cashflow/forecast 端点 — 基于历史数据的现金流预测
- [ ] 新增 POST /finance/budget — 预算录入 API
- [ ] 测试：≥ 8 个
```

#### 1.1.4 月报 + 凭证 [Week 6]

```
- [ ] 重写 monthly-report 端点 — 真实月度经营报告
      - 营收趋势/成本结构/利润变化/同比环比
      - 调用叙事引擎生成文字解读
- [ ] 重写 monthly-report HTML 端点 — 可打印 PDF 格式
- [ ] 新建 tx-finance/src/services/voucher_engine.py
      - 营收→凭证规则（借：银行存款/应收账款，贷：主营业务收入）
      - 成本→凭证规则（借：主营业务成本，贷：原材料）
      - 对接金蝶 K3 Cloud API（走 adapters/kingdee）
- [ ] 迁移脚本 v016_finance_tables.py（finance_budgets + finance_vouchers 表）
- [ ] 测试：≥ 6 个
```

### Sprint 1.2：储值卡体系（Week 7-8）

> **致命差距 #4：储值卡/预付费体系缺失**
>
> 正餐连锁最重要的现金流工具

#### 1.2.1 储值卡核心 [Week 7]

```
- [ ] 新建 tx-member/src/models/stored_value.py
      - StoredValueCard: card_no, customer_id, balance_fen, gift_balance_fen,
        status(active/frozen/expired), card_type(personal/corporate/gift)
      - StoredValueTransaction: txn_type(recharge/consume/refund/gift/transfer),
        amount_fen, balance_after_fen, order_id, operator_id
- [ ] 新建 tx-member/src/services/stored_value_service.py
      - recharge(): 充值（含赠送金规则：充500送50）
      - consume(): 消费扣款（先扣赠送金再扣本金）
      - refund(): 退款（仅退本金，赠送金按比例扣回）
      - freeze() / unfreeze(): 冻结/解冻
      - transfer(): 转赠
      - get_balance(): 查询余额
- [ ] 新建 tx-member/src/api/stored_value_routes.py
      - POST /member/stored-value/recharge
      - POST /member/stored-value/consume
      - POST /member/stored-value/refund
      - GET /member/stored-value/{card_no}/balance
      - GET /member/stored-value/{card_no}/transactions
- [ ] 迁移脚本 v017_stored_value_tables.py
- [ ] 测试：≥ 12 个（充值/消费/退款/赠送金/冻结/余额不足/并发扣款）
```

#### 1.2.2 储值卡 + 收银集成 [Week 8]

```
- [ ] tx-trade 结算流程支持储值卡支付方式
      - payment_method 新增 stored_value 类型
      - 结算时调用 stored_value_service.consume()
      - 退款时调用 stored_value_service.refund()
- [ ] web-pos 收银页面增加储值卡支付选项
      - 扫卡/输入卡号 → 查余额 → 确认扣款
- [ ] 储值卡充值活动配置（充值赠送规则 CRUD）
- [ ] miniapp-customer 会员中心显示储值卡余额 + 充值入口
- [ ] 测试：≥ 6 个（含收银全流程 E2E）
```

### Sprint 1.3：数据同步引擎（Week 9-11）

> **致命差距 #8：数据同步引擎是纯骨架**
>
> Mac mini 边缘架构的根基

#### 1.3.1 同步引擎核心实现 [Week 9-10]

```
- [ ] 实现 _get_local_changes()
      - 方案 A（推荐）：基于 updated_at 增量查询
      - 方案 B（进阶）：PG logical replication + pgoutput
      - 每张表记录 last_sync_watermark
- [ ] 实现 _push_to_cloud()
      - 批量 UPSERT（ON CONFLICT DO UPDATE）
      - 单次最多 1000 行，超出分批
      - 失败重试 3 次，记录 sync_error_log
- [ ] 实现 _get_cloud_changes()
      - 基于 updated_at > last_sync_at 查询云端变更
      - 排除本机上传的变更（避免循环同步）
- [ ] 实现 _apply_to_local()
      - 云端优先冲突策略：同一行云端 updated_at > 本地则覆盖
      - 事务性写入，失败则回滚整批
- [ ] 新增同步状态 API
      - GET /sync/status — 同步状态/进度/错误
      - POST /sync/force — 手动触发同步
      - GET /sync/conflicts — 冲突记录查询
- [ ] 测试：≥ 15 个（正常同步/断网重连/冲突覆盖/大批量/并发写入）
```

#### 1.3.2 断网收银 [Week 11]

```
- [ ] mac-station 离线模式
      - 检测云端不可达时自动切换到离线模式
      - 离线期间所有写入存入本地 PG
      - 恢复连接后自动追补同步
- [ ] 安卓 POS 检测 Mac mini 不可达时的降级策略
      - 最小可用模式：收银 + 打印（本地缓存菜品数据）
- [ ] 同步冲突告警推送（WebSocket → web-admin）
- [ ] 测试：≥ 6 个（断网→恢复→数据一致性校验）
```

### Sprint 1.4：外卖聚合统一管理（Week 12-14）

> **致命差距 #10：外卖聚合未集成**
>
> 外卖占连锁品牌营收 20-40%

#### 1.4.1 外卖统一接单 [Week 12-13]

```
- [ ] tx-trade/main.py 注册 takeaway_routes.py（已有代码激活）
- [ ] 新建 tx-trade/src/services/takeaway_aggregator.py
      - 统一订单模型：将美团/饿了么/抖音订单转换为屯象 Order
      - 自动接单规则（按门店配置：全自动/手动确认/忙时手动）
      - 防超卖：接单前校验库存（对接 tx-supply 沽清 API）
      - 订单状态同步：屯象出餐状态 → 平台骑手状态
- [ ] 新建外卖管理面板页面 web-pos/TakeawayPanel
      - 待接单/已接单/制作中/待取餐 四列看板
      - 多平台订单标签区分（美团绿/饿了么蓝/抖音黑）
      - 一键接单/拒单/备注
- [ ] Webhook 统一入口优化
      - 美团/饿了么/抖音回调统一解析 → 入库 → 推 KDS
- [ ] 测试：≥ 8 个
```

#### 1.4.2 外卖菜单同步 [Week 14]

```
- [ ] tx-menu 菜品变更事件 → 自动推送到外卖平台（走 Adapter）
      - 沽清同步：门店沽清 → 美团/饿了么自动下架
      - 价格同步：外卖独立定价，变更后推送
- [ ] 外卖报表集成到 tx-analytics
      - 各平台 GMV/订单量/客单价/差评率
      - 外卖 vs 堂食收入占比趋势
- [ ] 测试：≥ 4 个
```

**Phase 1 验收**：
- tx-finance 日利润 API 返回真实数据且准确率 ≥ 95%
- 储值卡充值→消费→退款全流程可运行
- sync-engine 可同步 orders/payments/customers 3 张表
- 外卖统一接单面板可展示多平台订单

---

## Phase 2：菜单 + 供应链 + 审批 + 多品牌（Week 15-26）🏢

### Sprint 2.1：菜单模板中心 + 多渠道发布（Week 15-18）

> **致命差距 #5：菜单模板中心 + 多渠道发布缺失**
>
> 80 家门店不能各自维护菜品

#### 2.1.1 菜单模板体系 [Week 15-16]

```
- [ ] 新建 tx-menu/src/models/menu_template.py
      - MenuTemplate: 集团级菜单模板（品牌维度）
      - MenuTemplateItem: 模板菜品项（含默认价格/BOM/分类）
      - StoreMenuOverride: 门店级覆盖（可加减菜品/调价格）
- [ ] 新建 tx-menu/src/services/menu_template_service.py
      - create_template(): 创建品牌级模板
      - apply_to_stores(): 批量下发到指定门店
      - store_override(): 门店个性化微调
      - diff_template(): 对比门店菜单与模板差异
      - sync_changes(): 模板变更自动推送到门店
- [ ] API 路由
      - CRUD /menu/templates
      - POST /menu/templates/{id}/apply — 下发到门店
      - GET /menu/templates/{id}/diff — 差异对比
      - PUT /menu/store-overrides/{store_id} — 门店覆盖
- [ ] web-admin 菜单模板管理页面
      - 模板列表 + 编辑 + 下发 + 差异审查
- [ ] 迁移脚本 v018_menu_template_tables.py
- [ ] 测试：≥ 10 个（创建/下发/覆盖/差异/同步/跨品牌隔离）
```

#### 2.1.2 多渠道发布引擎 [Week 17-18]

```
- [ ] 新建 tx-menu/src/services/channel_publisher.py
      - 渠道定义：dine_in / meituan / eleme / douyin / miniapp / corporate
      - 每个渠道独立定价（同一菜品不同渠道不同价）
      - 发布规则：全量发布 / 增量发布 / 定时发布
      - 发布到外卖平台走 Adapter（meituan-saas / eleme / douyin）
- [ ] API 路由
      - POST /menu/channels/{channel}/publish — 发布到指定渠道
      - GET /menu/channels/{channel}/status — 渠道发布状态
      - PUT /menu/channels/{channel}/pricing — 渠道定价规则
- [ ] web-admin 渠道发布管理页面
- [ ] 测试：≥ 8 个
```

### Sprint 2.2：中央厨房 + 配送管理（Week 19-24）

> **致命差距 #2：中央厨房 + 配送管理完全缺失**
>
> 大型连锁的基础设施

#### 2.2.1 中央厨房数据模型 [Week 19-20]

```
- [ ] 新建 tx-supply/src/models/central_kitchen.py
      - CentralKitchen: 中央厨房实体（名称/地址/产能/负责区域）
      - ProductionPlan: 生产计划（日期/菜品/数量/BOM 展开）
      - ProductionOrder: 生产工单（状态：待生产/生产中/质检/入库）
      - ProductionBatch: 生产批次（批次号/生产时间/保质期/数量）
      - QualityCheck: 质检记录（检查项/结果/检查人）
- [ ] 新建 tx-supply/src/models/warehouse.py
      - Warehouse: 仓库实体（类型：中央厨房仓/区域仓/门店仓）
      - WarehouseZone: 库区（冷藏/冷冻/常温/活鲜）
      - StockLocation: 库位
- [ ] 迁移脚本 v019_central_kitchen_tables.py
```

#### 2.2.2 生产计划 + 加工 [Week 21-22]

```
- [ ] 新建 tx-supply/src/services/production_service.py
      - generate_plan(): 根据门店历史销量 + 安全库存自动生成生产计划
      - create_order(): 计划→工单（BOM展开→原料需求→检查库存）
      - start_production(): 开始生产（扣减原料库存）
      - complete_production(): 完成生产（成品入库 + 批次号）
      - quality_check(): 质检（通过→可配送 / 不通过→报废）
- [ ] API 路由
      - CRUD /supply/production-plans
      - CRUD /supply/production-orders
      - POST /supply/production-orders/{id}/start
      - POST /supply/production-orders/{id}/complete
      - POST /supply/production-orders/{id}/quality-check
- [ ] 测试：≥ 12 个
```

#### 2.2.3 配送管理 [Week 23-24]

```
- [ ] 新建 tx-supply/src/models/distribution.py
      - DistributionOrder: 配送单（来源仓→目标门店/仓，状态，温控要求）
      - DistributionItem: 配送明细（商品/数量/批次）
      - DistributionRoute: 配送线路（车辆/司机/门店序列/温控记录）
- [ ] 新建 tx-supply/src/services/distribution_service.py
      - create_order(): 根据门店要货单生成配送单
      - assign_route(): 分配配送线路
      - confirm_delivery(): 门店签收（数量确认 + 温控检查）
      - return_goods(): 退货处理
- [ ] 新建 tx-supply/src/services/store_requisition_service.py
      - 门店要货：create_requisition() → 审批 → 中央厨房排产/区域仓出库
      - 智能要货建议：基于历史销量 + 库存 + 保质期
- [ ] 门店收货验收（致命差距 #2 补充 E6）
      - 到货签收 + 数量核对 + 质检 + 入库
      - 差异记录（短缺/损坏/温度异常）
- [ ] 门店间调拨（致命差距 E5）
      - 调拨申请 → 审批 → 出库 → 运输 → 入库
- [ ] API 路由（15+ 端点）
- [ ] 迁移脚本 v020_distribution_tables.py
- [ ] 测试：≥ 15 个
```

### Sprint 2.3：审批流引擎（Week 25-26）

> **致命差距 #7：审批流/工单引擎缺失**
>
> 集团运营的基础设施

#### 2.3.1 通用审批流引擎 [Week 25-26]

```
- [ ] 新建 tx-ops/src/services/approval_engine.py
      - ApprovalFlow: 审批流定义（名称/触发条件/节点链）
      - ApprovalNode: 审批节点（审批人规则/超时策略/自动审批条件）
      - ApprovalInstance: 审批实例（当前节点/状态/历史记录）
      - 审批人规则：指定人/角色/上级/部门负责人
      - 条件分支：金额>X走A链路，否则走B链路
      - 超时策略：超时自动通过/自动拒绝/升级到上级
- [ ] 预置审批流模板
      - 采购审批（金额分级：<1000 店长 / <10000 区域 / ≥10000 总部）
      - 折扣审批（超出角色权限→上级审批）
      - 价格变更审批（菜品调价→品牌经理审批）
      - 人事审批（入职/调动/离职→HR + 店长双审）
      - 报销审批（金额分级）
- [ ] API 路由
      - CRUD /ops/approval-flows — 审批流配置
      - POST /ops/approvals — 发起审批
      - POST /ops/approvals/{id}/approve — 审批通过
      - POST /ops/approvals/{id}/reject — 审批拒绝
      - GET /ops/approvals/pending — 我的待审批
      - GET /ops/approvals/history — 审批历史
- [ ] 企微/WebSocket 审批通知推送
- [ ] web-admin 审批流配置页面（可视化节点编排）
- [ ] 迁移脚本 v021_approval_flow_tables.py
- [ ] 测试：≥ 15 个（单级/多级/条件分支/超时/并行会签/驳回重提）
```

**Phase 2 验收**：
- 菜单模板可从总部下发到 5 家门店并支持门店覆盖
- 中央厨房生产计划→加工→配送→门店签收全流程可运行
- 审批流支持采购/折扣/价格变更 3 种场景
- web-admin 可配置审批流

---

## Phase 3：加盟 + 薪资 + 营销增长（Week 27-38）📱

### Sprint 3.1：多品牌 + 加盟管理（Week 27-30）

> **致命差距 #3：加盟管理完全缺失**
>
> 排除了中国 50%+ 连锁模式

#### 3.1.1 多品牌配置中心 [Week 27-28]

```
- [ ] 新建 services/gateway/src/brand_config.py（或激活 brand_switcher.py）
      - Brand 实体：名称/Logo/配色/域名/负责人
      - BrandConfig: 品牌级参数配置（默认折扣规则/毛利底线/出餐时限等）
      - 品牌间数据完全隔离（基于 tenant_id + brand_id）
- [ ] 新建品牌切换器
      - 集团用户可切换品牌视角查看数据
      - 品牌用户只能看到自己品牌的数据
- [ ] web-admin 品牌管理页面
      - 品牌列表/新增/编辑/配置
      - 品牌级经营看板（独立 P&L）
- [ ] 迁移脚本 v022_brand_config_tables.py
- [ ] 测试：≥ 6 个
```

#### 3.1.2 加盟管理模块 [Week 29-30]

```
- [ ] 新建 tx-org/src/models/franchise.py
      - Franchisee: 加盟商（公司名/法人/联系方式/合同信息）
      - FranchiseContract: 加盟合同（期限/费用/分润规则/区域保护）
      - FranchiseFeeRecord: 费用记录（加盟费/管理费/品牌使用费）
      - FranchiseStore: 加盟门店关联（加盟商→门店映射）
- [ ] 新建 tx-org/src/services/franchise_service.py
      - create_franchisee(): 新增加盟商（含合同签署）
      - calculate_fees(): 计算月度管理费/分润
      - franchise_report(): 加盟商经营报表（营收/成本/分润）
      - terminate_contract(): 合同终止（门店数据迁移/清理）
- [ ] 加盟商独立登录
      - 加盟商账号体系（独立于直营员工）
      - 可查看自己门店的经营数据
      - 可进行日常运营操作（在权限范围内）
      - 不可修改品牌级配置
- [ ] 加盟价管理
      - 供应链加盟价（区别于直营成本价）
      - 加盟商采购走独立价格体系
- [ ] API 路由（10+ 端点）
- [ ] 迁移脚本 v023_franchise_tables.py
- [ ] 测试：≥ 10 个
```

### Sprint 3.2：薪资计算引擎（Week 31-34）

> **致命差距 #6：薪资计算引擎缺失**
>
> 3000 人薪资不能手算

#### 3.2.1 薪资核心引擎 [Week 31-32]

```
- [ ] 新建 tx-org/src/services/payroll_engine.py
      - 薪资结构定义：基本工资 + 岗位津贴 + 绩效奖金 + 提成 + 加班费 - 扣款
      - 提成计算：按营收/按菜品/按桌数/按好评等多种提成模式
      - 加班计算：工作日 1.5x / 周末 2x / 法定假 3x
      - 扣款项：迟到/早退/旷工/处罚/代扣
      - 多薪资方案：不同岗位/门店/品牌可用不同方案
- [ ] 新建 tx-org/src/services/social_insurance_service.py
      - 五险一金基数设置（按城市不同）
      - 个人 + 企业缴费计算
      - 个税计算（累计预扣法）
      - 专项附加扣除
- [ ] 迁移脚本 v024_payroll_tables.py
- [ ] 测试：≥ 15 个（多方案/多城市社保/个税阶梯/提成计算/加班）
```

#### 3.2.2 薪资发放 + 报表 [Week 33-34]

```
- [ ] 新建 tx-org/src/services/payslip_service.py
      - generate_payslips(): 批量生成工资条
      - confirm_payroll(): 薪资确认（走审批流）
      - export_bank_file(): 导出银行代发文件（标准格式）
- [ ] 假期管理
      - 假期类型配置（年假/调休/病假/婚假/产假/事假）
      - 假期余额自动计算（按入职年限/工龄）
      - 请假 → 审批流 → 考勤联动 → 薪资扣减
- [ ] 员工自助查询
      - web-crew 增加"我的薪资"页面（查工资条/查社保/查假期余额）
- [ ] API 路由（12+ 端点）
- [ ] 测试：≥ 8 个
```

### Sprint 3.3：营销增长工具（Week 35-38）

> 补齐私域增长核心工具

#### 3.3.1 裂变营销工具 [Week 35-36]

```
- [ ] 新建 tx-member/src/services/growth_tools.py
      - 拼团：N人成团享X折（时限/人数/阶梯价）
      - 砍价：好友助力砍价（底价/砍价幅度/时限）
      - 邀请有礼：老带新双向奖励（奖励类型：券/积分/储值金）
      - 分销：KOL/KOC 推广码 + 佣金计算
- [ ] miniapp-customer 裂变页面
      - 拼团详情页 + 发起/参与
      - 砍价详情页 + 分享助力
      - 邀请海报生成（小程序码 + 头像）
- [ ] 测试：≥ 8 个
```

#### 3.3.2 积分商城 + 付费会员 [Week 37-38]

```
- [ ] 激活 tx-member/src/api/points_mall_routes.py（注册到 main.py）
      - 积分商品管理（实物/券/储值金/抽奖机会）
      - 积分兑换（扣积分 + 发放商品/券）
      - 积分过期提醒
- [ ] 新建付费会员卡
      - 会员卡类型：月卡/季卡/年卡
      - 权益配置：折扣/免配送/专属菜品/生日礼/积分倍数
      - 自动续费 / 到期提醒
- [ ] 激活 tx-member/src/api/premium_card_routes.py
- [ ] 测试：≥ 8 个
```

**Phase 3 验收**：
- 加盟商可独立登录并查看经营数据
- 薪资计算通过 20 个测试用例（含多城市社保）
- 裂变营销拼团/砍价可在小程序中运行
- 积分商城可兑换商品

---

## Phase 4：深化打磨 + V4.0 发布（Week 39-52）✨

### Sprint 4.1：集成打通 + 体验优化（Week 39-44）

```
- [ ] 所有"代码有未注册"的路由激活（14 项，见差距报告附录）
- [ ] web-admin 品牌/区域/门店三级切换体验
- [ ] 企微 SDK 深度对接（客户标签/群发/企微客服）
- [ ] 供应商门户 v1（自助报价/对账/送货确认）
- [ ] PWA 离线体验（Service Worker + IndexedDB 缓存菜品数据）
- [ ] 自定义报表 v1（拖拽式维度/指标选择器）
```

### Sprint 4.2：全链路 E2E 测试（Week 45-48）

```
- [ ] E2E 场景 01：新店上线（模板下发→配置→首单→日结）
- [ ] E2E 场景 02：堂食全流程（开台→点菜→加菜→称重→KDS→结算→打印→储值卡支付）
- [ ] E2E 场景 03：外卖全流程（美团下单→自动接单→KDS→出餐→骑手取餐→完成）
- [ ] E2E 场景 04：供应链全流程（门店要货→中央厨房排产→加工→配送→签收→入库）
- [ ] E2E 场景 05：会员全流程（注册→充值→消费→积分→兑换→拼团→邀请→裂变）
- [ ] E2E 场景 06：财务全流程（日结→成本核算→P&L→月报→凭证→对接金蝶）
- [ ] E2E 场景 07：人事全流程（入职→排班→考勤→请假→绩效→薪资→工资条）
- [ ] E2E 场景 08：审批全流程（采购申请→多级审批→超时升级→完成）
- [ ] E2E 场景 09：加盟全流程（签约→开店→采购→经营→月度分润）
- [ ] E2E 场景 10：Agent 全流程（异常检测→决策→约束校验→推送→审批→执行→复盘）
```

### Sprint 4.3：性能 + 安全 + 发布（Week 49-52）

```
- [ ] 压力测试：模拟 80 门店并发收银（≥ 200 TPS）
- [ ] DB 索引优化（基于慢查询日志）
- [ ] 前端包体积优化（目标：首屏 < 300KB gzip）
- [ ] 安全审计复查（RLS + Nginx + 端口 + 权限）
- [ ] Docker 镜像优化（多阶段构建，镜像 < 500MB）
- [ ] 全部文档更新（README + API 文档 + 部署手册）
- [ ] `git tag v4.0.0` + GitHub Release
```

**Phase 4 验收**：
- 10 个 E2E 场景全通过
- `make test` ≥ 500 tests
- 压力测试 ≥ 200 TPS
- 安全审计无 CRITICAL 级问题

---

## 交付物预估

| 指标 | V3.2.0 (当前) | V4.0.0 (目标) | 增量 |
|------|-------------|-------------|------|
| Tests | ~300 | **≥ 500** | +200 |
| API Endpoints | ~160 | **~300** | +140 |
| DB Tables | ~35 | **~60** | +25 |
| Migrations | 13 | **~25** | +12 |
| Services | 10 | **10**（功能大幅扩展） | 0 |
| 前端页面 | ~40 | **~55** | +15 |
| 财务得分 | 15/100 | **75/100** | +60 |
| 供应链得分 | 50/100 | **80/100** | +30 |
| 集团管控得分 | 35/100 | **75/100** | +40 |
| **综合竞争力** | **50/100** | **≥75/100** | **+25** |

---

## 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 财务计算逻辑复杂度超预期 | 延期 2-4 周 | 中 | 先做单店日报→再做集团聚合，分步交付 |
| 中央厨房业务理解不足 | 模型设计返工 | 高 | 找 1-2 家有中央厨房的客户做需求验证 |
| sync-engine 并发冲突 | 数据不一致 | 中 | 严格"云端优先"策略 + 冲突日志 + 人工兜底 |
| 加盟管理法律合规 | 分润计算有争议 | 低 | 参考行业标准合同模板，保留审计日志 |
| Phase 工期紧张 | 功能裁剪 | 高 | Phase 1/2 为硬核心不可砍，Phase 3/4 可调整优先级 |
| 前端开发资源不足 | 页面延期 | 中 | 后端 API 优先，前端可后续追赶 |

---

## 与现有开发计划的关系

| 现有计划 | 本计划关系 | 说明 |
|---------|-----------|------|
| v6 审计修复计划 | Phase 0 包含 | RLS 修复 + 凭证清除 + broad except 收窄 |
| v3.2 开发计划 | Phase 1-2 部分覆盖 | 储值卡/薪资/审批已在 v3.2 规划，本计划扩大范围 |
| 徐记蓝图 GAP | Phase 1-4 全覆盖 | 本计划以企业级全面差距为基础，比蓝图更广 |

---

*本计划基于《屯象OS 企业级差距分析报告 2026-Q1》十大致命差距制定，目标是将屯象OS 从"创业期产品"升级为"可签约集团级客户的企业级产品"。*
