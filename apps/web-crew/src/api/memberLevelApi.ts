/**
 * 会员等级运营 API — /api/v1/member/level-configs & /api/v1/members/:id/...
 */
import { txFetch } from './index';

// ─── 类型 ───

export type LevelCode = 'normal' | 'silver' | 'gold' | 'diamond';
export type TriggerType = 'points_upgrade' | 'spend_upgrade' | 'manual' | 'expiry_downgrade';
export type EarnType = 'consumption' | 'birthday' | 'signup' | 'referral' | 'checkin';

export interface LevelConfig {
  id: string;
  tenant_id: string;
  level_code: LevelCode;
  level_name: string;
  min_points: number;
  min_annual_spend_fen: number;
  discount_rate: number;
  birthday_bonus_multiplier: number;
  priority_queue: boolean;
  free_delivery: boolean;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LevelConfigCreate {
  level_code: LevelCode;
  level_name: string;
  min_points: number;
  min_annual_spend_fen: number;
  discount_rate: number;
  birthday_bonus_multiplier: number;
  priority_queue: boolean;
  free_delivery: boolean;
  sort_order: number;
  is_active: boolean;
}

export interface LevelConfigUpdate {
  level_name?: string;
  min_points?: number;
  min_annual_spend_fen?: number;
  discount_rate?: number;
  birthday_bonus_multiplier?: number;
  priority_queue?: boolean;
  free_delivery?: boolean;
  sort_order?: number;
  is_active?: boolean;
}

export interface CheckUpgradeResult {
  upgraded: boolean;
  from_level: string | null;
  to_level: string;
  current_points: number;
  current_annual_spend_fen: number;
}

export interface LevelHistoryItem {
  id: string;
  member_id: string;
  from_level: string | null;
  to_level: string;
  trigger_type: TriggerType;
  trigger_value: number | null;
  note: string | null;
  created_at: string;
}

export interface EarnPointsResult {
  earned_points: number;
  total_points: number;
}

export interface PointsRule {
  id: string;
  tenant_id: string;
  store_id: string | null;
  rule_name: string;
  earn_type: EarnType;
  points_per_100fen: number;
  fixed_points: number;
  multiplier: number;
  valid_from: string | null;
  valid_to: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PointsRuleCreate {
  store_id?: string;
  rule_name: string;
  earn_type: EarnType;
  points_per_100fen: number;
  fixed_points: number;
  multiplier: number;
  valid_from?: string;
  valid_to?: string;
  is_active: boolean;
}

// ─── 接口 ───

/** 获取等级配置列表 */
export async function fetchLevelConfigs(tenantId: string): Promise<{ items: LevelConfig[]; total: number }> {
  return txFetch(`/api/v1/member/level-configs?tenant_id=${encodeURIComponent(tenantId)}`);
}

/** 创建等级配置 */
export async function createLevelConfig(payload: LevelConfigCreate): Promise<LevelConfig> {
  return txFetch('/api/v1/member/level-configs', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 更新等级配置 */
export async function updateLevelConfig(id: string, payload: LevelConfigUpdate): Promise<LevelConfig> {
  return txFetch(`/api/v1/member/level-configs/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

/** 检查并执行升降级 */
export async function checkMemberUpgrade(memberId: string): Promise<CheckUpgradeResult> {
  return txFetch(`/api/v1/members/${encodeURIComponent(memberId)}/check-upgrade`, {
    method: 'POST',
  });
}

/** 获取升降级历史 */
export async function fetchLevelHistory(memberId: string): Promise<{ items: LevelHistoryItem[]; total: number }> {
  return txFetch(`/api/v1/members/${encodeURIComponent(memberId)}/level-history`);
}

/** 积分入账 */
export async function earnPoints(
  memberId: string,
  payload: {
    earn_type: EarnType;
    order_id?: string;
    amount_fen?: number;
    note?: string;
  },
): Promise<EarnPointsResult> {
  return txFetch(`/api/v1/members/${encodeURIComponent(memberId)}/points/earn`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 获取积分规则列表 */
export async function fetchPointsRules(storeId?: string): Promise<{ items: PointsRule[]; total: number }> {
  const q = storeId ? `?store_id=${encodeURIComponent(storeId)}` : '';
  return txFetch(`/api/v1/member/points-rules${q}`);
}

/** 创建积分规则 */
export async function createPointsRule(payload: PointsRuleCreate): Promise<PointsRule> {
  return txFetch('/api/v1/member/points-rules', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// ─── 工具函数 ───

/** 根据等级code返回显示颜色 */
export function getLevelColor(levelCode: string): string {
  if (levelCode === 'gold') return '#facc15';
  if (levelCode === 'silver') return '#c0c0c0';
  if (levelCode === 'diamond') return '#ffffff';
  return '#64748b';
}

/** 根据等级code返回背景色 */
export function getLevelBgColor(levelCode: string): string {
  if (levelCode === 'gold') return '#facc1522';
  if (levelCode === 'silver') return '#c0c0c022';
  if (levelCode === 'diamond') return '#ffffff22';
  return '#64748b22';
}

/** 获取下一个等级 */
export function getNextLevel(
  configs: LevelConfig[],
  currentCode: string,
): LevelConfig | null {
  const sorted = [...configs].sort((a, b) => a.sort_order - b.sort_order);
  const idx = sorted.findIndex(c => c.level_code === currentCode);
  if (idx === -1 || idx === sorted.length - 1) return null;
  return sorted[idx + 1];
}

/** 计算到下一等级还差多少积分 */
export function calcPointsToNextLevel(
  configs: LevelConfig[],
  currentCode: string,
  currentPoints: number,
): { nextLevel: LevelConfig | null; pointsNeeded: number; progressPct: number } {
  const sorted = [...configs].sort((a, b) => a.sort_order - b.sort_order);
  const current = sorted.find(c => c.level_code === currentCode);
  const next = getNextLevel(configs, currentCode);
  if (!next || !current) return { nextLevel: null, pointsNeeded: 0, progressPct: 100 };
  const pointsNeeded = Math.max(0, next.min_points - currentPoints);
  const range = next.min_points - current.min_points;
  const progressPct = range > 0 ? Math.min(100, Math.round(((currentPoints - current.min_points) / range) * 100)) : 100;
  return { nextLevel: next, pointsNeeded, progressPct };
}
