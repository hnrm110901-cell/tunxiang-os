/**
 * useOrdersCache — KDS 本地订单缓存 Hook（C1）
 *
 * 职责：
 *   - mount 时从 IDB hydrate 到内存
 *   - 对外暴露 upsert / getLastN / stats
 *   - 只读模式（断网健康检查尚未接入前手动控制，C2 将接 WebSocket health）
 *
 * 不在本次范围：
 *   - WebSocket 订阅 / 增量同步（留给 C2/C3）
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  upsertOrder as dbUpsertOrder,
  getAll as dbGetAll,
  getStats as dbGetStats,
  type KdsCachedOrder,
  type CacheStats,
} from '../db/kdsOrdersDB';
import { isFeatureEnabled } from '../config/featureFlags';

export interface UseOrdersCacheReturn {
  orders: KdsCachedOrder[];
  hydrating: boolean;
  readOnly: boolean;
  setReadOnly: (v: boolean) => void;
  upsert: (order: KdsCachedOrder) => Promise<void>;
  getLastN: (n: number) => KdsCachedOrder[];
  refresh: () => Promise<void>;
  stats: CacheStats | null;
}

export function useOrdersCache(): UseOrdersCacheReturn {
  const enabled = isFeatureEnabled('edge.kds.local_cache.enable');
  const [orders, setOrders] = useState<KdsCachedOrder[]>([]);
  const [hydrating, setHydrating] = useState(true);
  const [readOnly, setReadOnly] = useState(false);
  const [stats, setStats] = useState<CacheStats | null>(null);
  const mountedRef = useRef(true);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    const [all, s] = await Promise.all([dbGetAll(), dbGetStats()]);
    if (!mountedRef.current) return;
    setOrders(all);
    setStats(s);
  }, [enabled]);

  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) {
      setHydrating(false);
      return () => { mountedRef.current = false; };
    }
    (async () => {
      await refresh();
      if (mountedRef.current) setHydrating(false);
    })();
    return () => { mountedRef.current = false; };
  }, [enabled, refresh]);

  const upsert = useCallback(async (order: KdsCachedOrder): Promise<void> => {
    if (!enabled || readOnly) return;
    await dbUpsertOrder(order);
    await refresh();
  }, [enabled, readOnly, refresh]);

  const getLastN = useCallback((n: number): KdsCachedOrder[] => {
    return [...orders]
      .sort((a, b) => b.created_at - a.created_at)
      .slice(0, n);
  }, [orders]);

  return {
    orders,
    hydrating,
    readOnly,
    setReadOnly,
    upsert,
    getLastN,
    refresh,
    stats,
  };
}
