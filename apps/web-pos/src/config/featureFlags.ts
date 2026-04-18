/**
 * web-pos 前端 Feature Flags
 *
 * 统一 key 命名：<domain>.<module>.<feature>.<action>
 * 注册位置：flags/trade/trade_flags.yaml（Sprint A1 P1-4 落地）
 *
 * 三层优先级（从高到低）：
 *   1. setFlagOverride() 手动覆盖（测试 / 紧急开关）
 *   2. 远程 /api/v1/flags 下发（initFeatureFlags 拉取）
 *   3. 本地 DEFAULTS（与 yaml defaultValue 对齐的首屏保底值）
 *
 * 设计要点：
 *   - initFeatureFlags() 5s 超时不阻塞首屏；失败静默回退 DEFAULTS 并 log 警告
 *   - subscribe() 允许组件感知远程下发后的 flag 变化（Zustand 风格）
 *   - Unknown flag name 返回 false + log debug（避免生产开启未知功能，与后端 flag_client.py 保持一致）
 */

export type FlagKey =
  | 'trade.pos.settle.hardening.enable'
  | 'trade.pos.toast.enable'
  | 'trade.pos.errorBoundary.enable';

/** 首屏保底值（与 flags/trade/trade_flags.yaml defaultValue 对齐）。 */
const DEFAULTS: Record<FlagKey, boolean> = {
  'trade.pos.settle.hardening.enable': true,
  'trade.pos.toast.enable': true,
  'trade.pos.errorBoundary.enable': true,
};

/** 旧 key 的兼容别名（Sprint A1 早期硬编码）。保持向后兼容避免调用点碎片化。 */
const ALIASES: Record<string, FlagKey> = {
  'trade.pos.settle.hardening': 'trade.pos.settle.hardening.enable',
};

const remoteValues: Partial<Record<FlagKey, boolean>> = {};
const overrides: Partial<Record<FlagKey, boolean>> = {};

type Listener = () => void;
const listeners = new Set<Listener>();

function notify(): void {
  listeners.forEach((fn) => {
    try {
      fn();
    } catch (err) {
      // 监听者异常不应影响其他订阅者
      // eslint-disable-next-line no-console
      console.warn('[featureFlags] listener error', err);
    }
  });
}

function normalizeKey(key: string): FlagKey | null {
  if (key in DEFAULTS) return key as FlagKey;
  if (key in ALIASES) return ALIASES[key];
  return null;
}

/**
 * 查询 Flag 是否开启。
 *
 * - 未知 key：返回 false + log debug（与 shared/feature_flags/flag_client.py 一致）
 * - 优先级：overrides > remoteValues > DEFAULTS
 */
export function isEnabled(key: string): boolean {
  const normalized = normalizeKey(key);
  if (!normalized) {
    // eslint-disable-next-line no-console
    console.debug('[featureFlags] unknown flag', key);
    return false;
  }
  if (normalized in overrides) return overrides[normalized] as boolean;
  if (normalized in remoteValues) return remoteValues[normalized] as boolean;
  return DEFAULTS[normalized];
}

/** 手动覆盖（最高优先级），主要用于测试和紧急关停。 */
export function setFlagOverride(key: FlagKey, value: boolean): void {
  overrides[key] = value;
  notify();
}

/** 清空所有手动覆盖（测试 afterEach 用）。 */
export function resetFlagOverrides(): void {
  (Object.keys(overrides) as FlagKey[]).forEach((k) => delete overrides[k]);
  notify();
}

/** 清空远程缓存（测试用）。 */
export function _resetRemoteFlagsForTest(): void {
  (Object.keys(remoteValues) as FlagKey[]).forEach((k) => delete remoteValues[k]);
  notify();
}

/** 订阅 flag 变化，返回取消订阅函数。组件可用于远程下发后触发重渲染。 */
export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export interface FetchFlagsOptions {
  /** 基址。未指定时使用 VITE_API_BASE_URL；仍缺失时留空串（同源请求）。 */
  baseUrl?: string;
  /** 超时毫秒，默认 5000ms。失败不抛出。 */
  timeoutMs?: number;
  /** 可注入 fetch 用于测试。 */
  fetchFn?: typeof fetch;
  /** 域过滤，默认 trade。 */
  domain?: string;
}

interface RemoteFlagPayload {
  ok?: boolean;
  data?: {
    flags?: Record<string, boolean>;
  };
  // 允许后端直接返回 { "<name>": true, ... }
  [extra: string]: unknown;
}

/**
 * 从后端拉取当前租户可见的 flag 列表。
 *
 * 契约（待后端实现）：
 *   GET /api/v1/flags?domain=trade
 *   Header: X-Tenant-ID
 *   Response: { ok: true, data: { flags: { "<name>": boolean } } }
 *
 * 失败（网络异常 / 404 / 超时）静默回退到 DEFAULTS 并 log 警告。
 */
export async function fetchFlagsFromRemote(
  options: FetchFlagsOptions = {},
): Promise<Partial<Record<FlagKey, boolean>>> {
  const {
    baseUrl = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_BASE_URL ?? '',
    timeoutMs = 5000,
    fetchFn = typeof fetch !== 'undefined' ? fetch.bind(globalThis) : undefined,
    domain = 'trade',
  } = options;

  if (!fetchFn) {
    // eslint-disable-next-line no-console
    console.warn('[featureFlags] fetch unavailable, fall back to defaults');
    return {};
  }

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const url = `${baseUrl}/api/v1/flags?domain=${encodeURIComponent(domain)}`;
    const resp = await fetchFn(url, {
      method: 'GET',
      signal: ctrl.signal,
      headers: { Accept: 'application/json' },
    });
    if (!resp.ok) {
      // eslint-disable-next-line no-console
      console.warn('[featureFlags] remote fetch non-ok', {
        status: resp.status,
        hint: 'TODO: 后端补 /api/v1/flags 端点，当前降级到本地 DEFAULTS',
      });
      return {};
    }
    const body = (await resp.json()) as RemoteFlagPayload;
    const raw = body?.data?.flags ?? (body as unknown as Record<string, boolean>);
    const applied: Partial<Record<FlagKey, boolean>> = {};
    if (raw && typeof raw === 'object') {
      for (const [k, v] of Object.entries(raw)) {
        const normalized = normalizeKey(k);
        if (!normalized) continue;
        if (typeof v !== 'boolean') continue;
        remoteValues[normalized] = v;
        applied[normalized] = v;
      }
    }
    if (Object.keys(applied).length > 0) notify();
    return applied;
  } catch (err) {
    const isAbort = err instanceof DOMException && err.name === 'AbortError';
    // eslint-disable-next-line no-console
    console.warn('[featureFlags] remote fetch failed, fall back to defaults', {
      reason: isAbort ? 'timeout' : 'network',
      error: String(err),
    });
    return {};
  } finally {
    clearTimeout(timer);
  }
}

/**
 * App 启动时调用：异步拉取远程 flag，不阻塞首屏。
 *
 * 使用方式（main.tsx）：
 *   initFeatureFlags();               // 不 await
 *   ReactDOM.createRoot(...).render(...);
 *
 * 失败静默回退到 DEFAULTS，下次拉取可通过 subscribe() 回调刷新 UI。
 */
export function initFeatureFlags(options: FetchFlagsOptions = {}): Promise<void> {
  return fetchFlagsFromRemote(options).then(() => undefined);
}

/** 仅测试用：获取当前所有 flag 的合成值。 */
export function _snapshotForTest(): Record<FlagKey, boolean> {
  const snapshot = {} as Record<FlagKey, boolean>;
  (Object.keys(DEFAULTS) as FlagKey[]).forEach((k) => {
    snapshot[k] = isEnabled(k);
  });
  return snapshot;
}
