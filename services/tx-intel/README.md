# tx-intel · 市场情报中枢（:8011）

> 🟡 **POST-W12 MIGRATION MARKER**（2026-05-06, sprint-0-dedup R4）
>
> 本服务计划在 W12（2026-07-29）之后合并入 `services/tx-agent/sub/intel/` 子模块，
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

市场情报中枢（Market Intelligence Hub），覆盖：

- 竞对监测（Competitor Monitor）
- 消费洞察（Consumer Insight）
- 口碑分析
- 新品雷达（New Product Radar）
- 价格洞察
- 情报报告引擎（Intel Report Engine）
- 试点建议（Pilot Suggestion）
- 日历信号（Calendar Signal）

## 端口

`:8011`

## 入口

`services/tx-intel/src/main.py`
