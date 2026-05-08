/**
 * useOffline — 离线模式管理 Hook
 *
 * 职责：
 * - 检测网络状态（navigator.onLine + 心跳检测）
 * - 管理离线操作队列（IndexedDB 存储）
 * - 恢复连接后自动同步队列
 *
 * 编码规范：TypeScript strict，无 any
 */
import { useState, useEffect, useCallback, useRef } from 'react';

// ─── 类型 ───────────────────────────────────────────────────────────────────

export interface OfflineOperation {
  id: string;
  type: 'create_order' | 'add_item' | 'settle_order' | 'create_payment';
  payload: Record<string, unknown>;
  createdAt: string;
  retryCount: number;
  /**
   * 幂等键（R-补2-1 / Tier1）。replay 时作为 `X-Idempotency-Key` header 发给 server
   * 的 replay cache，防止同单跨会话/跨设备重连双扣。
   * 旧版本 IndexedDB 中已有的 op 没有这个字段（undefined），replay 前由
   * `deriveIdempotencyKey(op)` 从 type+payload 派生稳定 key 兜底。
   */
  idempotencyKey?: string;
}

/**
 * 旧版本 IndexedDB 队列里的 op 没有 idempotencyKey 字段时，按 type+payload 派生稳定 key。
 * 与 tradeApi 在线路径的命名规则保持一致（settle:{orderId} / payment:{orderId}:{method}），
 * 让"离线入队 → 网络恢复 replay" 与"短网络抖动重试" 走同一个 server replay cache 窗口。
 *
 * 暴露为模块级函数便于单测；非公开 API。
 */
export function deriveIdempotencyKey(op: OfflineOperation): string {
  if (op.idempotencyKey) return op.idempotencyKey;
  const orderId = (op.payload.orderId as string | undefined) ?? '';
  const method = (op.payload.method as string | undefined) ?? '';
  switch (op.type) {
    case 'settle_order':
      return `settle:${orderId}`;
    case 'create_payment':
      return `payment:${orderId}:${method}`;
    case 'add_item': {
      const dishId = (op.payload.dishId as string | undefined) ?? '';
      // add_item 缺乏天然唯一锚点，加 op.id 兜底（同一 op 重试稳定，不同 op 不会撞）
      return `add_item:${orderId}:${dishId}:${op.id}`;
    }
    case 'create_order':
      // 老 op 没有 server 侧 orderId，用 op.id（前端临时 ID）做兜底
      return `create_order:${op.id}`;
    default:
      return `legacy:${op.id}`;
  }
}

/**
 * enqueue 入参形态。R-补2-1（Tier1）：调用方必须显式提供 `idempotencyKey`，
 * 老调用点（仅传 type+payload）通过 TS 编译期错误暴露，强制走稳定 key 路径。
 */
export type EnqueueInput = Omit<OfflineOperation, 'id' | 'createdAt' | 'retryCount' | 'idempotencyKey'> & {
  idempotencyKey?: string;
};

interface UseOfflineResult {
  isOnline: boolean;
  offlineQueue: OfflineOperation[];
  queueLength: number;
  enqueue: (op: EnqueueInput) => Promise<string>;
  syncQueue: () => Promise<void>;
  syncing: boolean;
  clearQueue: () => Promise<void>;
}

/**
 * useOffline 可选 DI 参数。所有字段都有默认值（保留 zero-arg 调用 API）。
 *
 * 用途：
 *   - 单测/Storybook 注入 mock fetch / 自定义 replay
 *   - 跨终端复用（如 KDS 离线模式）只需改 apiBaseUrl + customReplay
 *   - 业务知识从 hook 模块中抽离，hook 仅负责"队列持久化 + 网络监听 + 调度"
 */
export interface UseOfflineOptions {
  /** API 基址。默认: import.meta.env.VITE_API_BASE_URL */
  apiBaseUrl?: string;
  /** 多租户 ID（注入到 X-Tenant-ID）。默认: import.meta.env.VITE_TENANT_ID */
  tenantId?: string;
  /** 心跳检测路径。默认: /api/v1/health */
  heartbeatPath?: string;
  /** 心跳轮询间隔 (ms)。默认: 15_000 */
  heartbeatIntervalMs?: number;
  /** 同步重试次数上限。默认: 5 */
  maxRetry?: number;
  /**
   * 自定义 replay 函数。提供后覆盖默认按 op.type 路由的内置逻辑。
   * 用于：跨终端复用（不同 API 路径）、测试注入、未来 op 类型扩展。
   */
  customReplay?: (op: OfflineOperation, ctx: ReplayContext) => Promise<boolean>;
}

/** replayOperation 的 DI 上下文 */
export interface ReplayContext {
  apiBaseUrl: string;
  tenantId: string;
  /** 注入 fetch 实现（默认 globalThis.fetch），便于测试 */
  fetch?: typeof fetch;
}

// ─── IndexedDB 工具 ─────────────────────────────────────────────────────────

const DB_NAME = 'tunxiang_pos_offline';
const DB_VERSION = 1;
const STORE_NAME = 'operations';

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function getAllOps(): Promise<OfflineOperation[]> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result as OfflineOperation[]);
    req.onerror = () => reject(req.error);
    tx.oncomplete = () => db.close();
  });
}

async function putOp(op: OfflineOperation): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    store.put(op);
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = () => { db.close(); reject(tx.error); };
  });
}

async function deleteOp(id: string): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    store.delete(id);
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = () => { db.close(); reject(tx.error); };
  });
}

async function clearAllOps(): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    store.clear();
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = () => { db.close(); reject(tx.error); };
  });
}

// ─── API 重放 ───────────────────────────────────────────────────────────────

const ENV_API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const ENV_TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

const DEFAULT_REPLAY_CONTEXT: ReplayContext = {
  apiBaseUrl: ENV_API_BASE_URL,
  tenantId: ENV_TENANT_ID,
};

/**
 * 单条 op 重放。R-补2-1（Tier1）：必须带 `X-Idempotency-Key` header，让 server
 * replay cache 在跨会话/重启场景下拦截重复请求，防止同单双扣。
 *
 * @param op  离线操作
 * @param ctx 可选 DI 上下文。未提供时从环境变量取（保持原行为，单测便于注入）。
 *
 * 暴露为模块级 export 便于单测，非业务 UI 直接调用。
 */
export async function replayOperation(
  op: OfflineOperation,
  ctx: ReplayContext = DEFAULT_REPLAY_CONTEXT,
): Promise<boolean> {
  const idempotencyKey = deriveIdempotencyKey(op);
  const { apiBaseUrl, tenantId } = ctx;
  const fetchImpl = ctx.fetch ?? fetch;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Idempotency-Key': idempotencyKey,
    ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
  };

  let path = '';
  let body = '';

  switch (op.type) {
    case 'create_order':
      path = '/api/v1/trade/orders';
      body = JSON.stringify(op.payload);
      break;
    case 'add_item':
      path = `/api/v1/trade/orders/${op.payload.orderId as string}/items`;
      body = JSON.stringify({
        dish_id: op.payload.dishId,
        dish_name: op.payload.dishName,
        quantity: op.payload.quantity,
        unit_price_fen: op.payload.unitPriceFen,
      });
      break;
    case 'settle_order':
      path = `/api/v1/trade/orders/${op.payload.orderId as string}/settle`;
      body = '{}';
      break;
    case 'create_payment':
      path = `/api/v1/trade/orders/${op.payload.orderId as string}/payments`;
      body = JSON.stringify({
        method: op.payload.method,
        amount_fen: op.payload.amountFen,
        trade_no: op.payload.tradeNo,
      });
      break;
    default:
      console.warn('未知离线操作类型:', op.type);
      return false;
  }

  const resp = await fetchImpl(`${apiBaseUrl}${path}`, {
    method: 'POST',
    headers,
    body,
  });
  const json: { ok: boolean } = await resp.json();
  return json.ok;
}

// ─── 心跳检测 默认值 ────────────────────────────────────────────────────────

const DEFAULT_HEARTBEAT_PATH = '/api/v1/health';
const DEFAULT_HEARTBEAT_INTERVAL_MS = 15_000;
const DEFAULT_MAX_RETRY = 5;

// ─── Hook ───────────────────────────────────────────────────────────────────

export function useOffline(options: UseOfflineOptions = {}): UseOfflineResult {
  const apiBaseUrl = options.apiBaseUrl ?? ENV_API_BASE_URL;
  const tenantId = options.tenantId ?? ENV_TENANT_ID;
  const heartbeatPath = options.heartbeatPath ?? DEFAULT_HEARTBEAT_PATH;
  const heartbeatIntervalMs = options.heartbeatIntervalMs ?? DEFAULT_HEARTBEAT_INTERVAL_MS;
  const maxRetry = options.maxRetry ?? DEFAULT_MAX_RETRY;
  const customReplay = options.customReplay;

  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [offlineQueue, setOfflineQueue] = useState<OfflineOperation[]>([]);
  const [syncing, setSyncing] = useState(false);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const syncingRef = useRef(false);

  // 从 IndexedDB 加载队列
  const refreshQueue = useCallback(async () => {
    const ops = await getAllOps();
    setOfflineQueue(ops.sort((a, b) => a.createdAt.localeCompare(b.createdAt)));
  }, []);

  // 网络状态监听
  useEffect(() => {
    const goOnline = () => setIsOnline(true);
    const goOffline = () => setIsOnline(false);
    window.addEventListener('online', goOnline);
    window.addEventListener('offline', goOffline);
    return () => {
      window.removeEventListener('online', goOnline);
      window.removeEventListener('offline', goOffline);
    };
  }, []);

  // 心跳检测 — 补偿 navigator.onLine 不可靠的场景
  useEffect(() => {
    const heartbeatUrl = `${apiBaseUrl}${heartbeatPath}`;
    const doHeartbeat = async () => {
      try {
        const resp = await fetch(heartbeatUrl, {
          method: 'GET',
          cache: 'no-store',
          signal: AbortSignal.timeout(5000),
        });
        if (resp.ok) {
          setIsOnline(true);
        } else {
          setIsOnline(false);
        }
      } catch {
        setIsOnline(false);
      }
    };

    heartbeatRef.current = setInterval(doHeartbeat, heartbeatIntervalMs);
    return () => {
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    };
  }, [apiBaseUrl, heartbeatPath, heartbeatIntervalMs]);

  // 初始化：加载队列
  useEffect(() => {
    refreshQueue();
  }, [refreshQueue]);

  // 恢复连接后自动同步
  useEffect(() => {
    if (isOnline && offlineQueue.length > 0 && !syncingRef.current) {
      syncQueue();
    }
  }, [isOnline]); // eslint-disable-line react-hooks/exhaustive-deps

  // 入队
  const enqueue = useCallback(async (
    op: EnqueueInput,
  ): Promise<string> => {
    const id = `offline_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    // R-补2-1：未传 idempotencyKey 时按 type+payload 派生稳定 key（与 replay 保持一致）
    const fullOpDraft: OfflineOperation = {
      ...op,
      id,
      createdAt: new Date().toISOString(),
      retryCount: 0,
    };
    const fullOp: OfflineOperation = {
      ...fullOpDraft,
      idempotencyKey: op.idempotencyKey ?? deriveIdempotencyKey(fullOpDraft),
    };
    await putOp(fullOp);
    await refreshQueue();
    return id;
  }, [refreshQueue]);

  // 同步队列
  const syncQueue = useCallback(async () => {
    if (syncingRef.current) return;
    syncingRef.current = true;
    setSyncing(true);

    const replayCtx: ReplayContext = { apiBaseUrl, tenantId };
    const replay = customReplay ?? ((op: OfflineOperation) => replayOperation(op, replayCtx));

    try {
      const ops = await getAllOps();
      const sorted = ops.sort((a, b) => a.createdAt.localeCompare(b.createdAt));

      for (const op of sorted) {
        try {
          const ok = await replay(op, replayCtx);
          if (ok) {
            await deleteOp(op.id);
          } else if (op.retryCount >= maxRetry) {
            console.error('离线操作重试次数超限，已丢弃:', op);
            await deleteOp(op.id);
          } else {
            await putOp({ ...op, retryCount: op.retryCount + 1 });
          }
        } catch (networkErr) {
          // 同步中断（又断网了），停止后续操作
          console.warn('同步中断:', networkErr);
          break;
        }
      }
    } finally {
      syncingRef.current = false;
      setSyncing(false);
      await refreshQueue();
    }
  }, [refreshQueue, apiBaseUrl, tenantId, customReplay, maxRetry]);

  // 清空队列
  const clearQueue = useCallback(async () => {
    await clearAllOps();
    await refreshQueue();
  }, [refreshQueue]);

  return {
    isOnline,
    offlineQueue,
    queueLength: offlineQueue.length,
    enqueue,
    syncQueue,
    syncing,
    clearQueue,
  };
}

// ─── 临时订单号生成（离线时使用） ───────────────────────────────────────────

export function generateOfflineOrderNo(): string {
  const ts = Date.now().toString(36).toUpperCase();
  const rand = Math.random().toString(36).slice(2, 6).toUpperCase();
  return `OFF-${ts}-${rand}`;
}

export function generateOfflineOrderId(): string {
  return `offline_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}
