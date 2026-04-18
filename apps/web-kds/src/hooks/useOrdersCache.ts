/**
 * useOrdersCache — KDS 本地订单缓存 Hook（C1 + C2 自动降级）
 *
 * 职责：
 *   - mount 时从 IDB hydrate 到内存
 *   - 对外暴露 upsert / getLastN / stats
 *   - 只读模式：
 *       * 手动 setReadOnly 仍保留（单元测试与覆盖场景使用）
 *       * 挂载了 ConnectionProvider 时，health !== 'online' 自动 readOnly=true，
 *         health=online 自动 readOnly=false；手动 setReadOnly 优先级最高
 *
 * 不在本次范围：
 *   - WebSocket 增量同步（留给 C3）
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
import { useConnection } from '../contexts/ConnectionContext';

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
  // 手动 override：undefined 表示跟随连接健康；true/false 为强制覆盖
  const [manualReadOnly, setManualReadOnly] = useState<boolean | undefined>(
    undefined,
  );
  const [stats, setStats] = useState<CacheStats | null>(null);
  const mountedRef = useRef(true);

  // 来自 ConnectionProvider 的健康状态（未挂载时默认 online）
  const { health } = useConnection();
  const autoReadOnly = health !== 'online';
  const readOnly = manualReadOnly !== undefined ? manualReadOnly : autoReadOnly;

  const setReadOnly = useCallback((v: boolean) => {
    setManualReadOnly(v);
  }, []);

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
