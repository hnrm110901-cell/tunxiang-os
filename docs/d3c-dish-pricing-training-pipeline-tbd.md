# D3c — 菜品动态定价 ML 训练管线（TBD）

> 状态：**未实施**。Sprint D Wave 3 仅交付 v0 规则版骨架（边缘 Swift + 云端 Python）。
> 真实 GBDT 训练管线 + Core ML 转换 + 影子模式回测 → Wave 4+ 实施。
>
> 本文件目的：描述未来落地路径，避免空中楼阁。

---

## 1. 目标

| 指标 | 当前（v0 规则版） | 上线后（ML 模型） |
|---|---|---|
| 平均毛利提升 | 0pp（无效果，仅毛利底线兜底） | **+2pp** vs 历史均值 |
| 推荐覆盖率 | 100% 菜品（规则可计算） | ≥ 80% 菜品（其余走规则降级） |
| 边缘 P99 推理延迟 | < 5ms（规则） | < 50ms（CoreML 推理） |
| 模型置信度 | 固定 0.78 / 0.60 / 0.50 | 真实 calibrated 概率 |

---

## 2. 数据源

### 2.1 训练样本来源（events 表）

通过 `shared/events/` 统一事件总线（v147）抓取：

```sql
-- 按菜品聚合的真实成交价（最近 90 天）
SELECT
    e.tenant_id,
    e.store_id,
    (e.payload->>'dish_id')::uuid AS dish_id,
    (e.payload->>'unit_price_fen')::int AS unit_price_fen,
    (e.payload->>'cost_fen')::int AS cost_fen,
    EXTRACT(HOUR FROM e.occurred_at) AS hour_of_day,
    EXTRACT(DOW FROM e.occurred_at) AS day_of_week,
    e.occurred_at
FROM events e
WHERE e.event_type = 'ORDER.PAID'
  AND e.occurred_at >= NOW() - INTERVAL '90 days';
```

### 2.2 上下文特征联表

- **库存状态** — `mv_inventory_bom`（v148）：`near_expiry / normal / low_stock`
- **客流预测** — `coreml-bridge:8100/predict/traffic` 历史回放或 `mv_store_pnl` 时段聚合
- **天气** — 后续接入第三方天气 API（小雨/暴雨对客流影响）
- **节假日** — 静态节假日表（春节/十一/中秋等）

### 2.3 标签（target）

`gross_margin_per_order_fen` — 该订单该菜品贡献的毛利金额（分）。
不直接预测最优价（缺乏因果），而是给候选价 → 模型预测期望毛利 → 取期望毛利最大的价。

---

## 3. 模型选择

**首选 GBDT（XGBoost / LightGBM）**

| 维度 | 理由 |
|---|---|
| 特征 | 异构表格特征（数值 + 类目混合）— GBDT 强项 |
| 数据量 | 单店日均 ~500 单，10 店 90 天 ~450K 样本 — GBDT 足够 |
| 可解释 | SHAP 值可向门店店长解释「为什么涨价 5%」 |
| Core ML | XGBoost/LightGBM 都有官方 → Core ML 转换工具 |
| 训练成本 | 单机 CPU 30 分钟内训完 — Mac mini M4 也能跑 |

**不选神经网络**：样本量不够，过拟合风险高，可解释性差。

---

## 4. 训练管线（拟实施）

### 4.1 部署位置
- 训练任务：云端 `services/tx-brain/scripts/train_dish_pricing.py`（每周一夜 02:00 跑）
- 转换 Core ML：训练完成后用 `coremltools` 转换 `.mlmodel`
- 分发：模型版本号纳入 `coreml-bridge` ModelManager.registerModel()，热替换

### 4.2 流程
```
events 表 ──┐
mv_*       ─┼─→ feature_engineering.py ─→ X_train, y_train
其他源     ─┘
                                          │
                                          ↓
                         train_xgboost.py (sklearn-style)
                                          │
                                          ↓
                         coremltools.convert(model)
                                          │
                                          ↓
                       DishPricePredictor.mlmodel (~5MB)
                                          │
                                          ↓
                  上传 oss://tx-models/dish_pricing/v{n}.mlmodel
                                          │
                                          ↓
                  edge/sync-engine 拉到 Mac mini
                                          │
                                          ↓
                  ModelManager.warmup() 重新加载 → 热替换
```

### 4.3 评估
- **离线**：5 折时间序列交叉验证（不能随机 shuffle，否则数据泄露）
  - RMSE 目标：单笔毛利预测 ≤ 1.5 元
- **影子模式**：14 天双轨运行
  - 模型预测但不下发到 POS UI
  - 收集预测价 vs 实际成交价 vs 实际毛利
  - 上线门槛：预测置信度 > 0.7 的样本中，模型平均毛利 ≥ 历史均值 + 2pp
- **A/B 灰度**：Phase 1 = 5% 门店 → Phase 2 = 50% → Phase 3 = 100%
  - 任一阶段毛利 < baseline → 自动回滚到规则版

---

## 5. 上线 Gate（不可跨过）

- [ ] 离线 5 折时间 CV RMSE 通过
- [ ] 影子模式 14 天达 +2pp 毛利目标
- [ ] 三条硬约束验证通过（毛利底线 / 食安合规 / 客户体验）
  - 毛利底线已在 service 层 GUARD（即使模型疯掉也兜底）
- [ ] 每条决策有 AgentDecisionLog 留痕，含 model_version
- [ ] Mac mini 部署灰度 5% 一周无回滚

---

## 6. Swift 端测试（TBD）

`edge/coreml-bridge/Tests/` 目前没有 Swift 测试基础设施（`tests/` 是 Python legacy）。
未来需要：
- 在 `Package.swift` 添加 `.testTarget(name: "CoreMLBridgeTests", dependencies: ["CoreMLBridge"])`
- 写 `Tests/CoreMLBridgeTests/DishPricePredictorTests.swift`
- 单测 `predictDishPrice(features:)` 的关键场景：
  - rogue input（cost=50%, multiplier=-0.50）→ 验证 floor protection 生效
  - 正常输入（near_expiry + low_traffic）→ 验证签名调价方向正确
  - 临界值（margin 刚好 15%）→ 验证不误触 protection

当前已知问题：
- `Sources/CoreMLBridge/ModelManager.swift` 与 `Sources/CoreMLBridge/Services/ModelManager.swift`
  存在源文件重复（不同字段定义），导致 `swift build` 失败。
- 这是预存在问题（Wave 3 之前已存在），需独立 PR 清理。
- 暂不影响 D3c 业务路径，因 Python 端 edge_client 走 HTTP，黑盒不受影响。

---

## 7. 时间表（建议）

| 阶段 | 时长 | 产出 |
|---|---|---|
| 数据集构建 | 1 周 | 90 天事件表 + 联表 + 特征工程脚本 |
| 模型训练 + 离线评估 | 1 周 | XGBoost baseline + RMSE + SHAP 解释 |
| Core ML 转换 + Mac mini 部署 | 0.5 周 | .mlmodel 文件 + ModelManager.warmup() 真接入 |
| 影子模式 | 2 周 | 双轨数据 + 上线 Gate 报告 |
| 灰度上线 | 2 周 | 5% → 50% → 100% |
| **总计** | **~6.5 周** | 真正能达成 +2pp 毛利目标 |

---

## 8. 风险

1. **冷启动**：新菜品没有历史数据 → 自动降级到 v0 规则版（已实现）
2. **节假日污染**：春节/十一数据点权重过高 → 训练时按节假日 indicator 单独建模或剔除
3. **促销污染**：折扣订单的低价不代表「自然成交价」→ 训练样本剔除 `discount_rate > 0.1` 的订单
4. **季节性**：海鲜价格随季节波动 → 加月份 one-hot 特征
5. **客流预测误差传递**：traffic_forecast 是另一个模型的输出，误差累计 → 影子模式监控双模型联合表现

---

## 9. 与其他 Agent 的关系

- **discount_guardian**（D1）：折扣守护检查的是事后折扣，dish_pricing 是事前定价；二者互不冲突
- **menu_optimizer**：菜单优化决定「卖什么」，dish_pricing 决定「卖多少钱」；解耦
- **inventory_sentinel**：库存预警提供 inventory_status 输入信号，下游消费者
