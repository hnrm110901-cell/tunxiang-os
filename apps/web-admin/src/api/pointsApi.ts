/**
 * 员工积分+赛马 API 客户端
 * 对接 tx-org /api/v1/points/* 端点
 */
import { txFetchData } from './client';

// ── Types ──────────────────────────────────────────────────────────────────

export interface LeaderboardItem {
  employee_id: string;
  emp_name: string;
  store_id: string | null;
  total_points: number;
  earned: number;
  consumed: number;
  rank: number;
  level: string;
}

export interface PointHistoryItem {
  id: string;
  rule_code: string;
  rule_name: string;
  points: number;
  balance_after: number;
  reason: string;
  source: string;
  date: string;
}

export interface PointBalanceInfo {
  employee_id: string;
  balance: number;
  level: string;
  next_level: string;
  points_to_next: number;
}

export interface RewardItem {
  id: string;
  reward_name: string;
  reward_type: string;
  points_cost: number;
  stock: number;
  description: string;
  is_active: boolean;
  created_at: string;
}

export interface HorseRaceSeason {
  id: string;
  season_name: string;
  scope_type: string;
  scope_id: string | null;
  start_date: string;
  end_date: string;
  ranking_dimension: string;
  status: string;
  prizes: Record<string, unknown>[];
  rules: Record<string, unknown>;
}

export interface SeasonRankingItem {
  employee_id: string;
  emp_name: string;
  store_id: string | null;
  season_points: number;
  rank: number;
}

export interface PointsStats {
  active_employees: number;
  total_earned: number;
  total_consumed: number;
  net_balance: number;
  total_redemptions: number;
  total_redeemed_points: number;
}

// ── API Functions ──────────────────────────────────────────────────────────

/** 发放积分 */
export async function awardPoints(body: {
  employee_id: string;
  rule_code: string;
  reason?: string;
  operator_id?: string;
}) {
  return txFetchData('/api/v1/points/award', {
    method: 'POST',
    body: JSON.stringify(body),
  }) as Promise<{ ok: boolean; data: Record<string, unknown> }>;
}

/** 扣减积分 */
export async function deductPoints(body: {
  employee_id: string;
  rule_code: string;
  reason?: string;
  operator_id?: string;
}) {
  return txFetchData('/api/v1/points/deduct', {
    method: 'POST',
    body: JSON.stringify(body),
  }) as Promise<{ ok: boolean; data: Record<string, unknown> }>;
}

/** 查询积分余额 */
export async function getPointBalance(employeeId: string) {
  return txFetchData(`/api/v1/points/balance/${employeeId}`) as Promise<{
    ok: boolean;
    data: PointBalanceInfo;
  }>;
}

/** 积分流水 */
export async function getPointHistory(
  employeeId: string,
  page = 1,
  size = 20,
) {
  const q = new URLSearchParams({ page: String(page), size: String(size) });
  return txFetchData(`/api/v1/points/history/${employeeId}?${q}`) as Promise<{
    ok: boolean;
    data: { items: PointHistoryItem[]; total: number };
  }>;
}

/** 积分排行榜 */
export async function getLeaderboard(params: {
  scope_type?: string;
  scope_id?: string;
  limit?: number;
}) {
  const q = new URLSearchParams();
  if (params.scope_type) q.set('scope_type', params.scope_type);
  if (params.scope_id) q.set('scope_id', params.scope_id);
  if (params.limit) q.set('limit', String(params.limit));
  return txFetchData(`/api/v1/points/leaderboard?${q}`) as Promise<{
    ok: boolean;
    data: { items: LeaderboardItem[]; total: number };
  }>;
}

/** 兑换积分 */
export async function redeemReward(body: {
  employee_id: string;
  reward_id: string;
}) {
  return txFetchData('/api/v1/points/redeem', {
    method: 'POST',
    body: JSON.stringify(body),
  }) as Promise<{ ok: boolean; data: Record<string, unknown> }>;
}

/** 兑换商品列表 */
export async function listRewards(activeOnly = true) {
  return txFetchData(`/api/v1/points/rewards?active_only=${activeOnly}`) as Promise<{
    ok: boolean;
    data: { items: RewardItem[]; total: number };
  }>;
}

/** 创建兑换商品 */
export async function createReward(body: {
  reward_name: string;
  reward_type: string;
  points_cost: number;
  stock?: number;
  description?: string;
}) {
  return txFetchData('/api/v1/points/rewards', {
    method: 'POST',
    body: JSON.stringify(body),
  }) as Promise<{ ok: boolean; data: Record<string, unknown> }>;
}

/** 启停商品 */
export async function toggleReward(rewardId: string) {
  return txFetchData(`/api/v1/points/rewards/${rewardId}/toggle`, {
    method: 'PUT',
  }) as Promise<{ ok: boolean; data: { id: string; is_active: boolean } }>;
}

/** 积分统计概览 */
export async function getPointsStats(storeId?: string) {
  const q = storeId ? `?store_id=${encodeURIComponent(storeId)}` : '';
  return txFetchData(`/api/v1/points/stats${q}`) as Promise<{
    ok: boolean;
    data: PointsStats;
  }>;
}

/** 创建赛马赛季 */
export async function createHorseRaceSeason(body: {
  season_name: string;
  start_date: string;
  end_date: string;
  scope_type?: string;
  scope_id?: string;
  ranking_dimension?: string;
  prizes?: Record<string, unknown>[];
  rules?: Record<string, unknown>;
}) {
  return txFetchData('/api/v1/points/horse-race', {
    method: 'POST',
    body: JSON.stringify(body),
  }) as Promise<{ ok: boolean; data: Record<string, unknown> }>;
}

/** 赛季列表 */
export async function listHorseRaceSeasons(status?: string) {
  const q = status ? `?status=${status}` : '';
  return txFetchData(`/api/v1/points/horse-race${q}`) as Promise<{
    ok: boolean;
    data: { items: HorseRaceSeason[]; total: number };
  }>;
}

/** 赛季排名 */
export async function getSeasonRanking(seasonId: string, limit = 50) {
  return txFetchData(
    `/api/v1/points/horse-race/${seasonId}/ranking?limit=${limit}`,
  ) as Promise<{
    ok: boolean;
    data: {
      season: { id: string; season_name: string; status: string; start_date: string; end_date: string };
      ranking: SeasonRankingItem[];
    };
  }>;
}

/** 更新赛季状态 */
export async function updateSeasonStatus(seasonId: string, status: string) {
  return txFetchData(`/api/v1/points/horse-race/${seasonId}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  }) as Promise<{ ok: boolean; data: Record<string, unknown> }>;
}
