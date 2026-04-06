/**
 * 增长中枢 API — Growth Hub V2
 */
import { txFetchData, txFetch } from './client';

// ---- Types ----
export interface GrowthProfile {
  customer_id: string;
  repurchase_stage: string;
  reactivation_priority: string;
  reactivation_reason: string | null;
  has_active_owned_benefit: boolean;
  owned_benefit_type: string | null;
  owned_benefit_expire_at: string | null;
  service_repair_status: string;
  growth_opt_out: boolean;
  last_growth_touch_at: string | null;
  last_growth_touch_channel: string | null;
  first_order_at: string | null;
  second_order_at: string | null;
  last_order_at: string | null;
}

export interface JourneyTemplate {
  id: string;
  code: string;
  name: string;
  journey_type: string;
  mechanism_family: string;
  is_active: boolean;
  is_system: boolean;
  priority: number;
  steps?: JourneyStep[];
  created_at: string;
}

export interface JourneyStep {
  id: string;
  step_no: number;
  step_type: string;
  mechanism_type: string | null;
  wait_minutes: number | null;
  observe_window_hours: number | null;
}

export interface JourneyEnrollment {
  id: string;
  customer_id: string;
  journey_template_id: string;
  journey_state: string;
  current_step_no: number | null;
  enrollment_source: string;
  entered_at: string;
  activated_at: string | null;
  exit_reason: string | null;
  pause_reason: string | null;
}

export interface TouchExecution {
  id: string;
  customer_id: string;
  channel: string;
  mechanism_type: string | null;
  execution_state: string;
  rendered_content: string | null;
  sent_at: string | null;
  opened_at: string | null;
  attributed_revenue_fen: number | null;
  created_at: string;
}

export interface ServiceRepairCase {
  id: string;
  customer_id: string;
  source_type: string;
  severity: string;
  repair_state: string;
  summary: string | null;
  owner_type: string;
  created_at: string;
}

export interface AgentSuggestion {
  id: string;
  customer_id: string | null;
  suggestion_type: string;
  priority: string;
  mechanism_type: string | null;
  recommended_offer_type: string | null;
  recommended_channel: string | null;
  explanation_summary: string;
  risk_summary: string | null;
  expected_outcome_json: Record<string, number> | null;
  review_state: string;
  requires_human_review: boolean;
  created_by_agent: string | null;
  created_at: string;
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
