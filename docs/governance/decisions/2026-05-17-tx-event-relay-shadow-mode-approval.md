# 守门会决议 — tx-event-relay shadow mode 部署批准 (2026-05-17)

**状态**: APPROVED (创始人 explicit-ack 2026-05-17)
**关联 issue**: #757 `[W3 P0 Outbox 内核] 真 Outbox 表 trade_event_outbox + tx-event-relay shadow mode 部署`
**关联 PR**: 本 PR (feat/shared-db-migrations-outbox-shadow-2026-05-17)
**策略文件**: `.omc/policy/service-freeze.yml:30` (planned_additions 已含 `tx-event-relay`)

---

## §1 背景

战略 plan §4 举措 3 "真 Outbox":
现行 `emit_event` (`shared/events/src/emitter.py`) fire-and-forget 双写 Redis Stream + PG events 表; PG 失败返 None / Redis `create_task` 不等待 — Tier 1 资金/状态机/库存事件丢失风险 P0.

引入 trade-side outbox 单元 (`v446_create_trade_event_outbox`) + 独立 worker (`services/tx-event-relay`, 端口 8020) 异步 polling 投递, 失败 backoff 重试不丢.

CLAUDE.md §26 服务冻结令 (frozen_until: 2026-06-12) 范围内, `tx-event-relay` 已列入 `planned_additions` 例外列表 (issue #755 ship 后正式生效); 本决议同 PR 落盘归档.

---

## §2 创始人 explicit-ask 4 问决议 (2026-05-17)

| Q | 决议 | 决策依据 |
|---|------|----------|
| **Q1**: 设计 A vs B (推送后 GC / 永久保留 dedup) | **A** | 1) 与 v147 events 表 RULE NO UPDATE 兼容; 2) 同事务原子语义清晰 (BEGIN; INSERT events; UPDATE outbox; COMMIT); 3) GC 简单 (30d delivered truncate); 4) events 表已 PARTITION BY RANGE, B 选项加 `outbox_source_id` 跨分区索引代价大 + 违反"事件总线为权威源"原则. |
| **Q2**: tx-event-relay 端口 | **8020** | base.yml 8000-8019 全占 (self-regrep 验证), 取 next sequential 0 冲突; 同步更新 `docs/infra/port-allocation-2026-05.md`. |
| **Q3**: shadow 期间 outbox GC 策略 | **30d delivered truncate** | 与审计窗口对齐; W11 follow-up issue 立 cron `DELETE WHERE delivered=true AND delivered_at < NOW() - INTERVAL '30 days'`; shadow 期间表预期 0 行, 不真投递, GC 实际不触发. |
| **Q4**: Helm chart Tier | **T3 default off** | shadow 单实例 0 业务影响; PodDisruptionBudget / NetworkPolicy / ConfigMap 全 disabled; W11 切真路径 follow-up issue 评估升 T2 maxU=1 / T1 minA=1. |

---

## §3 范围与边界 (强红线)

### 本 PR 包含

1. Migration `v446_create_trade_event_outbox.py` — 单表 + 2 CHECK + 3 partial index + RLS 四联
2. `services/tx-event-relay/` 完整 (Dockerfile / requirements / src/ / 15 tests)
3. `infra/helm/tx-event-relay/` 11 文件 (复用 tx-trade 模板 adapt, T3 default off)
4. `infra/compose/base.yml` 注册 :8020 + healthcheck
5. `docs/infra/port-allocation-2026-05.md` 加 8020 行
6. 本守门会决议文档

### OUT-OF-SCOPE (严禁本 PR 触)

- `shared/events/src/emitter.py` 任何改动 (Tier 1 邻接 §17 红线邻路径)
- `services/tx-trade/cashier_engine.py` / `order_service.py` / `payment_saga_service.py` (§17/G10 双红线)
- `services/tx-trade/invoice.py` / `services/tx-supply/inventory_io.py` (§17 红线)
- W4 follow-up: `settle_order` 业务路径写 outbox (issue #760)
- W5 follow-up: refund/recharge 接入 outbox (issue #768)
- W11 follow-up: 全 Tier 1 路径切真投递 + 30d GC cron (issue #767)

### delivered_event_id 引用完整性策略 (round-1 P1-5 纠错)

**delivered_event_id 永远是 informational pointer**, 不是 FK — events 表 PK 是
`(event_id, occurred_at)` 复合 (per `shared/db-migrations/versions/v147_unified_event_store.py`),
PG 16 分区表 composite FK 结构上不可行 (即使加 `(tenant_id, delivered_event_id) →
events (tenant_id, event_id)` 也因 events 唯一约束必须含 occurred_at 而建不上).

由 W4 follow-up (issue #760) 在**应用层**做引用完整性:
- INSERT events 成功后, 同事务内才允许 UPDATE outbox.delivered_event_id (with returned event_id)
- `chk_outbox_delivered_consistency` CHECK 兜底防 partial state (delivered=true 必有 delivered_at)
- W11 切真路径前 (issue #767) 评估是否补 polling-time `EXISTS` check 而非 FK

---

## §4 与服务冻结令 (CLAUDE.md §26) 关系

- `.omc/policy/service-freeze.yml:30` `planned_additions` 已含 `tx-event-relay   # W3 issue #757 — Event relay 服务`
- 本决议同 PR 归档至 `docs/governance/decisions/` (issue #761 ship 后正式归档目录已建立)
- 例外申请流程 4 步 (per CLAUDE.md §26):
  1. ✅ 创始人 explicit approval (本文档 §2 4 问决议)
  2. ✅ 架构守门会决议记录 (本文档)
  3. ✅ planned_additions 列表已含 (5/16 已落)
  4. ✅ 实施 (本 PR: services/tx-event-relay/ + infra/compose/base.yml 注册)

---

## §5 5 项验收 (本 PR ship 必满足)

| # | 验收项 | 验证方法 |
|---|--------|----------|
| 1 | `trade_event_outbox` 表存在且 polling 空表不报错 | dev compose up + 观察 relay log 30s 无 ERROR |
| 2 | `tx-event-relay /health` 返 polling 状态 + last_poll_at 不为 null | `curl http://localhost:8020/health` |
| 3 | 现有 `emit_event` 路径 0 改动 | `git diff origin/main shared/events/src/emitter.py shared/events/src/pg_event_store.py` 输出空 |
| 4 | relay 容错: PG/Redis 不通时 backoff 不崩 | unit test `test_relay_worker_shadow_tier1.py` 全 pass (15 测试) |
| 5 | 监控暴露: `outbox_pending_count` + `relay_delivery_lag_seconds` Prometheus metrics endpoint 可抓 | `curl http://localhost:8020/metrics` 见两 metric |

---

## §6 风险与缓解

| 风险 | 缓解 |
|------|------|
| Alembic 双 head (5/17 周末并行 session 可能改 migration) | 起手前 + push 前 `git fetch origin main && ls shared/db-migrations/versions/v44*` 确认无 v446_other; 双 head 用 merge revision (per memory `feedback_alembic_merge_revision_pattern.md`) |
| relay loop 在 shadow 模式下 still 写 events 表 (silent shadow break) | `relay_worker.py` `if shadow_mode: log + continue` 显式分支 + unit test `test_shadow_does_not_write_events` 强校验 + `test_shadow_mode_false_raises_not_implemented` 设防 |
| asyncpg pool 不复用致 PG max_connections 超 (per memory `feedback_projector_asyncpg_pool_model.md`) | shadow 单实例 min=1 max=3 = +3 conn (远低于 max_connections=100); W11 切真路径 follow-up issue 重评估 |
| 测试文件名漏 `_tier1.py` 后缀致 CI 不触 | 严格命名 `test_relay_worker_shadow_tier1.py` (含 `_tier1.py` 子串, per memory `feedback_tier1_test_filename_workflow_trigger.md`) |

---

## §7 后续审议

- **W4**: `settle_order` 业务路径写 outbox (issue #760)
- **W5**: refund/recharge 接入 outbox (issue #768)
- **W11**: 全 Tier 1 路径切真投递 + Helm Tier 升级评估 + 30d GC cron (issue #767)
- **下次守门会**: W22 (2026-05-25) — 不再讨论本服务部署 (已批准), 仅验收 shadow 验收 5 项 + 立 W4 follow-up

---

## §8 References

- 战略 plan §3 W3 验收 / §4 举措 3 真 Outbox / §7 W4 验收
- CLAUDE.md §15 事件总线 v147 / §17 Tier 1 / §19 独立验证 / §25 Tier 1 邻接 / §26 服务冻结令
- `.omc/plans/2026-05-17-outbox-shadow-plan.md` (本 PR planner SoT, 423 行)
- `.omc/policy/service-freeze.yml` (planned_additions verify)
- Memory: `feedback_planner_verified_claims_must_regrep.md` (数字 self-regrep) /
  `feedback_projector_asyncpg_pool_model.md` (asyncpg pool 模型) /
  `feedback_tier1_test_filename_workflow_trigger.md` (测试命名) /
  `feedback_carveout_admin_merge_pattern.md` (5 项裁决)

---

**决议人**: 创始人 (2026-05-17 explicit-ack)
**归档时间**: 2026-05-17
**Tier 1 邻接 explicit-ask 累计**: 第 38 例 (W1 末 #742 第 37 例 → 本 PR 第 38 例)
