# 预订业务 Sprint R2 契约文档

> 文档日期：2026-04-23
> 状态：契约冻结（Sprint R2 实装期间 3 个并行 Agent 不得修改本文约定）
> 关联：
> - 规划：`docs/reservation-roadmap-2026-q2.md` §5 / §6 Sprint R2
> - R1 契约：`docs/reservation-r1-contracts.md`
> - R1 DEV 联调：`docs/sprint-r1-dev-integration-report.md`（已通过 ✅）
> - 规范：`CLAUDE.md` §9 Agent 开发 / §14 审计修复期 / §15 事件总线 / §17 Tier 分级 / §18 Ontology 冻结

本文档是 Sprint R2 的契约冻结层，为三个并行实装 Agent（Track R2-A / R2-B / R2-C）提供共享的数据模型、事件约定、文件所有权边界、硬约束校验矩阵与测试场景。任何 Track 不得越界修改其他 Track 的文件。

---

## 1. Agent 分工 + 文件所有权边界

三条并行线，每条线独占一个目录前缀 + 一个 Pydantic 模块 + 一组迁移后缀。

### Track R2-A — reservation_concierge（AI 预订礼宾员，P0）

**可写**：
- `services/tx-agent/src/agents/skills/reservation_concierge.py`（新建）
- `services/tx-agent/src/services/reservation_concierge/` 全目录（新建）
- `services/tx-agent/src/api/reservation_concierge_routes.py`（新建）
- `services/tx-trade/src/services/reservation_invitation_service.py`（新建）
- `services/tx-trade/src/api/reservation_invitation_routes.py`（新建）
- `apps/web-pos/src/pages/CallerPopupPanel.tsx`（新建，来电弹屏）
- `edge/coreml-bridge/routes/whisper_transcribe.py`（新建，Whisper 桥接）
- `services/tx-agent/tests/tier2/test_reservation_concierge_tier2.py`（新建）
- `services/tx-trade/tests/tier2/test_reservation_invitations_tier2.py`（新建）

**可读**：
- `shared/ontology/src/extensions/reservation_invitations.py`
- `shared/ontology/src/extensions/agent_actions.py`（CallerIdentify/Suggest/Collision/SendInvitation/ConfirmArrival params）
- `shared/ontology/src/extensions/customer_lifecycle.py`（读沉睡状态）
- `shared/events/src/event_types.py`（`R2ReservationEventType`）
- R1 已建表：`customer_lifecycle_state` / `banquet_leads`
- 现有 `reservations` / `customers` / `members` 表

**禁止触碰**：
- `services/tx-agent/src/agents/skills/` 下其他 Agent 文件
- R1 已合入的 service / projector / 迁移
- `cashier_engine.py` / 支付 Saga

### Track R2-B — sales_coach（销售经理教练，P1）

**可写**：
- `services/tx-agent/src/agents/skills/sales_coach.py`（新建）
- `services/tx-agent/src/services/sales_coach/` 全目录（新建）
- `services/tx-agent/src/api/sales_coach_routes.py`（新建）
- `services/tx-org/src/services/sales_coach_job_service.py`（新建，每日定时派发）
- `apps/web-crew/src/tabs/SalesTargetTab.tsx`（新建）
- `apps/web-crew/src/tabs/TaskListTab.tsx`（新建）
- `services/tx-agent/tests/tier2/test_sales_coach_tier2.py`（新建）
- `services/tx-org/tests/tier2/test_sales_coach_job_tier2.py`（新建）

**可读**：
- `shared/ontology/src/extensions/agent_actions.py`（Decompose/Dispatch/Diagnose/Coach/Audit/ProfileCompleteness params）
- `shared/ontology/src/extensions/sales_targets.py` / `tasks.py`（R1 只读消费）
- `shared/ontology/src/extensions/customer_lifecycle.py`（读 4 象限）
- `shared/events/src/event_types.py`（`SalesCoachEventType` + 消费 R1 的 `TaskEventType` / `SalesTargetEventType` / `CustomerLifecycleEventType`）

**禁止触碰**：
- R1 的 task_dispatch_service / sales_target_service（只能通过 API 或事件消费）
- `reservation_concierge` / `banquet_contract_agent` 的任何内部模块
- `entities.py` / `base.py` / `enums.py`（§18 冻结）

### Track R2-C — banquet_contract_agent（宴会合同管家，P1）

**可写**：
- `services/tx-agent/src/agents/skills/banquet_contract_agent.py`（新建）
- `services/tx-agent/src/services/banquet_contract/` 全目录（新建）
- `services/tx-agent/src/api/banquet_contract_routes.py`（新建）
- `services/tx-trade/src/services/banquet_contract_service.py`（新建）
- `services/tx-trade/src/services/banquet_eo_service.py`（新建）
- `services/tx-trade/src/api/banquet_contract_routes.py`（新建）
- `services/tx-trade/src/templates/banquet_contract_pdf.py`（新建，PDF 模板）
- `apps/web-admin/src/pages/banquet/ContractBoard.tsx`（新建）
- `services/tx-agent/tests/tier2/test_banquet_contract_agent_tier2.py`（新建）
- `services/tx-trade/tests/tier2/test_banquet_contracts_tier2.py`（新建）

**可读**：
- `shared/ontology/src/extensions/banquet_contracts.py`
- `shared/ontology/src/extensions/agent_actions.py`（Generate/Split/Route/Lock/Reminder params）
- `shared/ontology/src/extensions/banquet_leads.py`（R1 只读消费）
- `shared/events/src/event_types.py`（`BanquetContractEventType` + 消费 R1 的 `BanquetLeadEventType`）

**禁止触碰**：
- R1 的 banquet_lead_service / banquet_funnel_projector（只读消费）
- 其他两个 Track 的 Agent 文件
- 现有 `banquet_*_routes.py` 中的 deposit/payment 支付链路

### 共享只读区（任何 Track 均不允许修改）

- `shared/ontology/src/entities.py` / `base.py` / `enums.py`（§18 冻结）
- `shared/events/src/emitter.py` / `pg_event_store.py`
- 已发布迁移 v001-v280，包括 R1 四迁移 v264-v267
- R2 两迁移 v281 / v282（本 PR 提交后冻结）
- R1 冻结的 `shared/ontology/src/extensions/` 四模块（customer_lifecycle/tasks/sales_targets/banquet_leads）

---

## 2. 事件类型 + payload schema

全部 R2 新事件已注册到 `shared/events/src/event_types.py`，入 `ALL_EVENT_ENUMS`，金额字段必须 **以 `_fen` 结尾、类型 int、单位分**（对齐 CLAUDE.md §15）。

### 2.1 R2ReservationEventType（Track R2-A）

| 事件类型 | 枚举 | payload 必填字段 | payload 可选字段 |
|---|---|---|---|
| `reservation.created` | `CREATED` | `reservation_id`, `channel` | `customer_id`, `store_id`, `scheduled_at` |
| `reservation.cancelled` | `CANCELLED` | `reservation_id`, `cancelled_at`, `reason` | `operator_id` |
| `reservation.no_show` | `NO_SHOW` | `reservation_id`, `scheduled_at`, `detected_at` | `confirm_call_id` |
| `reservation.confirmed` | `CONFIRMED` | `reservation_id`, `confirmed_at` | `confirm_channel` |
| `reservation.confirm_call_sent` | `CONFIRM_CALL_SENT` | `reservation_id`, `invitation_id`, `sent_at` | `call_id`, `transcript_excerpt` |
| `reservation.invitation_sent` | `INVITATION_SENT` | `reservation_id`, `invitation_id`, `channel`, `sent_at` | `coupon_code`, `coupon_value_fen` |

`stream_id` = `reservation_id`，`stream_type` = `reservation`，Redis Stream = `tx_reservation_events`（与 R1 `ReservationEventType` 共用）。

### 2.2 SalesCoachEventType（Track R2-B）

| 事件类型 | 枚举 | payload 必填字段 | payload 可选字段 |
|---|---|---|---|
| `sales_coach.daily_tasks_dispatched` | `DAILY_TASKS_DISPATCHED` | `plan_date`, `dispatched_count`, `employee_id` | `dispatched_count_by_type` |
| `sales_coach.coaching_advice` | `COACHING_ADVICE` | `employee_id`, `advice_count` | `focus`, `confidence` |
| `sales_coach.gap_alert` | `GAP_ALERT` | `target_id`, `achievement_rate`, `gap_threshold` | `suggested_call_count`, `expected_recovery_fen` |

`stream_id` = `employee_id` 或 `target_id`，`stream_type` = `sales_coach`，Redis Stream = `tx_sales_coach_events`。

> achievement_rate / gap_threshold 用字符串表达 Decimal，不用 float（对齐 R1 契约 §2.3）。

### 2.3 BanquetContractEventType（Track R2-C）

| 事件类型 | 枚举 | payload 必填字段 | payload 可选字段 |
|---|---|---|---|
| `banquet.contract_generated` | `CONTRACT_GENERATED` | `contract_id`, `lead_id`, `total_amount_fen` | `pdf_url`, `generation_ms` |
| `banquet.contract_signed` | `CONTRACT_SIGNED` | `contract_id`, `signed_at` | `signer_id`, `signature_provider` |
| `banquet.eo_dispatched` | `EO_DISPATCHED` | `contract_id`, `ticket_ids`, `departments` | `dispatched_at` |
| `banquet.approval_routed` | `APPROVAL_ROUTED` | `contract_id`, `approver_id`, `role`, `action` | `notes`, `next_role` |
| `banquet.schedule_locked` | `SCHEDULE_LOCKED` | `contract_id`, `scheduled_date`, `store_id` | `queued_contract_ids`, `deposit_paid_fen` |

`stream_id` = `contract_id`，`stream_type` = `banquet_lead`（复用 R1 stream_type），Redis Stream = `tx_banquet_lead_events`（与 R1 `BanquetLeadEventType` 共用）。

> 金额字段全部 `_fen` 结尾，单位为分（int）。

---

## 3. Pydantic 模型字段表

全部契约位于 `shared/ontology/src/extensions/`：

### 3.1 reservation_invitations.py

| 模型 | 字段 | 类型 | 说明 |
|---|---|---|---|
| `InvitationChannel`（Enum） | sms / wechat / call | str | 通道类型 |
| `InvitationStatus`（Enum） | pending / sent / confirmed / failed | str | 状态机 |
| `InvitationRecord` | invitation_id | UUID | PK |
| | tenant_id, store_id?, reservation_id, customer_id? | UUID | |
| | channel | InvitationChannel | 必填 |
| | status | InvitationStatus | 默认 pending |
| | sent_at?, confirmed_at? | datetime | 状态相关必填 |
| | coupon_code? (≤64), coupon_value_fen (≥0, int) | | 附带券 |
| | failure_reason? (≤200) | str | failed 必填 |
| | payload | dict | 通道上下文 |
| | source_event_id? | UUID | 因果链 |
| | created_at, updated_at | datetime | |
| `InvitationCreateRequest` | tenant_id, reservation_id, channel, coupon_*, payload | 输入子集 | send_invitation 用 |
| `InvitationUpdateRequest` | invitation_id, target_status, sent_at?, confirmed_at?, failure_reason? | 输入子集 | 回调状态跃迁 |

### 3.2 banquet_contracts.py

| 模型 | 字段 | 类型 | 说明 |
|---|---|---|---|
| `ContractStatus`（Enum） | draft / pending_approval / signed / cancelled | str | |
| `EOTicketStatus`（Enum） | pending / dispatched / in_progress / completed | str | |
| `EODepartment`（Enum） | kitchen / hall / purchase / finance / marketing | str | 5 部门 |
| `ApprovalAction`（Enum） | approve / reject | str | |
| `ApprovalRole`（Enum） | store_manager / district_manager / finance_manager | str | |
| `BanquetContract` | contract_id | UUID | PK |
| | tenant_id, store_id?, lead_id, customer_id, sales_employee_id? | mixed | |
| | banquet_type | BanquetType | 复用 R1 枚举 |
| | tables (≥0), total_amount_fen (≥0), deposit_fen (≥0 且 ≤total) | int | 金额分 |
| | pdf_url? (≤500), status, approval_chain | mixed | |
| | scheduled_date?, signed_at?, cancelled_at?, cancellation_reason? | | 状态相关必填 |
| | metadata, created_by?, created_at, updated_at | | |
| `BanquetEOTicket` | eo_ticket_id | UUID | PK |
| | tenant_id, contract_id (FK CASCADE), department, assignee_employee_id? | mixed | |
| | content, status, dispatched_at?, completed_at?, reminder_sent_at? | | 工单上下文 |
| | created_at, updated_at | datetime | |
| `BanquetApprovalLog` | log_id | UUID | PK |
| | tenant_id, contract_id (FK CASCADE), approver_id, role, action | mixed | |
| | notes? (≤500) | str | reject 必填 |
| | source_event_id?, created_at | | |
| `BanquetContractCreateRequest` / `BanquetEODispatchRequest` / `BanquetApprovalRouteRequest` | 输入子集 | | 3 Agent action 入参 |

### 3.3 agent_actions.py

每个 Agent 的 5~6 个 action 都对应一组 ActionParams + ActionResult：

#### reservation_concierge（5 组）
| Action | ActionParams | ActionResult |
|---|---|---|
| identify_caller | `CallerIdentifyParams` | `CallerIdentifyResult`（含 `CallerProfile`，`inference_layer=edge`） |
| suggest_slot | `SuggestSlotParams` | `SuggestSlotResult`（含 `SlotOption[]`） |
| detect_collision | `DetectCollisionParams` | `DetectCollisionResult`（含 `CollisionDecision`） |
| send_invitation | `SendInvitationParams` | `SendInvitationResult`（含 `InvitationRecord[]`） |
| confirm_arrival | `ConfirmArrivalParams` | `ConfirmArrivalResult`（`ConfirmArrivalOutcome`，`inference_layer=edge`） |

#### sales_coach（6 组）
| Action | ActionParams | ActionResult |
|---|---|---|
| decompose_target | `DecomposeTargetParams` | `DecomposeTargetResult`（父子总和校验） |
| dispatch_daily_tasks | `DispatchDailyTasksParams` | `DispatchDailyTasksResult`（按 task_type 聚合计数） |
| diagnose_gap | `DiagnoseGapParams` | `DiagnoseGapResult`（含 `GapRemediation[]`） |
| coach_action | `CoachActionParams` | `CoachActionResult`（含 `CoachingAdvice[]`） |
| audit_coverage | `AuditCoverageParams` | `AuditCoverageResult`（dormant_ratio + 未维护 VIP） |
| score_profile_completeness | `ProfileCompletenessParams` | `ProfileCompletenessResult`（按员工 `ProfileScoreEntry`） |

#### banquet_contract_agent（5 组）
| Action | ActionParams | ActionResult |
|---|---|---|
| generate_contract | `GenerateContractParams` | `GenerateContractResult`（含 `BanquetContract` + pdf_url） |
| split_eo | `SplitEOParams` | `SplitEOResult`（含 `BanquetEOTicket[]`） |
| route_approval | `RouteApprovalParams` | `RouteApprovalResult`（含 next_role / final_status） |
| lock_schedule | `LockScheduleParams` | `LockScheduleResult`（FIFO 候补队列） |
| progress_reminder | `ProgressReminderParams` | `ProgressReminderResult`（按部门推送） |

共享：`AgentDecisionLogRecord`（3 Agent 决策留痕共用结构，对齐 CLAUDE.md §9）。

---

## 4. Tier 验收标准

> 对齐 CLAUDE.md §17 / §20 — R2 三 Agent 的 Tier 级别定位。

| Agent | 优先级 | Tier | 验收门槛 | 备注 |
|---|---|---|---|---|
| reservation_concierge | **P0** | **Tier 2 高标准** | 集成测试覆盖主流程 + DEMO 环境手动验证 + Whisper 端到端跑通 | 涉及客户体验，不涉及资金；外呼/邀请函失败必须幂等，不可重发 |
| sales_coach | P1 | Tier 2 高标准 | 集成测试覆盖派单/诊断 + 500 任务批量派发 P99 < 2s | 不触发资金路径，但影响销售 KPI |
| banquet_contract_agent | P1 | Tier 2 高标准 | 集成测试 + 合同 PDF 生成 P99 < 3s + 审批链路端到端通过 | PDF 生成失败必须能重试；档期锁定必须幂等 |

> 合同 PDF 生成 P99 < 3s 和档期锁定是 R2 必须达到的硬性能门槛（对齐规划 §6 Sprint R2 Tier 2 验收）。

### 4.1 Tier 2 通用验收清单

- [ ] 集成测试覆盖主流程（DEV 环境）
- [ ] DEMO 环境（`demo-xuji-seafood.sql`）手动跑通主流程
- [ ] P99 延迟已记录
- [ ] 3 Agent 的 AgentDecisionLog 均正确写入
- [ ] 三条硬约束校验矩阵在 §6 覆盖的部分全部通过
- [ ] progress.md 已更新，注明已知风险（对齐 CLAUDE.md §18）

---

## 5. 测试场景清单（每 Agent ≥ 6 条）

### 5.1 reservation_concierge（8 条）

1. **`test_caller_identify_hit_vip_returns_profile_card_under_500ms`**
   已知 VIP 来电，Whisper 边缘推理 < 500ms，返回含 vip_level / 上次消费 / 忌口的画像卡。
2. **`test_caller_identify_miss_returns_none_with_reason`**
   未知号码来电，返回 `profile=None` + `matched_by="none"` + reasoning 有"未匹配"说明。
3. **`test_suggest_slot_wedding_peak_season_returns_vip_room_first`**
   5-6 月周末婚宴需求，suggest_slot 返回的 Top3 档期应优先 VIP 包间。
4. **`test_detect_collision_same_customer_3_channels_merge_correctly`**
   同一客户同日经美团/微信/电话 3 条预订，`detect_collision` 裁决保留首收单、其他合并。
5. **`test_send_invitation_sms_wechat_dual_channel_atomic`**
   send_invitation 同时触发 sms + wechat 两通道，任一失败全部回滚（事务一致），失败通道在 `failed_channels` 中。
6. **`test_confirm_arrival_t2h_auto_cancel_on_unreachable`**
   T-2h 外呼 3 次均未接通，status 标 `unreachable`，不写 CONFIRMED 事件。
7. **`test_confirm_arrival_rescheduled_writes_new_time`**
   客户在外呼中改期，`outcome=rescheduled` + `new_scheduled_at` 必填校验生效，原预订标记改期。
8. **`test_rls_cross_tenant_invitations_isolation`**
   A 租户不能查到 B 租户的邀请记录，即使同 reservation_id。

### 5.2 sales_coach（7 条）

1. **`test_decompose_annual_target_1200w_to_12_months_exact`**
   年目标 1200 万分解到 12 个月，子目标合计 = 父目标（误差 ≤ 0.01%），parent_target_id 正确挂链。
2. **`test_dispatch_daily_tasks_500_customers_p99_under_2s`**
   早 8 点按 4 象限扫全店 500 沉睡客户自动派 `dormant_recall`，P99 < 2s，每客户仅 1 条。
3. **`test_diagnose_gap_below_85_percent_emits_alert`**
   月中销售达成率 82%（偏差 > 15%），diagnose_gap 触发 `gap_alert` 事件 + `suggested_call_count > 0`。
4. **`test_diagnose_gap_above_threshold_no_alert`**
   销售达成率 92%（偏差 < 15%），has_gap=False，不写 gap_alert 事件。
5. **`test_audit_coverage_dormant_over_40pct_raises_alert`**
   门店客户中 45% 已沉睡（> 40% 阈值），dormant_alert=True，同时列出未维护 VIP。
6. **`test_score_profile_completeness_below_50pct_dispatches_repair_task`**
   某员工名下客户平均完整度 42%，自动派发 `adhoc` 补录任务到该员工，dispatched_task_count > 0。
7. **`test_coach_action_personalized_by_focus_dimension`**
   focus=dormant 时建议偏重召回话术；focus=high_value 时建议偏重 VIP 维护；两者推荐内容不同。

### 5.3 banquet_contract_agent（7 条）

1. **`test_generate_contract_pdf_p99_under_3s`**
   20 桌婚宴合同生成，PDF 渲染 + 上传对象存储 P99 < 3s。
2. **`test_generate_contract_deposit_ratio_correct`**
   总额 20 万 + deposit_ratio=0.30，合同 deposit_fen = 60000（分），且 ≤ total_amount_fen 校验通过。
3. **`test_split_eo_5_departments_atomic`**
   合同签约后 split_eo 一次生成 5 部门工单，任一失败全部回滚（事务一致）。
4. **`test_route_approval_under_10w_auto_pass`**
   合同总额 8 万（< 10W 阈值）且非婚宴，route_approval 自动过审，`auto_passed=True`，status 直接 signed。
5. **`test_route_approval_wedding_50w_chains_to_district_manager`**
   婚宴 55 万 → 店长审 → 区经审，两级审批 approval_chain 均写入 banquet_approval_logs。
6. **`test_lock_schedule_fifo_queue_deterministic`**
   同日两场 50 桌婚宴，先付订金者获得档期，后者进 queued_contract_ids（FIFO 顺序可回放）。
7. **`test_progress_reminder_t1d_pushes_4_departments`**
   T-1d 提醒阶段，向 kitchen/hall/purchase/finance 4 部门推送（marketing 已完成则跳过，`skipped_reason` 填充）。

---

## 6. 硬约束校验矩阵（对齐 CLAUDE.md §9 / §13）

屯象 Agent 硬约束三条：**margin（毛利底线）** / **safety（食安合规）** / **experience（客户体验）**。

| Agent | margin | safety | experience | 豁免项 + 理由 |
|---|---|---|---|---|
| **reservation_concierge** | ✅ 校验 | ❌ 豁免 | ✅ 校验 | safety：预订礼宾员不涉及食材出品；suggest_slot 推荐套餐触发 margin；confirm_arrival 外呼延迟触发 experience |
| **sales_coach** | ❌ 豁免 | ❌ 豁免 | ❌ 豁免 | 纯策略/诊断层，不直接影响门店出品与资金；`constraint_scope = set()` + waived_reason：「销售教练仅生成建议与任务派发，不涉及资金/食安/出品体验」 |
| **banquet_contract_agent** | ✅ 校验 | ✅ 校验 | ❌ 豁免 | margin：套餐总价与订金比例直接决定大额订单毛利；safety：宴会食材批次绑定到工单 content；experience：合同签约与客户体验非实时关系 |

### 6.1 校验落地方式

1. 每个 Agent 在 `SkillAgent` 子类声明 `constraint_scope`：
   - `reservation_concierge.constraint_scope = {"margin", "experience"}`
   - `sales_coach.constraint_scope = set()` + `constraint_waived_reason = "销售教练仅生成建议与任务派发，不涉及资金/食安/出品体验"`
   - `banquet_contract_agent.constraint_scope = {"margin", "safety"}`

2. 每次 action 执行后，`SkillAgent.run()` 基类自动：
   - 从 `result.context` 或 `result.data` 组装 `ConstraintContext`
   - 调用 `ConstraintChecker.check_all(ctx, scope)`
   - 将结果写入 `AgentResult.constraints_detail`
   - 违规触发 `logger.warning("constraint_violation", ...)`

3. 豁免类 Agent (`sales_coach`) 的 `waived_reason` 必须 ≥ 30 字符（CI 强校验）。

---

## 7. Agent 决策留痕 AgentDecisionLog 字段

对齐 CLAUDE.md §9 Decision Log，三 Agent 每次执行必须写一条记录。契约定义见 `shared/ontology/src/extensions/agent_actions.py::AgentDecisionLogRecord`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `decision_id` | UUID | PK |
| `tenant_id` | UUID | RLS |
| `agent_id` | str | `reservation_concierge` / `sales_coach` / `banquet_contract_agent` |
| `action` | str | 触发的 action 名（如 `identify_caller`） |
| `decision_type` | str | `suggest` / `auto` / `fully_autonomous` |
| `input_context` | dict | 输入上下文快照（脱敏手机号） |
| `reasoning` | str | 推理过程摘要 |
| `output_action` | dict | 输出动作快照 |
| `constraints_check` | dict | `{margin: passed/waived/n_a, safety: ..., experience: ..., violations: []}` |
| `confidence` | float | 置信度 0.0-1.0 |
| `inference_layer` | str | `edge`（Whisper/Core ML）或 `cloud`（Claude API） |
| `created_at` | datetime | |

> 留痕表沿用 `shared/skill_registry/` 或 `services/tx-agent/src/models/` 已有结构，R2 不新建表，只复用字段。

---

## 8. 对接 R1 底座的接口

### 8.1 reservation_concierge → R1

| action | R1 依赖 | 调用方式 |
|---|---|---|
| identify_caller | `customer_lifecycle_service.get_state(customer_id)` | HTTP GET `/api/v1/customer-lifecycle/state?customer_id=...` |
| identify_caller | `customers` / `members` 表 | 本服务 DB 直查（tx-member 域） |
| suggest_slot | `banquet_leads` 表（仅读，判断是否有在途商机） | R1 API `/api/v1/banquet-leads?customer_id=...` |
| send_invitation | 现有 `reservations` 表 | tx-trade 本服务直查 |
| confirm_arrival | 现有 `reservations` 表 + R1 `tasks` 表（关联 `confirm_arrival` 任务） | tx-trade + tx-org 跨服务 |

### 8.2 sales_coach → R1

| action | R1 依赖 | 调用方式 |
|---|---|---|
| decompose_target | R1 `sales_target_service.create()` / `get()` | HTTP API `/api/v1/sales-targets` |
| dispatch_daily_tasks | R1 `task_dispatch_service.bulk_dispatch()` | HTTP API `/api/v1/tasks/dispatch` |
| diagnose_gap | R1 `sales_progress` 表（只读） + 消费 `SalesTargetEventType.PROGRESS_UPDATED` 事件流 | Redis Stream 订阅 + PG 直查（只读） |
| audit_coverage | R1 `customer_lifecycle_state` 表（只读）+ 消费 `CustomerLifecycleEventType.STATE_CHANGED` 事件流 | tx-member HTTP + 事件订阅 |
| score_profile_completeness | 现有 `customers` 表 + R1 `task_dispatch_service.dispatch()` | 直查 + 通过 Task API 派单 |
| coach_action | 上述多源数据聚合 | 只读消费，不改写 R1 表 |

### 8.3 banquet_contract_agent → R1

| action | R1 依赖 | 调用方式 |
|---|---|---|
| generate_contract | R1 `banquet_lead_service.get(lead_id)` | HTTP API `/api/v1/banquet-leads/{lead_id}`（只读） |
| generate_contract | 写新表 `banquet_contracts`（v282） | tx-trade 本服务直写 |
| split_eo | 写新表 `banquet_eo_tickets` | tx-trade 本服务直写 |
| route_approval | 写新表 `banquet_approval_logs` | tx-trade 本服务直写 |
| lock_schedule | R1 `banquet_leads.stage` 写 `order` + 更新 `converted_reservation_id` | R1 API `POST /api/v1/banquet-leads/{lead_id}/change-stage`（发 `BanquetLeadEventType.CONVERTED` 事件） |
| lock_schedule | 现有 `reservations` 表（创建/锁定档期） | tx-trade 本服务直写 |
| progress_reminder | R1 `task_dispatch_service`（推送 `banquet_stage` 类型任务） | HTTP API `/api/v1/tasks/dispatch` |

### 8.4 跨 Agent 交互约束

- **禁止 Agent 直接 import 彼此的 service / repo**，只能通过 HTTP API 或事件总线通信
- 所有跨服务调用须带 `X-Tenant-ID` header 并激活 RLS
- 所有只读查询优先走 R1 已建的物化视图（R1 计划的 `mv_customer_lifecycle` / `mv_banquet_funnel` 将在 R2 投影器上线后可用）

---

## 9. 验收准入（R2 完成标准）

- [ ] 迁移 v281 / v282 在 DEV 环境 apply + downgrade 回退都通过
- [ ] 3 个 Agent 的 Tier 2 测试全部通过（P99 延迟达标）
- [ ] `shared/events/src/event_types.py` 新增 3 枚举已被 `ALL_EVENT_ENUMS` 包含（✅ 本 PR 已校验）
- [ ] `shared/ontology/src/extensions/` 下每个 R2 模型带 `Field(description=...)`（✅ 本 PR 已校验）
- [ ] 硬约束校验矩阵（§6）每 Agent 落到 `constraint_scope` 声明
- [ ] 本契约文档在 R2 结束前不被任何 Track 修改（改动需单独 PR，创始人确认）
- [ ] 三个 Track 的 PR 合并顺序：R2-A → R2-B → R2-C（按迁移依赖：v281 前置，v282 次之；sales_coach 不依赖新迁移）
- [ ] R2 全量 DEMO 验收通过（`demo-xuji-seafood.sql` 跑通 3 Agent 主流程）

---

## 10. 已知风险 / 遗留

- **R2 迁移版本号顺延**：规划原用 v230-v233，R1 顺延为 v264-v267；R2 本应接续 v268-v269，但 v266-v277 + v280 已被 SOP / 记忆进化 / 薪资异常平行分支占用，因此 R2 再次顺延到 **v281 / v282**。迁移链：`v267 → v270_tasks_idem → v281 → v282`（其中 `v270_tasks_idem` 为独立验证 P1-2 修复插入的 tasks 表幂等唯一索引迁移）。SOP / 记忆进化平行分支独立存在，由各自 PR 维护。
- **Whisper 边缘推理模型未部署**：需先在 `edge/coreml-bridge` 准备 Whisper.cpp 或 WhisperKit 模型包，否则 `reservation_concierge.identify_caller` / `confirm_arrival` 降级为云端推理。
- **电子签第三方选型未定**（复用规划 §9）：e 签宝 / 法大大 / 腾讯电子签三选一；R2 合同签约事件先占位 `signature_provider=placeholder`，第三方打通后切换。
- **sales_coach 定时任务调度未指定**：每日派单需接入 `services/tx-org/src/services/scheduler.py` 或独立 cron worker，R2 实装需确认。
- **banquet_contracts.lead_id 无外键**：跨服务弱耦合，应用层校验；若 R1 的 `banquet_leads` 行被误删会导致合同引用失效 — 通过事件流软一致性兜底。
- **reservation_invitations 未建与 reservations 表的外键**：R1 的 `reservations` 表在 R3 前仍在演进，本 R2 只以 UUID 字段存，由应用层校验。
- **AI 外呼牌照**（复用规划 §9）：运营商合作或讯飞/阿里云第三方平台未选型，R2 先打通 Whisper 转写 + 文本外呼协议栈。

---

## 11. 附录：规范引用一览

- `CLAUDE.md §9` Agent 开发规范（Master + Skill Agent / 双层推理 / 决策留痕）
- `CLAUDE.md §13` 禁止事项（包括"禁止 Agent 突破三条硬约束"）
- `CLAUDE.md §14` 审计修复期约束（新表必含 tenant_id + RLS 使用 `app.tenant_id`）
- `CLAUDE.md §15` 事件总线（emit_event 并行写入，payload 金额用分）
- `CLAUDE.md §17` Tier 分级（Tier 2 高标准：集成测试 + DEMO 手工验收）
- `CLAUDE.md §18` Ontology 冻结（entities.py 不得自动修改，扩展走 extensions/）
- `CLAUDE.md §20` Tier 测试标准（用例基于餐厅场景）
- `docs/reservation-roadmap-2026-q2.md §5.1-§5.3` 3 Agent 规划详情
- `docs/reservation-r1-contracts.md` R1 契约范式
