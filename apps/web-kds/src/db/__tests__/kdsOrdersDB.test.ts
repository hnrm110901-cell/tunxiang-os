/**
 * Tier 1: KDS 本地订单缓存（IndexedDB last-100-orders）
 * 场景：徐记海鲜后厨断网期间厨师依赖本地缓存出品。
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
  upsertOrder,
  upsertBatch,
  getAll,
  clear,
  clearAll,
  getStats,
  getByStatus,
  getByDevice,
  checkQuota,
  __forceMemoryFallback,
  __resetDBForTest,
  type KdsCachedOrder,
  type KdsOrderStatus,
} from '../kdsOrdersDB';
import {
  installFakeIndexedDB,
  resetFakeIndexedDB,
  disableFakeIndexedDB,
} from './fakeIndexedDB';

function mkOrder(id: string, createdAt: number, status: KdsCachedOrder['status'] = 'pending'): KdsCachedOrder {
  return {
    order_id: id,
    order_no: `NO-${id}`,
    table_no: 'A1',
    items: [{ name: '红烧肉', qty: 1, notes: '' }],
    status,
    created_at: createdAt,
    updated_at: createdAt,
    station_id: 's1',
    device_id: 'kds-dev-001',
  };
}

describe('kdsOrdersDB — IndexedDB 存储层', () => {
  beforeEach(async () => {
    installFakeIndexedDB();
    resetFakeIndexedDB();
    __resetDBForTest();
    await clear();
  });

  afterEach(() => {
    resetFakeIndexedDB();
    __resetDBForTest();
  });

  it('开新 IDB 写入 10 单后读取完整列表', async () => {
    const now = Date.now();
    for (let i = 0; i < 10; i++) {
      await upsertOrder(mkOrder(`o${i}`, now + i));
    }
    const all = await getAll();
    expect(all.length).toBe(10);
    const ids = all.map((o) => o.order_id).sort();
    expect(ids).toEqual(['o0', 'o1', 'o2', 'o3', 'o4', 'o5', 'o6', 'o7', 'o8', 'o9']);
  });

  it('超过 100 单时自动 LRU 淘汰最老已完成单', async () => {
    const now = Date.now();
    // 先写 50 张已完成的老单
    const completed = Array.from({ length: 50 }, (_, i) =>
      mkOrder(`done-${i}`, now - 1_000_000 + i, 'completed'),
    );
    await upsertBatch(completed);
    // 再写 60 张较新 pending 单（总数 110，触发 LRU）
    const pending = Array.from({ length: 60 }, (_, i) =>
      mkOrder(`pend-${i}`, now + i, 'pending'),
    );
    await upsertBatch(pending);

    const stats = await getStats();
    expect(stats.count).toBeLessThanOrEqual(100);

    const all = await getAll();
    // 应优先淘汰最老的 completed
    const survivingCompleted = all.filter((o) => o.status === 'completed').length;
    expect(survivingCompleted).toBeLessThan(50);
    // pending 单应全部保留
    const survivingPending = all.filter((o) => o.status === 'pending').length;
    expect(survivingPending).toBe(60);
  });

  it('同一 order_id 多次 upsert 取 updated_at 最新', async () => {
    const base = mkOrder('o1', 1000);
    await upsertOrder(base);
    await upsertOrder({ ...base, updated_at: 2000, status: 'cooking' });
    await upsertOrder({ ...base, updated_at: 1500, status: 'pending' }); // 老的不覆盖
    const all = await getAll();
    expect(all.length).toBe(1);
    expect(all[0].status).toBe('cooking');
    expect(all[0].updated_at).toBe(2000);
  });

  it('隐私模式/IDB 不可用时降级到内存 Map', async () => {
    disableFakeIndexedDB();
    __resetDBForTest();
    __forceMemoryFallback();

    const order = mkOrder('mem-1', Date.now());
    await upsertOrder(order);
    const all = await getAll();
    expect(all.length).toBe(1);
    expect(all[0].order_id).toBe('mem-1');

    const stats = await getStats();
    expect(stats.count).toBe(1);
    expect(stats.mode === 'memory').toBe(true);
  });

  it('IDB 读写并发不冲突（同时 upsertBatch + getAll）', async () => {
    const now = Date.now();
    const batch = Array.from({ length: 20 }, (_, i) => mkOrder(`c${i}`, now + i));
    const write = upsertBatch(batch);
    const read1 = getAll();
    const read2 = getAll();
    await Promise.all([write, read1, read2]);
    const final = await getAll();
    expect(final.length).toBe(20);
  });

  it('清空 IDB 后 getAll 返回空数组', async () => {
    await upsertBatch([mkOrder('a', 1), mkOrder('b', 2), mkOrder('c', 3)]);
    expect((await getAll()).length).toBe(3);
    await clear();
    expect(await getAll()).toEqual([]);
    const stats = await getStats();
    expect(stats.count).toBe(0);
  });

  // ─── C1+ 新增方法 ─────────────────────────────────────────

  describe('getByStatus — 按状态筛选', () => {
    it('返回 pending 状态的订单', async () => {
      const now = Date.now();
      await upsertBatch([
        mkOrder('a', now, 'pending'),
        mkOrder('b', now + 1, 'cooking'),
        mkOrder('c', now + 2, 'completed'),
        mkOrder('d', now + 3, 'pending'),
      ]);
      const pending = await getByStatus('pending');
      expect(pending.length).toBe(2);
      expect(pending.map((o) => o.order_id).sort()).toEqual(['a', 'd']);
    });

    it('没有匹配状态时返回空数组', async () => {
      await upsertBatch([
        mkOrder('a', 1, 'completed'),
        mkOrder('b', 2, 'completed'),
      ]);
      const cancelled = await getByStatus('cancelled');
      expect(cancelled).toEqual([]);
    });
  });

  describe('getByDevice — 按设备筛选', () => {
    it('返回指定设备的订单', async () => {
      const now = Date.now();
      await upsertBatch([
        { ...mkOrder('a', now), device_id: 'kds-fry-01' },
        { ...mkOrder('b', now + 1), device_id: 'kds-grill-02' },
        { ...mkOrder('c', now + 2), device_id: 'kds-fry-01' },
      ]);
      const fryOrders = await getByDevice('kds-fry-01');
      expect(fryOrders.length).toBe(2);
      expect(fryOrders.map((o) => o.order_id).sort()).toEqual(['a', 'c']);
    });
  });

  describe('clearAll — 清空全部缓存', () => {
    it('clearAll 后存储为空', async () => {
      await upsertBatch([
        mkOrder('a', 1),
        mkOrder('b', 2),
        mkOrder('c', 3),
      ]);
      expect((await getAll()).length).toBe(3);
      await clearAll();
      expect(await getAll()).toEqual([]);
    });

    it('clearAll 与 clear 行为一致', async () => {
      await upsertBatch([mkOrder('x', 1), mkOrder('y', 2)]);
      await clearAll();
      await clear();
      // 两次清空后仍是空
      expect(await getAll()).toEqual([]);
    });
  });

  describe('checkQuota — 存储配额检查', () => {
    it('返回 usage >= 0 且 limit > 0', async () => {
      await upsertBatch([
        mkOrder('q1', 1000),
        mkOrder('q2', 2000),
        mkOrder('q3', 3000),
      ]);
      const quota = await checkQuota();
      expect(quota.usage).toBeGreaterThan(0);
      expect(quota.limit).toBeGreaterThan(0);
    });

    it('空存储时 usage = 0', async () => {
      await clear();
      const quota = await checkQuota();
      expect(quota.usage).toBe(0);
      expect(quota.limit).toBeGreaterThan(0);
    });
  });
});
