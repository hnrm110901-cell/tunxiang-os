/**
 * ConnectionContext — KDS 全局连接健康上下文（Sprint C2 / C2+）
 *
 * App 根节点挂载 <ConnectionProvider>，内部使用 useConnectionHealth 聚合
 * 信号并把 { health, status, isDegraded, latency, uptime, cachedOrders,
 * offlineDurationMs, reconnect } 广播给整个树。
 *
 * useOrdersCache 可选地消费 useConnectionHealthContext()，在 health !== 'online'
 * 时自动 setReadOnly(true)，recovery 时自动回到读写模式。
 */
import { createContext, useContext, useMemo, type ReactNode } from 'react';
import {
  useConnectionHealth,
  type ConnectionHealth,
} from '../hooks/useConnectionHealth';

export interface ConnectionContextValue {
  /** @deprecated 改用 status */
  health: ConnectionHealth;
  /** 三态连接健康：online / degraded / offline */
  status: ConnectionHealth;
  /** 是否处于 degraded */
  isDegraded: boolean;
  /** 进入 offline 以来的毫秒数（online 时为 0） */
  offlineDurationMs: number;
  /** 最近一次 ping/pong 延迟（ms），未测量时为 -1 */
  latency: number;
  /** 本次在线连续时长（ms） */
  uptime: number;
  /** 本地 IndexedDB 缓存的订单数（近似） */
  cachedOrders: number;
  /** 尝试重新连接 */
  reconnect: () => void;
}

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const { health, status, isDegraded, offlineDurationMs, latency, uptime, cachedOrders, reconnect } =
    useConnectionHealth();
  const value = useMemo<ConnectionContextValue>(
    () => ({ health, status, isDegraded, offlineDurationMs, latency, uptime, cachedOrders, reconnect }),
    [health, status, isDegraded, offlineDurationMs, latency, uptime, cachedOrders, reconnect],
  );
  return (
    <ConnectionContext.Provider value={value}>
      {children}
    </ConnectionContext.Provider>
  );
}

export function useConnection(): ConnectionContextValue {
  const ctx = useContext(ConnectionContext);
  if (!ctx) {
    // Provider 未挂载：退化为 online（避免测试/孤立渲染崩溃）
    return {
      health: 'online',
      status: 'online',
      isDegraded: false,
      offlineDurationMs: 0,
      latency: -1,
      uptime: 0,
      cachedOrders: 0,
      reconnect: () => undefined,
    };
  }
  return ctx;
}
