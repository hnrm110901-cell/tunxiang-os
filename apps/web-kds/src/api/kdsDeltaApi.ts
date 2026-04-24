/**
 * Sprint C3 — KDS delta + device heartbeat 客户端
 * 契约层（无 IndexedDB 缓存 / 无 connectionHealth UI / 无 Playwright）
 *   — C1/C2/C4 留后续 sub-task。
 *
 * 与后端 /api/v1/kds/orders/delta + /api/v1/kds/device/heartbeat 对齐。
 * device_kind 六枚举与 v271 edge_device_registry CHECK 约束一致。
 */
import { txFetch } from './index';

// ─── 协议类型 ────────────────────────────────────────────────────────────────

export type DeviceKind =
  | 'pos'
  | 'kds'
  | 'crew_phone'
  | 'tv_menu'
  | 'reception'
  | 'mac_mini';

export const ALLOWED_DEVICE_KINDS: readonly DeviceKind[] = [
  'pos',
  'kds',
  'crew_phone',
  'tv_menu',
  'reception',
  'mac_mini',
] as const;

export type HealthStatus = 'healthy' | 'degraded' | 'offline' | 'unknown';

/**
 * KDS 视角订单（device_kind=kds 时后端剔除 customer_phone / total_amount_fen）
 */
export interface KDSDeltaOrder {
  tenant_id: string;
  id: string;
  order_no: string;
  store_id: string;
  status: 'pending' | 'confirmed' | 'preparing' | 'ready';
  table_number: string | null;
  updated_at: string; // ISO8601
  order_metadata?: Record<string, unknown>;
  items_count?: number;
}

export interface KDSDeltaResponse {
  orders: KDSDeltaOrder[];
  /** 下一轮拉取 cursor；无新单时等于本次 cursor 或 null */
  next_cursor: string | null;
  server_time: string; // ISO8601
  poll_interval_ms: number;
  device_id?: string | null;
  device_kind?: DeviceKind | null;
}

export interface HeartbeatResponse {
  device_id: string;
  device_kind: DeviceKind;
  server_time: string;
  poll_interval_ms: number;
}

export interface HeartbeatPayload {
  device_id: string;
  device_kind: DeviceKind;
  store_id: string;
  device_label?: string;
  os_version?: string;
  app_version?: string;
  buffer_backlog?: number;
  health_status?: HealthStatus;
}

// ─── API 调用 ────────────────────────────────────────────────────────────────

/**
 * Sprint C3 — 轮询 KDS 订单增量。
 *
 * @param params.store_id    门店 UUID
 * @param params.cursor      上次 response.next_cursor；首次传 null
 * @param params.device_id   当前 KDS 设备 ID（审计用）
 * @param params.device_kind 固定 'kds'（本函数即 KDS 端）
 * @param params.limit       单次上限 [1,500]，默认 100
 *
 * 错误处理：
 *   - 5xx：上层决定是否重试（见 retry helper）
 *   - 4xx：抛错，UI 显示为"接口异常"
 */
export async function pollOrdersDelta(params: {
  store_id: string;
  cursor: string | null;
  device_id: string;
  device_kind?: DeviceKind;
  limit?: number;
}): Promise<KDSDeltaResponse> {
  const q = new URLSearchParams();
  q.set('store_id', params.store_id);
  if (params.cursor) q.set('cursor', params.cursor);
  q.set('device_id', params.device_id);
  q.set('device_kind', params.device_kind ?? 'kds');
  q.set('limit', String(params.limit ?? 100));

  return txFetch<KDSDeltaResponse>(`/api/v1/kds/orders/delta?${q.toString()}`);
}

/**
 * 发送设备心跳。建议 KDS 30s 一次 / POS 60s 一次。
 */
export async function sendHeartbeat(
  payload: HeartbeatPayload,
): Promise<HeartbeatResponse> {
  if (!ALLOWED_DEVICE_KINDS.includes(payload.device_kind)) {
    throw new Error(`device_kind 非法: ${payload.device_kind}`);
  }
  return txFetch<HeartbeatResponse>(`/api/v1/kds/device/heartbeat`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// ─── Retry Helper（5xx 指数退避，最多 3 次） ────────────────────────────────

/**
 * 对 pollOrdersDelta 的轻量封装：5xx 错误指数退避 1s / 2s / 4s，最多 3 次。
 * 4xx 直接抛（语义错误不退避）。
 *
 * 本 helper 是 C3 契约层，不包含 IndexedDB 持久化（C1 留后续）。
 */
export async function pollOrdersDeltaWithRetry(
  params: Parameters<typeof pollOrdersDelta>[0],
  opts: { maxAttempts?: number; baseDelayMs?: number } = {},
): Promise<KDSDeltaResponse> {
  const maxAttempts = opts.maxAttempts ?? 3;
  const baseDelayMs = opts.baseDelayMs ?? 1000;

  let lastErr: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      return await pollOrdersDelta(params);
    } catch (err) {
      lastErr = err;
      const msg = (err as Error)?.message ?? '';
      // 4xx 语义错误直接抛
      if (/\b4\d\d\b/.test(msg) || /INVALID|FORBIDDEN|MISMATCH/i.test(msg)) {
        throw err;
      }
      if (attempt === maxAttempts - 1) break;
      const delay = baseDelayMs * 2 ** attempt;
      await new Promise((r) => setTimeout(r, delay));
    }
  }
  throw lastErr;
}
