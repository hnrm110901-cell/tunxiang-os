# 屯象OS P0 冲刺开发计划 — 先打透四个板块

> 基于 V2 产品架构 vs 代码实现差距分析
> 目标: 交易中台 50%→85% | 供应链中台 22%→60% | 日清日结 12%→50% | 守门员Agent 75%→90%
> 预计周期: 6周 (Sprint 1-6)

---

## 优先级原则

徐记海鲜样板要先证明四个结果：
1. **少亏折扣** → 守门员Agent + 收银稽核
2. **少亏损耗** → 供应链中台 (BOM/盘点/损耗)
3. **更快出餐翻台** → KDS调度 + 日清日结
4. **总部看清门店** → 经营驾驶舱 + 日清日结

---

## Sprint 1-2: 供应链中台补全 (最大缺口 22%→50%)

### S1-1 BOM与工艺中心 (C2)
**当前**: 表已建(v007), 无业务逻辑
**目标**: 标准BOM录入 + 理论耗料计算 + BOM版本管理

| 任务 | 文件位置 | 工作量 |
|------|---------|--------|
| BOM CRUD服务 | tx-supply/src/services/bom_service.py | 2天 |
| 理论耗料计算引擎 | tx-supply/src/services/cost_calculator.py | 2天 |
| BOM版本管理 | tx-supply/src/services/bom_version.py | 1天 |
| API路由 | tx-supply/src/api/bom_routes.py | 1天 |
| 测试 | tx-supply/src/tests/test_bom.py | 1天 |

### S1-2 成本核算与毛利中心 (C7)
**当前**: 几乎为零
**目标**: 理论成本 vs 实际成本 + 菜品毛利计算 + 门店毛利日报

| 任务 | 文件位置 | 工作量 |
|------|---------|--------|
| 理论成本引擎(基于BOM) | tx-supply/src/services/theoretical_cost.py | 2天 |
| 实际成本归集 | tx-supply/src/services/actual_cost.py | 2天 |
| 菜品毛利计算 | tx-supply/src/services/dish_margin.py | 1天 |
| 门店毛利日报 | tx-analytics/src/services/store_margin_report.py | 1天 |
| 成本偏差分析 | tx-analytics/src/services/cost_variance.py | 1天 |

### S1-3 领料扣料与损耗中心 (C6)
**当前**: waste_guard有基础
**目标**: 自动扣料(基于BOM+订单) + 盘点差异 + 损耗归因

| 任务 | 文件位置 | 工作量 |
|------|---------|--------|
| 自动扣料引擎(订单触发) | tx-supply/src/services/auto_deduction.py | 2天 |
| 盘点服务 | tx-supply/src/services/stocktake_service.py | 2天 |
| 损耗归因分析 | tx-supply/src/services/waste_attribution.py | 1天 |

### S1-4 原料与批次库存中心 (C4)
**当前**: 模型有, 业务逻辑缺
**目标**: 入库/出库 + 效期监控 + 安全库存预警 + 沽清预测

| 任务 | 文件位置 | 工作量 |
|------|---------|--------|
| 入库出库服务 | tx-supply/src/services/inventory_io.py | 2天 |
| 效期监控+临期预警 | tx-supply/src/services/expiry_monitor.py | 1天 |
| 安全库存+沽清预测 | tx-supply/src/services/stock_forecast.py | 1天 |

**Sprint 1-2 合计: ~22天工作量**

---

## Sprint 3-4: 交易中台补全 (50%→85%)

### S3-1 KDS与出餐调度中心 (B4) — 从30%到75%
**当前**: web-kds有前端, 后端逻辑薄
**目标**: 档口分单 + 出餐排序 + 催菜 + 超时预警

| 任务 | 文件位置 | 工作量 |
|------|---------|--------|
| 档口分单引擎 | tx-trade/src/services/kds_dispatch.py | 2天 |
| 出餐排序算法 | tx-trade/src/services/cooking_scheduler.py | 2天 |
| 催菜/重做/缺料处理 | tx-trade/src/services/kds_actions.py | 1天 |
| 出餐超时预警(联动Agent) | tx-trade/src/services/cooking_timeout.py | 1天 |
| web-kds前端补全(6个页面) | apps/web-kds/src/ | 3天 |

### S3-2 桌台与包厢经营中心 (B2) — 从40%到70%
**当前**: 状态机有, 业务逻辑缺

| 任务 | 文件位置 | 工作量 |
|------|---------|--------|
| 转台/并台/拆台 | tx-trade/src/services/table_operations.py | 2天 |
| 包厢低消规则引擎 | tx-trade/src/services/room_rules.py | 1天 |
| 翻台监控+热力图数据 | tx-analytics/src/services/table_analytics.py | 1天 |

### S3-3 交班对账与稽核中心 (B8) — 从40%到75%

| 任务 | 文件位置 | 工作量 |
|------|---------|--------|
| 收银员交班服务 | tx-trade/src/services/shift_handover.py | 2天 |
| 班次对账+现金长短款 | tx-trade/src/services/shift_reconciliation.py | 1天 |
| 渠道核对(微信/支付宝/现金) | tx-trade/src/services/channel_verify.py | 1天 |

### S3-4 点单补全 (B3) — 从75%到90%

| 任务 | 文件位置 | 工作量 |
|------|---------|--------|
| 时价称重菜处理 | tx-trade/src/services/weighing_price.py | 1天 |
| 套餐/宴席下单 | tx-trade/src/services/combo_order.py | 1天 |
| 赠菜+催菜+起菜 | tx-trade/src/services/order_actions.py | 1天 |

**Sprint 3-4 合计: ~20天工作量**

---

## Sprint 5-6: 日清日结 + 守门员补全

### S5-1 日清日结操作层 (E) — 从12%到50%
**当前**: 仅有daily_ops_service.py骨架

| 任务 | 文件位置 | 工作量 |
|------|---------|--------|
| E1 开店准备流程 | tx-ops/src/services/store_opening.py | 2天 |
| E2 营业巡航看板 | tx-ops/src/services/cruise_monitor.py | 2天 |
| E5 闭店盘点流程 | tx-ops/src/services/store_closing.py | 2天 |
| E6 收银交班流程 | tx-ops/src/services/cashier_handover.py | 1天 |
| E7 店长日复盘 | tx-ops/src/services/daily_review.py | 2天 |
| E4 异常处置工作流 | tx-ops/src/services/exception_workflow.py | 2天 |
| 检查表模板引擎 | tx-ops/src/services/checklist_engine.py | 1天 |

### S5-2 守门员Agent补全 (G1) — 从75%到90%

| 任务 | 文件位置 | 工作量 |
|------|---------|--------|
| 收银稽核Agent | tx-agent/src/agents/skills/cashier_audit.py | 1天 |
| 沽清预警Agent | tx-agent/src/agents/skills/stockout_alert.py | 1天 |
| 审计留痕Agent | tx-agent/src/agents/skills/audit_trail.py | 1天 |

### S5-3 经营驾驶舱 (D1) — 最小可用版
**目标**: 店长能看到今日核心指标

| 任务 | 文件位置 | 工作量 |
|------|---------|--------|
| 今日营业总览API | tx-analytics/src/services/today_overview.py | 1天 |
| 门店排行API | tx-analytics/src/services/store_ranking.py | 1天 |
| 异常摘要API | tx-analytics/src/services/alert_summary.py | 1天 |
| web-hub驾驶舱前端 | apps/web-hub/src/pages/ (3个页面) | 2天 |

**Sprint 5-6 合计: ~20天工作量**

---

## 6周冲刺后的预期覆盖率

| 板块 | 当前 | Sprint后 | 提升 |
|------|------|---------|------|
| B 交易中台 | 50% | **85%** | +35% |
| C 供应链中台 | 22% | **55%** | +33% |
| E 日清日结 | 12% | **50%** | +38% |
| G1 守门员Agent | 75% | **90%** | +15% |
| D1 经营驾驶舱 | 40% | **65%** | +25% |
| **P0加权总覆盖** | **35%** | **65%** | **+30%** |

---

## 每个Sprint的交付里程碑

| Sprint | 周期 | 交付物 | 可演示成果 |
|--------|------|--------|-----------|
| S1 | Week 1-2 | BOM引擎+成本计算+自动扣料 | "一道菜卖出去,理论成本自动算出来" |
| S2 | Week 2-3 | 盘点+损耗归因+效期监控 | "今天损耗多少钱,原因是什么,一目了然" |
| S3 | Week 3-4 | KDS调度+桌台操作+交班 | "后厨不堆单,前台能转台,收银能交班" |
| S4 | Week 4-5 | 点单补全+收银稽核 | "完整堂食闭环:预订→点单→出餐→收银" |
| S5 | Week 5-6 | 开闭店流程+巡航 | "门店每天开店到闭店有标准流程" |
| S6 | Week 6 | 驾驶舱+3个新Agent | "总部打开手机看到所有门店实时状态" |

---

## 技术约束（继承审计修复期规则）

1. 所有新代码禁止 `except Exception`（守门员兜底除外+exc_info=True）
2. 金额统一存分(fen)，API返回元
3. 数据库新表必须 tenant_id + RLS
4. AI调用通过 ModelRouter
5. POS数据通过品智适配器，不直连数据库
6. 每个服务模块附带 ≥3 个测试
