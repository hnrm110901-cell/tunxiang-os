# tx-predict · 预测引擎（:8013）

> 🟡 **POST-W12 MIGRATION MARKER**（2026-05-06, sprint-0-dedup R4）
>
> 本服务计划在 W12（2026-07-29）之后合并入 `services/tx-agent/sub/predict/` 子模块，
> 作为屯象 V4 Sprint 4 智能层收敛的一部分。
>
> **维护期约束**：
> - ❌ 不要在本 service 顶层新增 router / API（会增加迁移成本）
> - ✅ 新功能：先写在 `tx-agent`，迁移时一并合并；OR 等 W12 后规划干净迁移
> - ✅ 现有 router 的 bug 修复 / 性能优化照常
>
> 详见：[`.omc/plans/post-w12-tx-agent-merger.md`](../../.omc/plans/post-w12-tx-agent-merger.md)

---

## 职责

V6.0 核心模块，对标 Toast IQ / Fourth iQ 需求预测能力：

- 客流预测（历史订单时序 + 天气/节假日修正）
- 菜品需求预测（加权移动平均 + 多维修正）
- 营收预测（客流 × 客单价）
- 天气数据集成（和风天气 API）

## 端口

`:8013`

## 入口

`services/tx-predict/src/main.py`
