/**
 * useConnectionHealth — KDS 连接健康检测 Hook（Sprint C2+ 强化）
 *
 * 职责：
 *   聚合三路信号得出三态 health（online / degraded / offline），供 UI 顶栏与
 *   useOrdersCache 自动降级到只读。
 *
 * 信号来源：
 *   1. wsRef.current — 传入的 WebSocket 引用
 *      • 本 hook 每 30s 发送 ping 并记录发送时刻
 *      • pong 到来时计算 latency
 *      • heartbeatTimeoutMs（默认 15s）未收到任何消息 → degraded
 *      • 30s 仍无心跳或 ws.close/error → offline
 *   2. navigator.onLine — 浏览器网络栈
 *      • online 事件 → 恢复
 *      • offline 事件 → 立即 offline
 *   3. kdsOrdersDB — 本地缓存订单数统计
 *
 * 输出（兼容旧版字段 + 新增 C2 字段）：
 *   - health:              'online' | 'degraded' | 'offline'
 *   - status:              同 health（语义别名）
 *   - isDegraded:          当 health === 'degraded' 时为 true
 *   - offlineDurationMs:   进入 offline 以来的毫秒数（online 时为 0）
 *   - latency:             最近一次 ping/pong 延迟（ms），未测量时为 -1
 *   - uptime:              本次在线连续时长（ms），offline 时为 0
 *   - cachedOrders:        本地 IndexedDB 缓存的订单数（近似）
 *   - reconnect():         触发 onStatusChange('reconnect')，供上层重建 WS
 *
 * 本 Hook 不直接创建 / 关闭 WebSocket，只观察 + 发送 ping。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { getStats } from '../db/kdsOrdersDB';

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
  /** @deprecated 改用 status */
  health: ConnectionHealth;
  /** 三态连接健康：online / degraded / offline */
  status: ConnectionHealth;
  /** 是否处于 degraded（连接不稳定但本地缓存可用） */
  isDegraded: boolean;
  /** 进入 offline 以来的毫秒数（online 时为 0） */
  offlineDurationMs: number;
  /** 最近一次 ping/pong 延迟（ms），未测量时为 -1 */
  latency: number;
  /** 本次在线连续时长（ms），offline 或 degraded 时累加到断线前 */
  uptime: number;
  /** 本地 IndexedDB 缓存的订单数 */
  cachedOrders: number;
  /** 尝试重新连接 */
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
  const [latency, setLatency] = useState(-1);
  const [uptime, setUptime] = useState(0);
  const [cachedOrders, setCachedOrders] = useState(0);

  const lastHeartbeatRef = useRef<number>(Date.now());
  const lastPingSentRef = useRef<number>(-1);
  const onlineSinceRef = useRef<number | null>(null);
  const offlineSinceRef = useRef<number | null>(null);
  const networkOnlineRef = useRef<boolean>(
    typeof navigator !== 'undefined' ? navigator.onLine !== false : true,
  );
  const prevHealthRef = useRef<ConnectionHealth>(health);
  const statusCbRef = useRef(onStatusChange);
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const latencyCheckRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    statusCbRef.current = onStatusChange;
  }, [onStatusChange]);

  // ─── 刷新缓存订单数（轮询统计） ────────────────────────────
  const refreshCachedOrders = useCallback(async () => {
    try {
      const stats = await getStats();
      setCachedOrders(stats.count);
    } catch {
      // kdsOrdersDB 不可用时（测试环境等）静默跳过
    }
  }, []);

  // ─── 核心：重算当前 health ────────────────────────────────
  const evaluate = useCallback(() => {
    const now = Date.now();
    if (!networkOnlineRef.current) {
      if (offlineSinceRef.current == null) {
        offlineSinceRef.current = now;
        onlineSinceRef.current = null;
      }
      setOfflineDurationMs(now - offlineSinceRef.current);
      setUptime(0);
      if (prevHealthRef.current !== 'offline') {
        prevHealthRef.current = 'offline';
        setHealth('offline');
      }
      return;
    }

    const ws = wsRef?.current ?? null;
    // 无 ws 对象时，仅凭 navigator.onLine 判断
    if (!ws) {
      if (onlineSinceRef.current == null) onlineSinceRef.current = now;
      offlineSinceRef.current = null;
      setOfflineDurationMs(0);
      setUptime(now - onlineSinceRef.current);
      if (prevHealthRef.current !== 'online') {
        prevHealthRef.current = 'online';
        setHealth('online');
      }
      return;
    }

    // ws 已关闭 → offline
    if (ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
      if (offlineSinceRef.current == null) {
        offlineSinceRef.current = now;
        onlineSinceRef.current = null;
      }
      setOfflineDurationMs(now - offlineSinceRef.current);
      setUptime(0);
      if (prevHealthRef.current !== 'offline') {
        prevHealthRef.current = 'offline';
        setHealth('offline');
      }
      return;
    }

    // ws 仍在连接或已 open → 根据心跳间隔分级
    const sinceHeartbeat = now - lastHeartbeatRef.current;
    if (sinceHeartbeat >= offlineTimeoutMs) {
      if (offlineSinceRef.current == null) {
        offlineSinceRef.current = now;
        onlineSinceRef.current = null;
      }
      setOfflineDurationMs(now - offlineSinceRef.current);
      setUptime(0);
      if (prevHealthRef.current !== 'offline') {
        prevHealthRef.current = 'offline';
        setHealth('offline');
      }
      return;
    }
    if (sinceHeartbeat >= heartbeatTimeoutMs) {
      if (onlineSinceRef.current == null) onlineSinceRef.current = now;
      offlineSinceRef.current = null;
      setOfflineDurationMs(0);
      setUptime(now - onlineSinceRef.current);
      if (prevHealthRef.current !== 'degraded') {
        prevHealthRef.current = 'degraded';
        setHealth('degraded');
      }
      return;
    }

    if (onlineSinceRef.current == null) onlineSinceRef.current = now;
    offlineSinceRef.current = null;
    setOfflineDurationMs(0);
    setUptime(now - onlineSinceRef.current);
    if (prevHealthRef.current !== 'online') {
      prevHealthRef.current = 'online';
      setHealth('online');
    }
  }, [wsRef, heartbeatTimeoutMs, offlineTimeoutMs]);

  // health 变化触发回调 + 刷缓存订单数
  useEffect(() => {
    statusCbRef.current?.(health);
    // 状态变化时刷新缓存计数
    refreshCachedOrders();
  }, [health, refreshCachedOrders]);

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
      // 收到 pong → 计算延迟
      if (ev.data === 'pong') {
        if (lastPingSentRef.current > 0) {
          setLatency(Date.now() - lastPingSentRef.current);
        }
      }
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

  // ─── 每 30s 发送 ping + 计算 latency ─────────────────────
  useEffect(() => {
    const ws = wsRef?.current ?? null;
    if (!ws) return;

    // 清理旧 interval
    if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);

    pingIntervalRef.current = setInterval(() => {
      const wss = wsRef?.current;
      if (wss && wss.readyState === WebSocket.OPEN) {
        lastPingSentRef.current = Date.now();
        try {
          wss.send('ping');
        } catch {
          // WS 可能在发送瞬间关闭
        }
      }
    }, 30_000);

    return () => {
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }
    };
  }, [wsRef]);

  // ─── 每 10s 刷新缓存订单数（低频率避免 IDB 竞争） ─────────
  useEffect(() => {
    refreshCachedOrders();
    const interval = setInterval(refreshCachedOrders, 10_000);
    return () => clearInterval(interval);
  }, [refreshCachedOrders]);

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

  return {
    health,
    status: health,
    isDegraded: health === 'degraded',
    offlineDurationMs,
    latency,
    uptime,
    cachedOrders,
    reconnect,
  };
}
