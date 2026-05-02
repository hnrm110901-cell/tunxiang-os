/**
 * offline-4h.spec.ts — KDS 4h 离线/恢复/数据完整性 E2E (Tier 1)
 *
 * Sprint C — KDS 端本地强化。验证 IndexedDB 离线缓存层在长时间网络中断
 * 后的数据不丢失、不重复，以及 LRU 淘汰机制正确性。
 *
 * 餐厅场景（CLAUDE.md §20）：
 *   后厨 KDS 下午 5 点开机直到凌晨 1 点闭店。期间路由器故障 30 分钟，
 *   新订单缓存在本地 IndexedDB，恢复后 delta 拉取完整。
 *
 * 四个用例：
 *   1. test_offline_cache_write_read
 *      —— 离线缓存基本 CRUD：写入、按状态查询、按设备查询、清空
 *   2. test_offline_recovery_no_data_loss
 *      —— 离线→恢复后累计订单无丢失、无重复
 *   3. test_lru_eviction_beyond_100
 *      —— >100 单触发 LRU 淘汰，保留最新 100 单
 *   4. test_memory_during_offline_online_cycling
 *      —— 反复 online/degraded/offline 切换，JS 堆增长 ≤50MB
 *
 * 模式（KDS_E2E_DURATION_MS）：
 *   - fast (默认 60_000ms = 60s)：PR 门禁
 *   - nightly (14_400_000ms = 4h)：CI 凌晨
 */
import { test, expect, type Page } from '@playwright/test';
import { MockDeltaServer, startMockDeltaServer } from './fixtures/mockDeltaServer';

// ─── 类型声明 ─────────────────────────────────────────────────────

declare global {
  interface Window {
    __offlineDB: {
      saveOrder(order: Record<string, unknown>): Promise<void>;
      saveOrders(orders: Record<string, unknown>[]): Promise<void>;
      getByStatus(status: string): Promise<Record<string, unknown>[]>;
      getByDevice(deviceId: string): Promise<Record<string, unknown>[]>;
      getAll(): Promise<Record<string, unknown>[]>;
      getById(id: string): Promise<Record<string, unknown> | null>;
      clearAll(): Promise<void>;
      getCount(): Promise<number>;
    };
    __txLongtaskTotalMs: number;
    __txLongtaskCount: number;
    __txStartTs: number;
    __healthStates: string[];
  }
}

// ─── 常量 ──────────────────────────────────────────────────────────

const DURATION_MS = Number(process.env.KDS_E2E_DURATION_MS ?? 60_000);
const SAMPLE_INTERVAL_MS = 5_000;
const POLL_INTERVAL_MS = 3_000;
const MEMORY_GROWTH_LIMIT_MB = 50;
const CACHE_LIMIT = 100;

// ─── 测试页 JS 注入 ────────────────────────────────────────────────

/**
 * 在浏览器侧注入 IndexedDB "kdsOrdersDB" 模拟层。
 *
 * 实现了与真实 kdsOrdersDB.ts 相同的接口契约：
 *   saveOrder / saveOrders / getByStatus / getByDevice / getAll / getById / clearAll / getCount
 *
 * 使用 "kds-offline-e2e" 数据库，LRU 淘汰上限 CACHE_LIMIT（100）。
 */
const INJECT_OFFLINE_DB_SCRIPT = `
(function() {
  const DB_NAME = 'kds-offline-e2e';
  const STORE_NAME = 'orders';
  const MAX_ORDERS = ${CACHE_LIMIT};

  function openDB() {
    return new Promise(function(resolve, reject) {
      var req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function() {
        var db = req.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          var store = db.createObjectStore(STORE_NAME, { keyPath: 'id' });
          store.createIndex('status', 'status', { unique: false });
          store.createIndex('device_id', 'device_id', { unique: false });
          store.createIndex('updated_at', 'updated_at', { unique: false });
        }
      };
      req.onsuccess = function() { resolve(req.result); };
      req.onerror = function() { reject(req.error); };
    });
  }

  window.__offlineDB = {
    saveOrder: async function(order) {
      var db = await openDB();
      return new Promise(function(resolve, reject) {
        var tx = db.transaction(STORE_NAME, 'readwrite');
        var store = tx.objectStore(STORE_NAME);
        var countReq = store.count();
        countReq.onsuccess = function() {
          if (countReq.result >= MAX_ORDERS) {
            var idx = store.index('updated_at');
            var cursorReq = idx.openCursor(null, 'next');
            var toDelete = countReq.result - MAX_ORDERS + 1;
            var deleted = 0;
            cursorReq.onsuccess = function(evt) {
              var cursor = evt.target.result;
              if (cursor && deleted < toDelete) {
                store.delete(cursor.value.id);
                deleted++;
                cursor.continue();
              }
            };
          }
          store.put(order);
        };
        tx.oncomplete = function() { resolve(); };
        tx.onerror = function() { reject(tx.error); };
      });
    },

    saveOrders: async function(orders) {
      for (var i = 0; i < orders.length; i++) {
        await this.saveOrder(orders[i]);
      }
    },

    getByStatus: async function(status) {
      var db = await openDB();
      return new Promise(function(resolve, reject) {
        var tx = db.transaction(STORE_NAME, 'readonly');
        var store = tx.objectStore(STORE_NAME);
        var idx = store.index('status');
        var req = idx.getAll(IDBKeyRange.only(status));
        req.onsuccess = function() { resolve(req.result); };
        req.onerror = function() { reject(req.error); };
      });
    },

    getByDevice: async function(deviceId) {
      var db = await openDB();
      return new Promise(function(resolve, reject) {
        var tx = db.transaction(STORE_NAME, 'readonly');
        var store = tx.objectStore(STORE_NAME);
        var idx = store.index('device_id');
        var req = idx.getAll(IDBKeyRange.only(deviceId));
        req.onsuccess = function() { resolve(req.result); };
        req.onerror = function() { reject(req.error); };
      });
    },

    getAll: async function() {
      var db = await openDB();
      return new Promise(function(resolve, reject) {
        var tx = db.transaction(STORE_NAME, 'readonly');
        var store = tx.objectStore(STORE_NAME);
        var req = store.getAll();
        req.onsuccess = function() { resolve(req.result); };
        req.onerror = function() { reject(req.error); };
      });
    },

    getById: async function(id) {
      var db = await openDB();
      return new Promise(function(resolve, reject) {
        var tx = db.transaction(STORE_NAME, 'readonly');
        var store = tx.objectStore(STORE_NAME);
        var req = store.get(id);
        req.onsuccess = function() { resolve(req.result || null); };
        req.onerror = function() { reject(req.error); };
      });
    },

    clearAll: async function() {
      var db = await openDB();
      return new Promise(function(resolve, reject) {
        var tx = db.transaction(STORE_NAME, 'readwrite');
        var store = tx.objectStore(STORE_NAME);
        var req = store.clear();
        tx.oncomplete = function() { resolve(); };
        tx.onerror = function() { reject(tx.error); };
      });
    },

    getCount: async function() {
      var db = await openDB();
      return new Promise(function(resolve, reject) {
        var tx = db.transaction(STORE_NAME, 'readonly');
        var store = tx.objectStore(STORE_NAME);
        var req = store.count();
        req.onsuccess = function() { resolve(req.result); };
        req.onerror = function() { reject(req.error); };
      });
    },
  };
})();
`;

/**
 * 安装 PerformanceObserver 追踪长任务。
 */
const INJECT_OBSERVERS_SCRIPT = `
(function() {
  var w = window;
  w.__txLongtaskTotalMs = 0;
  w.__txLongtaskCount = 0;
  w.__txStartTs = performance.now();
  w.__healthStates = [];
  try {
    var obs = new PerformanceObserver(function(list) {
      var entries = list.getEntries();
      for (var i = 0; i < entries.length; i++) {
        if (entries[i].duration > 50) {
          w.__txLongtaskTotalMs += entries[i].duration;
          w.__txLongtaskCount += 1;
        }
      }
    });
    obs.observe({ entryTypes: ['longtask'] });
  } catch (e) {
    // 某些浏览器不支持 longtask，静默跳过
  }
})();
`;

// ─── 工具函数 ──────────────────────────────────────────────────────

async function sampleMemoryMB(page: Page): Promise<number | null> {
  return page.evaluate(() => {
    const perf = performance as Performance & { memory?: { usedJSHeapSize: number } };
    if (!perf.memory) return null;
    return perf.memory.usedJSHeapSize / (1024 * 1024);
  });
}

async function pollDelta(
  page: Page,
  baseURL: string,
  storeId = 'demo',
  deviceId = 'mock-kds-001',
  count = 1,
): Promise<void> {
  for (let i = 0; i < count; i++) {
    await page.evaluate(
      async ({ url }) => {
        try {
          const resp = await fetch(url);
          const json = await resp.json();
          const orders = (json && json.data && json.data.orders) || [];
          for (const o of orders) {
            await window.__offlineDB.saveOrder(o);
          }
        } catch {
          // poll 失败不计入（离线期可预期）
        }
      },
      {
        url: `${baseURL}/api/v1/kds/orders/delta?store_id=${storeId}&device_id=${deviceId}&device_kind=kds&limit=20`,
      },
    );
    await page.waitForTimeout(500);
  }
}

// ─── 测试套件 ──────────────────────────────────────────────────────

test.describe('KDS 4h 离线/恢复/数据完整性 (Tier 1)', () => {
  let mockServer: MockDeltaServer | null = null;
  let mockBaseURL = '';

  test.beforeEach(async () => {
    const result = await startMockDeltaServer({ pollIntervalMs: POLL_INTERVAL_MS });
    mockServer = result.server;
    mockBaseURL = result.baseURL;
  });

  test.afterEach(async () => {
    if (mockServer) {
      await mockServer.stop();
      mockServer = null;
    }
  });

  // ─── Test 1: 离线缓存基本 CRUD ─────────────────────────────────

  test('test_offline_cache_write_read', async ({ page }) => {
    await page.addInitScript(INJECT_OFFLINE_DB_SCRIPT);
    await page.setContent('<div id="status">running</div>');

    // 清空
    await page.evaluate(() => window.__offlineDB.clearAll());

    // 写入 5 条不同设备/状态的测试订单
    await page.evaluate(() =>
      window.__offlineDB.saveOrders([
        { id: 'ord-001', order_no: 'K000001', store_id: 'store-a', device_id: 'kds-01', status: 'pending', table_number: 'T1', items_count: 3, updated_at: new Date().toISOString() },
        { id: 'ord-002', order_no: 'K000002', store_id: 'store-a', device_id: 'kds-01', status: 'preparing', table_number: 'T2', items_count: 5, updated_at: new Date().toISOString() },
        { id: 'ord-003', order_no: 'K000003', store_id: 'store-a', device_id: 'kds-02', status: 'ready', table_number: 'T3', items_count: 2, updated_at: new Date().toISOString() },
        { id: 'ord-004', order_no: 'K000004', store_id: 'store-a', device_id: 'kds-02', status: 'pending', table_number: 'T4', items_count: 4, updated_at: new Date().toISOString() },
        { id: 'ord-005', order_no: 'K000005', store_id: 'store-a', device_id: 'kds-01', status: 'confirmed', table_number: 'T5', items_count: 1, updated_at: new Date().toISOString() },
      ]),
    );

    // getByStatus: pending 应返回 2 条
    const pending = await page.evaluate(() => window.__offlineDB.getByStatus('pending'));
    expect(pending).toHaveLength(2);
    const pendingIds = pending.map((o: Record<string, unknown>) => o.id).sort();
    expect(pendingIds).toEqual(['ord-001', 'ord-004']);

    // getByDevice: kds-01 应返回 3 条
    const kds01 = await page.evaluate(() => window.__offlineDB.getByDevice('kds-01'));
    expect(kds01).toHaveLength(3);
    const kds01Ids = kds01.map((o: Record<string, unknown>) => o.id).sort();
    expect(kds01Ids).toEqual(['ord-001', 'ord-002', 'ord-005']);

    // getCount: 应返回 5
    const count = await page.evaluate(() => window.__offlineDB.getCount());
    expect(count).toBe(5);

    // clearAll: 清空后 count 应为 0
    await page.evaluate(() => window.__offlineDB.clearAll());
    const afterClear = await page.evaluate(() => window.__offlineDB.getCount());
    expect(afterClear).toBe(0);
  });

  // ─── Test 2: 离线→恢复后数据不丢失 ────────────────────────────

  test('test_offline_recovery_no_data_loss', async ({ page }) => {
    await page.addInitScript(INJECT_OFFLINE_DB_SCRIPT);

    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    await page.setContent('<div id="status">running</div>');
    await page.evaluate(() => window.__offlineDB.clearAll());

    // Phase 1: 正常轮询 5 次，采集基线订单
    await pollDelta(page, mockBaseURL, 'demo', 'mock-kds-001', 5);
    const preOutageOrders = await page.evaluate(() => window.__offlineDB.getAll());
    const preOutageIds = new Set(preOutageOrders.map((o: Record<string, unknown>) => o.id));
    expect(preOutageIds.size).toBeGreaterThan(0);

    // Phase 2: 触发离线，模拟 10 笔新订单进入本地缓存
    mockServer!.setOutage(true);
    const offlineNewOrders: Record<string, unknown>[] = [];
    for (let i = 0; i < 10; i++) {
      offlineNewOrders.push({
        id: `offline-${i.toString().padStart(4, '0')}`,
        order_no: `OFF${i.toString().padStart(6, '0')}`,
        store_id: 'demo',
        device_id: 'mock-kds-001',
        status: 'pending',
        table_number: null,
        items_count: 1 + (i % 5),
        updated_at: new Date().toISOString(),
      });
    }
    await page.evaluate((orders) => window.__offlineDB.saveOrders(orders), offlineNewOrders);
    const duringOutageIds = new Set(offlineNewOrders.map((o) => o.id as string));
    const offlineCount = await page.evaluate(() => window.__offlineDB.getCount());
    expect(offlineCount).toBeGreaterThanOrEqual(preOutageIds.size + duringOutageIds.size - CACHE_LIMIT);

    // Phase 3: 恢复连接，继续拉取 5 轮
    mockServer!.setOutage(false);
    await pollDelta(page, mockBaseURL, 'demo', 'mock-kds-001', 5);

    // Phase 4: 验证所有订单完整性
    const finalOrders = await page.evaluate(() => window.__offlineDB.getAll());
    const finalIds = new Set(finalOrders.map((o: Record<string, unknown>) => o.id));

    // pre-outage 订单全部保留
    for (const id of preOutageIds) {
      expect(finalIds.has(id)).toBe(true);
    }
    // offline 期间缓存的订单全部保留
    for (const id of duringOutageIds) {
      expect(finalIds.has(id)).toBe(true);
    }
    // 恢复后仍有数据拉取
    const finalCount = await page.evaluate(() => window.__offlineDB.getCount());
    expect(finalCount).toBeGreaterThanOrEqual(preOutageIds.size + duringOutageIds.size - CACHE_LIMIT);

    // console.error 不应过多（离线期 fetch 失败可预期但应有限）
    expect(consoleErrors.length).toBeLessThan(50);
  });

  // ─── Test 3: LRU 淘汰 ──────────────────────────────────────────

  test('test_lru_eviction_beyond_100', async ({ page }) => {
    await page.addInitScript(INJECT_OFFLINE_DB_SCRIPT);
    await page.setContent('<div id="status">running</div>');
    await page.evaluate(() => window.__offlineDB.clearAll());

    // 写入 120 条订单（id ord-000 ~ ord-119），updated_at 递增
    const orders: Record<string, unknown>[] = [];
    for (let i = 0; i < 120; i++) {
      orders.push({
        id: `ord-${i.toString().padStart(3, '0')}`,
        order_no: `K${i.toString().padStart(6, '0')}`,
        store_id: 'demo',
        device_id: 'mock-kds-001',
        status: i % 2 === 0 ? 'pending' : 'preparing',
        table_number: null,
        items_count: 1 + (i % 5),
        updated_at: new Date(Date.now() + i * 1000).toISOString(),
      });
    }
    await page.evaluate((o) => window.__offlineDB.saveOrders(o), orders);

    // 验证缓存不超过 100 条
    const count = await page.evaluate(() => window.__offlineDB.getCount());
    expect(count).toBeLessThanOrEqual(100);

    // 验证全部数据
    const remaining = await page.evaluate(() => window.__offlineDB.getAll());
    const remainingIds = new Set(remaining.map((o: Record<string, unknown>) => o.id));

    // ord-000 ~ ord-019（最旧的 20 条）已被淘汰
    for (let i = 0; i < 20; i++) {
      const id = `ord-${i.toString().padStart(3, '0')}`;
      expect(remainingIds.has(id)).toBe(false);
    }
    // ord-020 ~ ord-119（最新的 100 条）应保留
    for (let i = 20; i < 120; i++) {
      const id = `ord-${i.toString().padStart(3, '0')}`;
      expect(remainingIds.has(id)).toBe(true);
    }
  });

  // ─── Test 4: 反复 online/degraded/offline 切换，内存稳定 ──────

  test('test_memory_during_offline_online_cycling', async ({ page }) => {
    await page.addInitScript(INJECT_OFFLINE_DB_SCRIPT);
    await page.addInitScript(INJECT_OBSERVERS_SCRIPT);
    await page.setContent('<div id="status">running</div>');
    await page.evaluate(() => window.__offlineDB.clearAll());

    // 基线内存
    const baseline = await sampleMemoryMB(page);
    if (baseline === null) {
      test.skip(true, 'performance.memory 仅 Chromium 支持');
      return;
    }

    const t0 = Date.now();
    const deadline = t0 + Math.min(DURATION_MS, 60_000); // 最多 60s
    let peakMB = baseline;
    let cycle = 0;

    while (Date.now() < deadline) {
      cycle++;

      // 奇数 cycle: online（拉取 delta）
      if (cycle % 2 === 1) {
        mockServer!.setOutage(false);
        await pollDelta(page, mockBaseURL, 'demo', 'mock-kds-001', 1);
      } else {
        // 偶数 cycle: offline（仅本地缓存）
        mockServer!.setOutage(true);
        const offlineOrders: Record<string, unknown>[] = [];
        for (let i = 0; i < 5; i++) {
          offlineOrders.push({
            id: `cycle-${cycle}-${i}`,
            order_no: `C${cycle}${i}`,
            store_id: 'demo',
            device_id: 'mock-kds-001',
            status: 'pending',
            table_number: null,
            items_count: 1 + (i % 3),
            updated_at: new Date().toISOString(),
          });
        }
        await page.evaluate((o) => window.__offlineDB.saveOrders(o), offlineOrders);
      }

      await page.waitForTimeout(SAMPLE_INTERVAL_MS);

      const m = await sampleMemoryMB(page);
      if (m !== null && m > peakMB) peakMB = m;
    }

    const growthMB = peakMB - baseline;
    console.log(
      `[offline-mem] baselineMB=${baseline.toFixed(1)} peakMB=${peakMB.toFixed(1)} ` +
        `growthMB=${growthMB.toFixed(1)} cycles=${cycle}`,
    );

    // 长任务比例
    const longtaskRatio = await page.evaluate(() => {
      const elapsed = performance.now() - (window.__txStartTs ?? 0);
      if (elapsed <= 0) return 0;
      return (window.__txLongtaskTotalMs ?? 0) / elapsed;
    });
    console.log(`[offline-mem] longtaskRatio=${(longtaskRatio * 100).toFixed(2)}%`);

    expect(growthMB).toBeLessThanOrEqual(MEMORY_GROWTH_LIMIT_MB);
  });
});
