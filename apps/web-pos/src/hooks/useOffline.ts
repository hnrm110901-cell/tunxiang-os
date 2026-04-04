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
}

interface UseOfflineResult {
  isOnline: boolean;
  offlineQueue: OfflineOperation[];
  queueLength: number;
  enqueue: (op: Omit<OfflineOperation, 'id' | 'createdAt' | 'retryCount'>) => Promise<string>;
  syncQueue: () => Promise<void>;
  syncing: boolean;
  clearQueue: () => Promise<void>;
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

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

async function replayOperation(op: OfflineOperation): Promise<boolean> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
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

  const resp = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers,
    body,
  });
  const json: { ok: boolean } = await resp.json();
  return json.ok;
}

// ─── 心跳检测 ───────────────────────────────────────────────────────────────

const HEARTBEAT_URL = `${BASE_URL}/api/v1/health`;
const HEARTBEAT_INTERVAL_MS = 15_000;
const MAX_RETRY = 5;

// ─── Hook ───────────────────────────────────────────────────────────────────

export function useOffline(): UseOfflineResult {
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
    const doHeartbeat = async () => {
      try {
        const resp = await fetch(HEARTBEAT_URL, {
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

    heartbeatRef.current = setInterval(doHeartbeat, HEARTBEAT_INTERVAL_MS);
    return () => {
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    };
  }, []);

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
    op: Omit<OfflineOperation, 'id' | 'createdAt' | 'retryCount'>,
  ): Promise<string> => {
    const id = `offline_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const fullOp: OfflineOperation = {
      ...op,
      id,
      createdAt: new Date().toISOString(),
      retryCount: 0,
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

    try {
      const ops = await getAllOps();
      const sorted = ops.sort((a, b) => a.createdAt.localeCompare(b.createdAt));

      for (const op of sorted) {
        try {
          const ok = await replayOperation(op);
          if (ok) {
            await deleteOp(op.id);
          } else if (op.retryCount >= MAX_RETRY) {
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
  }, [refreshQueue]);

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
