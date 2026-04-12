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
  owned_benefit_type: string | null;
  owned_benefit_expire_at: string | null;
  growth_opt_out: boolean;
  marketing_pause_until: string | null;
  first_order_at: string | null;
  second_order_at: string | null;
  last_order_at: string | null;
  last_growth_touch_at: string | null;
  last_growth_touch_channel: string | null;
  // P1 fields
  psych_distance_level: string | null;
  super_user_level: string | null;
  growth_milestone_stage: string | null;
  growth_milestone_progress: number | null;
  growth_milestone_next: string | null;
  referral_scenario: string | null;
  created_at: string;
  updated_at: string;
}

export interface JourneyTemplate {
  id: string;
  tenant_id: string;
  name: string;
  journey_type: string;
  mechanism_family: string | null;
  description: string | null;
  trigger_rule_json: Record<string, unknown> | null;
  total_steps: number;
  is_active: boolean;
  is_system?: boolean | null;
  priority?: number | null;
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
  recovered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentSuggestion {
  id: string;
  tenant_id: string;
  customer_id: string | null;
  suggestion_type: string;
  priority: string;
  template_id: string | null;
  agent_id: string | null;
  created_by_agent: string | null;
  confidence_score: number;
  reasoning: string | null;
  explanation_summary: string;
  mechanism_type: string | null;
  recommended_channel: string | null;
  recommended_offer_type: string | null;
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
  requires_human_review?: boolean | null;
  risk_summary?: string | null;
  expected_outcome_json?: Record<string, unknown> | null;
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

// ---- Attribution Types ----

export interface MechanismAttribution {
  mechanism_type: string;
  total_touches: number;
  delivered: number;
  opened: number;
  clicked: number;
  attributed: number;
  revenue_fen: number;
  profit_fen: number;
  open_rate: number;
  attribution_rate: number;
}

export interface JourneyTemplateAttribution {
  template_name: string;
  journey_type: string;
  mechanism_family: string;
  total_enrollments: number;
  completed: number;
  exited: number;
  completion_rate: number;
  total_touches: number;
  opened: number;
  attributed: number;
  revenue_fen: number;
}

export interface RepairEffectiveness {
  total_cases: number;
  recovered: number;
  failed: number;
  closed: number;
  in_progress: number;
  recovery_rate: number;
  avg_recovery_hours: number | null;
  avg_ack_minutes: number | null;
  days: number;
}

export interface MechanismSummaryItem {
  mechanism_type: string;
  total: number;
  opened: number;
  attributed: number;
  open_rate: number;
  attribution_rate: number;
}

// ---- Attribution API Functions ----

export const fetchMechanismAttribution = (days = 7) =>
  txFetchData<{ items: MechanismAttribution[]; days: number }>(`/api/v1/growth/attribution/by-mechanism?days=${days}`);

export const fetchJourneyTemplateAttribution = (days = 7) =>
  txFetchData<{ items: JourneyTemplateAttribution[]; days: number }>(`/api/v1/growth/attribution/by-journey-template?days=${days}`);

export const fetchRepairEffectiveness = (days = 30) =>
  txFetchData<RepairEffectiveness>(`/api/v1/growth/attribution/repair-effectiveness?days=${days}`);

// ---- Segment Rules & Tag Distribution (P0 补齐) ----

export interface SegmentPreset {
  id: string;
  name: string;
  description: string;
  tag_type: string;
  conditions: { field: string; op: string; value: unknown }[];
  matched_count: number;
  recommended_action: string;
  priority: string;
}

export interface TagDistribution {
  repurchase_stage: { stage: string; count: number }[];
  reactivation_priority: { priority: string; count: number }[];
  service_repair_status: { status: string; count: number }[];
}

export const fetchSegmentPresets = () =>
  txFetchData<{ presets: SegmentPreset[] }>('/api/v1/growth/segment-rules/presets');

export const fetchTagDistribution = () =>
  txFetchData<TagDistribution>('/api/v1/growth/segment-rules/tag-distribution');

// ---- Offer Packs (P0 权益包) ----

export interface OfferPackItem {
  type: string;
  name: string;
  description: string;
  cost_fen: number;
}

export interface OfferPack {
  code: string;
  name: string;
  pack_type: string;
  mechanism_type: string;
  description: string;
  items: OfferPackItem[];
  budget_limit_fen: number;
  valid_days: number;
}

export const fetchOfferPacks = (params?: { pack_type?: string; mechanism_type?: string }) => {
  const qs = params ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v != null) as [string, string][]).toString() : '';
  return txFetchData<{ items: OfferPack[]; total: number }>(`/api/v1/growth/offer-packs${qs}`);
};

// ---- P1 Distribution Types & APIs ----

export interface P1Distribution {
  psych_distance: { level: string; count: number }[];
  super_user: { level: string; count: number }[];
  milestones: { stage: string; count: number }[];
  referral: { scenario: string; count: number }[];
}

export const fetchP1Distribution = () =>
  txFetchData<P1Distribution>('/api/v1/growth/p1/distribution');

export const triggerP1Recompute = () =>
  txFetch<{ ok: boolean }>('/api/v1/growth/p1/recompute', { method: 'POST' });

// ---- Agent Suggestion with explanation (for dashboard TOP3) ----

export interface AgentSuggestionDetail {
  id: string;
  suggestion_type: string;
  confidence_score: number;
  reasoning: string | null;
  review_state: string;
  mechanism_type?: string | null;
  explanation_summary?: string | null;
  priority?: string | null;
  created_at: string;
}

export const fetchTopAgentSuggestions = (size = 3) =>
  txFetchData<{ items: AgentSuggestionDetail[]; total: number }>(
    `/api/v1/growth/agent-suggestions?review_state=pending_review&size=${size}`,
  );

// ---- Journey Enrollment Detail (for drill-down drawer) ----

export interface JourneyEnrollmentDetail {
  id: string;
  customer_id: string;
  journey_state: string;
  current_step_no: number | null;
  entered_at: string;
  completed_at: string | null;
  exited_at: string | null;
  exit_reason: string | null;
}

export const fetchJourneyEnrollmentsByTemplate = (templateId: string, size = 20) =>
  txFetchData<{ items: JourneyEnrollmentDetail[]; total: number }>(
    `/api/v1/growth/journey-enrollments?journey_template_id=${templateId}&size=${size}`,
  );

// ---- Sprint G/H: Store & Brand Attribution Types ----

export interface StoreAttribution {
  store_id: string;
  store_name: string;
  brand_name: string;
  active_journeys: number;
  total_touches: number;
  opened: number;
  open_rate: number;
  attributed_orders: number;
  attribution_rate: number;
  attributed_gmv_fen: number;
  second_visit_rate: number;
  recall_rate: number;
  stored_value_rate: number;
  journey_roi: number;
}

export interface BrandDashboardStats {
  brand_name: string;
  total_customers: number;
  active_journeys: number;
  touches_7d: number;
  open_rate: number;
  attribution_rate: number;
  stable_repurchase: number;
  high_priority_recall: number;
  second_visit_rate: number;
  recall_rate: number;
  active_rate: number;
}

export const fetchStoreAttribution = (days = 7) =>
  txFetchData<{ items: StoreAttribution[]; days: number }>(
    `/api/v1/growth/attribution/by-store?days=${days}`,
  );

export const fetchBrandDashboardStats = (days = 7) =>
  txFetchData<{ items: BrandDashboardStats[]; days: number }>(
    `/api/v1/growth/dashboard-stats/by-brand?days=${days}`,
  );

// ---- Sprint I: Experiment Types ----

export interface ExperimentVariant {
  variant: string;
  total: number;
  completed: number;
  exited: number;
  active: number;
  completion_rate: number;
  avg_duration_hours: number | null;
  // Thompson Sampling fields (in select-variant response)
  successes?: number;
  failures?: number;
  alpha?: number;
  beta?: number;
  sample?: number;
  expected_rate?: number;
}

export interface ExperimentSummary {
  template_id: string;
  variants: ExperimentVariant[];
}

export interface ExperimentSelectResult {
  selected: string;
  reason: string;
  variants: ExperimentVariant[];
}

export interface ExperimentAutoPauseResult {
  action: string;
  reason: string;
  best_rate?: number;
  pause_variants?: string[];
  variants: { variant: string; successes: number; total: number; success_rate: number }[];
}

export const fetchExperimentSummary = (templateId: string) =>
  txFetchData<ExperimentSummary>(`/api/v1/growth/experiments/${templateId}/summary`);

export const fetchExperimentSelectVariant = (templateId: string) =>
  txFetchData<ExperimentSelectResult>(`/api/v1/growth/experiments/${templateId}/select-variant`);

export const fetchExperimentAutoPause = (templateId: string, minSamples = 30) =>
  txFetchData<ExperimentAutoPauseResult>(
    `/api/v1/growth/experiments/${templateId}/auto-pause-check?min_samples=${minSamples}`,
  );

// ---- V2.3: Cross-Brand & Auto-Iterate Types ----

export interface CrossBrandProfile {
  customer_id: string;
  brand_profiles: {
    brand_id: string;
    brand_name: string;
    repurchase_stage: string;
    reactivation_priority: string;
    super_user_level: string;
    psych_distance_level: string;
  }[];
  brand_count: number;
  cross_brand_touch_total: number;
  cross_brand_touch_today: number;
  cross_brand_touch_week: number;
}

export interface CrossBrandOpportunity {
  customer_id: string;
  brand_count: number;
  brands: { brand_id: string; brand_name: string; repurchase_stage: string; reactivation_priority: string }[];
  opportunity: { type: string; description: string; recommended_action: string } | null;
}

export interface ExperimentAdjustment {
  type: string;
  mechanism_type?: string;
  channel?: string;
  journey_code?: string;
  journey_name?: string;
  open_rate?: number;
  completion_rate?: number;
  recommendation: string;
}

// ---- V2.3: Cross-Brand API Functions ----

export const fetchCrossBrandOpportunities = (page = 1, size = 20) =>
  txFetchData<{ items: CrossBrandOpportunity[]; total: number }>(`/api/v1/growth/cross-brand/opportunities?page=${page}&size=${size}`);

export const fetchCrossBrandProfile = (customerId: string) =>
  txFetchData<CrossBrandProfile>(`/api/v1/growth/cross-brand/customers/${customerId}/profile`);

export const fetchCrossBrandFrequency = (customerId: string) =>
  txFetchData<{ can_touch: boolean; today_count: number; week_count: number }>(`/api/v1/growth/cross-brand/customers/${customerId}/frequency`);

export const triggerAutoIterate = () =>
  txFetch<{ ok: boolean }>('/api/v1/growth/experiments/auto-iterate', { method: 'POST' });

export const fetchExperimentAdjustments = () =>
  txFetchData<{ adjustments: ExperimentAdjustment[] }>('/api/v1/growth/experiments/adjustments');


// ===========================================================================
// V3.0: External Signals + Store Capability
// ===========================================================================

// ---- Weather Signal Types ----
export interface WeatherImpact {
  traffic_impact: number;
  delivery_boost: number;
  indoor_preference?: number;
  outdoor_preference?: number;
}

export interface WeatherRecommendation {
  type: string;
  description: string;
  suggested_journey: string | null;
  suggested_channel: string;
  date?: string;
}

export interface WeatherSignal {
  city: string;
  date: string;
  weather_type: string;
  temperature_high: number;
  temperature_low: number;
  impact: WeatherImpact;
  growth_recommendations: WeatherRecommendation[];
}

export interface WeatherForecast {
  city: string;
  period: string;
  daily_signals: WeatherSignal[];
  aggregated_recommendations: WeatherRecommendation[];
}

// ---- Calendar Signal Types ----
export interface CalendarEvent {
  date: string;
  name: string;
  type: 'national' | 'consumer' | 'industry';
  impact: 'low' | 'medium' | 'high';
  days_before_push: number;
  target_segment?: string;
  suggested_journey?: string;
  seasonal_dish?: string;
  push_start_date: string;
  days_until: number;
  should_push_now: boolean;
}

export interface CalendarTrigger {
  event_name: string;
  event_date: string;
  event_type: string;
  impact: string;
  days_until: number;
  action?: string;
  target_segment?: string;
  suggested_journey?: string;
  seasonal_dish?: string;
  description?: string;
}

// ---- Store Capability Types ----
export interface StoreCapability {
  store_id: string;
  store_name: string;
  city: string;
  district: string;
  seats: number;
  status: string;
  has_private_room: boolean;
  has_live_seafood: boolean;
  has_outdoor_seating: boolean;
  has_delivery: boolean;
  has_stored_value: boolean;
  peak_capacity: number;
  supported_journey_types: string[];
}

export interface StoreReadiness {
  store_id: string;
  store_name: string;
  readiness_pct: number;
  supported_journeys: number;
  total_journeys: number;
  capabilities: Record<string, boolean>;
  missing_capabilities: { capability: string; blocked_journey: string; recommendation: string }[];
}

export interface StoreReadinessRankItem {
  store_id: string;
  store_name: string;
  city: string;
  seats: number;
  supported_journeys: number;
  readiness_pct: number;
}

// ---- Weather Signal API ----
export const fetchWeatherSignal = (city: string) =>
  txFetchData<WeatherSignal>(`/api/v1/growth/signals/weather?city=${encodeURIComponent(city)}`);

export const fetchWeatherForecast = (city: string) =>
  txFetchData<WeatherForecast>(`/api/v1/growth/signals/weather/forecast?city=${encodeURIComponent(city)}`);

// ---- Calendar Signal API ----
export const fetchCalendarUpcoming = (days = 14) =>
  txFetchData<CalendarEvent[]>(`/api/v1/growth/signals/calendar/upcoming?days=${days}`);

export const fetchCalendarTriggers = () =>
  txFetchData<CalendarTrigger[]>('/api/v1/growth/signals/calendar/triggers');

// ---- Store Capability API ----
export const fetchStoreCapabilities = (storeId: string) =>
  txFetchData<StoreCapability>(`/api/v1/growth/stores/${storeId}/capabilities`);

export const fetchStoreGrowthReadiness = (storeId: string) =>
  txFetchData<StoreReadiness>(`/api/v1/growth/stores/${storeId}/growth-readiness`);

export const fetchStoresReadinessRanking = () =>
  txFetchData<{ stores: StoreReadinessRankItem[]; total: number }>('/api/v1/growth/stores/readiness-ranking');

export const fetchMatchJourneyStores = (journeyCode: string) =>
  txFetchData<{ journey_code: string; required_capabilities: string[]; matching_stores: StoreReadinessRankItem[]; total: number }>(
    `/api/v1/growth/stores/match-journey/${encodeURIComponent(journeyCode)}`
  );
