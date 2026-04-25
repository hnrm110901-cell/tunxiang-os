/**
 * Tier 2 — kdsOrderCache.ts vitest 覆盖
 *
 * 场景命名贴近徐记海鲜后厨真实操作：
 *   - hydrate: 后厨开机，从 IDB 拉出最近 100 单
 *   - upsert / upsertBatch: 主厨完成 / KDS 推送增量
 *   - 容量淘汰: 早高峰 200 单冲入，按 updatedAt 旧→新淘汰
 *   - 多 store 隔离: 17 号店与 18 号店同台 KDS 总部预览，互不污染
 *   - size / getApproxSizeBytes: 离线 4h 缓存大小自检 < 20MB
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
  hydrate,
  upsert,
  upsertBatch,
  evictOlderThan,
  clear,
  size,
  getApproxSizeBytes,
  MAX_ORDERS_PER_PARTITION,
  __resetForTest,
} from '../kdsOrderCache';
import {
  installFakeIndexedDB,
  resetFakeIndexedDB,
} from '../../db/__tests__/fakeIndexedDB';
import type { KDSDeltaOrder } from '../../api/kdsDeltaApi';

const TENANT_A = '00000000-0000-0000-0000-000000000aaa';
const TENANT_B = '00000000-0000-0000-0000-000000000bbb';
const STORE_17 = '00000000-0000-0000-0000-000000000017';
const STORE_18 = '00000000-0000-0000-0000-000000000018';

function mkOrder(
  id: string,
  updatedAtMs: number,
  opts: Partial<KDSDeltaOrder> = {},
): KDSDeltaOrder {
  return {
    tenant_id: TENANT_A,
    id,
    order_no: `NO-${id}`,
    store_id: STORE_17,
    status: 'preparing',
    table_number: 'A1',
    updated_at: new Date(updatedAtMs).toISOString(),
    items_count: 3,
    ...opts,
  };
}

describe('kdsOrderCache — IndexedDB last-100 缓存', () => {
  beforeEach(() => {
    installFakeIndexedDB();
    resetFakeIndexedDB();
    __resetForTest();
  });

  afterEach(() => {
    resetFakeIndexedDB();
    __resetForTest();
  });

  it('hydrate: 后厨开机从 IDB 拉出指定 (tenant,store) 分区的最新 100 单', async () => {
    const now = Date.now();
    const orders = Array.from({ length: 50 }, (_, i) =>
      mkOrder(`o${i}`, now + i * 1000),
    );
    await upsertBatch(orders);
    const hydrated = await hydrate(TENANT_A, STORE_17);
    expect(hydrated).toHaveLength(50);
    // 最新在前
    expect(hydrated[0].id).toBe('o49');
    expect(hydrated[49].id).toBe('o0');
  });

  it('upsert: 同 orderId 仅在 updatedAt 更新时覆盖', async () => {
    const t0 = 1000;
    await upsert(mkOrder('x1', t0, { status: 'pending' }));
    await upsert(mkOrder('x1', t0 + 5_000, { status: 'preparing' }));
    // 旧版本 (t0) 来覆盖新版本应被忽略
    await upsert(mkOrder('x1', t0, { status: 'pending' }));
    const all = await hydrate(TENANT_A, STORE_17);
    expect(all).toHaveLength(1);
    expect(all[0].status).toBe('preparing');
  });

  it('容量淘汰: 早高峰 200 单冲入，按 updatedAt 旧→新淘汰，仅保留 100 条', async () => {
    const base = Date.now();
    const burst = Array.from({ length: 200 }, (_, i) => mkOrder(`b${i}`, base + i));
    await upsertBatch(burst);
    const hydrated = await hydrate(TENANT_A, STORE_17);
    expect(hydrated).toHaveLength(MAX_ORDERS_PER_PARTITION);
    // 应保留最新的 100 条 (b100..b199)
    const ids = hydrated.map((o) => o.id);
    expect(ids).toContain('b199');
    expect(ids).not.toContain('b0');
    expect(ids).not.toContain('b99');
  });

  it('多 store 隔离: 17 号店 hydrate 不返回 18 号店订单', async () => {
    const base = Date.now();
    await upsertBatch([
      mkOrder('s17a', base, { store_id: STORE_17 }),
      mkOrder('s17b', base + 1, { store_id: STORE_17 }),
      mkOrder('s18a', base, { store_id: STORE_18 }),
    ]);
    const at17 = await hydrate(TENANT_A, STORE_17);
    const at18 = await hydrate(TENANT_A, STORE_18);
    expect(at17.map((o) => o.id).sort()).toEqual(['s17a', 's17b']);
    expect(at18.map((o) => o.id)).toEqual(['s18a']);
  });

  it('多租户隔离: 总部多品牌时 tenant_A 不污染 tenant_B', async () => {
    const t = Date.now();
    await upsertBatch([
      mkOrder('a1', t, { tenant_id: TENANT_A }),
      mkOrder('b1', t, { tenant_id: TENANT_B, store_id: STORE_17 }),
    ]);
    const ha = await hydrate(TENANT_A, STORE_17);
    const hb = await hydrate(TENANT_B, STORE_17);
    expect(ha.map((o) => o.id)).toEqual(['a1']);
    expect(hb.map((o) => o.id)).toEqual(['b1']);
  });

  it('clear: 切店时清空 17 号店分区，18 号店保留', async () => {
    const t = Date.now();
    await upsertBatch([
      mkOrder('keep18', t, { store_id: STORE_18 }),
      mkOrder('drop17', t, { store_id: STORE_17 }),
    ]);
    await clear(TENANT_A, STORE_17);
    const at17 = await hydrate(TENANT_A, STORE_17);
    const at18 = await hydrate(TENANT_A, STORE_18);
    expect(at17).toHaveLength(0);
    expect(at18).toHaveLength(1);
  });

  it('evictOlderThan: 回收 4h 前的旧单（跨分区扫描）', async () => {
    const now = Date.now();
    const fourHrs = 4 * 60 * 60 * 1000;
    await upsertBatch([
      mkOrder('old', now - fourHrs - 1, { store_id: STORE_17 }),
      mkOrder('fresh', now - 1000, { store_id: STORE_17 }),
      mkOrder('old18', now - fourHrs - 1, { store_id: STORE_18 }),
    ]);
    const removed = await evictOlderThan(now - fourHrs);
    expect(removed).toBe(2);
    expect(await size()).toBe(1);
  });

  it('size: 全库总条数等于各分区合计', async () => {
    const t = Date.now();
    await upsertBatch([
      mkOrder('a', t, { store_id: STORE_17 }),
      mkOrder('b', t + 1, { store_id: STORE_17 }),
      mkOrder('c', t, { store_id: STORE_18 }),
    ]);
    expect(await size()).toBe(3);
  });

  it('getApproxSizeBytes: 100 单 × 1 分区远小于 20MB（4h 离线门禁）', async () => {
    const t = Date.now();
    const orders = Array.from({ length: 100 }, (_, i) =>
      mkOrder(`o${i}`, t + i, {
        order_metadata: {
          // 模拟 KDS 视角的 items 列表（剔除敏感字段后剩余有效负载）
          items: Array.from({ length: 5 }, (_, j) => ({
            dish_name: `菜品 ${i}-${j}`,
            quantity: (j % 3) + 1,
            notes: '少辣',
          })),
        },
      }),
    );
    await upsertBatch(orders);
    const bytes = await getApproxSizeBytes();
    expect(bytes).toBeLessThan(20 * 1024 * 1024);
    // 也应该非零（避免空实现误通过）
    expect(bytes).toBeGreaterThan(0);
  });

  it('upsertBatch: 同批次有重复 orderId 时取 updatedAt 最大', async () => {
    const t = Date.now();
    await upsertBatch([
      mkOrder('dup', t, { status: 'pending' }),
      mkOrder('dup', t + 5000, { status: 'preparing' }),
      mkOrder('dup', t + 1000, { status: 'confirmed' }),
    ]);
    const all = await hydrate(TENANT_A, STORE_17);
    expect(all).toHaveLength(1);
    expect(all[0].status).toBe('preparing');
  });
});
