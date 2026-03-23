# Agent 三分类映射（蓝图 → V3.0 代码）

> 蓝图定义守门员/优化型/增长型三类 Agent，本文档映射到代码中的 9 Skill Agent。

## 映射关系

### 守门员型 Agent（实时拦截，保护经营底线）

| 蓝图 Agent | 代码 Skill Agent | 核心能力 | 三条硬约束 |
|-----------|-----------------|---------|-----------|
| 折扣守门员 | **discount_guard** (P0) | 异常折扣检测、证照扫描 | 毛利底线 |
| 出餐守门员 | **serve_dispatch** (P1) | 出餐时间预测、超时告警 | 客户体验 |
| 食安守门员 | **store_inspect** (P2) | 食安巡检、保质期监控 | 食安合规 |

### 优化型 Agent（分析优化，降本增效）

| 蓝图 Agent | 代码 Skill Agent | 核心能力 | 价值指标 |
|-----------|-----------------|---------|---------|
| 库存优化 | **inventory_alert** (P1) | 需求预测(4算法)、补货告警、供应商评级 | 降低损耗率 |
| 排菜优化 | **smart_menu** (P0) | BOM成本仿真、四象限分类、菜单结构优化 | 提升毛利率 |
| 财务优化 | **finance_audit** (P1) | 营收异常检测、KPI快照、场景识别 | 降低成本率 |

### 增长型 Agent（主动出击，促进营收）

| 蓝图 Agent | 代码 Skill Agent | 核心能力 | 价值指标 |
|-----------|-----------------|---------|---------|
| 会员增长 | **member_insight** (P1) | RFM分析、流失召回、旅程触发 | 提升复购率 |
| 私域增长 | **private_ops** (P2) | 营销活动、绩效评分、宴会管理 | 提升客单价 |
| 服务增长 | **smart_service** (P2) | 投诉处理、培训管理、技能差距分析 | 提升满意度 |

## 约束校验层

所有三类 Agent 的决策输出都必须通过 `ConstraintChecker` 校验：

```
Agent 决策 → ConstraintChecker.check_all() → 通过 → 执行
                                            → 拦截 → 记录违规 + 通知
```

| 硬约束 | 守门员负责 | 优化型参考 | 增长型参考 |
|--------|-----------|-----------|-----------|
| 毛利底线 | discount_guard | smart_menu, finance_audit | private_ops |
| 食安合规 | store_inspect | inventory_alert | — |
| 客户体验 | serve_dispatch | — | member_insight, smart_service |

## Master Agent 编排规则

```
1. 守门员优先：任何时刻，守门员告警 > 优化建议 > 增长建议
2. 边缘优先：discount_guard + serve_dispatch 在 Mac mini Core ML 执行
3. 协同触发：库存告警 → 自动触发排菜调整（Memory Bus 传递 Finding）
4. 推送分级：守门员告警→拦截弹窗，优化建议→企微推送，增长建议→Agent Feed
```
