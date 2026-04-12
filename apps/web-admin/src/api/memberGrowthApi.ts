/**
 * 会员增长中枢 API
 * 服务: tx-member + tx-growth
 * 页面: MemberDashboardPage / MemberSegmentPage
 */
import { txFetchData } from './client';

// ────────── 类型定义 ──────────

export interface MemberDashboardData {
  total_members: number;
  daily_new: number;
  active_members: number;
  active_rate: number;
  stored_value_total_fen: number;
  monthly_recharge_fen: number;
  avg_ticket_fen: number;
  avg_ticket_change: number;
  repurchase_rate: number;
  repurchase_change: number;
  member_revenue_ratio: number;
  member_revenue_change: number;
  rfm_distribution: RFMDistItem[];
  lifecycle: LifecycleStep[];
  trend_30d: MemberTrendPoint[];
  channel_sources: ChannelSource[];
}

export interface RFMDistItem {
  level: string;
  label: string;
  count: number;
  color: string;
}

export interface LifecycleStep {
  stage: string;
  count: number;
  conversion_rate: number;
}

export interface MemberTrendPoint {
  date: string;
  new_members: number;
  active: number;
  recharge_fen: number;
}

export interface ChannelSource {
  channel: string;
  count: number;
  ratio: number;
}

export interface RFMCell {
  level: string;
  label: string;
  r: 'high' | 'low';
  f: 'high' | 'low';
  m: 'high' | 'low';
  count: number;
  ratio: number;
  description: string;
  color: string;
}

export interface RFMDistribution {
  cells: RFMCell[];
  total_members: number;
  updated_at: string;
}

export interface MemberListItem {
  id: string;
  name: string;
  phone_masked: string;
  total_spent_fen: number;
  last_order_at: string;
  order_count: number;
  rfm_level: string;
  tags: string[];
  registered_at: string;
}

export interface MemberListResult {
  items: MemberListItem[];
  total: number;
}

export interface MemberTag {
  id: string;
  name: string;
  color: string;
  member_count: number;
  is_auto: boolean;
  rule?: string;
}

export interface CreateTagPayload {
  name: string;
  color: string;
  description?: string;
  is_auto?: boolean;
  rule?: string;
}

export interface CreateSegmentPayload {
  name: string;
  rfm_levels: string[];
  tag_ids: string[];
  description?: string;
}

export interface SegmentResult {
  id: string;
  name: string;
  member_count: number;
  created_at: string;
}

// ────────── API 函数 ──────────

/** 会员驾驶舱总览数据 */
export async function fetchMemberDashboard(): Promise<MemberDashboardData> {
  return txFetchData<MemberDashboardData>('/api/v1/member/dashboard');
}

/** RFM 分层分布（矩阵数据） */
export async function fetchRFMDistribution(): Promise<RFMDistribution> {
  return txFetchData<RFMDistribution>('/api/v1/member/rfm/distribution');
}

/** 某个 RFM 层级的会员列表 */
export async function fetchRFMLevelMembers(
  level: string,
  page = 1,
  size = 20,
): Promise<MemberListResult> {
  return txFetchData<MemberListResult>(
    `/api/v1/member/rfm/${encodeURIComponent(level)}/members?page=${page}&size=${size}`,
  );
}

/** 标签列表 */
export async function fetchMemberTags(): Promise<MemberTag[]> {
  return txFetchData<MemberTag[]>('/api/v1/member/tags');
}

/** 创建标签 */
export async function createMemberTag(payload: CreateTagPayload): Promise<MemberTag> {
  return txFetchData<MemberTag>('/api/v1/member/tags', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 创建人群包 */
export async function createSegment(payload: CreateSegmentPayload): Promise<SegmentResult> {
  return txFetchData<SegmentResult>('/api/v1/member/segments', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
