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
  getStats,
  __forceMemoryFallback,
  __resetDBForTest,
  type KdsCachedOrder,
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
});
