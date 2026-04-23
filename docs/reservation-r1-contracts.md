# 预订业务 Sprint R1 契约文档

> 文档日期：2026-04-23
> 状态：契约冻结（Sprint R1 实装期间 4 个并行 Agent 不得修改本文约定）
> 关联：
> - 规划：`docs/reservation-roadmap-2026-q2.md` §6 Sprint R1
> - 规范：`CLAUDE.md` §14 审计修复期 / §15 事件总线 / §17 Tier 1 / §18 Ontology 冻结

本文档是 Sprint R1 的契约冻结层，为四个并行实装 Agent（Track A/B/C/D）提供共享的数据模型、事件约定、文件所有权边界。任何 Track 不得越界修改其他 Track 的文件。

---

## 1. 迁移版本分配

| 迁移版本 | 文件 | 主题 | 对应 Track |
|---|---|---|---|
| `v264` | `shared/db-migrations/versions/v264_customer_lifecycle_fsm.py` | 客户生命周期 FSM | A — CustomerLifecycle |
| `v265` | `shared/db-migrations/versions/v265_tasks.py` | 统一任务引擎 | B — TaskEngine |
| `v266` | `shared/db-migrations/versions/v266_sales_targets.py` | 销售目标 + 进度 | C — SalesTarget |
| `v267` | `shared/db-migrations/versions/v267_banquet_leads.py` | 宴会商机漏斗 | D — BanquetLead |

> 说明：规划文件原始建议 v230-v233，但本仓库 `shared/db-migrations/versions/` 中 v230-v263 全部已占用（最高已用版本 v263_kiosk_voice_count.py）。为避免版本号冲突，R1 从 `v264` 起顺延。
>
> 迁移链：`v263 → v264 → v265 → v266 → v267`，严格顺序依赖。

---

## 2. 事件类型清单 + payload schema

全部新事件已注册到 `shared/events/src/event_types.py`，用于 `emit_event()` 调用。金额字段必须 **以 `_fen` 结尾、类型 int、单位分**（对齐 CLAUDE.md §15）。

### 2.1 CustomerLifecycleEventType（Track A）

| 事件类型 | 枚举 | payload 必填字段 | payload 可选字段 |
|---|---|---|---|
| `customer.state_changed` | `STATE_CHANGED` | `previous_state`, `next_state`, `customer_id`, `since_ts`（ISO8601） | `reason`, `trigger_event_id`, `transition_count` |

`stream_id` = `customer_id`（UUID 字符串），`stream_type` = `customer_lifecycle`。

### 2.2 TaskEventType（Track B）

| 事件类型 | 枚举 | payload 必填字段 | payload 可选字段 |
|---|---|---|---|
| `task.dispatched` | `DISPATCHED` | `task_type`, `assignee_employee_id`, `due_at`（ISO8601） | `customer_id`, `store_id`, `source_event_id` |
| `task.completed` | `COMPLETED` | `completed_at`（ISO8601） | `notes`, `outcome_code` |
| `task.escalated` | `ESCALATED` | `escalated_to_employee_id`, `escalated_at`（ISO8601） | `escalation_level`, `reason` |

`stream_id` = `task_id`，`stream_type` = `task`。

### 2.3 SalesTargetEventType（Track C）

| 事件类型 | 枚举 | payload 必填字段 | payload 可选字段 |
|---|---|---|---|
| `sales_target.set` | `SET` | `employee_id`, `period_type`, `period_start`, `period_end`, `metric_type`, `target_value` | `parent_target_id`, `notes` |
| `sales_target.progress_updated` | `PROGRESS_UPDATED` | `target_id`, `actual_value`, `achievement_rate`（字符串化 Decimal） | `source_event_id` |

`stream_id` = `target_id`（SET 时）或 `target_id`（PROGRESS_UPDATED 时相同），`stream_type` = `sales_target`。

> 所有数值字段（target_value/actual_value）类型 int；achievement_rate 用字符串表达 Decimal，不用 float。

### 2.4 BanquetLeadEventType（Track D）

| 事件类型 | 枚举 | payload 必填字段 | payload 可选字段 |
|---|---|---|---|
| `banquet.lead_created` | `CREATED` | `customer_id`, `banquet_type`, `source_channel`, `stage="all"` | `sales_employee_id`, `estimated_amount_fen`, `estimated_tables`, `scheduled_date` |
| `banquet.lead_stage_changed` | `STAGE_CHANGED` | `previous_stage`, `next_stage`, `stage_changed_at` | `invalidation_reason`（next_stage=invalid 必填）, `operator_employee_id` |
| `banquet.lead_converted` | `CONVERTED` | `converted_reservation_id`, `converted_at` | `operator_employee_id` |

`stream_id` = `lead_id`，`stream_type` = `banquet_lead`。

---

## 3. Pydantic 模型字段表

所有契约位于 `shared/ontology/src/extensions/`（新建子目录，符合 §18 Ontology 冻结，不修改现有 entities.py）。

### 3.1 customer_lifecycle.py

| 模型 | 字段 | 类型 | 说明 |
|---|---|---|---|
| `CustomerLifecycleState`（Enum） | `NO_ORDER` / `ACTIVE` / `DORMANT` / `CHURNED` | str | 四象限 |
| `CustomerLifecycleRecord` | customer_id | UUID | PK 复合 |
| | tenant_id | UUID | RLS |
| | state | CustomerLifecycleState | 当前状态 |
| | since_ts | datetime | 进入时间 |
| | previous_state | CustomerLifecycleState \| None | 上一状态 |
| | transition_count | int | ≥ 0 |
| | last_transition_event_id | UUID \| None | events.event_id |
| | updated_at | datetime | |
| `CustomerLifecycleTransitionRequest` | customer_id, tenant_id, target_state, source_event_id, occurred_at, reason? | mixed | 迁移输入契约 |

### 3.2 tasks.py

| 模型 | 字段 | 类型 | 说明 |
|---|---|---|---|
| `TaskType`（Enum） | 10 种 | str | lead_follow_up / banquet_stage / dining_followup / birthday / anniversary / dormant_recall / new_customer / confirm_arrival / adhoc / banquet_followup |
| `TaskStatus`（Enum） | pending / completed / escalated / cancelled | str | |
| `Task` | task_id | UUID | PK |
| | tenant_id, store_id?, task_type | mixed | |
| | assignee_employee_id | UUID | 必填 |
| | customer_id? | UUID | |
| | due_at | datetime | 截止 |
| | status | TaskStatus | 默认 pending |
| | escalated_to_employee_id? / escalated_at? | | 升级元数据 |
| | cancel_reason? (≤200) | str | cancelled 时填 |
| | source_event_id? | UUID | 因果链 |
| | payload | dict | 任务上下文 |
| | dispatched_at / completed_at? / created_at / updated_at | datetime | |
| `TaskDispatchRequest` | 同 Task 部分字段 | | 派单输入 |
| `TaskDispatchResponse` | ok, task_id, dispatched_at, event_id? | | 派单响应 |

### 3.3 sales_targets.py

| 模型 | 字段 | 类型 | 说明 |
|---|---|---|---|
| `PeriodType`（Enum） | year / month / week / day | str | |
| `MetricType`（Enum） | revenue_fen / order_count / table_count / unit_avg_fen / per_guest_avg_fen / new_customer_count | str | |
| `SalesTarget` | target_id | UUID | PK |
| | tenant_id, store_id?, employee_id | mixed | |
| | period_type, period_start, period_end | mixed | 起止闭区间 |
| | metric_type, target_value (≥0, int) | mixed | 金额类以 _fen 结尾 |
| | parent_target_id? | UUID | 目标分解链 |
| | notes? (≤500), created_by?, created_at, updated_at | | |
| `SalesProgress` | progress_id | UUID | PK |
| | tenant_id, target_id | UUID | |
| | actual_value (≥0, int) | int | |
| | achievement_rate | Decimal(5,4) | 0.0000~9.9999 |
| | snapshot_at, source_event_id?, created_at | | |
| `SalesTargetCreateRequest` | 同 SalesTarget 输入子集 | | |

### 3.4 banquet_leads.py

| 模型 | 字段 | 类型 | 说明 |
|---|---|---|---|
| `BanquetType`（Enum） | wedding / birthday / corporate / baby_banquet / reunion / graduation | str | |
| `SourceChannel`（Enum） | booking_desk / referral / hunliji / dianping / internal / meituan / gaode / baidu | str | |
| `LeadStage`（Enum） | all / opportunity / order / invalid | str | |
| `BanquetLead` | lead_id | UUID | PK |
| | tenant_id, store_id?, customer_id | mixed | |
| | sales_employee_id? | UUID | 可暂缺 |
| | banquet_type, source_channel, stage | Enum | |
| | estimated_amount_fen (≥0, int) | int | 分 |
| | estimated_tables (≥0, int) | int | |
| | scheduled_date? | date | |
| | stage_changed_at / previous_stage? | | 漏斗时长分析用 |
| | invalidation_reason? (≤200) | str | invalid 阶段必填 |
| | converted_reservation_id? | UUID | order 阶段写入 |
| | metadata, created_by?, created_at, updated_at | | |
| `BanquetLeadCreateRequest` / `BanquetLeadStageChangeRequest` | 输入子集 | | |

---

## 4. 实装 Agent 的文件所有权边界

> **铁律**：每个 Track 只能在自己的范围写入代码。跨 Track 调用通过本文档约定的 Pydantic 模型 + 事件总线进行，不允许任何 Track 直接 import 别的 Track 的内部 service 模块。

### Track A — CustomerLifecycleFSM（客户状态机）

**可写**：
- `services/tx-member/src/services/customer_lifecycle_service.py`（新建）
- `services/tx-member/src/api/customer_lifecycle_routes.py`（新建）
- `services/tx-member/src/projectors/customer_lifecycle_projector.py`（新建）
- `services/tx-member/tests/tier1/test_customer_lifecycle_tier1.py`（新建）

**可读**：
- `shared/ontology/src/extensions/customer_lifecycle.py`
- `shared/events/src/event_types.py`（CustomerLifecycleEventType）
- `shared/events/src/emitter.py`

**禁止触碰**：其他 Track 的 service / projector / 迁移文件。

### Track B — TaskEngine（任务引擎）

**可写**：
- `services/tx-org/src/services/task_dispatch_service.py`（新建）
- `services/tx-org/src/services/task_escalation_service.py`（新建）
- `services/tx-org/src/api/task_routes.py`（新建）
- `services/tx-org/tests/tier1/test_task_engine_tier1.py`（新建）

**可读**：
- `shared/ontology/src/extensions/tasks.py`
- `shared/events/src/event_types.py`（TaskEventType）

**禁止触碰**：customer_lifecycle / sales_targets / banquet_leads 表及其服务。

### Track C — SalesTarget（销售目标）

**可写**：
- `services/tx-org/src/services/sales_target_service.py`（新建）
- `services/tx-org/src/services/sales_progress_service.py`（新建）
- `services/tx-org/src/api/sales_target_routes.py`（新建）
- `services/tx-org/tests/tier1/test_sales_target_tier1.py`（新建）

**可读**：
- `shared/ontology/src/extensions/sales_targets.py`
- `shared/events/src/event_types.py`（SalesTargetEventType）
- 订单事件流（只读消费：`order.paid`）

**禁止触碰**：任务引擎 / 客户状态机 / 宴会商机 直接实现。

> Track B 与 Track C 同属 tx-org，必须使用独立文件前缀（`task_*` vs `sales_target_*`）避免文件冲突。

### Track D — BanquetLead（宴会商机漏斗）

**可写**：
- `services/tx-trade/src/services/banquet_lead_service.py`（新建）
- `services/tx-trade/src/api/banquet_lead_routes.py`（新建）
- `services/tx-trade/src/projectors/banquet_funnel_projector.py`（新建）
- `services/tx-trade/tests/tier1/test_banquet_lead_tier1.py`（新建）

**可读**：
- `shared/ontology/src/extensions/banquet_leads.py`
- `shared/events/src/event_types.py`（BanquetLeadEventType）

**禁止触碰**：现有预订/宴会主流程（`cashier_engine.py` / 现有 banquet_* routes），R1 只新增 lead 域。

### 共享只读区（任何 Track 均不允许修改）

- `shared/ontology/src/entities.py` / `base.py` / `enums.py`（§18 冻结）
- `shared/events/src/emitter.py` / `pg_event_store.py`
- 已发布迁移 v001-v263
- Sprint R1 四个迁移 v264-v267（本 PR 提交后冻结）

---

## 5. Tier 1 测试场景清单

> 对齐 CLAUDE.md §17（Sprint R1 四任务均为 Tier 1 零容忍）与 §20（用例描述基于餐厅场景，不是技术边界）。

### 5.1 Track A — CustomerLifecycleFSM

1. **`test_200_customers_concurrent_state_transition_no_conflict`**
   200 桌并发结账，对应 200 个 `no_order → active` 跃迁，行锁不冲突、事件完整写入。
2. **`test_dormant_180d_transition_idempotent`**
   同一客户"180 天无消费"投影被重放 3 次，`customer_lifecycle_state` 中 state/since_ts 保持幂等。
3. **`test_churned_to_active_recall_emits_single_event`**
   已流失客户首次消费触发 `churned → active`，事件总线仅产生一条 `CUSTOMER.STATE_CHANGED`，避免 recall 重算造成双写。
4. **`test_rls_cross_tenant_lifecycle_isolation`**
   A 租户的 Agent 查询时不得返回 B 租户任何客户状态，即使同一手机号。

### 5.2 Track B — TaskEngine

1. **`test_banquet_6_stage_tasks_dispatch_chain`**
   一份婚宴合同签订后自动派发 T-7d/T-3d/T-1d/T-2h 四级任务，全部落入对应销售/店长，payload 指向同一 banquet_lead_id。
2. **`test_overdue_task_escalates_exactly_once`**
   销售员工未在 `due_at` 前完成，升级到店长只触发一次（即使定时器跑了 3 次）。
3. **`test_bulk_dispatch_500_dormant_recall_tasks_p99`**
   月度沉睡客户召回批量派单 500 条，P99 < 200ms。
4. **`test_cancelled_task_requires_reason_not_escalate`**
   状态为 cancelled 的任务不再进入升级扫描，cancel_reason 必填校验生效。

### 5.3 Track C — SalesTarget

1. **`test_year_target_decompose_to_monthly_weekly_daily`**
   年目标 1200 万 → 自动分解 12 个月（parent_target_id 指向年）→ 周/日目标，合计误差 ≤ 0.01%。
2. **`test_order_paid_updates_progress_snapshot`**
   `order.paid` 事件驱动 `sales_target.progress_updated`，actual_value 为当期已结账单总金额（分），achievement_rate 更新。
3. **`test_concurrent_200_orders_progress_no_double_count`**
   200 笔并发结账事件，同一目标的 actual_value 不被重复累加（幂等键 = source_event_id）。
4. **`test_rls_cross_tenant_target_isolation`**
   A 租户销售不能看到 B 租户同员工ID 的目标（极端情况：员工跨租户入职）。

### 5.4 Track D — BanquetLead

1. **`test_lead_stage_transition_all_to_order_atomic`**
   all → opportunity → order 连续状态变更，写表与事件写入同一事务，任一失败全回滚。
2. **`test_invalid_lead_requires_reason`**
   stage=invalid 且无 invalidation_reason 时 API 400；DB 约束兜底也拒绝。
3. **`test_banquet_funnel_conversion_rate_by_channel`**
   投影器消费事件流，按 source_channel 聚合转化率与 v148 物化视图口径一致（误差 0）。
4. **`test_converted_lead_links_to_reservation_ok`**
   stage=order 时 converted_reservation_id 必须指向真实 reservation；外键不存在时 API 400。

---

## 6. 验收准入（R1 完成标准）

- [ ] 迁移 v264-v267 在 DEV 环境 apply + downgrade 回退都通过
- [ ] 四个 Track 的 Tier 1 测试全部通过（P99 延迟达标）
- [ ] `shared/events/src/event_types.py` 新枚举被 `ALL_EVENT_ENUMS` 包含，ruff 无 broad except
- [ ] `shared/ontology/src/extensions/` 下每个模型带 `Field(description=...)`
- [ ] 本契约文档在 R1 结束前不被任何 Track 修改（改动需单独 PR，创始人确认）
- [ ] 四个 Track 的 PR 合并顺序：A → B → C → D（按迁移版本号 v264 → v267 依序合并，避免 Alembic 分叉）

---

## 7. 已知风险 / 遗留

- **v264-v267 顺序依赖**：四个迁移形成线性链（v263 ← v264 ← v265 ← v266 ← v267），Track 间 PR 必须串行合并；并行只发生在服务层代码与 projector。
- **customer_lifecycle 阈值未定**：N（活跃→沉睡）、M（沉睡→流失）天数由门店配置决定，本 R1 只建数据层，阈值读取服务在 R2 `sales_coach` 接入时补。
- **sales_progress 幂等键未落到 DB 约束**：`source_event_id` 仅在 actual_value 累加时做应用层去重；如并发极端情况出现双写，依赖 events 表单次 exactly-once 语义兜底。
- **banquet_leads.converted_reservation_id 尚无外键**：`reservations` 表结构仍在演进（R3 前会补齐），本 R1 暂以 UUID 字段存，由应用层校验。
- **物化视图 mv_customer_lifecycle / mv_banquet_funnel 未在本 PR 建**：按规划归入 Sprint R2 投影器上线包。

---

## 8. 附录：规范引用一览

- `CLAUDE.md §6` Ontology 六大实体（本 R1 通过 Customer/Order/Employee 扩展关系表实现）
- `CLAUDE.md §14` 审计修复期约束（新表必含 tenant_id + RLS 使用 `app.tenant_id`）
- `CLAUDE.md §15` 事件总线（emit_event 并行写入，payload 金额用分）
- `CLAUDE.md §17` Tier 1 零容忍（TDD + DEMO 验收）
- `CLAUDE.md §18` Ontology 冻结（entities.py 不得自动修改，扩展走 extensions/）
- `CLAUDE.md §20` Tier 1 测试标准（用例基于餐厅场景）
