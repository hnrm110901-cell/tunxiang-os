/**
 * KDS Order Cache — Sprint C1
 *
 * 基于 IndexedDB 的 last-100 KDS 订单本地缓存（按 tenantId+storeId 分区）。
 *
 * 与 src/db/kdsOrdersDB.ts 的差异：
 *   - 该模块面向 /kds/orders/delta 轮询路径（C3 引入），按 (tenantId,storeId)
 *     分区，是多门店总部场景的主缓存。
 *   - kdsOrdersDB.ts 是单店 WebSocket 路径的旧实现，保留原有契约不动。
 *
 * 设计要点：
 *   - 单 IDB 数据库 + 单 ObjectStore；分区通过复合索引 [tenantId,storeId] 实现。
 *   - 容量上限 100/分区；超额按 updatedAt 旧→新淘汰。
 *   - 大小自检 getApproxSizeBytes() 用于断言 < 20MB（每条 ~2KB × 100 = ~200KB / 分区）。
 *   - 启动时降级：indexedDB 不可用退化为内存 Map，API 不变。
 *
 * Schema（DB v1）:
 *   db:    tunxiang_kds_orders
 *   store: orders, keyPath = orderId
 *   idx:   ['tenantId','storeId']           — 分区主索引
 *   idx:   updatedAt                         — LRU 淘汰
 */

import type { KDSDeltaOrder } from '../api/kdsDeltaApi';

// ─── 持久化记录类型 ───────────────────────────────────────

/** 缓存中的订单记录 */
export interface CachedKdsOrder {
  orderId: string;
  tenantId: string;
  storeId: string;
  status: string;
  items: unknown[];
  /** epoch ms — IDB 索引列，必须 number 而非 ISO 字符串 */
  updatedAt: number;
  payload: KDSDeltaOrder;
}

const DB_NAME = 'tunxiang_kds_orders';
const DB_VERSION = 1;
const STORE_NAME = 'orders';

/** 每分区上限。超过该值按 updatedAt 旧→新淘汰。 */
export const MAX_ORDERS_PER_PARTITION = 100;

// ─── 后端抽象 ───────────────────────────────────────────

interface Backend {
  putMany(records: CachedKdsOrder[]): Promise<void>;
  getByPartition(tenantId: string, storeId: string): Promise<CachedKdsOrder[]>;
  deleteIds(ids: string[]): Promise<void>;
  clearPartition(tenantId: string, storeId: string): Promise<void>;
  countAll(): Promise<number>;
  getAll(): Promise<CachedKdsOrder[]>;
}

// ─── IDB 后端 ───────────────────────────────────────────

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'orderId' });
        // 复合索引用于按 (tenantId,storeId) 分区查询
        store.createIndex('partition', ['tenantId', 'storeId'], { unique: false });
        store.createIndex('updatedAt', 'updatedAt', { unique: false });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

class IDBBackend implements Backend {
  constructor(private db: IDBDatabase) {}

  putMany(records: CachedKdsOrder[]): Promise<void> {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      for (const r of records) store.put(r);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async getByPartition(tenantId: string, storeId: string): Promise<CachedKdsOrder[]> {
    // FakeIndexedDB shim 不支持 index.getAll()，统一走 getAll() + JS 过滤。
    // 真 IDB 性能足够（单分区 ≤ 100 条）。
    const all = await this.getAll();
    return all.filter((r) => r.tenantId === tenantId && r.storeId === storeId);
  }

  deleteIds(ids: string[]): Promise<void> {
    if (ids.length === 0) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      for (const id of ids) store.delete(id);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async clearPartition(tenantId: string, storeId: string): Promise<void> {
    const ids = (await this.getByPartition(tenantId, storeId)).map((r) => r.orderId);
    await this.deleteIds(ids);
  }

  async countAll(): Promise<number> {
    const all = await this.getAll();
    return all.length;
  }

  getAll(): Promise<CachedKdsOrder[]> {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(STORE_NAME, 'readonly');
      const req = tx.objectStore(STORE_NAME).getAll();
      req.onsuccess = () => resolve((req.result as CachedKdsOrder[]) ?? []);
      req.onerror = () => reject(req.error);
    });
  }
}

// ─── 内存后端 ───────────────────────────────────────────

class MemoryBackend implements Backend {
  private map = new Map<string, CachedKdsOrder>();
  async putMany(records: CachedKdsOrder[]) {
    for (const r of records) this.map.set(r.orderId, r);
  }
  async getByPartition(tenantId: string, storeId: string) {
    return Array.from(this.map.values()).filter(
      (r) => r.tenantId === tenantId && r.storeId === storeId,
    );
  }
  async deleteIds(ids: string[]) {
    for (const id of ids) this.map.delete(id);
  }
  async clearPartition(tenantId: string, storeId: string) {
    for (const [k, v] of this.map) {
      if (v.tenantId === tenantId && v.storeId === storeId) this.map.delete(k);
    }
  }
  async countAll() {
    return this.map.size;
  }
  async getAll() {
    return Array.from(this.map.values());
  }
}

// ─── 单例 ───────────────────────────────────────────────

let backendPromise: Promise<Backend> | null = null;
let forceMemory = false;

async function getBackend(): Promise<Backend> {
  if (backendPromise) return backendPromise;
  backendPromise = (async (): Promise<Backend> => {
    if (forceMemory || typeof indexedDB === 'undefined') {
      return new MemoryBackend();
    }
    try {
      const db = await openDB();
      return new IDBBackend(db);
    } catch {
      return new MemoryBackend();
    }
  })();
  return backendPromise;
}

// ─── 转换：KDSDeltaOrder → CachedKdsOrder ────────────────

function toRecord(order: KDSDeltaOrder): CachedKdsOrder {
  const items = Array.isArray((order.order_metadata as { items?: unknown[] } | undefined)?.items)
    ? ((order.order_metadata as { items?: unknown[] }).items as unknown[])
    : [];
  return {
    orderId: order.id,
    tenantId: order.tenant_id,
    storeId: order.store_id,
    status: order.status,
    items,
    updatedAt: parseUpdatedAt(order.updated_at),
    payload: order,
  };
}

function parseUpdatedAt(iso: string): number {
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : Date.now();
}

// ─── LRU 淘汰（按分区） ──────────────────────────────────

async function enforcePartitionLRU(
  be: Backend,
  tenantId: string,
  storeId: string,
): Promise<void> {
  const part = await be.getByPartition(tenantId, storeId);
  if (part.length <= MAX_ORDERS_PER_PARTITION) return;
  const overflow = part.length - MAX_ORDERS_PER_PARTITION;
  const sorted = [...part].sort((a, b) => a.updatedAt - b.updatedAt);
  const toRemove = sorted.slice(0, overflow).map((r) => r.orderId);
  await be.deleteIds(toRemove);
}

// ─── 公开 API ───────────────────────────────────────────

/**
 * 启动时把 (tenantId,storeId) 分区的最新 100 条 hydrate 到调用方。
 * 返回按 updatedAt 降序（最新在前）。
 */
export async function hydrate(
  tenantId: string,
  storeId: string,
): Promise<KDSDeltaOrder[]> {
  const be = await getBackend();
  const records = await be.getByPartition(tenantId, storeId);
  records.sort((a, b) => b.updatedAt - a.updatedAt);
  return records.slice(0, MAX_ORDERS_PER_PARTITION).map((r) => r.payload);
}

/**
 * upsert 单条订单。若 orderId 已存在但 updatedAt 不更新则忽略。
 */
export async function upsert(order: KDSDeltaOrder): Promise<void> {
  await upsertBatch([order]);
}

/**
 * 批量 upsert。同一 orderId 取 updatedAt 最新；按分区独立淘汰。
 */
export async function upsertBatch(orders: KDSDeltaOrder[]): Promise<void> {
  if (orders.length === 0) return;
  const be = await getBackend();

  // 1) 同批次内按 orderId 去重，只保留 updatedAt 最大的版本
  const dedup = new Map<string, CachedKdsOrder>();
  for (const o of orders) {
    const r = toRecord(o);
    const cur = dedup.get(r.orderId);
    if (!cur || cur.updatedAt < r.updatedAt) dedup.set(r.orderId, r);
  }
  const records = Array.from(dedup.values());

  // 收集本批涉及的所有分区，仅在批量结束后对各分区做一次 LRU 淘汰
  const partitions = new Set<string>();
  for (const r of records) partitions.add(`${r.tenantId}|${r.storeId}`);

  // 2) 读取当前已存在记录，过滤 updatedAt 不更新的
  const existing = await be.getAll();
  const byId = new Map<string, CachedKdsOrder>();
  for (const e of existing) byId.set(e.orderId, e);

  const toWrite: CachedKdsOrder[] = [];
  for (const r of records) {
    const cur = byId.get(r.orderId);
    if (!cur || cur.updatedAt < r.updatedAt) toWrite.push(r);
  }

  if (toWrite.length > 0) await be.putMany(toWrite);

  // 3) 各分区独立 LRU 淘汰
  for (const key of partitions) {
    const [tenantId, storeId] = key.split('|');
    await enforcePartitionLRU(be, tenantId, storeId);
  }
}

/**
 * 删除 updatedAt 早于阈值的记录（跨分区扫描）。
 * 主要用于演练 / 4h 离线回收测试。
 */
export async function evictOlderThan(ts: number): Promise<number> {
  const be = await getBackend();
  const all = await be.getAll();
  const ids = all.filter((r) => r.updatedAt < ts).map((r) => r.orderId);
  if (ids.length > 0) await be.deleteIds(ids);
  return ids.length;
}

/**
 * 清空指定分区。切店时调用以保证内存视图与 IDB 视图一致。
 */
export async function clear(tenantId: string, storeId: string): Promise<void> {
  const be = await getBackend();
  await be.clearPartition(tenantId, storeId);
}

/**
 * 全库总条数（所有分区合计）。运维诊断用。
 */
export async function size(): Promise<number> {
  const be = await getBackend();
  return be.countAll();
}

/**
 * 估算 IDB 占用字节数 = JSON.stringify(allRecords).length。
 * 单条订单 ~1.5–2KB，100 单 × N 分区，应远小于 20MB。
 *
 * 测试断言：getApproxSizeBytes() < 20 * 1024 * 1024。
 */
export async function getApproxSizeBytes(): Promise<number> {
  const be = await getBackend();
  const all = await be.getAll();
  // JSON.stringify 长度 = utf-16 字符数；中文一字 = 1 字符 = 2 字节，但绝大多数
  // KDSDeltaOrder 字段是 ASCII（id / iso8601），按字符数当字节数估算偏低不超过 ~2x，
  // 上层告警阈值留一倍冗余即可。
  try {
    return JSON.stringify(all).length;
  } catch {
    return 0;
  }
}

// ─── 测试 / 诊断用 ───────────────────────────────────────

export function __forceMemoryFallbackForTest(): void {
  forceMemory = true;
  backendPromise = null;
}

export function __resetForTest(): void {
  forceMemory = false;
  backendPromise = null;
}
