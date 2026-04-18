/**
 * ConnectionContext — KDS 全局连接健康上下文（Sprint C2）
 *
 * App 根节点挂载 <ConnectionProvider>，内部使用 useConnectionHealth 聚合
 * 信号并把 { health, offlineDurationMs, reconnect } 广播给整个树。
 *
 * useOrdersCache 可选地消费 useConnectionHealthContext()，在 health !== 'online'
 * 时自动 setReadOnly(true)，recovery 时自动回到读写模式。
 *
 * 当前 WebSocket 主循环由 useKdsWebSocket / KDSBoardPage 各自管理；Provider 不
 * 持有 ws，而是通过 wsRef 观察。为简化首次接入，Provider 默认只用 navigator.onLine
 * 信号，上层若需加入 ws 观察，可直接在页面内调用 useConnectionHealth({ wsRef })
 * 并把结果 "提交" 到 context（setHealth）。目前 Step 3 只需 navigator.onLine 级别
 * 就能驱动只读 guard，后续 C3 再精化。
 */
import { createContext, useContext, useMemo, type ReactNode } from 'react';
import {
  useConnectionHealth,
  type ConnectionHealth,
} from '../hooks/useConnectionHealth';

export interface ConnectionContextValue {
  health: ConnectionHealth;
  offlineDurationMs: number;
  reconnect: () => void;
}

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const { health, offlineDurationMs, reconnect } = useConnectionHealth();
  const value = useMemo<ConnectionContextValue>(
    () => ({ health, offlineDurationMs, reconnect }),
    [health, offlineDurationMs, reconnect],
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
      offlineDurationMs: 0,
      reconnect: () => undefined,
    };
  }
  return ctx;
}
