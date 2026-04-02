/**
 * 屯象OS P0 关键页面 — 完整字段字典
 *
 * 本文件是 6 个 P0 页面的 TypeScript 类型"单一事实源"。
 * 前端、BFF、后端 API 全部从此处引用，不手写 interface。
 *
 * 命名规范：
 *   scope_*       — 页面上下文字段
 *   summary_*     — Agent 输出摘要
 *   recommended_* — Agent 推荐动作
 *   risk_*        — 风险相关
 *   *_status      — 状态枚举
 *   *_at          — 存储时间 (ISO 8601)
 *   *_display_time — 展示时间 (格式化字符串)
 */

// ═══════════════════════════════════════════════════════════
// 通用枚举与基础类型
// ═══════════════════════════════════════════════════════════

export type AlertLevel = 'p1' | 'p2' | 'p3';
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

export type AlertCategory = 'operation' | 'service' | 'kitchen' | 'cashier' | 'member' | 'risk';

export type AlertType =
  | 'revenue_drop' | 'table_turn_drop' | 'service_delay'
  | 'kitchen_timeout' | 'refund_spike' | 'member_loss' | 'payment_abnormal';

export type AlertStatus = 'new' | 'pending' | 'processing' | 'closed' | 'ignored';

export type ReservationStatus =
  | 'pending_confirm' | 'confirmed' | 'arrived' | 'seated' | 'canceled' | 'no_show';

export type QueueStatus = 'waiting' | 'called' | 'missed' | 'seated' | 'canceled';

export type TableStatus =
  | 'idle' | 'reserved' | 'seated' | 'ordering' | 'dining'
  | 'waiting_payment' | 'cleaning' | 'disabled' | 'overtime';

export type CloseStatus = 'draft' | 'verifying' | 'waiting_signoff' | 'signed_off' | 'returned';

export type StepStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped';

export type CloseStepStatus = 'pending' | 'processing' | 'completed' | 'returned';

export type TaskType = 'analysis' | 'alert_disposal' | 'rectification_generate' | 'message_dispatch';
export type TaskSource = 'manual_input' | 'alert_context' | 'report_context' | 'template';
export type ExecutorType = 'orchestrator' | 'agent' | 'tool' | 'user';

export type CloseStepCode =
  | 'revenue_check' | 'payment_check' | 'refund_discount_check'
  | 'invoice_check' | 'inventory_sampling' | 'handover_check' | 'signoff';

export type TableEventType =
  | 'seated' | 'checkout' | 'overtime' | 'merge' | 'split' | 'cleaning_done';

// ═══════════════════════════════════════════════════════════
// 1. 总控 Agent 工作台 (/hub/agent/orchestrator)
// ═══════════════════════════════════════════════════════════

export interface OrchestratorTaskInput {
  task_id: string;
  task_type: TaskType;
  task_source: TaskSource;
  task_prompt: string;
  task_template_id?: string;
  task_priority: AlertLevel;
  scope_brand_ids: string[];
  scope_region_ids: string[];
  scope_store_ids: string[];
  business_date: string;
  time_range?: { start: string; end: string };
}

export interface OrchestratorStep {
  step_id: string;
  step_order: number;
  step_name: string;
  step_type: 'query_data' | 'call_agent' | 'call_tool' | 'human_approval' | 'summarize';
  executor_type: ExecutorType;
  executor_name: string;
  step_status: StepStatus;
  start_time?: string;
  end_time?: string;
  duration_ms?: number;
  error_message?: string;
  tools_called?: string[];
  result_summary?: string;
}

export interface OrchestratorResultItem {
  entity_type: 'store' | 'region' | 'member_segment' | 'reservation_group';
  entity_id: string;
  entity_name: string;
  problem_type: string;
  problem_score: number;
  problem_reason: string;
  recommended_action: string;
  requires_approval: boolean;
}

export interface OrchestratorResult {
  summary_text: string;
  target_count: number;
  risk_level: RiskLevel;
  result_items: OrchestratorResultItem[];
  next_actions: {
    action_type: string;
    action_label: string;
    action_target_id?: string;
    is_enabled: boolean;
  }[];
}

export interface ToolCallRecord {
  tool_call_id: string;
  tool_name: string;
  tool_category: string;
  input_summary: string;
  output_summary: string;
  call_status: 'success' | 'failed' | 'pending';
  call_duration_ms: number;
  retry_count: number;
}

// ═══════════════════════════════════════════════════════════
// 2. 预警中心 (/hub/alerts)
// ═══════════════════════════════════════════════════════════

export interface AlertListItem {
  alert_id: string;
  alert_code: string;
  alert_type: AlertType;
  alert_category: AlertCategory;
  alert_level: AlertLevel;
  brand_id: string;
  brand_name: string;
  region_id: string;
  region_name: string;
  store_id: string;
  store_name: string;
  metric_name: string;
  metric_value: string;
  baseline_value: string;
  deviation_rate: number;
  first_trigger_time: string;
  latest_trigger_time: string;
  alert_status: AlertStatus;
  owner_user_id?: string;
  owner_user_name?: string;
  source_type: string;
  has_agent_analysis: boolean;
  task_count: number;
}

export interface AlertDetail {
  alert_id: string;
  event_summary: string;
  impact_scope: string;
  business_shift: string;
  business_date: string;
  root_cause_candidates: {
    cause_label: string;
    confidence_score: number;
    explanation: string;
  }[];
  recommended_actions: {
    action_type: string;
    action_label: string;
    target_role: string;
    priority: AlertLevel;
  }[];
  similar_cases: {
    case_id: string;
    case_title: string;
    resolution_summary: string;
  }[];
  related_tasks: {
    task_id: string;
    task_name: string;
    task_status: string;
  }[];
}

// ═══════════════════════════════════════════════════════════
// 3. 前厅工作台 (/front/workbench)
// ═══════════════════════════════════════════════════════════

export interface FrontWorkbenchStats {
  reservation_total_today: number;
  waitlist_current_count: number;
  idle_table_count: number;
  overtime_table_count: number;
}

export interface ReservationListItem {
  reservation_id: string;
  reservation_no: string;
  reservation_time: string;
  customer_name: string;
  customer_mobile_masked: string;
  party_size: number;
  table_type_required: string;
  room_required: boolean;
  reservation_status: ReservationStatus;
  source_channel: string;
  vip_level?: string;
  estimated_value_level?: 'high' | 'medium' | 'low';
  special_notes?: string;
  assigned_table_id?: string;
  confirm_status: 'unconfirmed' | 'confirmed' | 'contacted';
  last_contact_time?: string;
}

export interface WaitlistItem {
  queue_id: string;
  queue_no: string;
  customer_name?: string;
  party_size: number;
  arrival_time: string;
  wait_duration_min: number;
  estimated_seat_time: string;
  risk_level: RiskLevel;
  queue_status: QueueStatus;
  vip_tag?: string;
  appeasement_status: 'none' | 'sent' | 'accepted';
  recommended_table_type?: string;
}

export interface TableThumbnail {
  table_id: string;
  table_no: string;
  zone_id: string;
  capacity: number;
  table_status: TableStatus;
  current_party_size?: number;
  occupied_duration_min?: number;
  next_reservation_time?: string;
}

export interface AgentSuggestionItem {
  suggestion_id: string;
  suggestion_type: 'confirm_reservation' | 'appease_waitlist' | 'turn_table' | 'vip_alert';
  priority: AlertLevel;
  title: string;
  summary: string;
  recommended_action: string;
  related_entity_type: 'reservation' | 'waitlist' | 'table';
  related_entity_id: string;
}

// ═══════════════════════════════════════════════════════════
// 4. 预订台账 (/front/reservations)
// ═══════════════════════════════════════════════════════════

export type ReservationTag = 'birthday' | 'vip' | 'banquet' | 'repeat_customer';

export interface ReservationFullItem extends ReservationListItem {
  reservation_tag?: ReservationTag[];
  assigned_table_no?: string;
  agent_risk_flag?: boolean;
  last_updated_at: string;
}

export interface ReservationDetail {
  reservation_id: string;
  reservation_note?: string;
  customer_id?: string;
  customer_level?: string;
  historical_visit_count: number;
  historical_avg_spend: number;
  dietary_preferences?: string[];
  arrival_eta?: string;
  recommended_table_options: {
    table_id: string;
    table_no: string;
    zone_name: string;
    capacity: number;
    match_score: number;
  }[];
  conflict_checks: {
    conflict_type: 'time_overlap' | 'capacity_exceed' | 'zone_full';
    conflict_desc: string;
    severity: RiskLevel;
  }[];
  contact_records: {
    contact_time: string;
    contact_channel: 'phone' | 'sms' | 'wechat';
    contact_result: 'confirmed' | 'no_answer' | 'rescheduled' | 'canceled';
  }[];
}

export interface ReservationForm {
  customer_name: string;
  customer_mobile: string;
  reservation_date: string;
  reservation_time: string;
  party_size: number;
  table_type_required: string;
  room_required: boolean;
  special_notes?: string;
  source_channel: string;
  operator_id: string;
}

// ═══════════════════════════════════════════════════════════
// 5. 桌态总览 (/front/tables)
// ═══════════════════════════════════════════════════════════

export interface TableFullItem {
  table_id: string;
  table_no: string;
  zone_id: string;
  zone_name: string;
  table_type: string;
  capacity: number;
  merge_group_id?: string;
  table_status: TableStatus;
  current_order_id?: string;
  current_party_size?: number;
  occupy_start_time?: string;
  occupy_duration_min?: number;
  estimated_turn_time?: number;
  next_reservation_time?: string;
  is_vip_reserved: boolean;
  alert_flag?: boolean;
}

export interface TableDetail {
  table_id: string;
  reservation_id?: string;
  customer_name?: string;
  customer_level?: string;
  current_order_amount?: number;
  dish_progress_summary?: string;
  service_alerts: string[];
  recommended_actions: {
    action_type: 'seat' | 'move' | 'merge' | 'split' | 'rush' | 'view_order';
    action_label: string;
    is_enabled: boolean;
  }[];
  available_merge_targets: string[];
  split_options: string[];
}

export interface TableEvent {
  event_id: string;
  event_type: TableEventType;
  table_id: string;
  table_no: string;
  event_time: string;
  operator_name?: string;
}

// ═══════════════════════════════════════════════════════════
// 6. 日清日结 (/store/manager/day-close)
// ═══════════════════════════════════════════════════════════

export interface DayCloseRecord {
  close_id: string;
  store_id: string;
  business_date: string;
  shift_type: string;
  close_status: CloseStatus;
  progress_percent: number;
  pending_item_count: number;
  abnormal_item_count: number;
  operator_user_id: string;
  signoff_user_id?: string;
  signoff_time?: string;
}

export interface DayCloseStep {
  step_id: string;
  step_code: CloseStepCode;
  step_name: string;
  step_order: number;
  step_status: CloseStepStatus;
  required_flag: boolean;
}

export interface RevenueCheck {
  gross_sales_amount: number;
  net_sales_amount: number;
  should_receive_amount: number;
  actual_receive_amount: number;
  difference_amount: number;
  difference_reason_code?: string;
  difference_note?: string;
}

export interface PaymentCheck {
  wechat_amount: number;
  alipay_amount: number;
  bankcard_amount: number;
  cash_amount: number;
  stored_value_amount: number;
  other_tender_amount: number;
  payment_total_should: number;
  payment_total_actual: number;
  payment_difference_amount: number;
}

export interface RefundDiscountCheck {
  refund_order_count: number;
  refund_amount: number;
  discount_amount: number;
  discount_order_count: number;
  abnormal_discount_flag: boolean;
  abnormal_discount_note?: string;
}

export interface InvoiceCheck {
  invoice_apply_count: number;
  invoice_issued_count: number;
  invoice_pending_count: number;
  invoice_amount_total: number;
  invoice_exception_flag: boolean;
}

export interface InventorySampling {
  sampling_item_count: number;
  sampling_diff_count: number;
  sampling_diff_amount: number;
  sampling_note?: string;
}

export interface HandoverCheck {
  shift_user_count: number;
  handover_note?: string;
  pending_issue_count: number;
  handover_confirm_flag: boolean;
}

export interface DayCloseAgentExplanation {
  daily_summary: string;
  abnormal_highlights: {
    highlight_type: string;
    highlight_desc: string;
    severity: RiskLevel;
  }[];
  root_causes: {
    cause_desc: string;
    confidence_score: number;
  }[];
  improvement_actions: {
    action_label: string;
    owner_role: string;
    expected_deadline: string;
  }[];
  rectification_draft_id?: string;
}

// ═══════════════════════════════════════════════════════════
// 页面联动参数
// ═══════════════════════════════════════════════════════════

/** 预警中心 → 总控Agent 跳转参数 */
export interface AlertToOrchestratorParams {
  alert_id: string;
  store_id: string;
  alert_type: AlertType;
  business_date: string;
}

/** 前厅工作台 → 预订台账 跳转参数 */
export interface WorkbenchToReservationParams {
  reservation_status?: ReservationStatus;
  date?: string;
}

/** 前厅工作台/预订台账 → 桌态总览 跳转参数 */
export interface ToTableBoardParams {
  highlight_table_id?: string;
  queue_id?: string;
  customer_phone?: string;
  party_size?: number;
  reservation_id?: string;
}

/** 日清日结 → 总控Agent 跳转参数 */
export interface DayCloseToOrchestratorParams {
  store_id: string;
  business_date: string;
  abnormal_items: string[];
  difference_items: string[];
}
