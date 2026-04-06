/**
 * 增长中枢 API — Growth Hub V2
 */
import { txFetchData, txFetch } from './client';

// ---- Types ----
export interface GrowthProfile {
  id: string;
  tenant_id: string;
  customer_id: string;
  repurchase_stage: string;
  reactivation_priority: string;
  reactivation_reason: string | null;
  service_repair_status: string;
  service_repair_case_id: string | null;
  has_active_owned_benefit: boolean;
  growth_opt_out: boolean;
  marketing_pause_until: string | null;
  last_order_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface JourneyTemplate {
  id: string;
  tenant_id: string;
  name: string;
  journey_type: string;
  description: string | null;
  trigger_rule_json: Record<string, unknown> | null;
  total_steps: number;
  is_active: boolean;
  steps?: JourneyStep[];
  created_at: string;
  updated_at: string;
}

export interface JourneyStep {
  step_no: number;
  step_type: string;
  touch_template_code: string | null;
  wait_minutes: number | null;
  decision_rule_json: Record<string, unknown> | null;
  observe_window_hours: number | null;
  offer_type: string | null;
  on_success_goto: number | null;
  on_fail_goto: number | null;
  on_skip_goto: number | null;
}

export interface JourneyEnrollment {
  id: string;
  tenant_id: string;
  customer_id: string;
  template_id: string;
  journey_state: string;
  current_step_no: number | null;
  enrollment_source: string;
  source_event_type: string | null;
  source_event_id: string | null;
  suggestion_id: string | null;
  entered_at: string;
  activated_at: string | null;
  paused_at: string | null;
  completed_at: string | null;
  exited_at: string | null;
  exit_reason: string | null;
  pause_reason: string | null;
  next_execute_at: string | null;
  template_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface TouchExecution {
  id: string;
  customer_id: string;
  journey_enrollment_id: string | null;
  journey_template_id: string | null;
  step_no: number | null;
  touch_template_id: string | null;
  channel: string;
  mechanism_type: string | null;
  execution_state: string;
  blocked_reason: string | null;
  rendered_content: string | null;
  attributed_order_id: string | null;
  attributed_revenue_fen: number | null;
  attributed_gross_profit_fen: number | null;
  created_at: string;
  updated_at: string;
}

export interface ServiceRepairCase {
  id: string;
  tenant_id: string;
  customer_id: string;
  source_type: string;
  source_ref_id: string | null;
  severity: string;
  summary: string | null;
  owner_type: string;
  repair_state: string;
  emotion_ack_at: string | null;
  compensation_plan_json: Record<string, unknown> | null;
  selected_compensation: string | null;
  observe_until: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentSuggestion {
  id: string;
  tenant_id: string;
  customer_id: string | null;
  suggestion_type: string;
  template_id: string | null;
  agent_id: string | null;
  confidence_score: number;
  reasoning: string | null;
  suggested_channel: string | null;
  suggested_timing: string | null;
  suggested_message: string | null;
  review_state: string;
  reviewer_id: string | null;
  reviewer_note: string | null;
  published_at: string | null;
  published_enrollment_id: string | null;
  created_at: string;
  updated_at: string;
}

// ---- API Functions ----
export const fetchGrowthProfile = (customerId: string) =>
  txFetchData<GrowthProfile>(`/api/v1/growth/customers/${customerId}/profile`);

export const fetchJourneyTemplates = (params?: Record<string, string>) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  return txFetchData<{ items: JourneyTemplate[]; total: number }>(`/api/v1/growth/journey-templates${qs}`);
};

export const fetchJourneyTemplate = (id: string) =>
  txFetchData<JourneyTemplate>(`/api/v1/growth/journey-templates/${id}`);

export const fetchJourneyEnrollments = (params?: Record<string, string>) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  return txFetchData<{ items: JourneyEnrollment[]; total: number }>(`/api/v1/growth/journey-enrollments${qs}`);
};

export const fetchTouchExecutions = (params?: Record<string, string>) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  return txFetchData<{ items: TouchExecution[]; total: number }>(`/api/v1/growth/touch-executions${qs}`);
};

export const fetchRepairCases = (params?: Record<string, string>) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  return txFetchData<{ items: ServiceRepairCase[]; total: number }>(`/api/v1/growth/service-repair-cases${qs}`);
};

export const fetchAgentSuggestions = (params?: Record<string, string>) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  return txFetchData<{ items: AgentSuggestion[]; total: number }>(`/api/v1/growth/agent-suggestions${qs}`);
};

export const reviewSuggestion = (id: string, body: { review_result: string; reviewer_id: string; reviewer_note?: string }) =>
  txFetch<{ ok: boolean }>(`/api/v1/growth/agent-suggestions/${id}/review`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const publishSuggestion = (id: string) =>
  txFetch<{ ok: boolean }>(`/api/v1/growth/agent-suggestions/${id}/publish`, { method: 'POST' });
