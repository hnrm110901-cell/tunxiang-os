/**
 * KDS 多维标识与颜色规则配置 API
 * 对应后端 GET/PUT /api/v1/kds-rules/{store_id}
 */
import { txFetch } from './index';

// ─── 类型定义 ───

export interface KDSChannelColors {
  dine_in: string;
  takeout: string;
  pickup: string;
  [key: string]: string;
}

export interface KDSRuleConfig {
  // 超时预警
  warn_minutes: number;
  warn_color: string;
  urgent_minutes: number;
  urgent_color: string;
  // 渠道标识色
  channel_colors: KDSChannelColors;
  // 标识开关
  show_guest_seat: boolean;
  show_remark: boolean;
  show_cooking_method: boolean;
  show_channel_badge: boolean;
  // 特殊标识颜色
  gift_badge_color: string;
  return_badge_color: string;
}

export const DEFAULT_KDS_RULES: KDSRuleConfig = {
  warn_minutes: 15,
  warn_color: '#FFA500',
  urgent_minutes: 25,
  urgent_color: '#FF0000',
  channel_colors: {
    dine_in: '#4CAF50',
    takeout: '#2196F3',
    pickup: '#9C27B0',
  },
  show_guest_seat: true,
  show_remark: true,
  show_cooking_method: true,
  show_channel_badge: true,
  gift_badge_color: '#FFD700',
  return_badge_color: '#607D8B',
};

// ─── API 调用 ───

export async function fetchKDSRules(storeId: string): Promise<KDSRuleConfig> {
  return txFetch<KDSRuleConfig>(`/api/v1/kds-rules/${encodeURIComponent(storeId)}`);
}

export async function saveKDSRules(
  storeId: string,
  config: KDSRuleConfig,
): Promise<KDSRuleConfig> {
  return txFetch<KDSRuleConfig>(`/api/v1/kds-rules/${encodeURIComponent(storeId)}`, {
    method: 'PUT',
    body: JSON.stringify(config),
  });
}

// ─── 工具函数 ───

export type TimeLevel = 'normal' | 'warning' | 'urgent';

/**
 * 根据已等待分钟数和规则，计算超时等级
 */
export function getTimeLevelFromRules(
  elapsedMinutes: number,
  rules: KDSRuleConfig,
): TimeLevel {
  if (elapsedMinutes >= rules.urgent_minutes) return 'urgent';
  if (elapsedMinutes >= rules.warn_minutes) return 'warning';
  return 'normal';
}

/**
 * 根据超时等级返回背景色（用于卡片高亮）
 */
export function getCardBgColorFromLevel(
  level: TimeLevel,
  rules: KDSRuleConfig,
): string | undefined {
  if (level === 'urgent') return rules.urgent_color + '22';  // ~13% 透明度
  if (level === 'warning') return rules.warn_color + '22';
  return undefined;
}

/**
 * 根据超时等级返回计时器文字颜色
 */
export function getTimerColorFromLevel(
  level: TimeLevel,
  rules: KDSRuleConfig,
): string {
  if (level === 'urgent') return rules.urgent_color;
  if (level === 'warning') return rules.warn_color;
  return '#0F6E56';
}

/**
 * 根据渠道类型返回标识色
 */
export function getChannelColor(
  channel: string,
  rules: KDSRuleConfig,
): string {
  return rules.channel_colors[channel] ?? '#888888';
}
