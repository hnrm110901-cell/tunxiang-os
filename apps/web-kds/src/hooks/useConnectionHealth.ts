/**
 * useConnectionHealth — KDS 连接健康检测 Hook（Sprint C2）
 *
 * 职责：
 *   聚合两路信号得出三态 health（online / degraded / offline），供 UI 顶栏与
 *   useOrdersCache 自动降级到只读。
 *
 * 信号来源：
 *   1. wsRef.current — 传入的 WebSocket 引用
 *      • 任一非 pong 的 message（或 pong）均视作心跳
 *      • heartbeatTimeoutMs（默认 15s）未收到消息 → degraded
 *      • 30s 仍无心跳或 ws.close/error → offline
 *   2. navigator.onLine — 浏览器网络栈
 *      • online 事件 → 恢复
 *      • offline 事件 → 立即 offline
 *
 * 输出：
 *   - health:               'online' | 'degraded' | 'offline'
 *   - offlineDurationMs:    进入 offline 以来的毫秒数（online 时为 0）
 *   - reconnect():          触发 onStatusChange('reconnect')，供上层重建 WS
 *
 * 本 Hook 不直接创建 / 关闭 WebSocket，只观察。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export type ConnectionHealth = 'online' | 'degraded' | 'offline';

export interface UseConnectionHealthOptions {
  /** WebSocket 引用（可选），不传则仅用 navigator.onLine */
  wsRef?: React.RefObject<WebSocket | null>;
  /** 心跳超时阈值（ms），默认 15_000 */
  heartbeatTimeoutMs?: number;
  /** offline 升级阈值（ms），从 degraded 开始计时，默认 30_000 */
  offlineTimeoutMs?: number;
  /** health 变化回调 */
  onStatusChange?: (health: ConnectionHealth | 'reconnect') => void;
}

export interface UseConnectionHealthReturn {
  health: ConnectionHealth;
  offlineDurationMs: number;
  reconnect: () => void;
}

export function useConnectionHealth(
  options: UseConnectionHealthOptions = {},
): UseConnectionHealthReturn {
  const {
    wsRef,
    heartbeatTimeoutMs = 15_000,
    offlineTimeoutMs = 30_000,
    onStatusChange,
  } = options;

  const [health, setHealth] = useState<ConnectionHealth>(() =>
    typeof navigator !== 'undefined' && navigator.onLine === false
      ? 'offline'
      : 'online',
  );
  const [offlineDurationMs, setOfflineDurationMs] = useState(0);

  const lastHeartbeatRef = useRef<number>(Date.now());
  const offlineSinceRef = useRef<number | null>(null);
  const networkOnlineRef = useRef<boolean>(
    typeof navigator !== 'undefined' ? navigator.onLine !== false : true,
  );
  const prevHealthRef = useRef<ConnectionHealth>(health);
  const statusCbRef = useRef(onStatusChange);

  useEffect(() => {
    statusCbRef.current = onStatusChange;
  }, [onStatusChange]);

  // ─── 核心：重算当前 health ────────────────────────────────
  const evaluate = useCallback(() => {
    const now = Date.now();
    if (!networkOnlineRef.current) {
      if (offlineSinceRef.current == null) offlineSinceRef.current = now;
      setOfflineDurationMs(now - offlineSinceRef.current);
      if (prevHealthRef.current !== 'offline') {
        prevHealthRef.current = 'offline';
        setHealth('offline');
      }
      return;
    }

    const ws = wsRef?.current ?? null;
    // 无 ws 对象时，仅凭 navigator.onLine 判断
    if (!ws) {
      offlineSinceRef.current = null;
      setOfflineDurationMs(0);
      if (prevHealthRef.current !== 'online') {
        prevHealthRef.current = 'online';
        setHealth('online');
      }
      return;
    }

    // ws 已关闭 → offline
    if (ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
      if (offlineSinceRef.current == null) offlineSinceRef.current = now;
      setOfflineDurationMs(now - offlineSinceRef.current);
      if (prevHealthRef.current !== 'offline') {
        prevHealthRef.current = 'offline';
        setHealth('offline');
      }
      return;
    }

    // ws 仍在连接或已 open → 根据心跳间隔分级
    const sinceHeartbeat = now - lastHeartbeatRef.current;
    if (sinceHeartbeat >= offlineTimeoutMs) {
      if (offlineSinceRef.current == null) offlineSinceRef.current = now;
      setOfflineDurationMs(now - offlineSinceRef.current);
      if (prevHealthRef.current !== 'offline') {
        prevHealthRef.current = 'offline';
        setHealth('offline');
      }
      return;
    }
    if (sinceHeartbeat >= heartbeatTimeoutMs) {
      offlineSinceRef.current = null;
      setOfflineDurationMs(0);
      if (prevHealthRef.current !== 'degraded') {
        prevHealthRef.current = 'degraded';
        setHealth('degraded');
      }
      return;
    }

    offlineSinceRef.current = null;
    setOfflineDurationMs(0);
    if (prevHealthRef.current !== 'online') {
      prevHealthRef.current = 'online';
      setHealth('online');
    }
  }, [wsRef, heartbeatTimeoutMs, offlineTimeoutMs]);

  // health 变化触发回调
  useEffect(() => {
    statusCbRef.current?.(health);
  }, [health]);

  // ─── 绑定 WebSocket message / close / error ───────────────
  useEffect(() => {
    const ws = wsRef?.current ?? null;
    if (!ws) return;

    // 保存已有 handler，装饰后恢复
    const prevOnMessage = ws.onmessage;
    const prevOnClose = ws.onclose;
    const prevOnError = ws.onerror;
    const prevOnOpen = ws.onopen;

    ws.onmessage = (ev: MessageEvent) => {
      lastHeartbeatRef.current = Date.now();
      evaluate();
      prevOnMessage?.call(ws, ev);
    };
    ws.onopen = (ev: Event) => {
      lastHeartbeatRef.current = Date.now();
      evaluate();
      prevOnOpen?.call(ws, ev);
    };
    ws.onclose = (ev: CloseEvent) => {
      evaluate();
      prevOnClose?.call(ws, ev);
    };
    ws.onerror = (ev: Event) => {
      evaluate();
      prevOnError?.call(ws, ev);
    };

    return () => {
      // 只还原我们替换过的引用（若仍是我们设置的）
      if (ws.onmessage && typeof ws.onmessage === 'function') ws.onmessage = prevOnMessage;
      if (ws.onclose && typeof ws.onclose === 'function') ws.onclose = prevOnClose;
      if (ws.onerror && typeof ws.onerror === 'function') ws.onerror = prevOnError;
      if (ws.onopen && typeof ws.onopen === 'function') ws.onopen = prevOnOpen;
    };
  }, [wsRef, evaluate]);

  // ─── navigator online/offline ────────────────────────────
  useEffect(() => {
    const handleOnline = () => {
      networkOnlineRef.current = true;
      // 浏览器报告网络恢复 → 视为一次心跳（允许 WS 重新计时）
      lastHeartbeatRef.current = Date.now();
      evaluate();
    };
    const handleOffline = () => {
      networkOnlineRef.current = false;
      evaluate();
    };
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, [evaluate]);

  // ─── 周期性 tick（检查心跳超时 + 更新 offline 计时） ─────
  useEffect(() => {
    const interval = setInterval(evaluate, 1000);
    return () => clearInterval(interval);
  }, [evaluate]);

  const reconnect = useCallback(() => {
    lastHeartbeatRef.current = Date.now();
    statusCbRef.current?.('reconnect');
    evaluate();
  }, [evaluate]);

  return { health, offlineDurationMs, reconnect };
}
