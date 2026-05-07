# tx-brain · 智能内核（:8010）

> 🟡 **POST-W12 MIGRATION MARKER**（2026-05-06, sprint-0-dedup R4）
>
> 本服务计划在 W12（2026-07-29）之后合并入 `services/tx-agent/sub/brain/` 子模块，
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

智能内核统一服务（V6.0 引入），集成：

- **Voice AI** — ASR + NLU + Dialog + TTS
- **CFO Dashboard** — 财务驾驶舱后端
- **Evolution 2030** — 长期演进路线

## 端口

`:8010`

## 入口

`services/tx-brain/src/main.py`
