/**
 * KDS 管理 API — 档口路由规则 / 出餐码 / KDS出单模式配置
 *
 * 路径来源（以实际后端代码为准）：
 *   档口规则:  /api/v1/dispatch-rules/{store_id}  (GET/POST)
 *             /api/v1/dispatch-rules/{rule_id}    (PUT/DELETE)
 *             /api/v1/dispatch-rules/{rule_id}/test (POST)
 *             /api/v1/dispatch-rules/{store_id}/simulate (GET)
 *
 *   出餐码:    /api/v1/dispatch-codes/generate    (POST)
 *             /api/v1/dispatch-codes/scan         (POST)
 *             /api/v1/dispatch-codes/order/{order_id} (GET)
 *             /api/v1/dispatch-codes/pending/{store_id} (GET)
 *
 *   KDS配置:   /api/v1/kds-config/push-mode/{store_id} (GET/PUT)
 *             /api/v1/kds-config/calling/{store_id}    (GET)
 *             /api/v1/kds-config/calling/{store_id}/stats (GET)
 */

import { txFetchData } from './client';

// ─── 公共工具 ──────────────────────────────────────────────────────────────

function getTenantId(): string {
  return localStorage.getItem('tenantId') || '';
}

function apiHeaders(): HeadersInit {
  return {
    'Content-Type': 'application/json',
    'X-Tenant-ID': getTenantId(),
  };
}

async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    headers: apiHeaders(),
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${path} failed (${res.status}): ${text}`);
  }
  const json = await res.json() as { ok: boolean; data: T; error?: { message?: string } };
  if (!json.ok) {
    throw new Error(json.error?.message ?? '请求失败');
  }
  return json.data;
}

// ─── 档口路由规则 ──────────────────────────────────────────────────────────

/**
 * 档口路由规则（对应 dispatch_rule_routes.py DispatchRule 模型）
 * 匹配条件按字段拆分：菜品ID / 菜品分类 / 品牌 / 渠道 / 时段 / 工作日类型
 */
export interface DispatchRule {
  id: string;
  store_id: string;
  tenant_id: string;
  name: string;
  priority: number;

  // 匹配条件（可选，任意组合）
  match_dish_id: string | null;
  match_dish_category: string | null;
  match_brand_id: string | null;
  match_channel: 'dine_in' | 'takeaway' | 'delivery' | 'reservation' | null;
  match_time_start: string | null;  // HH:MM
  match_time_end: string | null;    // HH:MM
  match_day_type: 'weekday' | 'weekend' | 'holiday' | null;

  // 目标
  target_dept_id: string;
  target_printer_id: string | null;

  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface DispatchRuleCreatePayload {
  name: string;
  priority?: number;
  match_dish_id?: string | null;
  match_dish_category?: string | null;
  match_brand_id?: string | null;
  match_channel?: string | null;
  match_time_start?: string | null;
  match_time_end?: string | null;
  match_day_type?: string | null;
  target_dept_id: string;
  target_printer_id?: string | null;
  is_active?: boolean;
}

export interface DispatchRuleUpdatePayload extends Partial<DispatchRuleCreatePayload> {}

export interface RuleTestPayload {
  dish_id?: string;
  dish_category?: string;
  brand_id?: string;
  channel?: string;
  order_time?: string;
}

export interface RuleTestResult {
  matched: boolean;
  target_dept_id?: string;
  reason?: string;
}

export interface SimulateResult {
  matched: boolean;
  dept: {
    dept_id: string;
    dept_name: string;
    dept_code: string;
    printer_address: string;
  } | null;
  printer_id_override: string | null;
}

/** 列出门店所有档口路由规则（按 priority DESC） */
export async function listDispatchRules(storeId: string): Promise<DispatchRule[]> {
  const data = await apiFetch<DispatchRule[]>(`/api/v1/dispatch-rules/${encodeURIComponent(storeId)}`);
  return data;
}

/** 创建档口路由规则 */
export async function createDispatchRule(
  storeId: string,
  payload: DispatchRuleCreatePayload,
): Promise<DispatchRule> {
  return apiFetch<DispatchRule>(`/api/v1/dispatch-rules/${encodeURIComponent(storeId)}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 更新档口路由规则 */
export async function updateDispatchRule(
  ruleId: string,
  payload: DispatchRuleUpdatePayload,
): Promise<DispatchRule> {
  return apiFetch<DispatchRule>(`/api/v1/dispatch-rules/${encodeURIComponent(ruleId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

/** 删除（软删除）档口路由规则 */
export async function deleteDispatchRule(ruleId: string): Promise<{ deleted: boolean; rule_id: string }> {
  return apiFetch<{ deleted: boolean; rule_id: string }>(
    `/api/v1/dispatch-rules/${encodeURIComponent(ruleId)}`,
    { method: 'DELETE' },
  );
}

/** 测试单条规则是否匹配 */
export async function testDispatchRule(
  ruleId: string,
  context: RuleTestPayload,
): Promise<RuleTestResult> {
  return apiFetch<RuleTestResult>(
    `/api/v1/dispatch-rules/${encodeURIComponent(ruleId)}/test`,
    { method: 'POST', body: JSON.stringify(context) },
  );
}

/** 模拟完整路由：给定菜品信息，返回会路由到哪个档口 */
export async function simulateDispatchRouting(
  storeId: string,
  params: {
    dish_id: string;
    dish_category?: string;
    brand_id?: string;
    channel?: string;
    order_time?: string;
  },
): Promise<SimulateResult> {
  const qs = new URLSearchParams({ dish_id: params.dish_id });
  if (params.dish_category) qs.set('dish_category', params.dish_category);
  if (params.brand_id) qs.set('brand_id', params.brand_id);
  if (params.channel) qs.set('channel', params.channel);
  if (params.order_time) qs.set('order_time', params.order_time);
  return apiFetch<SimulateResult>(
    `/api/v1/dispatch-rules/${encodeURIComponent(storeId)}/simulate?${qs.toString()}`,
  );
}

// ─── 出餐码（dispatch_code_routes.py） ────────────────────────────────────

/**
 * 出餐码记录（对应 DispatchCode model）
 * 注意：后端 dispatch_code 是外卖出餐流程的扫码确认，不是"档口编码方案"
 */
export interface DispatchCode {
  id: string;
  order_id: string;
  code: string;
  platform: string;
  confirmed: boolean;
  confirmed_at: string | null;
  operator_id: string | null;
  created_at: string;
}

export interface DispatchCodePending {
  id: string;
  order_id: string;
  code: string;
  platform: string;
  confirmed: boolean;
  created_at: string;
}

/** 为外卖订单生成出餐码（幂等） */
export async function generateDispatchCode(
  orderId: string,
  platform = 'unknown',
): Promise<{ code: string; qr_data: string; order_id: string; platform: string; confirmed: boolean; created_at: string }> {
  return apiFetch('/api/v1/dispatch-codes/generate', {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId, platform }),
  });
}

/** 扫码确认出餐 */
export async function scanDispatchCode(
  code: string,
  operatorId: string,
): Promise<{ success: boolean; order_id: string; platform: string; already_confirmed: boolean }> {
  return apiFetch('/api/v1/dispatch-codes/scan', {
    method: 'POST',
    body: JSON.stringify({ code, operator_id: operatorId }),
  });
}

/** 查询订单出餐码状态 */
export async function getDispatchCodeByOrder(orderId: string): Promise<DispatchCode | null> {
  return apiFetch<DispatchCode | null>(
    `/api/v1/dispatch-codes/order/${encodeURIComponent(orderId)}`,
  );
}

/** 待确认出餐码列表（待打包订单） */
export async function listPendingDispatchCodes(
  storeId: string,
): Promise<{ items: DispatchCodePending[]; total: number; store_id: string }> {
  return apiFetch(
    `/api/v1/dispatch-codes/pending/${encodeURIComponent(storeId)}`,
  );
}

// ─── KDS 出单模式配置（kds_config_routes.py） ─────────────────────────────

export type KDSPushMode = 'IMMEDIATE' | 'POST_PAYMENT';

export interface KDSPushModeConfig {
  store_id: string;
  push_mode: KDSPushMode;
  description: string;
}

/**
 * KDS 呼号配置（前端自定义结构，存 localStorage，
 * 部分字段（push_mode）写入后端，其余为前端本地配置）
 */
export interface KDSCallConfig {
  store_id: string;
  push_mode: KDSPushMode;

  // 显示规则（前端本地配置）
  timeout_warn_seconds: number;       // 超时预警时长（秒）
  timeout_color: string;              // 超时后颜色
  warn_color: string;                 // 预警颜色
  urgent_blink: boolean;              // 催单闪烁开关
  urgent_color: string;               // 催单闪烁颜色

  // 渠道标识色
  channel_color_dine_in: string;
  channel_color_takeaway: string;
  channel_color_delivery: string;
  channel_color_self_order: string;

  // 特殊菜品标识开关
  show_gift_badge: boolean;
  show_void_badge: boolean;
  show_addon_badge: boolean;

  // 呼号配置
  call_volume: number;                // 0-100
  announcement_enabled: boolean;
  announcement_interval_seconds: number;
}

export const DEFAULT_KDS_CALL_CONFIG: Omit<KDSCallConfig, 'store_id'> = {
  push_mode: 'IMMEDIATE',
  timeout_warn_seconds: 300,
  timeout_color: '#A32D2D',
  warn_color: '#BA7517',
  urgent_blink: true,
  urgent_color: '#FF6B35',
  channel_color_dine_in: '#0F6E56',
  channel_color_takeaway: '#185FA5',
  channel_color_delivery: '#BA7517',
  channel_color_self_order: '#9B59B6',
  show_gift_badge: true,
  show_void_badge: true,
  show_addon_badge: true,
  call_volume: 80,
  announcement_enabled: true,
  announcement_interval_seconds: 30,
};

/** 获取门店 KDS 出单模式（后端 API） */
export async function getKDSPushMode(storeId: string): Promise<KDSPushModeConfig> {
  return apiFetch<KDSPushModeConfig>(
    `/api/v1/kds-config/push-mode/${encodeURIComponent(storeId)}`,
  );
}

/** 设置门店 KDS 出单模式 */
export async function setKDSPushMode(
  storeId: string,
  mode: KDSPushMode,
): Promise<{ store_id: string; push_mode: KDSPushMode }> {
  return apiFetch(`/api/v1/kds-config/push-mode/${encodeURIComponent(storeId)}`, {
    method: 'PUT',
    body: JSON.stringify({ mode }),
  });
}

// ─── 等叫队列（kds_config_routes.py） ─────────────────────────────────────

export interface KDSCallingTask {
  task_id: string;
  status: string;
  dept_id: string | null;
  order_item_id: string;
  called_at: string | null;
  call_count: number;
  created_at: string | null;
}

export interface KDSCallingStats {
  calling_count: number;
  avg_waiting_minutes: number;
}

/** 获取等叫队列 */
export async function getCallingTasks(
  storeId: string,
): Promise<{ items: KDSCallingTask[]; total: number }> {
  return apiFetch(`/api/v1/kds-config/calling/${encodeURIComponent(storeId)}`);
}

/** 等叫统计 */
export async function getCallingStats(storeId: string): Promise<KDSCallingStats> {
  return apiFetch(`/api/v1/kds-config/calling/${encodeURIComponent(storeId)}/stats`);
}

/** 标记等叫（cooking → calling） */
export async function markTaskCalling(
  taskId: string,
): Promise<{ task_id: string; status: string; called_at: string | null; call_count: number }> {
  return apiFetch(`/api/v1/kds-config/task/${encodeURIComponent(taskId)}/call`, {
    method: 'POST',
  });
}

/** 确认上桌（calling → done） */
export async function confirmTaskServed(
  taskId: string,
): Promise<{ task_id: string; status: string; served_at: string | null }> {
  return apiFetch(`/api/v1/kds-config/task/${encodeURIComponent(taskId)}/serve`, {
    method: 'POST',
  });
}

// ─── 本地持久化（KDS显示配置，存 localStorage） ────────────────────────────

const KDS_CONFIG_STORAGE_KEY = 'tx_kds_call_config';

export function loadKDSCallConfig(storeId: string): KDSCallConfig {
  try {
    const raw = localStorage.getItem(`${KDS_CONFIG_STORAGE_KEY}_${storeId}`);
    if (raw) {
      return { ...DEFAULT_KDS_CALL_CONFIG, ...JSON.parse(raw), store_id: storeId } as KDSCallConfig;
    }
  } catch {
    // ignore
  }
  return { ...DEFAULT_KDS_CALL_CONFIG, store_id: storeId };
}

export function saveKDSCallConfig(config: KDSCallConfig): void {
  localStorage.setItem(
    `${KDS_CONFIG_STORAGE_KEY}_${config.store_id}`,
    JSON.stringify(config),
  );
}

// ─── 门店列表（辅助） ──────────────────────────────────────────────────────

export interface StoreOption {
  value: string;
  label: string;
}

export async function fetchStoreOptions(): Promise<StoreOption[]> {
  try {
    const data = await txFetchData<{ items: Array<{ id: string; name: string }> }>(
      '/api/v1/org/stores?status=active',
    );
    return (data.items ?? []).map((s) => ({ value: s.id, label: s.name }));
  } catch {
    return [];
  }
}

// ─── 档口（ProductionDept）辅助 ────────────────────────────────────────────

export interface ProductionDept {
  id: string;
  dept_name: string;
  dept_code: string;
  printer_address?: string;
}

export async function fetchProductionDepts(storeId: string): Promise<ProductionDept[]> {
  try {
    const data = await apiFetch<ProductionDept[]>(
      `/api/v1/production-depts/${encodeURIComponent(storeId)}`,
    );
    return data;
  } catch {
    return [];
  }
}
