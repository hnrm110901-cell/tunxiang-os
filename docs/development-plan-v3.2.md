# 屯象OS V3.2 开发计划

> 综合三个来源的差距：23 系统替换 + 徐记蓝图 GAP + 品智借鉴 12 项
> 基线：V3.1.0（31 commits, 291 tests, 35 pages, 73/73 agents, 10 services）

---

## 总览：4 个 Sprint，8 周

| Sprint | 周期 | 主题 | 交付目标 |
|--------|------|------|--------|
| **S1** | W1-2 | 品智 P0 借鉴 + V2.x 核心迁移 | 快速开店/菜品发布/出品部门/角色级别 + 薪资/工单迁移 |
| **S2** | W3-4 | 品智 P1 借鉴 + 前端补齐 | 支付实收/营销方案/门店标签 + web-pos/kds 补齐 |
| **S3** | W5-6 | 23 系统 100% 替代 + 蓝图字段 | 剩余 V2.x 迁移 + Ontology 字段扩展到 50% |
| **S4** | W7-8 | 集成测试 + 性能优化 + v3.2.0 发布 | 全链路 E2E + 商米真机 + 压力测试 |

---

## Sprint 1：品智 P0 + V2.x 核心迁移（W1-2）

> 目标：让屯象OS在运营配置深度上不输品智，同时补齐红海云/蓝凌替代

### W1：品智 P0 四项

#### 1.1 快速开店 — 配置克隆 API
```
POST /api/v1/ops/stores/clone
Body: { source_store_id, target_store_id, clone_items: ["dishes","payments","tables","marketing","kds","roles"] }
```
- [ ] gateway 或 tx-ops 新增 `/stores/clone` 端点
- [ ] 后端逐项复制逻辑（菜品/支付/桌台/营销/KDS/角色）
- [ ] 前端 web-admin SystemPage 增加"快速开店"弹窗（3步向导：选门店→选配置→完成）
- [ ] 测试：≥5 个（全选/部分选/跨品牌限制）

#### 1.2 菜品三级发布方案
- [ ] tx-menu 新增模型：`PublishPlan`（发布方案）+ `PriceAdjustment`（价格调整方案）
- [ ] API：`POST /menu/publish-plans`（创建发布方案）+ `POST /menu/publish-plans/{id}/execute`（执行发布）
- [ ] API：`POST /menu/price-adjustments`（时段/节假日/外卖差异化定价）
- [ ] web-admin CatalogPage 增加"菜品发布"Tab + "价格调整"Tab
- [ ] 测试：≥6 个

#### 1.3 出品部门 → 打印/KDS 联动
- [ ] tx-trade 新增模型：`ProductionDept`（出品部门：热菜间/凉菜间/面点/海鲜/吧台）
- [ ] 菜品-出品部门关联（Dish 增加 `production_dept_id` 字段）
- [ ] 打印路由：出品部门 → 打印机映射配置
- [ ] KDS 路由：出品部门 → KDS 终端映射配置
- [ ] 加菜时自动分单到对应档口（ReceiptService.split_by_station 升级为按出品部门分）
- [ ] 测试：≥4 个

#### 1.4 角色级别体系 (1-10)
- [ ] Employee/Role 模型增加字段：
  ```
  role_level: int (1-10)
  max_discount_pct: float  # 单品折扣上限
  max_tip_off_fen: int     # 最大抹零金额(分)
  max_gift_fen: int        # 单品赠送上限(分)
  max_order_gift_fen: int  # 订单赠送上限(分)
  data_query_limit: str    # 查询时限(unlimited/7d/30d/90d/1y)
  ```
- [ ] 折扣审批弹层集成角色级别校验（超出角色权限→需上级审批）
- [ ] 测试：≥5 个

### W2：V2.x 核心 Service 迁移（红海云+蓝凌替代）

#### 2.1 薪资引擎迁移 → tx-org
- [ ] 从 V2.x 迁移 `salary_formula_engine.py`（1109 行）→ `services/tx-org/src/services/`
- [ ] 从 V2.x 迁移 `payroll_service.py`（928 行）
- [ ] 从 V2.x 迁移 `hr/payroll_service.py`（397 行）
- [ ] API：`POST /org/payroll/compute` + `GET /org/payroll/slips`
- [ ] 测试：≥8 个

#### 2.2 审批工单引擎迁移 → tx-ops
- [ ] 从 V2.x 迁移 `workflow_engine.py`（658 行）
- [ ] 从 V2.x 迁移 `approval_engine.py`（771 行）
- [ ] 从 V2.x 迁移 `hr/approval_workflow_service.py`（335 行）
- [ ] API：`POST /ops/workflows` + `POST /ops/approvals/{id}/approve`
- [ ] 测试：≥6 个

#### 2.3 社保/假期迁移 → tx-org
- [ ] 从 V2.x 迁移 `hr/social_insurance_service.py`（56 行）
- [ ] 从 V2.x 迁移 `hr/leave_service.py`（179 行）+ `leave_service.py`
- [ ] API：`GET /org/insurance` + `GET /org/leaves`
- [ ] 测试：≥4 个

**S1 验收**：`make test` 全通过 + 快速开店可演示 + 薪资计算可运行

---

## Sprint 2：品智 P1 + 前端补齐（W3-4）

### W3：品智 P1 四项

#### 3.1 支付实收属性 + 分类扩展
- [ ] Payment 模型增加 `is_actual_revenue: bool` + `actual_revenue_ratio: float` + `payment_category: str`（13 类）
- [ ] 结算汇总按实收/优惠分别统计
- [ ] 测试：≥3 个

#### 3.2 营销方案引擎（7 种 + 互斥规则）
- [ ] tx-member 新增模型：`MarketingScheme`（方案类型：特价/买赠/加价换购/再买/会员/订单折扣/满减）
- [ ] 执行顺序引擎：按优先级依次计算折扣
- [ ] 共享互斥规则：方案间可配置共享/互斥
- [ ] API：`CRUD /member/marketing-schemes` + `POST /member/marketing-schemes/calculate`
- [ ] 测试：≥8 个

#### 3.3 门店标签 + 沉睡天数
- [ ] Store 模型增加 `tags: JSON` + `store_category_id` + `store_tags: JSON`（3维度×N标签）
- [ ] 支付方式/营销方案增加 `last_used_at` + 沉睡天数查询 API
- [ ] 测试：≥3 个

### W4：前端路由补齐

#### 4.1 web-pos +4 页面
- [ ] `/pos/dashboard` — 门店工作台首页（今日 KPI + 待办 + Agent 建议）
- [ ] `/pos/queue` — 排队管理（取号/叫号/等位）
- [ ] `/pos/settings-lite` — 门店设置（桌台/打印/KDS 配置）
- [ ] `/pos/reports` — 门店报表（日报/周报/对比）

#### 4.2 web-kds +4 页面
- [ ] `/kds/history` — 出餐历史（按时段/档口统计）
- [ ] `/kds/stats` — 出餐统计（平均时长/超时率）
- [ ] `/kds/config` — 档口配置（出品部门→KDS 映射）
- [ ] `/kds/alerts` — 超时告警（实时 + 历史）

**S2 验收**：营销方案可配置可计算 + web-pos 12/12 路由 + web-kds 5/5 路由

---

## Sprint 3：23 系统 100% + 字段扩展（W5-6）

### W5：剩余 V2.x 迁移

#### 5.1 券体系迁移 → tx-member
- [ ] 从 V2.x 迁移 `coupon_distribution_service.py`（99 行）+ `coupon_roi_service.py`
- [ ] 实体卡管理（新开发，小）
- [ ] 储值卡核销逻辑
- [ ] 测试：≥4 个

#### 5.2 供应链扩展迁移 → tx-supply
- [ ] 从 V2.x 迁移 `supply_chain_service.py`（205 行）+ `supply_chain_integration.py`
- [ ] 批次追踪模型 + API
- [ ] 调拨单模型 + API
- [ ] 渠道发布（菜品→美团/饿了么推送，走 adapter）
- [ ] 测试：≥4 个

#### 5.3 菜单模板完善
- [ ] 确保 V3.0 Ontology 中 DishMaster→BrandMenu→StoreMenu 三级继承可用
- [ ] tx-menu 菜品发布方案与模板联动
- [ ] 测试：≥3 个

### W6：Ontology 字段扩展（23% → 50%）

#### 6.1 Order 扩展（蓝图 P0 字段）
- [ ] 增加：room_flag, customer_level, customer_tag, open_time
- [ ] OrderItem 增加：taste_value, cook_method, served_flag, discount_flag, approval_status

#### 6.2 Table 扩展
- [ ] 增加：min_spend, reservation_flag, reservation_time, dish_progress, pending_checkout_flag, vip_flag
- [ ] 桌台详情字段：expected_turnover_time, pending_dishes_count, urge_count, complaint_count

#### 6.3 KDS 专用模型
- [ ] 新增 `KDSTicket` 模型：ticket_id, priority_level, elapsed_time, station_name, chef_name, abnormal_type

#### 6.4 日清日结扩展
- [ ] DailyOpsNode 增加：planned_start/end_time, actual_start/end_time, check_score
- [ ] 盘点字段：theoretical_qty, actual_qty, variance_qty, variance_amount

**S3 验收**：23 系统 100% 可替代 + Ontology 字段覆盖 ≥50%

---

## Sprint 4：集成测试 + 优化 + 发布（W7-8）

### W7：全链路集成测试

#### 7.1 E2E 场景测试
- [ ] 场景 1：新店上线全流程（快速开店→配置→首笔收银→日结）
- [ ] 场景 2：完整收银链路（开台→点菜→KDS出餐→结算→支付→打印→交班）
- [ ] 场景 3：营销方案计算（特价+满减+会员折扣互斥/共享）
- [ ] 场景 4：Agent 决策→约束校验→企微推送→审批回调
- [ ] 场景 5：日清日结 E1→E8 全流程 + 复盘 + 整改闭环

#### 7.2 商米真机联调
- [ ] android-shell APK 构建 + 商米 T2 安装
- [ ] TXBridge 7 接口真机验证（打印/钱箱/秤/扫码/设备信息）
- [ ] WebView 性能测试（菜单切换 FPS ≥ 30）

### W8：性能优化 + v3.2.0 发布

#### 8.1 性能优化
- [ ] DB 查询优化（N+1 检查、索引补齐）
- [ ] 前端包体积优化（代码分割、懒加载）
- [ ] Docker 镜像瘦身

#### 8.2 发布
- [ ] `make test` 全通过（目标 ≥ 350 tests）
- [ ] `make smoke` 烟雾测试通过
- [ ] README 更新
- [ ] `git tag v3.2.0` + GitHub Release
- [ ] 更新 23 系统替换分析（确认 23/23 = 100%）

**S4 验收**：v3.2.0 发布 + 5 个 E2E 场景通过 + 商米真机可收银

---

## 交付物预估

| 指标 | V3.1.0 (当前) | V3.2.0 (目标) | 增量 |
|------|-------------|-------------|------|
| Tests | 291 | **≥350** | +60 |
| Pages | 35 | **43** | +8 |
| API endpoints | ~120 | **~160** | +40 |
| Services | 10 | **10** | 0（功能内增） |
| V2.x 迁移 | 7 算法 | **7 算法 + 7 service** | +3193 行 |
| 品智借鉴 | 0 | **8 项落地** | |
| 23 系统替代率 | 91% | **100%** | |
| 蓝图字段覆盖 | 23% | **≥50%** | |

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| V2.x service 迁移后 import 路径问题 | 编译失败 | 逐文件迁移 + 单元测试覆盖 |
| 营销方案互斥规则复杂度 | 计算错误 | 参考品智的执行顺序设计 + 大量测试 |
| 商米真机 WebView 性能 | FPS 不达标 | 动效降级 + 图片懒加载 |
| 8 周工期紧张 | 延期 | S1/S2 核心功能优先，S3/S4 可灵活调整 |

---

*本计划基于：23系统替换差距 + 徐记海鲜蓝图 GAP + 品智极智版 12 项借鉴，综合排序后形成 4 Sprint 8 周交付路线。*
