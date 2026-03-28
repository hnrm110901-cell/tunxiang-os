/**
 * web-admin 统一 API 客户端
 * 总部管理后台所有页面通过此文件调用后端。
 */

// ─── 基础配置 ───

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

export async function txFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
      ...(options?.headers as Record<string, string> || {}),
    },
  });
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data;
}

// ─── 各域 API 统一导出 ───

export * from './dashboardApi';
export * from './storeAnalysisApi';
export * from './dishAnalysisApi';
export * from './financeAnalyticsApi';
export * from './memberAnalyticsApi';
export * from './reviewApi';
export * from './regionalApi';
export * from './dispatchApi';

// ─── 门店健康 ───

export interface StoreHealthData {
  store_id: string;
  store_name: string;
  status: string;
  online_devices: number;
  today_revenue_fen: number;
  today_orders: number;
}

export async function fetchStoreHealth(storeId?: string): Promise<StoreHealthData[]> {
  const query = storeId ? `?store_id=${encodeURIComponent(storeId)}` : '';
  return txFetch(`/api/v1/ops/store-health${query}`);
}

// ─── KPI 预警 ───

export interface KPIAlert {
  alert_id: string;
  metric: string;
  current_value: number;
  threshold: number;
  severity: string;
  message: string;
  created_at: string;
}

export async function fetchKPIAlerts(storeId: string): Promise<{ items: KPIAlert[]; total: number }> {
  return txFetch(`/api/v1/analytics/kpi-alerts?store_id=${encodeURIComponent(storeId)}`);
}

// ─── Top3 决策建议 ───

export interface DecisionSuggestion {
  decision_id: string;
  agent_id: string;
  title: string;
  description: string;
  priority: string;
  confidence: number;
}

export async function fetchTop3Decisions(storeId: string): Promise<DecisionSuggestion[]> {
  return txFetch(`/api/v1/agent/decisions/top3?store_id=${encodeURIComponent(storeId)}`);
}

// ─── Agent 管理 ───

export interface AgentInfo {
  agent_id: string;
  agent_name: string;
  priority: string;
  status: string;
  last_run_at: string;
}

export async function fetchAgentList(): Promise<{ items: AgentInfo[]; total: number }> {
  return txFetch('/api/v1/agent/agents');
}

export async function dispatchAgent(
  agentId: string,
  action: string,
  params: Record<string, unknown> = {},
): Promise<{ task_id: string; status: string }> {
  return txFetch(`/api/v1/agent/dispatch?agent_id=${encodeURIComponent(agentId)}&action=${encodeURIComponent(action)}`, {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

// ─── 菜单配置（按角色） ───

export interface MenuItem {
  key: string;
  label: string;
  icon: string;
  path: string;
  children?: MenuItem[];
}

export async function fetchMenuConfig(role: string): Promise<MenuItem[]> {
  return txFetch(`/api/v1/system/menu-config?role=${encodeURIComponent(role)}`);
}

// ─── 交易域：订单列表 ───

export interface TradeOrder {
  order_id: string;
  order_no: string;
  table_no: string;
  status: string;
  total_fen: number;
  created_at: string;
}

export async function fetchTradeOrders(
  storeId: string,
  page = 1,
  size = 20,
): Promise<{ items: TradeOrder[]; total: number }> {
  return txFetch(`/api/v1/trade/orders?store_id=${encodeURIComponent(storeId)}&page=${page}&size=${size}`);
}

// ─── 商品域：菜品管理 ───

export interface CatalogDish {
  dish_id: string;
  dish_name: string;
  category: string;
  price_fen: number;
  is_available: boolean;
  kitchen_station: string;
}

export async function fetchCatalogDishes(
  storeId: string,
  page = 1,
  size = 20,
): Promise<{ items: CatalogDish[]; total: number }> {
  return txFetch(`/api/v1/menu/dishes?store_id=${encodeURIComponent(storeId)}&page=${page}&size=${size}`);
}

// ─── 供应链域：库存 ───

export interface InventoryItem {
  ingredient_id: string;
  ingredient_name: string;
  current_qty: number;
  unit: string;
  min_qty: number;
  expiry_date: string;
  status: string;
}

export async function fetchInventory(
  storeId: string,
  page = 1,
  size = 20,
): Promise<{ items: InventoryItem[]; total: number }> {
  return txFetch(`/api/v1/supply/inventory?store_id=${encodeURIComponent(storeId)}&page=${page}&size=${size}`);
}

// ─── 财务域：日利润 ───

export interface DailyProfitData {
  date: string;
  revenue_fen: number;
  cost_fen: number;
  profit_fen: number;
  margin_rate: number;
}

export async function fetchFinanceDailyProfit(
  storeId: string,
  date?: string,
): Promise<DailyProfitData> {
  const query = date ? `&date=${encodeURIComponent(date)}` : '';
  return txFetch(`/api/v1/finance/daily-profit?store_id=${encodeURIComponent(storeId)}${query}`);
}

// ─── 组织域：员工 ───

export interface Employee {
  employee_id: string;
  name: string;
  role: string;
  phone: string;
  store_id: string;
  status: string;
}

export async function fetchEmployees(
  storeId: string,
  page = 1,
  size = 20,
): Promise<{ items: Employee[]; total: number }> {
  return txFetch(`/api/v1/org/employees?store_id=${encodeURIComponent(storeId)}&page=${page}&size=${size}`);
}

// ─── 会员域：客户 ───

export interface Customer {
  customer_id: string;
  name: string;
  phone: string;
  level: string;
  total_spend_fen: number;
  visit_count: number;
  last_visit_at: string;
}

export async function fetchCustomers(
  storeId: string,
  page = 1,
  size = 20,
): Promise<{ items: Customer[]; total: number }> {
  return txFetch(`/api/v1/member/customers?store_id=${encodeURIComponent(storeId)}&page=${page}&size=${size}`);
}

// ─── 运营域：每日运营流水 ───

export interface DailyOpsFlow {
  date: string;
  store_id: string;
  open_time: string;
  close_time: string;
  events: Array<{ time: string; type: string; detail: string }>;
}

export async function fetchDailyOpsFlow(storeId: string, date?: string): Promise<DailyOpsFlow> {
  const query = date ? `&date=${encodeURIComponent(date)}` : '';
  return txFetch(`/api/v1/ops/daily-flow?store_id=${encodeURIComponent(storeId)}${query}`);
}

// ─── 分析域：效率指标 ───

export interface EfficiencyData {
  store_id: string;
  avg_serve_time_sec: number;
  table_turnover_rate: number;
  labor_efficiency: number;
  peak_hour_orders: number;
}

export async function fetchEfficiency(storeId: string): Promise<EfficiencyData> {
  return txFetch(`/api/v1/analytics/efficiency?store_id=${encodeURIComponent(storeId)}`);
}
