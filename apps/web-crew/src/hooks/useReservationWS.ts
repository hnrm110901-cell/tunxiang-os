/**
 * useReservationWS — 预订实时推送 WebSocket Hook
 *
 * 连接路径：/api/v1/booking/ws/{storeId}
 * 心跳：每 25 秒发送 "ping"，服务端回 "pong"。
 * 断线重连：5 秒后自动重连。
 * WS 降级：connect 失败时调用 onFallback() 通知页面启用轮询。
 */
import { useEffect, useRef, useCallback } from 'react';

// ─── 消息类型 ─────────────────────────────────────────────────────────────────

export interface ReservationWSMessage {
  type: 'new_reservation' | 'reservation_updated' | 'reservation_cancelled';
  reservation: Record<string, unknown>;
  source: string;
  timestamp: string;
}

// ─── Hook 参数 ────────────────────────────────────────────────────────────────

export interface UseReservationWSOptions {
  storeId: string;
  onMessage: (msg: ReservationWSMessage) => void;
  /** WS 连接状态变化回调 */
  onStatusChange?: (connected: boolean) => void;
  /** WS 连接失败（多次）时触发，通知页面降级到轮询 */
  onFallback?: () => void;
  /** 是否启用（默认 true）*/
  enabled?: boolean;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useReservationWS({
  storeId,
  onMessage,
  onStatusChange,
  onFallback,
  enabled = true,
}: UseReservationWSOptions): void {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const failCountRef = useRef(0);
  // 使用 ref 存 callback，避免 connect 闭包因 deps 变化重建
  const onMessageRef = useRef(onMessage);
  const onStatusChangeRef = useRef(onStatusChange);
  const onFallbackRef = useRef(onFallback);

  useEffect(() => { onMessageRef.current = onMessage; }, [onMessage]);
  useEffect(() => { onStatusChangeRef.current = onStatusChange; }, [onStatusChange]);
  useEffect(() => { onFallbackRef.current = onFallback; }, [onFallback]);

  const connect = useCallback(() => {
    if (!enabled || !storeId) return;

    // 构造 WebSocket URL：从 VITE_API_BASE_URL 或 window.__TX_API_BASE__ 读取
    const apiBase =
      (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
      ((window as Window & { __TX_API_BASE__?: string }).__TX_API_BASE__) ||
      '';

    const wsUrl =
      apiBase.replace(/^https/, 'wss').replace(/^http/, 'ws') +
      `/api/v1/booking/ws/${encodeURIComponent(storeId)}`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      failCountRef.current = 0;
      onStatusChangeRef.current?.(true);

      // 每 25 秒发送心跳
      pingTimerRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, 25000);
    };

    ws.onmessage = (event: MessageEvent<string>) => {
      if (event.data === 'pong') return;
      try {
        const msg = JSON.parse(event.data) as ReservationWSMessage;
        onMessageRef.current(msg);
      } catch {
        // 忽略非 JSON 帧
      }
    };

    ws.onclose = () => {
      if (pingTimerRef.current) {
        clearInterval(pingTimerRef.current);
        pingTimerRef.current = null;
      }
      onStatusChangeRef.current?.(false);

      failCountRef.current += 1;

      // 连续失败 5 次触发降级
      if (failCountRef.current >= 5) {
        onFallbackRef.current?.();
        return;
      }

      // 5 秒后重连
      reconnectTimerRef.current = setTimeout(connect, 5000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [storeId, enabled]);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
      wsRef.current = null;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (pingTimerRef.current) {
        clearInterval(pingTimerRef.current);
        pingTimerRef.current = null;
      }
    };
  }, [connect]);
}
