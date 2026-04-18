/**
 * KDS 本地订单缓存（IndexedDB last-100-orders）
 * 断网时厨师依赖本地缓存继续出品。C1 仅负责存储层。
 *
 * Schema:
 *   DB:    tunxiang_kds_cache (version 1)
 *   Store: orders (keyPath: order_id)
 *   Idx:   updated_at, status, device_id
 *
 * LRU: 超过 MAX_ORDERS 时优先淘汰 status=completed 且最老的；
 *      若没有可淘汰的 completed，则淘汰最老的任意状态。
 * Fallback: IDB 不可用（隐私模式/jsdom/旧浏览器）降级到内存 Map。
 */

export interface KdsOrderItem {
  name: string;
  qty: number;
  notes?: string;
  spec?: string;
}

export type KdsOrderStatus = 'pending' | 'cooking' | 'completed' | 'cancelled';

export interface KdsCachedOrder {
  order_id: string;
  order_no: string;
  table_no: string;
  items: KdsOrderItem[];
  status: KdsOrderStatus;
  created_at: number;
  updated_at: number;
  station_id: string;
  device_id: string;
  priority?: 'normal' | 'rush' | 'vip';
}

export interface CacheStats {
  count: number;
  oldest: number | null;
  newest: number | null;
  mode: 'idb' | 'memory';
}

const DB_NAME = 'tunxiang_kds_cache';
const DB_VERSION = 1;
const STORE_NAME = 'orders';
const MAX_ORDERS = 100;

// ─── 后端抽象 ───

interface Backend {
  put(order: KdsCachedOrder): Promise<void>;
  putMany(orders: KdsCachedOrder[]): Promise<void>;
  getAll(): Promise<KdsCachedOrder[]>;
  remove(id: string): Promise<void>;
  clearAll(): Promise<void>;
}

// ─── IDB 后端 ───

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'order_id' });
        store.createIndex('updated_at', 'updated_at', { unique: false });
        store.createIndex('status', 'status', { unique: false });
        store.createIndex('device_id', 'device_id', { unique: false });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function idbPut(db: IDBDatabase, order: KdsCachedOrder): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).put(order);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

function idbPutMany(db: IDBDatabase, orders: KdsCachedOrder[]): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    for (const o of orders) store.put(o);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

function idbGetAll(db: IDBDatabase): Promise<KdsCachedOrder[]> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const req = tx.objectStore(STORE_NAME).getAll();
    req.onsuccess = () => resolve(req.result as KdsCachedOrder[]);
    req.onerror = () => reject(req.error);
  });
}

function idbDelete(db: IDBDatabase, id: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

function idbClear(db: IDBDatabase): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).clear();
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

class IDBBackend implements Backend {
  constructor(private db: IDBDatabase) {}
  put(o: KdsCachedOrder) { return idbPut(this.db, o); }
  putMany(os: KdsCachedOrder[]) { return idbPutMany(this.db, os); }
  getAll() { return idbGetAll(this.db); }
  remove(id: string) { return idbDelete(this.db, id); }
  clearAll() { return idbClear(this.db); }
}

// ─── 内存后端 ───

class MemoryBackend implements Backend {
  private map = new Map<string, KdsCachedOrder>();
  async put(o: KdsCachedOrder) { this.map.set(o.order_id, o); }
  async putMany(os: KdsCachedOrder[]) { for (const o of os) this.map.set(o.order_id, o); }
  async getAll() { return Array.from(this.map.values()); }
  async remove(id: string) { this.map.delete(id); }
  async clearAll() { this.map.clear(); }
}

// ─── 单例管理 ───

let backendPromise: Promise<Backend> | null = null;
let backendMode: 'idb' | 'memory' = 'idb';
let forceMemory = false;

async function getBackend(): Promise<Backend> {
  if (backendPromise) return backendPromise;
  backendPromise = (async (): Promise<Backend> => {
    if (forceMemory || typeof indexedDB === 'undefined') {
      backendMode = 'memory';
      return new MemoryBackend();
    }
    try {
      const db = await openDB();
      backendMode = 'idb';
      return new IDBBackend(db);
    } catch {
      backendMode = 'memory';
      return new MemoryBackend();
    }
  })();
  return backendPromise;
}

// ─── LRU 淘汰 ───

async function enforceLRU(be: Backend): Promise<void> {
  const all = await be.getAll();
  if (all.length <= MAX_ORDERS) return;
  const overflow = all.length - MAX_ORDERS;
  // 优先淘汰 completed 且最老的
  const completed = all
    .filter((o) => o.status === 'completed' || o.status === 'cancelled')
    .sort((a, b) => a.updated_at - b.updated_at);
  const toRemove: string[] = [];
  for (let i = 0; i < overflow && i < completed.length; i++) {
    toRemove.push(completed[i].order_id);
  }
  // 若仍超额，淘汰最老的任意单
  if (toRemove.length < overflow) {
    const remaining = all
      .filter((o) => !toRemove.includes(o.order_id))
      .sort((a, b) => a.updated_at - b.updated_at);
    for (let i = 0; i < overflow - toRemove.length && i < remaining.length; i++) {
      toRemove.push(remaining[i].order_id);
    }
  }
  for (const id of toRemove) await be.remove(id);
}

// ─── 公开 API ───

/**
 * upsert 单条订单。若 order_id 已存在且 updated_at 不新于现有值则丢弃。
 */
export async function upsertOrder(order: KdsCachedOrder): Promise<void> {
  const be = await getBackend();
  const all = await be.getAll();
  const existing = all.find((o) => o.order_id === order.order_id);
  if (existing && existing.updated_at >= order.updated_at) return;
  await be.put(order);
  await enforceLRU(be);
}

/**
 * 批量 upsert。相同 order_id 取 updated_at 最新。
 */
export async function upsertBatch(orders: KdsCachedOrder[]): Promise<void> {
  const be = await getBackend();
  const all = await be.getAll();
  const map = new Map<string, KdsCachedOrder>();
  for (const o of all) map.set(o.order_id, o);
  for (const o of orders) {
    const cur = map.get(o.order_id);
    if (!cur || cur.updated_at < o.updated_at) map.set(o.order_id, o);
  }
  // 只写入新增或更新的
  const toWrite = orders.filter((o) => {
    const cur = all.find((a) => a.order_id === o.order_id);
    return !cur || cur.updated_at < o.updated_at;
  });
  if (toWrite.length > 0) await be.putMany(toWrite);
  await enforceLRU(be);
}

export async function getAll(): Promise<KdsCachedOrder[]> {
  const be = await getBackend();
  return be.getAll();
}

export async function getLastN(n: number): Promise<KdsCachedOrder[]> {
  const all = await getAll();
  return all.sort((a, b) => b.created_at - a.created_at).slice(0, n);
}

export async function clear(): Promise<void> {
  const be = await getBackend();
  await be.clearAll();
}

export async function getStats(): Promise<CacheStats> {
  const all = await getAll();
  if (all.length === 0) {
    return { count: 0, oldest: null, newest: null, mode: backendMode };
  }
  let oldest = Infinity;
  let newest = -Infinity;
  for (const o of all) {
    if (o.created_at < oldest) oldest = o.created_at;
    if (o.created_at > newest) newest = o.created_at;
  }
  return { count: all.length, oldest, newest, mode: backendMode };
}

// ─── 测试专用 ───

export function __forceMemoryFallback(): void {
  forceMemory = true;
  backendPromise = null;
}

export function __resetDBForTest(): void {
  backendPromise = null;
  backendMode = 'idb';
  forceMemory = false;
}
