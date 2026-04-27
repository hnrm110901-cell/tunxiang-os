# Sprint R1 独立验证报告（徐记海鲜收银员视角）

- 日期：2026-04-23
- 审查人：独立验证 Agent（CLAUDE.md §19 独立验证规则）
- 审查范围：feat/sprint-r1 分支 / PR #90 / 4 Track 并行实装
- 角色设定：徐记海鲜长沙解放西店收银员「老王」——20 年餐饮老兵
- 参考文档：
  - `/Users/lichun/tunxiang-os/.claude/worktrees/hopeful-lehmann-b617b1/docs/reservation-r1-contracts.md`
  - `/Users/lichun/tunxiang-os/.claude/worktrees/hopeful-lehmann-b617b1/docs/sprint-r1-dev-integration-report.md`

---

## 总评：7.2 / 10

**一句话结论**：代码工程质量过关，契约/事件/RLS/Tier 1 测试都齐备；但从徐记海鲜真实业务视角看，**有 2 个 P0 阻塞项**（客户状态机对 ORDER.CANCELLED 无响应 + 存在并行双生命周期系统）和若干 P1 风险，不建议立即在 DEMO 环境对徐记数据灰度——**建议带 P0 修复包再进 DEMO**。PR 技术上可合并进 main（不改动 Tier 1 生产路径），但接入前需补齐。

---

## Q1-Q10 详细评审

---

### Q1：200 桌结账高峰期会不会出问题？

**评分：6 / 10**

**证据**：
- `services/tx-member/src/repositories/customer_lifecycle_repo.py:82-106` 使用 `SELECT FOR UPDATE` 锁单行。主键 `(tenant_id, customer_id)`，不同客户不会互锁。
- `services/tx-org/src/services/task_dispatch_service.py:97-106` 使用 **内存级 `asyncio.Lock()` 按 tenant 一把大锁** (`_locks: dict[UUID, asyncio.Lock]`) 保护幂等查询+插入。
- `services/tx-org/src/repositories/task_repo.py:323-357` 幂等键 SQL：`DATE(due_at AT TIME ZONE 'UTC') = DATE(:due_at AT TIME ZONE 'UTC')` **没有索引覆盖**（v265 的 `idx_tasks_assignee_status_due` 是 `(tenant_id, assignee, status, due_at)`，无法用于 `DATE()` 函数索引）。

**风险**：
1. `task_dispatch_service._locks` **是一把租户级全局大锁**：200 桌同时结账如果都要派 `dining_followup` 任务，会串行化！徐记解放西店周五晚 19:30 爆桌时，这 200 个结账并发走 tx-org 派单会退化为单线程，**幂等检查的 SQL 又无索引**，P99 极可能破 200ms。
2. `customer_lifecycle_state` 的 `FOR UPDATE` 本身只锁一行，但 `transition()` 内完成 `SELECT FOR UPDATE → evaluate → emit_event(create_task) → UPDATE`，其中 `asyncio.create_task(emit_event)` 是不等待的旁路——**事件写入和 DB 事务提交顺序无保证**，DB rollback 时事件仍然会发出去（已脏）。参见 `customer_lifecycle_fsm.py:238-247`。
3. `task_dispatch_service.py:178-196`：事件发射放在了 `async with self._lock_for(tenant_id)` 代码块**之外**（锁已释放），这是对的；但幂等键 DB 查询在锁内，实际阻塞点仍然是 DB。

**改进建议**：
- [P1] 把 `_locks` 改为 `(tenant_id, task_type, assignee_id, date(due_at))` 复合键，或直接依赖 DB `UNIQUE` 约束 + `ON CONFLICT DO NOTHING RETURNING`，删掉应用层锁。
- [P1] `tasks` 表加一个 `DATE(due_at)` 的函数表达式索引，或增加一个生成列 `due_date DATE`。
- [P1] FSM `transition()` 的 `emit_event` 必须改为**先 commit 再 create_task**，或者采用 Phase 1 outbox 模式（先写 `events` 表到同一事务，再由 emitter 读出）。目前这种写法在 DB 事务回滚时会产生「幽灵状态迁移事件」。

---

### Q2：客户临时改桌/改人数，客户状态机会不会乱？

**评分：5 / 10** ← 本 PR 最严重的业务语义缺口之一

**证据**：
- `customer_lifecycle_projector.py:40`: `event_types = {"order.paid"}` —— 投影器**只订阅 order.paid，完全不消费 order.cancelled / order.refunded / order.partial_refunded**。
- `shared/events/src/event_types.py:30-36` 明确存在 `OrderEventType.CANCELLED/REFUNDED/PARTIAL_REFUNDED` 事件，但本 PR 未挂钩。
- `customer_lifecycle_fsm.py:177-181`：`evaluate_state` 只看 `last_order_at + order_count`，未考虑"上一单已退款"的语义。

**风险场景**（老王视角）：
1. 周五晚客户下单 5000 元 → 支付成功 → 客户从 `dormant` → `active`（Agent 给他推会员专属券）→ 1 分钟后客户突然说临时有事要走、要求整单退款 → `ORDER.REFUNDED` 事件发出 → **客户状态机依然停留在 `active`**，Agent 依然认为他是活跃客户 → 推错营销信息 → 老王被客户投诉"上次都没吃成你们还推菜单"。
2. 老婆/老公来换单（第一单取消，第二单重下）：同一客户 id 来回 cancel/pay，投影器只看 paid，`transition_count` 会暴涨，却不反映真实业务。

**改进建议**：
- [P0] 订阅 `order.cancelled` / `order.refunded`：当被取消订单是客户当期「唯一」或「最后一单」时，应把 `last_order_at` 回退到前一单，并重算状态（或标记 `pending_recompute`）。
- [P0] 至少在 Tier 1 测试里加一条 `test_refund_after_single_order_reverts_to_no_order`，当前 8 条测试没有任何一条覆盖退款场景。
- [P1] 契约文档 §2.1 里没有约定 `previous_state = no_order` 的逆向场景；建议显式说明「退款不会触发 STATE_CHANGED」是当前默认行为，让产品/业务知悉。

---

### Q3：婚宴 30 桌客户退宴，订金 5 万退款，商机漏斗会不会留死数据？

**评分：6 / 10**

**证据**：
- `banquet_lead_service.py:73-78` 状态机：`ORDER → INVALID`，`INVALID` 是终态。
- `banquet_lead_service.py:223-226`：转 invalid 时强校验 `invalidation_reason`。
- `banquet_lead_service.py:91-120`：**没有任何 deposit / 押金 / refund 相关字段、事件、Saga。**
- `shared/events/src/event_types.py:322-332`：`DepositEventType` 已定义（COLLECTED/APPLIED/CONVERTED/REFUNDED 等）**——但 Track D 完全未调用**。
- `shared/events/src/event_types.py:103-104`：`ReservationEventType.BANQUET_DEPOSIT_PAID` 存在，**Track D 也没挂钩**。
- Tier 1 测试 `test_banquet_lead_tier1.py:223-246`（`test_invalid_without_reason_raises`）只校验"invalid 必填原因"，**没有「已付订金 → 退款 → invalid」的完整链路测试**。

**风险场景**（老王视角）：
徐记解放西店 30 桌婚宴，订金 5 万（5,000,000 分）已收，客户新郎新娘闹掰，要求取消。现状：
1. 财务要给客户退 5 万，走的是 `tx-trade` 里的存量 banquet 退款流程（如有）或手工退款。
2. Track D 只能把 `banquet_lead.stage` 标记为 `invalid` 并写 `invalidation_reason="客户取消"`。
3. **订金退款事件（deposit.refunded）和 banquet_lead.stage_changed 是两条独立事件流，没有 Saga 或 causation_id 关联**。
4. 未来 banquet_contract_agent（R2）若想根据退单重算销售佣金回收，需要自己跨 `deposit_events` + `banquet_lead_events` JOIN，工作量转嫁到 R2。

**改进建议**：
- [P1] 在 `BanquetLeadStageChangeRequest` 里加一个 `linked_deposit_refund_event_id` 可选字段；当 next_stage=invalid 且有订金时，必填。
- [P1] 加 Tier 1 测试：`test_invalid_with_paid_deposit_requires_refund_linkage`。
- [P2] R2 做 banquet_contract_agent 时，新增 `banquet_cancellation_saga`，统一编排"退款 + 销售佣金回收 + 食材订购取消 + 场地预留释放"四件事。

---

### Q4：断网 4 小时后重连，会有什么数据问题？

**评分：7 / 10**

**证据**：
- `customer_lifecycle_fsm.py:188-199`：幂等短路依赖 `last_transition_event_id == trigger_event_id`。断网期间 order.paid 事件积压在 Redis Stream / PG events 表，恢复后 projector 逐条重放，每条 event_id 唯一 → 幂等有效。
- `customer_lifecycle_projector.py:82`：`last_order_at = occurred_at  # 本次就是最新一次` —— **这里有坑**：事件重放时 `occurred_at` 是原业务时间，但如果事件乱序到达（event_id_A 的 occurred_at > event_id_B 的 occurred_at 但 B 后处理），会把 `last_order_at` 覆盖成旧的！
- `task_auto_generator.py:113-140`：`_run_providers` 用 `asyncio.gather(..., return_exceptions=True)`，单个 provider 失败不影响其他。幂等在下层 `dispatch_task` 用当日键兜底，**同一天多次运行不会产生重复**。
- 但 `task_auto_generator` 没有对"断网 4 小时跨日"场景做补跑：如果 4 月 1 日凌晨 02:00 的 daily 扫描因断网没跑，4 月 1 日 06:00 恢复后，**调度器是否会自动补跑当天的任务？本 PR 没看到调度器代码，只看到生成器本身**。

**风险**：
1. 事件乱序处理时 `last_order_at` 回退是隐藏 bug，实际结果是客户状态周期计算错误（但影响有限，FSM 会在下次 order.paid 重算）。
2. `sales_target_service.py:414-422`：progress 幂等依靠 `source_event_id`，断网重放是稳的。
3. `banquet_funnel_projector.py:69-96`：handle 里有内存状态 `self._state`，**进程重启后内存丢失**；通过 `_apply_stage_changed` 对「补数/重放缺 CREATED」有兜底，但在多副本部署下会出现内存状态不一致（没问题——落地到 mv_banquet_funnel 才是权威）。

**改进建议**：
- [P1] projector handle 里加一行 `if record["last_order_at"] > occurred_at: return`（防止 older event 覆盖 newer）。
- [P2] 明确 daily_generator 在漏跑时的补跑策略（at-least-once 是前提）；建议加一个 `last_run_at` 持久化，作为健康检查指标。

---

### Q5：老会员来电预订保留上次偏好，这个能力已经就绪了吗？

**评分：5 / 10**

**证据**：
- R1 只建底座，`reservation_concierge` Agent 是 R2 才有（契约 §7 已声明）。
- 老王现在**能**查客户当前状态：`GET /api/v1/customer-lifecycle/{customer_id}`（`customer_lifecycle_routes.py:140-182`）。
- 老王**不能**查客户上次包厢 / 忌口偏好：
  - `shared/ontology/src/entities.py:77` 有 `Customer.dietary_restrictions`（JSON），但 R1 **没有暴露任何新 API** 读这个字段。
  - R1 没有新增 `last_preferred_table_id` / `last_preferred_store_id` 等预订偏好字段。
  - 客户预订历史表 `reservations` 在本 PR 未被触碰。
- `banquet_leads` 表的 `metadata` JSONB 可以塞偏好，但**没有标准化 schema**，且 banquet_lead ≠ 普通预订。

**风险场景**（老王视角）：
"王阿姨，上次是给您留的 2 号包厢，大儿子不吃香菜，对吧？" —— **这句话现在说不出来**。R2 `reservation_concierge` Agent 要把这个做出来，必须：
1. 读 `customers.dietary_restrictions`；
2. 读 `reservations` 表按 customer_id 按 created_at 倒序取最近 N 次包厢；
3. 结合 `customer_lifecycle_state` 判断是否该重点关怀。

R1 只提供了「生命周期状态」这一条视图，**缺另外 2 条**。

**改进建议**：
- [P2] R2 启动前，在 tx-member 补一个 `GET /api/v1/customers/{customer_id}/preferences` 接口，聚合 RFM + 生命周期 + 忌口 + 近 N 次预订偏好（table_number/guest_count/scheduled_at 模式）。
- [P2] 数据层考虑新增 `customer_preferences` materialized view（R2 物化视图包一起做）。

---

### Q6：销售经理目标 KPI，老王（收银员）有没有被错误卷入？

**评分：6 / 10**

**证据**：
- `sales_targets` 表 `employee_id` 是必填字段，没有 role 约束（`v266_sales_targets.py:76`）。
- `sales_target_service.py:480-533` 的 `aggregate_from_orders`：按 `store_id + metric_type + 期间` 聚合 `mv_store_pnl`，然后**写给"当期生效的所有 targets"**。这意味着：
  - 如果老王的 `employee_id` 被误建了一个 `revenue_fen` 目标，aggregate_from_orders 会把**门店全部营收**都算给他。
  - `metric_type=new_customer_count` 目标如果挂到老王头上，老王接待的新客也会被归为他的业绩。
- `aggregate_metric_from_views` 查 `mv_store_pnl` 是**门店粒度**，不是员工粒度！`sales_target_repo.py:532-540`：`revenue_fen → SUM(gross_revenue_fen)` 从门店维度取值，完全没有 `WHERE employee_id = ...` 子句。
- `test_sales_target_tier1.py` 测试矩阵里**没有一条是"同门店不同员工目标的值分离"**——所有测试都是单一员工单一目标。

**风险**：
这是一个**静默的业务逻辑 bug**：
1. 老王是收银员，不应该有销售 KPI；
2. 但一旦系统把 revenue_fen 目标挂到老王名下，`aggregate_from_orders` 会把他门店的所有营收都算成他的完成值 → `achievement_rate` 爆表 → 老王莫名进了排行榜第一。
3. 更严重：销售经理张三和销售经理李四同门店，都挂了月度 revenue_fen 目标，**两人 actual_value 会相同**（都是门店 SUM），谁拿不拿业绩提成？

**改进建议**：
- [P0] `aggregate_metric_from_views` 必须按 `employee_id` 过滤（从 `orders.created_by` 或 `orders.served_by` 归因）。当前实现只按 `store_id` + `tenant_id`，**必定会把多个员工目标算成相同值**。
- [P1] `set_target` 时应校验 `employee_id` 对应员工的 `role` 是销售类角色（cashier/waiter 不应有 revenue 目标），或至少打 warning。
- [P1] 补 Tier 1 测试：`test_two_sales_employees_same_store_do_not_share_actual`。

---

### Q7：多店集团客户一卡通用时，RLS 会不会误隔离？

**评分：7 / 10**

**证据**：
- `shared/ontology/src/entities.py:124-206` 的 `Store` 是继承 `TenantBase`，意味着 `stores.tenant_id` 唯一 —— 即**徐记海鲜集团 20 家店共享同一个 tenant_id**（每家店是 `store_id` 不同的行）。
- `v024_add_brand_groups.py` 注释里也确认了："tenant_id：集团主租户 ID（与普通品牌 tenant_id 格式一致，但语义不同）"。
- 因此 `customer_lifecycle_state` 主键 `(tenant_id, customer_id)` 在徐记 20 店场景下**是全集团一条记录**，老王在解放西店看到的客户状态和其他店看到的是同一条 → **跨店 OK，RLS 不会误隔离**。
- 但这里潜藏另一个问题：`customer_lifecycle_state.since_ts` 对「某客户在 A 店活跃，但 B 店从未到过」的语义是**模糊的**——表是集团级，无法回答"这客户在本店是 active 还是 dormant"。

**风险**：
1. 集团模型 OK，一卡通用场景可用。
2. **区分「店忠诚客户」的能力缺失**：徐记可能希望看「在解放西店活跃 / 在五一广场店已流失」的客户分布，当前 `customer_lifecycle_state` 只能给一个状态。
3. `banquet_leads.store_id UUID`（`v267_banquet_leads.py:95`）允许空 = 集团级商机 — 合理。但漏斗聚合 `bulk_funnel_counts` 里没有 `store_id` 维度过滤，如果徐记 20 店都在同一 tenant_id 下，漏斗会把**全集团所有 30 个婚宴合同算作一个漏斗**——解放西店老板看不到自己门店的漏斗。

**改进建议**：
- [P1] `banquet_lead_service.compute_conversion_rate` 增加 `store_id: UUID | None` 可选参数；默认 None=集团全量，指定 store_id 后按单店统计。
- [P2] R2 考虑新增 `customer_store_engagement_state (tenant_id, customer_id, store_id) → 状态`，用于门店粒度的客户分层（当前 `customer_lifecycle_state` 保持集团粒度）。

---

### Q8：是否有"宴会电子合同 + EO 工单"的接入点？

**评分：6 / 10**

**证据**：
- `banquet_leads` 表字段：`metadata JSONB NOT NULL DEFAULT '{}'`（`v267_banquet_leads.py:108`），**预留了 JSONB 作为扩展点**。
- `converted_reservation_id` UUID 存在，但**没有外键约束**（契约 §7 已声明："reservations 表结构仍在演进，R1 暂以 UUID 字段存，由应用层校验"）——这是一把双刃剑：R2 能改结构、但现在没有 DB 层保护。
- 没有预留 `contract_pdf_url` / `eo_ticket_id` / `signed_at` 等专用字段。

**风险**：
R2 banquet_contract_agent 上线时，需要存储：
- 合同 PDF 文件 URL
- 合同编号
- 签署人、签署时间、电子签名 hash
- 对应的 EO（Event Order）工单 ID

当前 `metadata` JSONB 足以承载这些，**但缺乏 schema 约束**，容易不同 Agent 写入不同 key 导致 schema drift。

**改进建议**：
- [P2] R2 启动前，在 `shared/ontology/src/extensions/banquet_leads.py` 新增 `BanquetLeadMetadata` Pydantic 子模型，强制约束 metadata schema。
- [P2] 如必须用 FK，R3 建 `banquet_contracts` 子表 + `v268_banquet_contracts.py` 迁移。**不必在 R1 回补**。

**不需要**改 v267 迁移 —— JSONB 已足够承载 R2 需求。

---

### Q9：三条硬约束有没有 Agent 真正校验？

**评分：9 / 10**（R1 底座正确地跳过了硬约束——但 R2 有隐患）

**证据**：
- R1 全部 4 Track **没有任何 Agent 决策动作**，只是数据层 + 事件写入。不校验硬约束是对的。
- 但未来 R2 的 3 个 Agent（reservation_concierge / sales_coach / banquet_contract_agent）上线时，需要与 `shared/ontology/src/extensions/customer_lifecycle.py` 等配合产生决策。
- `task_auto_generator.py` 产出的任务（dormant_recall 等）会触发营销活动——如果 R2 允许这些活动动态发券（自动折扣），**会绕过 tx-trade 的折扣守护 Agent 硬约束校验**。

**风险**：
R2 会遇到的硬约束盲区：
1. **毛利底线**：sales_coach 给沉睡客户批量发券；任务派发时 payload 里携带 coupon_id；但 task 完成后若没走 `tx-trade/cashier_engine.py` 的结账主路径，**毛利校验可能被跳过**。
2. **食安合规**：R1 不涉及。
3. **客户体验（出餐时间）**：R1 不涉及。

**改进建议**：
- [P1] R2 启动前，在 `tx-agent` 层补 `constraints_check` 装饰器，所有 Skill Agent 决策动作强制过 3 条约束。
- [P2] 本 R1 不需要改。

---

### Q10：PR #90 拆分可行性评估

**评分：7 / 10**

**证据**：
- 当前 PR 包含 6 个原子提交：
  - `dd9601d3` 契约锁定（shared 层，必须先合）
  - `cc712fca` Track A
  - `06e4da90` Track B
  - `36b414f6` Track C
  - `249d8cc6` Track D
  - `8c978a2c` + `2796d529` 文档/日志
- 每个 Track commit 只动各自微服务文件夹，**边界清晰**。
- 迁移链 v263 → v264 → v265 → v266 → v267 **强顺序依赖**，Alembic 无法分叉。

**建议合并策略**（从 Tier 1 零容忍角度）：
1. **不拆分成 4 PR**：事实上 4 迁移串联，合并到 main 要么一起合要么一起退，拆 PR 反而容易导致 CI 中断与回滚困难。
2. **建议方式**：保留当前大 PR，但在合并前：
   - **Step A（立即）**：补 Q2 的 P0（order.cancelled 处理）+ Q6 的 P0（aggregate 按员工过滤）+ Q1.P1（DB 唯一索引替代应用锁）
   - **Step B（合并前）**：全部 Tier 1 测试通过 + 补上述 P0 测试
   - **Step C（合并）**：一次性合入 main，CI 跑完即可
   - **Step D（DEMO 前）**：清理 `LifecycleService` 旧实现（见 P0 下文）

---

## P0 阻塞项（必修 — 徐记海鲜 DEMO 灰度前）

### P0-1：客户状态机对 ORDER.CANCELLED 无响应（Q2）
- 文件：`services/tx-member/src/services/customer_lifecycle_projector.py:40`
- 修复：扩展 `event_types` 到 `{"order.paid", "order.cancelled", "order.refunded"}`，在 handle 里对 cancelled/refunded 做状态回滚（或 pending_recompute 标记）。
- 必须补测试：`test_refund_after_single_order_reverts_to_no_order`、`test_refund_of_latest_order_rolls_back_last_order_at`。
- 影响面：200 桌高峰退单直接把客户分群玩坏，下游营销推送错误。

### P0-2：销售目标 aggregate 不按员工过滤（Q6）
- 文件：`services/tx-org/src/repositories/sales_target_repo.py:510-581` (`aggregate_metric_from_views`)
- 修复：加 `employee_id` 参数并透传到 SQL；`mv_store_pnl` 若缺员工维度，先按 `store_id` 降级，但至少**同员工的多条目标不能拿到相同的门店 actual**。或者：按员工角色/归因表过滤后再 SUM。
- 必须补测试：`test_two_sales_employees_same_store_do_not_share_actual`。
- 影响面：销售经理业绩提成算错、排行榜失真，会直接影响薪资发放。

### P0-3：并行的两套生命周期系统互相不感知（架构隐患）
- 现状：`services/tx-member/src/services/lifecycle_service.py:49-65`（老版，阈值 7/30/90 天）与 `services/tx-member/src/services/customer_lifecycle_fsm.py:70-71`（本 PR 新版，阈值 60/180 天）**同库共存**。
- 风险：两个系统用不同阈值给客户打标签，Agent 取哪一个？同一客户在 A 系统是 `active`、B 系统是 `dormant`。
- 修复：**二选一**——要么立即下线 `LifecycleService`（推荐，因为本 PR 才是事件溯源架构）、要么在本 PR 标注"R1 新系统不上线"——绝不能两套系统并存。
- 必须在 DEVLOG.md 明确：R1 上线后是否废弃 `lifecycle_service.py`？如废弃，何时删除？

---

## P1 改进项（建议在 R2 前修）

- **P1-1**（Q1）：tasks 表应用层 `_locks` 替换为 DB `UNIQUE` 约束 + `ON CONFLICT`，避免租户级大锁。需要修改 v265 迁移增加复合唯一索引。
- **P1-2**（Q1）：FSM `transition()` 的 `emit_event` 改为先 commit 再 create_task（或用 outbox 模式）。
- **P1-3**（Q3）：`BanquetLeadStageChangeRequest` 新增 `linked_deposit_refund_event_id` 可选字段，并补 Tier 1 测试覆盖"已付订金转 invalid"场景。
- **P1-4**（Q4）：projector handle 里加 occurred_at 单调性检查，防止事件乱序覆盖 `last_order_at`。
- **P1-5**（Q7）：`compute_conversion_rate` 加 `store_id` 过滤，让 20 店集团能看到单店漏斗。
- **P1-6**（Q9）：R2 Agent 装饰器强制过 3 条硬约束。

---

## P2 技术债（可留后补）

- **P2-1**（Q5）：R2 启动前补 `GET /customers/{id}/preferences` 聚合接口。
- **P2-2**（Q4）：`task_auto_generator` 加 `last_run_at` 持久化字段，作为断网补跑依据。
- **P2-3**（Q8）：R2 banquet_contract_agent 上线时，定义 `BanquetLeadMetadata` Pydantic schema 规范 metadata JSONB。
- **P2-4**（Q7）：R2 考虑 `customer_store_engagement_state` 物化视图支持门店粒度的客户分层。

---

## Tier 1 测试矩阵覆盖度评估

| Track | 契约要求用例 | 实际实现 | 覆盖率 |
|---|---|---|---|
| A CustomerLifecycle | 4 条（§5.1） | 10 条（含纯函数边界） | **120%** ✓ |
| B TaskEngine | 4 条（§5.2） | 12 条 | **300%** ✓ |
| C SalesTarget | 4 条（§5.3） | 9 条 | **225%** ✓ |
| D BanquetLead | 4 条（§5.4） | 5 条 | **125%** ✓ |

覆盖条数超额，但**语义缺口**：
- Track A 无退款场景测试（P0-1 直接指向）。
- Track C 无多员工同门店测试（P0-2 直接指向）。
- Track D 无订金退款链路测试（P1-3）。

---

## RLS 隔离评估（基于 dev 集成报告）

PostgreSQL RLS 策略在 v264-v267 均 enable + force，dev 集成报告确认：tunxiang_app 普通用户下，tenant_A 无法看到 tenant_B 数据。**✓ 通过**。

但需要警示：**集团 20 家店共享 tenant_id**，所以"跨店查询"不靠 RLS 隔离，靠业务层 store_id 过滤。**R1 聚合/查询都默认集团粒度**，店长看到的数据会比他期望的多——P1-5 建议就是修这个。

---

## 结论

- [x] **PR #90 在完成 P0 修复后可合并进 main**（2 个 P0 业务语义修复 + 1 个架构决策）
- [ ] **PR #90 暂不可在徐记海鲜 DEMO 数据上灰度**——需完成下列必做项：

### DEMO 灰度前必做清单
1. P0-1：修 ORDER.CANCELLED 无响应，补 2 条 refund 测试。
2. P0-2：修 aggregate_from_orders 不按 employee_id 过滤，补 2 条多员工测试。
3. P0-3：在 DEVLOG.md 明确 `LifecycleService` 老版的淘汰时间表，避免双系统并存。
4. 补 Tier 1 测试：P1-3 的 banquet 订金退款链路（至少 1 条）。
5. CI 在 staging 库 `demo-xuji-seafood.sql` 全量跑通 RLS 隔离 + 200 并发压测，P99 < 200ms。

### 推荐的合并路径
```
feat/sprint-r1 （当前）
  ├─ commit: fix(tx-member): customer lifecycle projector handle refund/cancel   [P0-1]
  ├─ commit: fix(tx-org): sales_target aggregate by employee_id                  [P0-2]
  ├─ commit: docs(devlog): deprecate legacy LifecycleService, keep new FSM only  [P0-3]
  ├─ commit: test(tx-member/tx-org): add refund + multi-employee tier1 cases
  └─ → merge to main → staging CI → demo-xuji-seafood 灰度 5% → 50% → 100%
```

---

## 附录：审查方法与证据留痕

- 审查时长：1 会话
- 阅读文件数：22 个（含契约/迁移/服务/仓库/API/测试）
- 使用工具：Read / Grep / Glob（未运行 pytest，符合约束）
- 视角：徐记海鲜解放西店收银员老王 + 代码审查者双视角

**审查人签名**：Claude Opus 4.7 (1M context)
**审查提交签名**：`git show HEAD --stat` on `feat/sprint-r1`（HEAD=`2796d529`）
**审查完成时间**：2026-04-23（北京时间）

> 本报告只读产出，未修改任何代码/测试/文档。下一步由创始人决策：立即启动 P0 修复？还是接受 P0 进入 R2 开局？
