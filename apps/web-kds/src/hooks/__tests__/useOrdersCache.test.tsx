/**
 * Tier 1: useOrdersCache hook — IDB hydrate + upsert + 订阅者通知
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useOrdersCache } from '../useOrdersCache';
import {
  upsertBatch,
  clear,
  __resetDBForTest,
  type KdsCachedOrder,
} from '../../db/kdsOrdersDB';
import {
  installFakeIndexedDB,
  resetFakeIndexedDB,
} from '../../db/__tests__/fakeIndexedDB';

function mkOrder(id: string, createdAt: number, status: KdsCachedOrder['status'] = 'pending'): KdsCachedOrder {
  return {
    order_id: id,
    order_no: `NO-${id}`,
    table_no: 'A1',
    items: [{ name: '清蒸鱼', qty: 1, notes: '' }],
    status,
    created_at: createdAt,
    updated_at: createdAt,
    station_id: 's1',
    device_id: 'kds-dev-001',
  };
}

describe('useOrdersCache — KDS 本地缓存 Hook', () => {
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

  it('mount 时从 IDB hydrate 到内存', async () => {
    await upsertBatch([
      mkOrder('o1', 1000),
      mkOrder('o2', 2000),
      mkOrder('o3', 3000),
    ]);
    const { result } = renderHook(() => useOrdersCache());
    await waitFor(() => expect(result.current.hydrating).toBe(false));
    expect(result.current.orders.length).toBe(3);
    const ids = result.current.orders.map((o) => o.order_id).sort();
    expect(ids).toEqual(['o1', 'o2', 'o3']);
  });

  it('WebSocket 收到新单自动 upsert 到 IDB + 通知订阅者', async () => {
    const { result } = renderHook(() => useOrdersCache());
    await waitFor(() => expect(result.current.hydrating).toBe(false));
    await act(async () => {
      await result.current.upsert(mkOrder('ws-new', Date.now()));
    });
    expect(result.current.orders.find((o) => o.order_id === 'ws-new')).toBeDefined();
  });

  it('connection health 从 online→offline 时停止写 IDB 但保留读', async () => {
    const { result } = renderHook(() => useOrdersCache());
    await waitFor(() => expect(result.current.hydrating).toBe(false));
    // 写入一张
    await act(async () => {
      await result.current.upsert(mkOrder('on-1', 1000));
    });
    // 切到 offline 后调用 upsert 不应报错，读仍然返回已有数据
    act(() => {
      result.current.setReadOnly(true);
    });
    await act(async () => {
      await result.current.upsert(mkOrder('off-1', 2000));
    });
    // 读仍可用
    expect(result.current.orders.length).toBeGreaterThanOrEqual(1);
    // 只读模式下新单不进内存
    expect(result.current.orders.find((o) => o.order_id === 'off-1')).toBeUndefined();
  });

  it('getLastN(50) 返回按 created_at 降序的最近 50 单', async () => {
    const now = Date.now();
    const batch = Array.from({ length: 70 }, (_, i) => mkOrder(`o${i}`, now + i));
    await upsertBatch(batch);
    const { result } = renderHook(() => useOrdersCache());
    await waitFor(() => expect(result.current.hydrating).toBe(false));
    const last50 = result.current.getLastN(50);
    expect(last50.length).toBe(50);
    // 最新的在前
    expect(last50[0].created_at).toBeGreaterThan(last50[49].created_at);
  });

  it('订单状态更新触发 React 重渲（hook 返回新引用）', async () => {
    await upsertBatch([mkOrder('o1', 1000, 'pending')]);
    const { result } = renderHook(() => useOrdersCache());
    await waitFor(() => expect(result.current.hydrating).toBe(false));
    const firstRef = result.current.orders;
    await act(async () => {
      await result.current.upsert({
        ...mkOrder('o1', 1000, 'cooking'),
        updated_at: 2000,
      });
    });
    expect(result.current.orders).not.toBe(firstRef);
    expect(result.current.orders.find((o) => o.order_id === 'o1')?.status).toBe('cooking');
  });
});
