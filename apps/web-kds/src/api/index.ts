/**
 * web-kds 统一 API 客户端
 * 后厨显示屏通过 WebSocket 接收实时订单，REST API 查询历史和统计。
 */

// ─── 基础配置 ───

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const WS_BASE = import.meta.env.VITE_WS_BASE_URL || API_BASE.replace(/^http/, 'ws');
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

export * from './kdsOpsApi';
export * from './shortageApi';

// ─── WebSocket 连接 ───

export interface KDSMessage {
  type: string;
  ticket_id: string;
  order_id: string;
  order_no: string;
  items: Array<{
    dish_name: string;
    quantity: number;
    special_notes: string;
  }>;
  table_no: string;
  priority: string;
  created_at: string;
}

/**
 * 连接 KDS WebSocket，实时接收后厨订单推送。
 * 内置自动重连机制（5秒间隔）。
 */
export function connectKDS(
  stationId: string,
  onMessage: (msg: KDSMessage) => void,
): WebSocket {
  const url = `${WS_BASE}/api/v1/kds/ws?station_id=${encodeURIComponent(stationId)}&tenant_id=${encodeURIComponent(TENANT_ID)}`;
  const ws = new WebSocket(url);

  ws.onopen = () => {
    console.log(`[KDS] WebSocket connected: station=${stationId}`);
  };

  ws.onmessage = (event: MessageEvent) => {
    try {
      const msg: KDSMessage = JSON.parse(event.data);
      onMessage(msg);
    } catch (err) {
      console.error('[KDS] Failed to parse WebSocket message:', err);
    }
  };

  ws.onerror = (event: Event) => {
    console.error('[KDS] WebSocket error:', event);
  };

  ws.onclose = (event: CloseEvent) => {
    console.warn(`[KDS] WebSocket closed: code=${event.code}, reason=${event.reason}`);
    // 自动重连（5秒延迟）
    setTimeout(() => {
      console.log('[KDS] Attempting reconnect...');
      connectKDS(stationId, onMessage);
    }, 5000);
  };

  return ws;
}

// ─── REST API ───

export interface KDSTicket {
  ticket_id: string;
  order_id: string;
  order_no: string;
  table_no: string;
  items: Array<{ dish_name: string; quantity: number; special_notes: string }>;
  status: string;
  priority: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export async function fetchKDSHistory(
  stationId: string,
  page = 1,
  size = 50,
): Promise<{ items: KDSTicket[]; total: number }> {
  return txFetch(
    `/api/v1/kds/history?station_id=${encodeURIComponent(stationId)}&page=${page}&size=${size}`,
  );
}

export interface KDSStats {
  station_id: string;
  today_total: number;
  today_completed: number;
  avg_cook_time_sec: number;
  current_pending: number;
  current_cooking: number;
}

export async function fetchKDSStats(stationId: string): Promise<KDSStats> {
  return txFetch(`/api/v1/kds/stats?station_id=${encodeURIComponent(stationId)}`);
}

export async function updateTicketStatus(
  ticketId: string,
  status: string,
): Promise<{ ticket_id: string; status: string; updated_at: string }> {
  return txFetch(`/api/v1/kds/tickets/${encodeURIComponent(ticketId)}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  });
}

// ─── 超时告警 ───

export interface KDSAlert {
  alert_id: string;
  ticket_id: string;
  order_id: string;
  order_no: string;
  table_no: string;
  items: string[];
  elapsed_min: number;
  station_name: string;
  chef: string;
  created_at: string;
  resolved: boolean;
  resolved_at: string | null;
}

export async function fetchKDSAlerts(
  stationId: string,
  resolved?: boolean,
): Promise<{ items: KDSAlert[]; total: number }> {
  const query = resolved !== undefined ? `&resolved=${resolved}` : '';
  return txFetch(
    `/api/v1/kds/alerts?station_id=${encodeURIComponent(stationId)}${query}`,
  );
}

export async function resolveKDSAlert(
  alertId: string,
): Promise<{ alert_id: string; resolved_at: string }> {
  return txFetch(`/api/v1/kds/alerts/${encodeURIComponent(alertId)}/resolve`, {
    method: 'POST',
  });
}

// ─── 缺料上报 ───

export interface ShortagePayload {
  station_id: string;
  ingredient_ids: string[];
  reporter: string;
}

export interface ShortageRecord {
  id: string;
  ingredient_id: string;
  ingredient_name: string;
  reported_at: string;
  reporter: string;
  affected_dishes: string[];
  status: 'reported' | 'confirmed' | 'resolved';
}

export async function submitShortage(
  payload: ShortagePayload,
): Promise<{ records: ShortageRecord[] }> {
  return txFetch('/api/v1/kds/shortage', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function fetchShortageRecords(
  stationId: string,
): Promise<{ items: ShortageRecord[] }> {
  return txFetch(`/api/v1/kds/shortage?station_id=${encodeURIComponent(stationId)}`);
}

// ─── 重做 ───

export type RemakeReason = 'complaint' | 'quality' | 'wrong_dish' | 'wrong_spec' | 'other';

export interface RemakePayload {
  ticket_id: string;
  reason: RemakeReason;
  note?: string;
}

export async function submitRemake(
  payload: RemakePayload,
): Promise<{ ticket_id: string; remake_id: string; status: string }> {
  return txFetch(`/api/v1/kds/tickets/${encodeURIComponent(payload.ticket_id)}/remake`, {
    method: 'POST',
    body: JSON.stringify({ reason: payload.reason, note: payload.note }),
  });
}

// ─── 档口配置 ───

export interface KDSStation {
  station_id: string;
  name: string;
  dish_count: number;
  printer: string;
  status: 'online' | 'offline';
}

export async function fetchStations(): Promise<{ items: KDSStation[] }> {
  return txFetch('/api/v1/kds/stations');
}

export async function createStation(
  name: string,
  printer: string,
): Promise<KDSStation> {
  return txFetch('/api/v1/kds/stations', {
    method: 'POST',
    body: JSON.stringify({ name, printer }),
  });
}

export async function updateStation(
  stationId: string,
  name: string,
  printer: string,
): Promise<KDSStation> {
  return txFetch(`/api/v1/kds/stations/${encodeURIComponent(stationId)}`, {
    method: 'PUT',
    body: JSON.stringify({ name, printer }),
  });
}

export async function deleteStation(
  stationId: string,
): Promise<{ station_id: string; deleted: boolean }> {
  return txFetch(`/api/v1/kds/stations/${encodeURIComponent(stationId)}`, {
    method: 'DELETE',
  });
}

// ─── 档口选择/负载 ───

export interface StationLoad {
  station_id: string;
  name: string;
  pending_count: number;
  cooking_count: number;
  load_level: 'low' | 'medium' | 'high';
}

export async function fetchStationLoads(): Promise<{ items: StationLoad[] }> {
  return txFetch('/api/v1/kds/stations/load');
}

// ─── 原料库存查询（缺料上报时） ───

export interface IngredientInfo {
  ingredient_id: string;
  name: string;
  category: string;
  unit: string;
  current_stock: number;
  safety_stock: number;
}

export async function fetchIngredients(
  stationId: string,
): Promise<{ items: IngredientInfo[] }> {
  return txFetch(`/api/v1/kds/ingredients?station_id=${encodeURIComponent(stationId)}`);
}
