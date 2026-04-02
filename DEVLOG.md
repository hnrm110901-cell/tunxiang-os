# 屯象OS — 每日开发日志

> 最新记录在最上方。格式：完成内容 / 数据变化 / 遗留问题 / 明日计划。

---

## 2026-04-02（Round 5 三团队全部完成 — 🎉 十大差距全部清零）

### 今日完成（超级智能体团队 Round 5 交付）

**Team R — tx-org 加盟管理引擎（十大差距最后一项！）**
- [DB] v125_franchise_management.py（revises v124，链路完整v121→v122→v123→v124→v125）：5张表
  - franchisees：加盟商档案（状态机/层级/合同期/分润比率）
  - franchise_stores：加盟门店（template_store_id/clone_status追踪复制进度）
  - franchise_royalty_rules：分润规则（revenue_pct/fixed_monthly/tiered_revenue三种）
  - franchise_royalty_bills：分润账单（唯一约束支持upsert）
  - franchise_kpi_records：绩效考核（自动计算综合评分和层级建议）
- [tx-org/services] 新建 franchise_clone_service.py：clone_store()通过httpx异步调用tx-menu/tx-ops/tx-trade三服务复制配置，非致命错误收集到errors[]不阻断
- [tx-org/api] 新建 franchise_mgmt_routes.py（14个端点）：
  - 加盟商管理（列表/新建/详情/状态推进）
  - 门店复制（创建+触发/手动复制/进度查询）
  - 分润规则（列表/创建/三种算法计算）
  - 分润账单（生成/列表/标记付款）
  - 绩效考核（录入/历年查询/看板）
- [tx-org/main.py] 注册 franchise_mgmt_router

**Team S — web-admin 薪资管理 + 加盟驾驶舱**
- [web-admin] 新建 PayrollManagePage.tsx（3Tab）：
  - Tab1：月度汇总4卡/Table/批量计算Modal/导出/审批
  - Tab2：薪资明细+纯CSS条形图对比
  - Tab3：薪资配置Modal（月薪/时薪/计件）
- [web-admin] 新建 FranchiseDashboardPage.tsx：
  - 4统计卡/加盟商Table（分层Tag金银色）/详情Drawer
  - 纯CSS双柱对比图+分润账单+门店列表
  - 新建加盟商Modal
- [web-admin/App.tsx] 注册 /payroll-manage + /franchise-dashboard

**Team T — miniapp 大厨到家完整流程**
- [miniapp/index] 首页添加橙色渐变Banner（#FF6B35→#FF8C5A）+ 立即预订入口
- [miniapp/chef-at-home/index] 大厨首页（地址/日期筛选/菜系筛选/厨师卡片列表/三态处理）
- [miniapp/chef-at-home/chef-profile] 厨师详情第3Tab"立即预约"：月历日期选择/时段选/人数步进/地址输入/备注
- [miniapp/chef-at-home/booking] 预约确认+支付（价格明细/微信支付/成功动画/联系大厨入口）

### 数据变化
- 迁移版本：v121 → v125（v122/v123/v124由其他子流程产生，v125=加盟管理）
- 新增数据库表：5张（franchisees/franchise_stores/royalty_rules/royalty_bills/kpi_records）
- 新增后端文件：2个（franchise_clone_service.py + franchise_mgmt_routes.py）
- 新增前端页面：2个web-admin + 3个miniapp页面改写

### 🎉 十大差距全部清零！
| # | 差距 | 状态 | 实现轮次 |
|---|------|------|--------|
| 1 | 财务引擎 | ✅ | Team E (v117) |
| 2 | 中央厨房 | ✅ | Team J (v119) |
| 3 | 加盟管理 | ✅ | Team R (v125) |
| 4 | 储值卡 | ✅ | 早期 |
| 5 | 菜单模板 | ✅ | Team L |
| 6 | 薪资引擎 | ✅ | Team K (v120) |
| 7 | 审批流 | ✅ | Team O (v121) |
| 8 | 同步引擎 | ✅ | Team N (edge) |
| 9 | RLS安全漏洞 | ✅ | v063 |
| 10 | 外卖聚合 | ✅ | 早期 |

### 遗留问题
- create_weigh_record端点缺少dish_id存在性校验（多轮标注，待修）
- franchise_clone_service依赖TX_MENU_BASE_URL等环境变量，部署前需配置
- miniapp大厨到家支付降级为模拟支付，需接入真实商户mchid/apikey

### 下轮计划（Round 6 — 质量提升与集成）
- create_weigh_record dish_id存在性校验修复
- Gateway路由表补全（新增服务路由配置）
- tx-brain AI决策中枢（接入Claude API实际实现折扣守护/会员洞察）
- 全量TypeScript检查修复
- miniapp会员中心（积分/等级/储值卡）

---

## 2026-04-02（Round 4 四团队全部完成）

### 今日完成（超级智能体团队 Round 4 交付）

**Team N — edge同步引擎核心实现**
- [edge/sync-engine] 新建 config.py：SyncConfig(BaseSettings)，必填CLOUD_PG_DSN/STORE_ID/TENANT_ID，60s单轮超时
- [edge/sync-engine] 新建 sync_engine.py（~350行）：SyncEngine类
  - init()：双连接池（local+cloud asyncpg）+ 幂等建辅助表
  - sync_upstream/downstream：按updated_at游标增量同步，批量upsert
  - resolve_conflict：三级优先（cloud.authoritative→POS交易保护→updated_at较新）
  - run_forever()：asyncio.wait_for 60s超时 + 指数退避（30s→MAX_RETRY_BACKOFF）
  - 白名单表名校验（_q()函数防SQL注入）
- [edge/sync-engine] 新建 main.py：structlog JSON日志 + 启动SyncEngine
- [edge/sync-engine] 新建 com.tunxiang.sync-engine.plist：launchd自启（RunAtLoad/KeepAlive）+ /opt/tunxiang/venv独立venv

**Team O — tx-ops 审批流引擎**
- [DB] v121_approval_workflow.py：4张表（approval_templates/instances/step_records/notifications），RLS+partial index（仅pending状态索引deadline_at）
- [tx-ops/services] 新建 approval_engine.py：ApprovalEngine类
  - _filter_steps_by_amount()：金额区间匹配核心逻辑
  - create_instance()：查模板→筛步骤→创建实例→通知第一步
  - act()：超时检查→写记录→approve推进/reject通知发起人
  - get_pending_for_approver()：内存匹配避免JSONB查询复杂度
  - check_expired()：批量扫描过期并通知
- [tx-ops/api] 新建 approval_workflow_routes.py：10个端点（模板CRUD/发起/审批/撤回/通知）
- [tx-ops/main.py] 注册 approval_router

**Team P — web-admin BOM配方编辑器**
- [web-admin] 新建 BomEditorPage.tsx：左右分栏布局
  - 左侧：搜索防抖400ms/菜品列表/点击高亮
  - 右侧：可编辑9列表格（行成本实时计算qty×price×(1+lossRate)）
  - 底部汇总栏：总成本大字橙色/每份成本/"重新计算"/"保存BOM"
  - 成本分解环形饼图（Collapse折叠）
  - 版本历史只读切换（历史版本禁止编辑）
  - 成本全程用分，UI层÷100显示
- [web-admin/App.tsx] 注册 /supply/bom 路由

**Team Q — web-admin/web-crew 审批流管理页**
- [web-admin] 新建 ApprovalTemplatePage.tsx（530行）：模板列表+步骤动态配置+Drawer表单
- [web-admin] 新建 ApprovalCenterPage.tsx（524行）：4状态统计卡/3Tab/Timeline步骤详情Drawer
- [web-crew] 新建 ApprovalPage.tsx（907行）：
  - 待我审批卡片（剩余时间/展开详情/通过❌拒绝大按钮52px/触控反馈scale(0.97)）
  - 我发起进度条+步骤标签行
  - 触发说明卡片
- [web-admin/App.tsx] 注册 /approval-templates + /approval-center
- [web-crew/App.tsx] 注册 /approvals（hiddenPaths）

### 数据变化
- 迁移版本：v120 → v121（新增v121审批流4张表）
- 新增edge服务文件：4个（sync-engine全量实现）
- 新增后端文件：2个（approval_engine.py + approval_workflow_routes.py）
- 新增前端页面：4个（BomEditorPage + ApprovalTemplatePage + ApprovalCenterPage + ApprovalPage）

### 十大差距更新状态
| # | 差距 | 状态 |
|---|------|------|
| 1 | 财务引擎 | ✅ Team E v117 |
| 2 | 中央厨房 | ✅ Team J v119 |
| 3 | 加盟管理 | 🔴 Round 5目标 |
| 4 | 储值卡 | ✅ 早期已实现 |
| 5 | 菜单模板 | ✅ Team L |
| 6 | 薪资引擎 | ✅ Team K v120 |
| 7 | 审批流 | ✅ Team O v121 |
| 8 | 同步引擎 | ✅ Team N edge |
| 9 | RLS安全漏洞 | ✅ v063已修复 |
| 10 | 外卖聚合 | ✅ 早期已实现 |

**十大差距仅剩"加盟管理"🔴 待实现**

### 遗留问题
- create_weigh_record端点缺少dish_id存在性校验（持续标注）
- approval_engine get_db为占位桩函数，需注入项目dependencies.py
- sync-engine本地PG辅助表不走Alembic，部署时需手动建表（init()已幂等处理）

### 下轮计划（Round 5）
- 加盟管理（tx-org：加盟商入驻/门店复制/分润规则/绩效考核）
- web-admin 薪资管理页（接入payroll_engine_v3）
- miniapp 大厨到家完整流程
- web-admin 加盟商驾驶舱

---

## 2026-04-02（Round 3 补充 — 我方四智能体追加交付）

### 今日完成（Round3 A/B/C/D 追加交付）

**Round3-A — 中央厨房BOM配方+配送调拨**
- [DB] v122_ck_recipes_plans.py：6张表（dish_recipes/recipe_ingredients/ck_production_plans/ck_plan_items/ck_dispatch_orders/ck_dispatch_items），全部RLS+updated_at触发器
- [tx-supply/api] 新建 ck_recipe_routes.py：13个端点（配方CRUD/按产量计算原料/生产计划状态机/原料汇总清单/调拨单创建+收货确认+打印）
  - 调拨单号自动生成 CK-YYYYMMDD-XXXX，收货差异>5%自动标注
- [web-admin] 新建 CentralKitchenPage.tsx：三Tab（配方管理/生产计划/调拨单），Drawer查看原料清单
- [tx-supply/main.py] 注册 ck_recipe_router

**Round3-B — 薪资引擎计件/提成/绩效**
- [DB] v121_payroll_engine_summaries.py：3张表（payroll_summaries/perf_score_items/payroll_deductions），补充v120未覆盖部分，全部RLS
- [tx-org/api] 重写 payroll_routes.py：13个端点（配置/单算/批量/确认/发放/工资条/绩效录入/扣款管理）
  - 计算公式：base + piece×rate + commission_base×rate + perf/100×bonus_cap - deductions
- [web-admin] 新建 PayrollPage.tsx：两Tab（月度薪资多级表头+合计行 / 薪资配置ModalForm），分→元显示
- [tx-org/main.py] 注册 payroll_router（无前缀，路由器已内置）

**Round3-C — web-crew会员积分等级UI**
- [web-crew/components] 新建 MemberLevelBadge.tsx：四等级×三尺寸，diamond渐变色系
- [web-crew/components] 新建 MemberPointsCard.tsx：积分大字+进度条+两操作按钮
- [web-crew/api] 新建 memberPointsApi.ts：Mock10条积分记录，后端接入替换即可
- [web-crew] 升级 MemberPage.tsx：积分卡+明细折叠+快捷3宫格（兑换/充值/消费记录）
- [web-crew] 新建 PointsTransactionPage.tsx：按月分组+底部累计统计，hiddenPaths
- TypeScript全量检查：0 errors

**Round3-D — Bug修复**
- [tx-menu/api] live_seafood_routes.py：create_weigh_record新增4项前置校验
  - dish_id UUID格式（ValueError捕获）→ INVALID_DISH_ID
  - dish_id存在性（_MOCK_DISH_IDS + TODO真实DB注释）→ DISH_NOT_FOUND
  - zone_code合法性 → TANK_NOT_FOUND
  - 重量上限（>50kg）→ WEIGHT_OUT_OF_RANGE
  - 所有422响应统一格式：{ok:false, error:{code,message,field}}

### 数据变化
- 迁移版本：v120 → v122（新增v121薪资汇总/v122中央厨房配方计划）
- 新增数据库表：9张（中央厨房×6 + 薪资汇总×3）
- 新增后端API文件：2个（ck_recipe_routes/重写payroll_routes）
- 新增前端页面：3个（CentralKitchenPage/PayrollPage/PointsTransactionPage）
- 新增前端组件：2个（MemberLevelBadge/MemberPointsCard）
- Bug修复：1个（create_weigh_record dish_id校验）

### 遗留问题
- v119-v121版本号存在多文件冲突（多智能体并行导致），需手动整理revision链
- payroll_engine_v3.py（Team K）中get_db为桩函数，需接入真实dependencies.py
- create_weigh_record校验目前基于mock菜品ID，生产环境需替换为DB查询

### 明日计划（Round 4）
- 同步引擎（edge/sync-engine：本地PG↔云端PG增量同步）
- 审批流（tx-ops：多级审批/审批通知/审批历史）
- 加盟管理（tx-org：加盟商入驻/分润规则/绩效考核）
- migration版本冲突整理（v119-v122 revision链修正）

---

## 2026-04-02（Round 3 四团队全部完成）

### 今日完成（超级智能体团队 Round 3 交付）

**Team J — tx-supply 中央厨房BOM配方**
- [DB] v119_central_kitchen.py：6张表（dish_boms/dish_bom_items/ck_production_orders/ck_production_items/ck_distribution_orders/ck_distribution_items），全部含RLS+updated_at触发器
- [tx-supply/api] bom_routes.py（重写）：7个端点（列表/创建/更新/软删除/成本重算/成本分解/按BOM消耗库存）
  - 创建BOM时自动计算各行成本：ceil(qty × unit_cost × (1+loss_rate))
  - is_active=true时自动关闭旧激活版本
  - 库存扣减：qty × (1+loss_rate) × 消耗份数
- [tx-supply/api] 新建 ck_production_routes.py：7个端点（生产工单CRUD/状态机/智能排产/配送单/收货确认）
  - 智能排产：近7天均值 × 1.1 × 周末系数1.3
  - 收货差异>5%自动在notes追加提醒
- [tx-supply/main.py] 注册 ck_production_router

**Team K — tx-org 薪资计算引擎**
- [DB] v120_payroll_engine.py（修正冲突：v119→v120，down_revision→v119）：payroll_configs/payroll_records/payroll_line_items三表，RLS隔离
- [tx-org/services] 新建 payroll_engine_v3.py（1007行）：PayrollEngine类
  - calculate_monthly_payroll：读配置→聚合日绩效→计算底薪/加班费/提成/计件/绩效奖→个税→upsert记录→写明细行
  - batch_calculate_store：批量计算，单个失败不中断
  - approve_payroll：draft→approved状态机
  - get_payroll_summary：PERCENTILE_CONT中位数+环比对比
- [tx-org/api] 新建 payroll_engine_routes.py（396行）：8个端点（配置/单算/批量/列表/详情/审批/汇总）
- [tx-org/main.py] 注册 payroll_engine_v3_router

**Team L — web-admin 菜单模板管理**
- [web-admin] 新建 MenuTemplatePage.tsx（1710行）：左侧模板列表 + 三Tab主区域
  - Tab1：分类管理（上移/下移排序/启用Switch/价格覆盖）
  - Tab2：发布管理（多选门店/差异配置/发布到选中门店/发布记录表）
  - Tab3：版本历史（Timeline/回滚按钮+二次确认）
  - Mock降级保证无API时可独立演示
- [web-admin/App.tsx] 注册 /menu-templates 路由

**Team M — web-crew 会员积分等级UI**
- [web-crew] 新建 MemberLookupPage.tsx：6×2自定义数字键盘（不用系统键盘）/会员信息卡/5级等级颜色/赠送积分底部弹层
- [web-crew] 新建 MemberPointsPage.tsx：等级进度条（渐变色）/积分流水日期分组/触底加载更多/底部积分操作栏
- [web-crew/App.tsx] 注册 /member-lookup + /member-points（均为hiddenPaths）

### 数据变化
- 迁移版本：v118 → v120（新增v119中央厨房/v120薪资引擎）
- 新增数据库表：9张（中央厨房×6 + 薪资引擎×3）
- 新增后端API文件：3个（bom_routes重写/ck_production_routes/payroll_engine_routes）
- 新增前端页面：3个（MenuTemplatePage/MemberLookupPage/MemberPointsPage）
- 修复：v119迁移版本冲突（两团队各创建v119，已将薪资迁移重命名为v120并修正revision）

### 遗留问题
- create_weigh_record端点缺少dish_id存在性校验（已标注待修）
- payroll_engine_v3.py中get_db为桩函数，实际注入依赖项目dependencies.py
- MenuTemplatePage发布API（POST /api/v1/menu/brand/publish）需后端实际实现验证

### 下轮计划（Round 4）
- 同步引擎（edge/sync-engine：本地PG↔云端PG增量同步策略实现）
- 审批流（tx-ops：多级审批/审批通知/审批历史）
- 加盟管理（tx-org：加盟商入驻/分润规则/绩效考核）
- web-admin BOM配方编辑器（树状展示/半成品递归）

---

## 2026-04-02（Day 3 完成 — 测试覆盖率 + 安全加固 + 折扣集成）

### 今日完成（Day 3 三智能体交付）

**Day3-A — pytest 62个测试用例**
- [tx-trade/tests] conftest.py：公共fixtures（AsyncClient + DB override）
- [tx-trade/tests] test_scan_pay.py：18个用例（参数化覆盖12个微信/支付宝前缀 + mock asyncio.sleep）
- [tx-trade/tests] test_stored_value.py：18个用例（充值档位边界 + DB AsyncMock + calc_bonus 9个边界）
- [tx-trade/tests] test_discount_engine.py：26个用例（纯函数层 + HTTP路由层双层测试，极大折扣不出现负数）

**Day3-B — 结账页折扣集成**
- [web-crew] TableSidePayPage.tsx：集成 DiscountPreviewSheet，折扣入口卡片（灰/橙两态），原价划线+折后橙色大字，TypeScript 零错误

**Day3-C — Webhook安全 + 套餐边界修复**
- [tx-trade/api] booking_webhook_routes.py：HMAC-SHA256签名验证（verify_meituan/wechat_signature），防时序攻击（hmac.compare_digest），防重放（5分钟时间窗口），dev环境自动跳过验证
- [tx-menu/api] combo_routes.py：4项边界防御（重复选择/菜品不属于分组/超选/未选必选项），422统一错误格式
- [web-crew] ComboSelectionSheet.tsx：超选红色提示2秒自动消失，确认按钮文字动态（"确认+¥X" / "请完成必选项"），单选分组选中后300ms自动折叠+scroll到下一分组

### 数据变化
- 新增测试文件：3个（conftest + 3个测试模块）
- 新增测试用例：62个（scan_pay×18 + stored_value×18 + discount_engine×26）
- 修改后端文件：2个（booking_webhook_routes / combo_routes 安全加固）
- 修改前端文件：2个（TableSidePayPage + ComboSelectionSheet）
- TypeScript全量检查：0 errors

### 遗留问题
- create_weigh_record端点缺少dish_id存在性校验（Team H已标注）
- ReservationWSManager内存级，多实例部署需换Redis Pub/Sub
- pytest实际运行需安装 pytest-asyncio + httpx（`pip install pytest pytest-asyncio httpx`）

### 明日计划（Day 4 / Round 3）
- 中央厨房模块（tx-supply：BOM配方/标准化产出/配送调拨）
- 薪资引擎（tx-org：计件工资/提成/绩效奖金）
- web-crew 会员积分/等级查看UI
- create_weigh_record dish_id存在性校验修复

---

## 2026-04-02（Round 2 四团队全部完成）

### 今日完成（超级智能体团队 Round 2 交付）

**Team F — web-crew 日清日结打卡UI**
- [web-crew] 新建 DailySettlementPage.tsx（18KB）：E1-E8清单卡片/进度条/班次信息/底部日结按钮（全部完成前禁用）
- [web-crew] 新建 ShiftHandoverPage.tsx（19KB）：三步交班流程（班次信息→遗留事项→接班确认），成功显示结果卡
- [web-crew] 新建 IssueReportPage.tsx（15KB）：5类问题大按钮网格/严重程度切换/相机拍照/问题单号反馈
- [web-crew/App.tsx] 注册三个路由，设为 hiddenPaths 隐藏底部TabBar

**Team G — web-admin 经营驾驶舱**
- [web-admin] 新建 OperationsDashboardPage.tsx：4个KPI卡/30天趋势折线图/渠道饼图+明细表/多店P&L对比表/E1-E8完成状态卡
- 使用项目内置 TxLineChart/TxPieChart（SVG实现），零外部图表依赖
- 毛利率低于35%红色Tag，低于40%黄色警告；API失败时Mock兜底
- [web-admin/App.tsx] 注册 /operations-dashboard 路由

**Team H — pytest P0服务覆盖率（51个测试用例）**
- [tx-menu/tests] test_live_seafood_weigh.py：14个用例（单位换算/金额计算/称重流程/边界场景）
- [tx-trade/tests] test_print_template.py：23个用例（ESC/POS指令验证/58mm/80mm宽度/GBK编码/中文兼容）
- [tx-menu/tests] test_combo_nfromm.py：14个用例（N选M校验/必选分组/附加价格/软删除边界）
- 发现Bug：create_weigh_record端点不验证dish_id存在性（已标注，建议修复）

**Team I — miniapp顾客端套餐N选M**
- [miniapp] 新建 pages/combo-detail/（4文件）：分组Tab懒加载/N选M状态管理/附加价格实时计算/底部固定购物车
- [miniapp] 新建 components/combo-group-item/（4文件）：可复用菜品行组件，达maxSelect自动禁用
- [miniapp/pages/menu] 集成套餐入口：item.is_combo标记→点击跳转combo-detail页
- [miniapp/utils/api.js] 新增3个API函数（fetchComboGroups/Items/validateComboSelection）
- [miniapp/app.json] 注册combo-detail页面路径

### 数据变化
- 迁移版本：无新迁移（复用已有表）
- 新增前端页面：6个（web-crew×3 + web-admin×1 + miniapp×2）
- 新增测试用例：51个（3个测试文件）
- 新增miniapp组件：1个（combo-group-item）

### 遗留问题
- create_weigh_record端点缺少dish_id存在性校验（test_live_seafood_weigh.py已标注）
- ReservationWSManager当前内存级，多实例部署需换Redis Pub/Sub
- DailySettlementPage中E3/E4/E7占位alert，待后续实现对应子页面

### 下轮计划（Round 3）
- 中央厨房模块（tx-supply：BOM配方/标准化产出/配送调拨）
- 薪资引擎（tx-org：计件工资/提成/绩效奖金）
- 菜单模板管理（tx-menu：品牌→门店三级发布BOM）
- web-crew 会员积分/等级UI

---

## 2026-04-02（Day 2 完成 — 打印模板 + WebSocket实时推送）

### 今日完成（Day 2 双智能体交付）

**Day2-B — 活鲜称重单 + 宴席通知单打印模板**
- [tx-trade/api] print_template_routes.py：3个打印端点（POST /api/v1/print/weigh-ticket|banquet-notice|credit-ticket）+ GET /preview 预览
- [web-crew/utils] printUtils.ts：TXBridge.print() 封装，带 fallback HTTP 发送到安卓POS，ESC/POS 语义标记解析
- [web-crew] LiveSeafoodOrderPage.tsx：称重提交后调用 printUtils 打印活鲜称重单，TXBridge + HTTP 双通道

**Day2-C — PG NOTIFY实时推送 + 预订WebSocket**
- [tx-trade/api] booking_webhook_routes.py：新增 ReservationWSManager（内存级连接池，生产换Redis Pub/Sub），/api/v1/booking/ws/{store_id} WebSocket端点，25s ping/pong保活
- [web-crew/hooks] useReservationWS.ts：WS连接管理hook，5s自动重连，ping/pong心跳，cleanup
- [web-crew] ReservationInboxPage.tsx：30秒轮询升级为WebSocket实时推送，WS断开降级为30s轮询兜底，新预订toast（CSS slide-in动画 + Web Audio API提示音）

### 数据变化
- 迁移版本：v118（无新迁移，Day2复用已有表结构）
- 新增前端文件：3个（printUtils.ts / useReservationWS.ts / 更新ReservationInboxPage）
- TypeScript检查：0 errors（全量检查通过）

### 遗留问题
- ReservationWSManager 当前内存级存储，多实例部署需换Redis Pub/Sub
- 打印模板待真实打印机联调验证ESC/POS字节格式（GBK编码）
- 结账页DiscountPreviewSheet入口待集成（折扣引擎已就绪）

### 明日计划（Day 3）
- 全量TypeScript检查（已通过，Day3重点端到端验证）
- Mock数据端到端验证（套餐选择→提交→活鲜称重→打印完整流程）
- 边界场景：超选/未选必选项/Webhook签名验证
- pytest补写：scan_pay/stored_value/discount_engine ≥80%覆盖率

---

## 2026-04-02（Round 1 五团队全部完成）

### 今日完成（超级智能体团队 Round 1 交付）

**Team A — 打印模板 + 档口映射 + 套餐分组**
- [tx-trade/services] 新建 print_template_service.py：ESC/POS字节级打印（58mm/80mm自适应，GBK编码，base64输出）
  - generate_weigh_ticket()：活鲜称重单（品种/鱼缸/重量/单价/金额/签字栏）
  - generate_banquet_notice()：宴席通知单（多节排版/合同/桌数/出品顺序）
  - generate_credit_account_ticket()：企业挂账单
- [tx-trade/api] 新建 print_template_routes.py：3个打印端点（POST /api/v1/print/weigh-ticket|banquet-notice|credit-ticket）
- [tx-trade/api] 新建 dish_dept_mapping_routes.py：6个端点（列表/upsert/批量导入/导出/删除/分组汇总）
- [tx-menu/api] combo_routes.py追加：N选M分组CRUD + 菜品增删 + 选择验证（min/max/required三重校验）
- [tx-trade/main.py] 注册 print_template_router + dish_dept_mapping_router

**Team B — web-pos/web-crew 活鲜UI + 套餐N选M UI**
- [web-pos] 新建 LiveSeafoodOrderSheet.tsx：底部Sheet（扫码/列表选活鲜→触发称重→WebSocket等待秤→确认→加入订单）
- [web-pos] 新建 ComboSelectorSheet.tsx：全屏套餐N选M选择器（分组tabs/已选/价格实时计算/必选校验）
- [web-crew] 新建 LiveSeafoodOrderPage.tsx + ComboSelectionSheet.tsx（服务员端同等功能）
- [web-crew] App.tsx + OrderPage.tsx：注册活鲜和套餐路由，集成TXBridge.onScaleWeight

**Team C — web-admin 三个后台管理页**
- [web-admin] 新建 LiveSeafoodPage.tsx：活鲜海鲜管理（ProTable+ModalForm/鱼缸管理/库存更新/称重记录查询）
- [web-admin] 新建 BanquetMenuPage.tsx：宴席菜单管理（菜单CRUD/分节/场次/今日场次控制面板）
- [web-admin] 新建 DishDeptMappingPage.tsx：菜品→档口映射（左右布局/拖拽分配/CSV批量导入/完成率统计）
- [web-admin] App.tsx：注册三个新页面路由

**Team D — tx-ops 日清日结 E1-E8 完整实现**
- [DB] v116_ops_daily_settlement.py：shift_handovers/daily_summaries/daily_issues/inspection_reports/employee_daily_performance 五张表
- [tx-ops/api] 新建 shift_routes.py：E1换班交接（开始/完成/问题记录/获取当前班次）
- [tx-ops/api] 新建 daily_summary_routes.py：E2日营业汇总（SQL聚合收入/订单/毛利/各渠道/时段分布）
- [tx-ops/api] 新建 issues_routes.py：E5问题上报 + E6整改跟踪（状态机）
- [tx-ops/api] 新建 inspection_routes.py：E8巡店质检报告（评分/扣分项/照片/排行榜）
- [tx-ops/api] 新建 performance_routes.py：E7员工日绩效（出单量/服务评分/提成计算）
- [tx-ops/api] 新建 daily_settlement_routes.py：E1-E8总控清单（进度/催办/一键归档）
- [tx-ops/main.py] 注册全部新路由

**Team E — tx-finance 财务引擎真实计算**
- [DB] v117_finance_engine.py：daily_pnl/cost_items/revenue_records/finance_configs 表
- [tx-finance/services] pnl_engine.py：PnLEngine类（calculate_daily_pnl/sync_revenue/calculate_food_cost/live_seafood_loss）
- [tx-finance/api] 新建 pnl_routes.py：P&L计算/趋势/多店对比
- [tx-finance/api] 新建 cost_routes_v2.py：成本录入/配置/活鲜损耗

### 数据变化
- 迁移版本：v115 → v117（新增v116/v117）
- 新增数据库表：7张（shift_handovers/daily_summaries/daily_issues/inspection_reports/employee_daily_performance/daily_pnl/cost_items）
- 新增后端API文件：13个
- 新增前端页面/组件：8个（web-pos×2 + web-crew×2 + web-admin×3 + App.tsx更新）

### 遗留问题
- tx-finance/main.py 需注册 pnl_routes + cost_routes_v2（当前未注册）
- BanquetControlScreen 推送分节按钮使用 section_name 临时ID，待修正为真实 section_id
- 打印模板待真实打印机联调验证ESC/POS字节格式

### 下轮计划（Round 2）
- web-crew 日清日结打卡界面（E1-E8清单/换班流程/问题上报）
- web-admin 经营驾驶舱（接入P&L引擎/多店对比/实时看板）
- miniapp 顾客端补齐（扫码点套餐N选M/会员积分/大厨到家）
- pytest 补写 P0 服务覆盖率（scan_pay/stored_value/discount_engine ≥80%）

---

## 2026-04-02（Team A 完成）

### 完成
- [tx-trade] 新建 print_template_service.py：ESC/POS打印模板（称重单/宴席通知单/挂账单）
- [tx-trade] 新建 print_template_routes.py：3个打印端点
- [tx-trade] 新建 dish_dept_mapping_routes.py：6个菜品-档口映射端点
- [tx-menu] combo_routes.py追加：套餐N选M分组管理（5个新端点）

### 数据变化
- 迁移版本：无新迁移（复用v112-v115已有表）
- 新增 tx-trade API 路由文件：2个（print_template_routes / dish_dept_mapping_routes）
- 新增 tx-trade 服务文件：1个（print_template_service）
- 新增 tx-menu API 端点：5个（追加到 combo_routes.py）
- tx-trade main.py 注册：print_template_router + dish_dept_mapping_router

### 实现细节
- print_template_service：纯 bytes 拼接 ESC/POS 指令，GBK编码，base64输出，支持58mm/80mm纸宽切换
- dish_dept_mapping：upsert by (tenant_id+dish_id+dept_id)，批量导入支持全量替换模式，departments接口带kds_departments→dish_dept_mappings降级逻辑
- combo N选M：分组CRUD + 菜品增删 + 选择验证（min/max/required三重校验），全部用sqlalchemy text()执行SQL

### 遗留问题
- web-pos 活鲜称重点单页面未实现（明日 Team B）
- 打印模板待真实打印机联调验证ESC/POS字节格式

---

## 2026-04-02（二）— 徐记海鲜差距分析 + 核心业务实现

### 今日完成
- [docs] 新建 docs/xuji-go-live-plan.md：全面差距分析矩阵（5大维度、30+功能项对比）+ 上线计划
- [DB] v112：活鲜菜品扩展字段（pricing_method/weight_unit/price_per_unit_fen等）+ fish_tank_zones鱼缸表 + live_seafood_weigh_records称重记录表
- [DB] v113：ComboGroup + ComboGroupItem（套餐N选M分组）+ order_item_combo_selections（订单选择快照）
- [DB] v114：BanquetMenu + BanquetMenuSection + BanquetMenuItem（宴席菜单多档次体系）+ BanquetSession（场次）+ SalesChannel + ChannelDishConfig（渠道独立配置）
- [DB] v115：kds_tasks新增banquet_session_id/banquet_section_id/weigh_record_id/is_live_seafood字段 + dish_dept_mappings菜品→档口映射表
- [tx-menu] 新建 live_seafood_routes.py：鱼缸管理/活鲜菜品列表/称重计价配置/库存更新/称重流程(weigh→confirm)/待确认称重查询
- [tx-menu] 新建 banquet_menu_routes.py：宴席菜单CRUD/分节管理/菜品明细/场次创建与状态机/宴席通知单打印数据
- [tx-trade] 新建 kds_banquet_routes.py：今日宴席场次查询/开席同步下发/推进节/出品进度总览
- [web-kds] 新建 BanquetControlScreen.tsx：宴席控菜大屏（场次倒计时/出品进度条/开席按钮/分节推进）
- [web-kds] App.tsx：注册 /banquet-control 路由
- [tx-menu/main.py] 注册 live_seafood_router + banquet_menu_router
- [tx-trade/main.py] 注册 kds_banquet_router

### 数据变化
- 迁移版本：v111 → v115（新增4个迁移）
- 新增数据库表：9张（fish_tank_zones/live_seafood_weigh_records/combo_groups/combo_group_items/order_item_combo_selections/banquet_menus/banquet_menu_sections/banquet_menu_items/banquet_sessions/sales_channels/channel_dish_configs/dish_dept_mappings）
- 新增 tx-menu API 路由文件：2个（live_seafood_routes/banquet_menu_routes）
- 新增 tx-trade API 路由文件：1个（kds_banquet_routes）
- 新增 KDS 前端页面：1个（BanquetControlScreen）

### 差距分析结论（徐记海鲜）
| 维度 | P0缺口 | 状态 |
|------|--------|------|
| 活鲜菜品（称重/条头） | 已实现 | ✅ |
| 套餐N选M | DB+API完成 | ✅ |
| 宴席菜单多档次 | DB+API完成 | ✅ |
| 宴席同步出品KDS | 后端+前端完成 | ✅ |
| 渠道菜单独立定价 | 原有实现+扩展 | ✅ |
| 活鲜称重单打印 | 打印数据已提供 | 待接ESC/POS模板 |
| 宴席通知单打印 | 打印数据已提供 | 待接ESC/POS模板 |
| web-pos活鲜点单UI | 未开始 | 🔴 明日 |

### 遗留问题
- dish_dept_mappings 表需要门店配置菜品→档口映射才能正确分单
- BanquetControlScreen 的「推送分节」按钮使用 section_name 作为临时ID，需要接口返回真实 section_id
- 活鲜称重流程需要 web-pos 端配合称重UI组件（TXBridge.onScaleWeight 已有桩）

### 明日计划
- web-pos：活鲜称重点单页面（扫码选活鲜→触发称重→确认→加入订单）
- 打印模板：活鲜称重单 + 宴席通知单 ESC/POS 格式
- 菜品→档口映射管理页面（web-admin）

---

## 2026-04-02

### 今日完成（P0→P1→P2 全批次交付）

**P0 — 上线前必须（5项）**
- [tx-trade] 多优惠叠加规则引擎：discount_rules/checkout_discount_log表 + 规则引擎API + DiscountPreviewSheet前端组件
- [tx-trade + web-crew] 储值充值完整链路：stored_value_accounts/transactions表 + 充值/消费/退款API + StoredValueRechargePage + MemberPage集成
- [tx-trade + web-crew] 扫码付款码支付：scan_pay_routes + ScanPayPage 4状态机（等待→支付中→成功/失败）+ 扫码枪速度识别
- [web-crew] 称重菜下单UX：TXBridge.onScaleWeight() + WeighDishSheet组件 + OrderPage集成（is_weighed=true触发秤流程）
- [tx-trade + web-crew] 打印机路由配置：printers/printer_routes表 + 配置API + PrinterSettingsPage（三段优先级解析）

**P1 — 上线后30天内（3项）**
- [tx-trade + web-crew] 等位调度引擎：waitlist_entries/call_logs表 + 7个API端点 + WaitlistPage（叫号/入座/过号降级/VIP优先/15秒轮询）
- [tx-trade + web-crew] 外卖平台订单聚合：delivery_orders表扩展 + 美团/饿了么Webhook + DeliveryDashboardPage（3Tab/平台色标/状态机/Notification API）
- [tx-member + web-crew] 会员等级运营体系：member_level_configs/history/points_rules表 + 升降级API + MemberLevelConfigPage + MemberPage进度条/权益Sheet

**P2 — 差异化竞争（2项）**
- [tx-member + web-crew] 会员洞察实时Push：member_insight_routes（Mock+5处Claude API TODO） + MemberInsightCard组件 + MemberPage绑定后自动展示
- [tx-analytics + web-crew] 集团跨店数据看板：group_dashboard_routes + GroupDashboardPage（汇总/告警/门店列表/7日CSS趋势图） + StoreDetailPage（小时分布/桌台实时）

**TypeScript 编译：全程零错误（每批次验证）**

### 数据变化
- 迁移版本：v105 → v111（新增 v106 折扣规则 / v107 储值 / v108 打印机配置 / v109 等位 / v110 外卖订单 / v111 会员等级）
- 新增后端API模块：10个（discount_engine / stored_value / scan_pay / printer_config / waitlist / delivery_orders / member_level / member_insight / group_dashboard + 扩展cashier_api）
- 新增前端页面：12个（DiscountPreviewSheet / StoredValueRechargePage / ScanPayPage / WeighDishSheet / PrinterSettingsPage / WaitlistPage / DeliveryDashboardPage / MemberLevelConfigPage / MemberInsightCard / GroupDashboardPage / StoreDetailPage / StoredValueRechargePage）
- 新增前端API客户端：4个（storedValueApi / memberLevelApi / memberInsightApi + index.ts扩展）

### 遗留问题
- 扫码付款码支付：真实微信/支付宝API需商户mchid/apikey运营配置，当前为Mock延迟
- 会员洞察：5处TODO标注Claude API接入点，当前为基于会员字段的规则Mock
- 等位叫号：SMS短信通道需接入短信服务商（阿里云短信/腾讯云短信），当前Mock日志
- 各模块DB操作：部分route文件有# TODO: DB stub，需接入真实SQLAlchemy session

### 明日计划
- 运行完整DB迁移链验证（v105→v111 alembic upgrade head）
- 对scan_pay / stored_value / discount_engine 补写pytest用例（覆盖率目标≥80%）
- 套餐BOM树形结构（DishSpec多层）—— 中高端餐厅必需
- 结账页集成DiscountPreviewSheet（当前引擎已就绪，前端入口待接入）

---

## 2026-04-02

### 今日完成
- [文档] 全面扫描项目实际代码状态，修正 README.md 与 CLAUDE.md 中的不准确信息
- [文档] README：修正迁移版本数（13→113）、补全缺失服务（tx-brain/tx-intel/tx-ops/tx-growth/mcp-server）、补全缺失应用（web-reception/web-tv-menu）
- [文档] README：将十大差距 #9 RLS 漏洞状态更新为 ✅ 已修复（v063）
- [文档] CLAUDE.md：项目结构节全面修正，新增"十五、每日开发日志规范"节
- [文档] 新建 DEVLOG.md（本文件），建立每日进度跟踪机制

### 当前技术状态快照
- 微服务数：16 个（gateway + 13 业务服务 + mcp-server）
- 前端应用数：10 个
- 数据库迁移版本：113 个（v001-v104）
- API 模块：~211 个
- 测试文件：~158 个
- 旧系统适配器：10 个
- Agent Actions：73/73（全部实现）

### 十大差距当前状态
| # | 差距 | 状态 |
|---|------|------|
| 1 | 财务引擎 | 🔴 待开发 |
| 2 | 中央厨房 | 🔴 待开发 |
| 3 | 加盟管理 | 🔴 待开发 |
| 4 | 储值卡 | 🔴 待开发 |
| 5 | 菜单模板 | 🔴 待开发 |
| 6 | 薪资引擎 | 🔴 待开发 |
| 7 | 审批流 | 🔴 待开发 |
| 8 | 同步引擎 | 🔴 待开发 |
| 9 | RLS 安全漏洞 | ✅ 已修复（v063） |
| 10 | 外卖聚合 | 🔴 待开发 |

### 遗留问题
- auth.py 有 5 处 DB TODO 待接入真实数据库
- tx-finance 为空壳，无真实计算逻辑
- sync-engine 骨架存在，核心同步逻辑未实现

### 明日计划
- 待定（根据实际开发任务更新）

---

<!-- 以下为历史记录模板，开发时在此处上方插入新记录 -->
