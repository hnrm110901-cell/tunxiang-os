/**
 * tx-trade API 客户端
 * 收银全流程：开单→加菜→结算→支付→打印
 *
 * 超时分级（Sprint A1）：
 *   - TIMEOUT_SETTLE_SOFT(3s)：UI 提示 + 软 abort + 自动重试 1 次（网络抖动自愈）
 *   - TIMEOUT_SETTLE_HARD(8s)：硬失败，降级到 ErrorBoundary（收银员扫桌重试）
 *   - TIMEOUT_SETTLE(8s)：兼容旧调用点，等价 HARD（P99 约 1.8s，留足冗余）
 *   - TIMEOUT_QUERY(3s)：查询类读操作
 *
 * 幂等性（Sprint A1 R2）：
 *   - 每次请求自动生成 X-Idempotency-Key（crypto.randomUUID 优先）
 *   - 软超时重试时复用同一 idempotency_key，防止 saga 双扣费
 *
 * 离线处理（Sprint A1 修复 P0-1）：
 *   - txFetchTrade 离线时返回 {ok:false, error.code:'OFFLINE_QUEUED'}（不 throw）
 *   - txFetchOffline 在离线时自动入本地队列，返回 {ok:true, data:{queued:true, offline_id}}
 */
import { isEnabled } from '../config/featureFlags';

const BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

export const TIMEOUT_SETTLE_SOFT = 3000;
export const TIMEOUT_SETTLE_HARD = 8000;
export const TIMEOUT_SETTLE = TIMEOUT_SETTLE_HARD;
export const TIMEOUT_QUERY = 3000;

/**
 * 专门用于双级超时触达硬上限后抛出的错误。ErrorBoundary 捕获后可据此定位
 * timeout_reason=fetch_timeout / recovery_action=abort。
 */
export class TxTimeoutError extends Error {
  readonly timeoutMs: number;
  readonly attempts: number;
  constructor(message: string, timeoutMs: number, attempts: number) {
    super(message);
    this.name = 'TxTimeoutError';
    this.timeoutMs = timeoutMs;
    this.attempts = attempts;
  }
}

export type TradeErrorCode =
  | 'NET_TIMEOUT'
  | 'NET_FAILURE'
  | 'SERVER_5XX'
  | 'BUSINESS_REJECT'
  | 'OFFLINE_QUEUED'
  | 'UNKNOWN';

export interface TradeApiError {
  code: TradeErrorCode;
  message: string;
  status?: number;
  timeout_ms?: number;
  cause?: unknown;
}

export interface TradeApiResult<T> {
  ok: boolean;
  data?: T;
  error?: TradeApiError;
  request_id: string;
}

function generateRequestId(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  const rand = Math.random().toString(16).slice(2, 10);
  return `${Date.now().toString(16)}-${rand}`;
}

function buildAbortSignal(timeoutMs: number, external?: AbortSignal | null): { signal: AbortSignal; cleanup: () => void } {
  const ctrl = new AbortController();
  const onAbort = () => ctrl.abort();
  if (external) {
    if (external.aborted) ctrl.abort();
    else external.addEventListener('abort', onAbort);
  }
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  return {
    signal: ctrl.signal,
    cleanup: () => {
      clearTimeout(timer);
      external?.removeEventListener('abort', onAbort);
    },
  };
}

export interface TxFetchTradeOptions extends RequestInit {
  /**
   * 硬超时（毫秒）。未指定时默认用 TIMEOUT_QUERY(3s)。
   * 结算/支付应显式传 TIMEOUT_SETTLE_HARD（=8s）。
   */
  timeoutMs?: number;
  /**
   * 软超时（毫秒）。>0 时启用双级超时：
   *   - 达到 softTimeoutMs → 软 abort 并自动重试 1 次（同一 idempotency_key）
   *   - 达到 timeoutMs（硬） → 硬失败，返回 NET_TIMEOUT
   * 默认不启用（= 单级超时）。Sprint A1 结算/支付推荐设为 TIMEOUT_SETTLE_SOFT(3s)。
   */
  softTimeoutMs?: number;
  /** 自定义幂等键。未传时自动生成 UUID v4，保证同一次逻辑操作一致。 */
  idempotencyKey?: string;
}

function _generateIdempotencyKey(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  // 退化方案（旧浏览器）：时间戳 + 16 位随机
  const rand = Math.random().toString(16).slice(2, 18);
  return `idem-${Date.now().toString(16)}-${rand}`;
}

// ─── Sprint A3 离线订单号（UUID v7 + 人读前缀） ────────────────────────────
//
// 契约与后端 services/tx-trade/src/services/offline_order_id.py 一致：
//   order_id = `${device_id}:${ms_epoch}:${counter}`
//   idempotency_key = `settle:${order_id}`
//
// UUID v7 按 RFC 9562 手工构造：48-bit ms_epoch + 4-bit ver + 12-bit randA
// + 2-bit var + 62-bit randB。采用 crypto.getRandomValues（CSPRNG）。

let _offlineCounter = 0;
let _lastOfflineMs = 0;

function _deviceId(): string {
  // 优先读 POS 壳层注入的 device_id；浏览器环境退化到 localStorage UUID
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const bridge = (globalThis as any).TXBridge;
  if (bridge && typeof bridge.getDeviceInfo === 'function') {
    try {
      const info = JSON.parse(bridge.getDeviceInfo() || '{}');
      if (info && typeof info.device_id === 'string' && info.device_id) {
        return info.device_id;
      }
    } catch {
      // TXBridge.getDeviceInfo 返回非 JSON — 退化到 localStorage
    }
  }
  const LS_KEY = 'tx.device_id';
  try {
    const cached = localStorage.getItem(LS_KEY);
    if (cached) return cached;
    const fresh = `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    localStorage.setItem(LS_KEY, fresh);
    return fresh;
  } catch {
    // SSR / 隐身模式无 localStorage
    return `web-ephemeral-${Math.random().toString(36).slice(2, 8)}`;
  }
}

function _uuidV7(msEpoch: number): string {
  const bytes = new Uint8Array(16);
  const c = globalThis.crypto as Crypto | undefined;
  if (c && typeof c.getRandomValues === 'function') {
    c.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  // 48-bit unix_ts_ms, big-endian
  bytes[0] = (msEpoch / 2 ** 40) & 0xff;
  bytes[1] = (msEpoch / 2 ** 32) & 0xff;
  bytes[2] = (msEpoch >>> 24) & 0xff;
  bytes[3] = (msEpoch >>> 16) & 0xff;
  bytes[4] = (msEpoch >>> 8) & 0xff;
  bytes[5] = msEpoch & 0xff;
  // version = 7 (high nibble of byte 6)
  bytes[6] = (bytes[6] & 0x0f) | 0x70;
  // variant = 10xx (high 2 bits of byte 8)
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * 生成离线订单号（Sprint A3）。
 *
 * - order_id = `${device_id}:${ms_epoch}:${counter}`（人读，收银员肉眼识别）
 * - uuid_v7 作为随机 payload（客户端不拼入 order_id，服务端用作 cloud_order_id 候选）
 * - 同毫秒多次调用 counter++，跨毫秒 counter 重置
 * - 仅在 `edge.offline.order_id_bridge` flag on 时使用
 *
 * 契约：与后端 services/tx-trade/src/services/offline_order_id.py 完全对齐。
 */
export function generateOfflineOrderId(deviceId?: string): {
  orderId: string;
  uuidV7: string;
  deviceId: string;
  msEpoch: number;
  counter: number;
} {
  const did = deviceId || _deviceId();
  const msEpoch = Date.now();
  if (msEpoch === _lastOfflineMs) {
    _offlineCounter += 1;
  } else {
    _offlineCounter = 1;
    _lastOfflineMs = msEpoch;
  }
  const counter = _offlineCounter;
  const uuidV7 = _uuidV7(msEpoch);
  const orderId = `${did}:${msEpoch}:${counter}`;
  return { orderId, uuidV7, deviceId: did, msEpoch, counter };
}

/** 测试辅助：重置离线 counter 状态（不是公开契约）。 */
export function _resetOfflineOrderIdCounterForTest(): void {
  _offlineCounter = 0;
  _lastOfflineMs = 0;
}

export async function txFetchTrade<T>(path: string, options: TxFetchTradeOptions = {}): Promise<TradeApiResult<T>> {
  const requestId = generateRequestId();
  const hardening = isEnabled('trade.pos.settle.hardening');

  if (hardening && typeof navigator !== 'undefined' && navigator.onLine === false) {
    return {
      ok: false,
      request_id: requestId,
      error: { code: 'OFFLINE_QUEUED', message: '当前离线，请求已进入本地队列' },
    };
  }

  // 幂等键：调用方传入则复用，否则单次调用自动生成（重试时沿用，防 saga 双扣费）
  const idempotencyKey = options.idempotencyKey ?? _generateIdempotencyKey();

  const baseHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Request-Id': requestId,
    'X-Idempotency-Key': idempotencyKey,
    ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
    ...((options.headers as Record<string, string>) || {}),
  };

  const explicitTimeout = typeof options.timeoutMs === 'number' ? options.timeoutMs : undefined;
  const hardTimeoutMs = hardening ? (explicitTimeout ?? TIMEOUT_QUERY) : 30_000;
  const softTimeoutMs =
    hardening && typeof options.softTimeoutMs === 'number' && options.softTimeoutMs > 0
      ? Math.min(options.softTimeoutMs, hardTimeoutMs)
      : undefined;

  // 单次 fetch 执行（用于软/硬两轮复用）
  const doAttempt = async (attemptTimeoutMs: number): Promise<TradeApiResult<T> | { _retry: true }> => {
    const { signal, cleanup } = buildAbortSignal(attemptTimeoutMs, options.signal);
    try {
      const resp = await fetch(`${BASE}${path}`, { ...options, headers: baseHeaders, signal });
      const status = resp.status;

      let parsed: { ok?: boolean; data?: T; error?: { code?: string; message?: string } } = {};
      try {
        parsed = await resp.json();
      } catch {
        parsed = {};
      }

      if (status >= 500) {
        return {
          ok: false,
          request_id: requestId,
          error: { code: 'SERVER_5XX', status, message: parsed.error?.message || '服务器繁忙' },
        };
      }
      if (status >= 400) {
        return {
          ok: false,
          request_id: requestId,
          error: {
            code: 'BUSINESS_REJECT',
            status,
            message: parsed.error?.message || '请求被拒绝',
          },
        };
      }
      if (parsed.ok === false) {
        return {
          ok: false,
          request_id: requestId,
          error: { code: 'BUSINESS_REJECT', status, message: parsed.error?.message || '业务校验失败' },
        };
      }
      return { ok: true, data: parsed.data as T, request_id: requestId };
    } catch (err) {
      const isAbort = err instanceof DOMException && err.name === 'AbortError';
      if (isAbort) {
        // 本轮超时：由外层决定是重试（软）还是返回（硬）
        return { _retry: true };
      }
      const msg = err instanceof Error ? err.message : 'network error';
      return {
        ok: false,
        request_id: requestId,
        error: { code: 'NET_FAILURE', message: msg, cause: err },
      };
    } finally {
      cleanup();
    }
  };

  // 双级超时：软 abort → 重试 1 次（同一 idempotency_key）→ 硬失败
  if (softTimeoutMs !== undefined) {
    const softResult = await doAttempt(softTimeoutMs);
    if (!('_retry' in softResult)) return softResult;
    // 软 abort：重试 1 次，剩余预算 = hard - soft
    const hardBudget = Math.max(hardTimeoutMs - softTimeoutMs, 0);
    if (hardBudget === 0) {
      return {
        ok: false,
        request_id: requestId,
        error: { code: 'NET_TIMEOUT', message: '网络超时', timeout_ms: hardTimeoutMs },
      };
    }
    const retryResult = await doAttempt(hardBudget);
    if (!('_retry' in retryResult)) return retryResult;
    return {
      ok: false,
      request_id: requestId,
      error: { code: 'NET_TIMEOUT', message: '网络超时', timeout_ms: hardTimeoutMs },
    };
  }

  // 单级超时（兼容旧调用点）
  const result = await doAttempt(hardTimeoutMs);
  if ('_retry' in result) {
    return {
      ok: false,
      request_id: requestId,
      error: { code: 'NET_TIMEOUT', message: '网络超时', timeout_ms: hardTimeoutMs },
    };
  }
  return result;
}

async function txFetch<T>(path: string, options: TxFetchTradeOptions = {}): Promise<T> {
  const res = await txFetchTrade<T>(path, options);
  if (!res.ok || res.data === undefined) {
    throw new Error(res.error?.message || 'API Error');
  }
  return res.data;
}

/**
 * 离线队列入队器的最小接口。
 * 生产由 useOffline.enqueue 提供；测试可注入 stub。
 */
export type OfflineEnqueueFn = (op: {
  type: 'create_order' | 'add_item' | 'settle_order' | 'create_payment';
  payload: Record<string, unknown>;
}) => Promise<string>;

let _enqueueFn: OfflineEnqueueFn | null = null;
/**
 * 注册离线入队器。应在 App 启动时由 useOffline 的宿主组件调用。
 * 未注册时 txFetchOffline 回落为返回 OFFLINE_QUEUED 错误（不静默）。
 */
export function registerOfflineEnqueue(fn: OfflineEnqueueFn | null): void {
  _enqueueFn = fn;
}

/**
 * 幂等键记录（5 分钟 TTL）。同一订单同一动作在 TTL 内只入队一次，
 * 防止收银员连点、断网抖动反复入队导致重复扣款。
 */
interface IdemEntry { expireAt: number; offlineId: string }
const _idemStore: Map<string, IdemEntry> = new Map();
const IDEMPOTENCY_TTL_MS = 5 * 60 * 1000;

function _pruneIdem(now: number): void {
  for (const [k, v] of _idemStore) {
    if (v.expireAt < now) _idemStore.delete(k);
  }
}

/** 测试辅助：清空幂等缓存。非公开契约，仅供测试使用。 */
export function _resetOfflineIdempotencyForTest(): void {
  _idemStore.clear();
}

export interface OfflineQueuedData {
  queued: true;
  offline_id: string;
  reused?: boolean;
}

export interface TxFetchOfflineOptions extends TxFetchTradeOptions {
  /**
   * 离线排队时使用的操作类型。必填，决定 replay 时走哪个 API。
   */
  offlineType: 'create_order' | 'add_item' | 'settle_order' | 'create_payment';
  /**
   * 离线排队时写入队列的 payload。
   */
  offlinePayload: Record<string, unknown>;
  /**
   * 幂等键。同一键在 TTL 内只入队一次（再次调用返回同一 offline_id 且 reused:true）。
   * 推荐组合：`${offlineType}:${orderId}` 或 `settle:${orderId}`。
   */
  idempotencyKey: string;
}

/**
 * 离线友好版 txFetchTrade。
 *
 * - 在线 → 正常调用 txFetchTrade
 * - 离线（navigator.onLine=false 或 NET_FAILURE/TIMEOUT）→ 调用已注册的 enqueue，
 *   返回 `{ok:true, data:{queued:true, offline_id}}`（不 throw，不弹"支付失败"）
 * - 幂等键复用 → 返回 `{reused:true, offline_id}`（不重复入队）
 */
export async function txFetchOffline<T>(
  path: string,
  options: TxFetchOfflineOptions,
): Promise<TradeApiResult<T | OfflineQueuedData>> {
  const { offlineType, offlinePayload, idempotencyKey, ...fetchOptions } = options;
  const hardening = isEnabled('trade.pos.settle.hardening');

  const tryEnqueue = async (): Promise<TradeApiResult<OfflineQueuedData>> => {
    const requestId = generateRequestId();
    const now = Date.now();
    _pruneIdem(now);

    const cached = _idemStore.get(idempotencyKey);
    if (cached) {
      return {
        ok: true,
        request_id: requestId,
        data: { queued: true, offline_id: cached.offlineId, reused: true },
      };
    }

    if (!_enqueueFn) {
      return {
        ok: false,
        request_id: requestId,
        error: { code: 'OFFLINE_QUEUED', message: '离线队列未就绪，请联系技术' },
      };
    }

    const offlineId = await _enqueueFn({ type: offlineType, payload: offlinePayload });
    _idemStore.set(idempotencyKey, { expireAt: now + IDEMPOTENCY_TTL_MS, offlineId });
    return {
      ok: true,
      request_id: requestId,
      data: { queued: true, offline_id: offlineId, reused: false },
    };
  };

  // 1) 先判离线
  if (hardening && typeof navigator !== 'undefined' && navigator.onLine === false) {
    return tryEnqueue() as Promise<TradeApiResult<T | OfflineQueuedData>>;
  }

  // 2) 在线：正常打网络
  const res = await txFetchTrade<T>(path, fetchOptions);
  if (res.ok) {
    return res as TradeApiResult<T | OfflineQueuedData>;
  }

  // 3) 网络层失败（超时 / 连接失败 / 后端 5xx）→ 降级入队
  const code = res.error?.code;
  if (code === 'NET_TIMEOUT' || code === 'NET_FAILURE' || code === 'SERVER_5XX' || code === 'OFFLINE_QUEUED') {
    return tryEnqueue() as Promise<TradeApiResult<T | OfflineQueuedData>>;
  }

  // 4) 业务拒绝 / 未知错误：透传
  return res as TradeApiResult<T | OfflineQueuedData>;
}

// ─── 订单 ───

export interface CreateOrderResult {
  order_id: string;
  order_no: string;
}

export async function createOrder(storeId: string, tableNo: string): Promise<CreateOrderResult> {
  return txFetch('/api/v1/trade/orders', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, table_no: tableNo, order_type: 'dine_in' }),
  });
}

export interface AddItemResult {
  item_id: string;
  subtotal_fen: number;
}

export async function addItem(
  orderId: string,
  dishId: string,
  dishName: string,
  quantity: number,
  unitPriceFen: number,
): Promise<AddItemResult> {
  return txFetch(`/api/v1/trade/orders/${orderId}/items`, {
    method: 'POST',
    body: JSON.stringify({ dish_id: dishId, dish_name: dishName, quantity, unit_price_fen: unitPriceFen }),
  });
}

export async function removeItem(orderId: string, itemId: string): Promise<void> {
  await txFetch(`/api/v1/trade/orders/${orderId}/items/${itemId}`, { method: 'DELETE' });
}

export async function settleOrder(orderId: string): Promise<{ order_no: string; final_amount_fen: number }> {
  return txFetch(`/api/v1/trade/orders/${orderId}/settle`, {
    method: 'POST',
    timeoutMs: TIMEOUT_SETTLE_HARD,
    softTimeoutMs: TIMEOUT_SETTLE_SOFT,
    idempotencyKey: `settle:${orderId}`,
  });
}

/**
 * 结算订单 — 离线友好版。
 * 联网时直接结算；断网时自动入队并返回 `{queued:true, offline_id}`。
 * 幂等键 = `settle:${orderId}`，同一订单 5 分钟内重复调用不重复入队。
 */
export async function settleOrderOffline(
  orderId: string,
): Promise<TradeApiResult<{ order_no: string; final_amount_fen: number } | OfflineQueuedData>> {
  return txFetchOffline<{ order_no: string; final_amount_fen: number }>(
    `/api/v1/trade/orders/${orderId}/settle`,
    {
      method: 'POST',
      timeoutMs: TIMEOUT_SETTLE,
      offlineType: 'settle_order',
      offlinePayload: { orderId },
      idempotencyKey: `settle:${orderId}`,
    },
  );
}

export async function cancelOrder(orderId: string, reason = ''): Promise<void> {
  await txFetch(`/api/v1/trade/orders/${orderId}/cancel?reason=${encodeURIComponent(reason)}`, {
    method: 'POST',
    timeoutMs: TIMEOUT_SETTLE,
  });
}

export async function getOrder(orderId: string): Promise<Record<string, unknown>> {
  return txFetch(`/api/v1/trade/orders/${orderId}`);
}

// ─── 支付 ───

export async function createPayment(
  orderId: string,
  method: string,
  amountFen: number,
  tradeNo?: string,
): Promise<{ payment_id: string; payment_no: string }> {
  return txFetch(`/api/v1/trade/orders/${orderId}/payments`, {
    method: 'POST',
    timeoutMs: TIMEOUT_SETTLE_HARD,
    softTimeoutMs: TIMEOUT_SETTLE_SOFT,
    idempotencyKey: `payment:${orderId}:${method}`,
    body: JSON.stringify({ method, amount_fen: amountFen, trade_no: tradeNo }),
  });
}

/**
 * 创建支付 — 离线友好版。
 * 幂等键 = `payment:${orderId}:${method}`，避免同一桌同一方式重复入队。
 */
export async function createPaymentOffline(
  orderId: string,
  method: string,
  amountFen: number,
  tradeNo?: string,
): Promise<TradeApiResult<{ payment_id: string; payment_no: string } | OfflineQueuedData>> {
  return txFetchOffline<{ payment_id: string; payment_no: string }>(
    `/api/v1/trade/orders/${orderId}/payments`,
    {
      method: 'POST',
      timeoutMs: TIMEOUT_SETTLE,
      body: JSON.stringify({ method, amount_fen: amountFen, trade_no: tradeNo }),
      offlineType: 'create_payment',
      offlinePayload: { orderId, method, amountFen, tradeNo },
      idempotencyKey: `payment:${orderId}:${method}`,
    },
  );
}

export async function processRefund(
  orderId: string,
  paymentId: string,
  amountFen: number,
  reason = '',
): Promise<{ refund_no: string }> {
  return txFetch(`/api/v1/trade/orders/${orderId}/refund`, {
    method: 'POST',
    timeoutMs: TIMEOUT_SETTLE,
    body: JSON.stringify({ payment_id: paymentId, amount_fen: amountFen, reason }),
  });
}

// ─── 打印 ───

export async function printReceipt(orderId: string): Promise<{ content_base64: string }> {
  return txFetch(`/api/v1/trade/orders/${orderId}/print/receipt`, {
    method: 'POST',
    timeoutMs: TIMEOUT_SETTLE,
  });
}

export async function printKitchen(orderId: string, station = ''): Promise<Record<string, unknown>> {
  return txFetch(`/api/v1/trade/orders/${orderId}/print/kitchen?station=${encodeURIComponent(station)}`, {
    method: 'POST',
    timeoutMs: TIMEOUT_SETTLE,
  });
}

// ─── Agent ───

export async function dispatchAgent(agentId: string, action: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  return txFetch(`/api/v1/agent/dispatch?agent_id=${agentId}&action=${action}`, {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

export async function listAgents(): Promise<Array<{ agent_id: string; agent_name: string; priority: string }>> {
  return txFetch('/api/v1/agent/agents');
}
