/**
 * 预警规则配置 API — /api/v1/ops/alert-rules/*
 * 预警规则的增删改查、启用/禁用、规则测试
 */
import { txFetchData } from './client';

// ─── 类型定义 ───

export type RuleDomain = 'revenue' | 'inventory' | 'quality' | 'labor' | 'safety';
export type NotifyChannel = 'wecom' | 'sms' | 'push' | 'email';
export type TriggerOp = 'gt' | 'lt' | 'eq' | 'gte' | 'lte' | 'consecutive_days';

export interface AlertRule {
  id: string;
  name: string;
  domain: RuleDomain;
  metric: string;
  metric_label: string;
  trigger_op: TriggerOp;
  trigger_value: number;
  thresholds: {
    green: number;
    yellow: number;
    red: number;
  };
  scope: 'all' | 'region' | 'store';
  scope_ids: string[];
  scope_names: string[];
  notify_channels: NotifyChannel[];
  notify_roles: string[];
  enabled: boolean;
  created_at: string;
  updated_at: string;
  last_triggered_at?: string;
  trigger_count_7d: number;
}

export interface AlertRuleCreatePayload {
  name: string;
  domain: RuleDomain;
  metric: string;
  metric_label: string;
  trigger_op: TriggerOp;
  trigger_value: number;
  thresholds: { green: number; yellow: number; red: number };
  scope: 'all' | 'region' | 'store';
  scope_ids: string[];
  notify_channels: NotifyChannel[];
  notify_roles: string[];
  enabled: boolean;
}

export interface AlertRuleTestPayload {
  metric_value: number;
}

export interface AlertRuleTestResult {
  triggered: boolean;
  level: 'green' | 'yellow' | 'red';
  message: string;
}

export interface AlertRuleHistoryItem {
  id: string;
  rule_id: string;
  action: string;
  diff: Record<string, { before: unknown; after: unknown }>;
  operator: string;
  created_at: string;
}

// ─── API 方法 ───

const BASE = '/api/v1/ops/alert-rules';

/** 获取规则列表（按域筛选） */
export async function fetchAlertRules(domain?: RuleDomain): Promise<AlertRule[]> {
  const query = domain ? `?domain=${domain}` : '';
  return txFetchData<AlertRule[]>(`${BASE}${query}`);
}

/** 创建规则 */
export async function createAlertRule(payload: AlertRuleCreatePayload): Promise<AlertRule> {
  return txFetchData<AlertRule>(BASE, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 更新规则 */
export async function updateAlertRule(id: string, payload: Partial<AlertRuleCreatePayload>): Promise<AlertRule> {
  return txFetchData<AlertRule>(`${BASE}/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

/** 启用/禁用规则 */
export async function toggleAlertRule(id: string, enabled: boolean): Promise<AlertRule> {
  return txFetchData<AlertRule>(`${BASE}/${id}/toggle`, {
    method: 'PATCH',
    body: JSON.stringify({ enabled }),
  });
}

/** 测试规则 */
export async function testAlertRule(id: string, payload: AlertRuleTestPayload): Promise<AlertRuleTestResult> {
  return txFetchData<AlertRuleTestResult>(`${BASE}/${id}/test`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 获取规则修改历史 */
export async function fetchAlertRuleHistory(id: string): Promise<AlertRuleHistoryItem[]> {
  return txFetchData<AlertRuleHistoryItem[]>(`${BASE}/${id}/history`);
}
