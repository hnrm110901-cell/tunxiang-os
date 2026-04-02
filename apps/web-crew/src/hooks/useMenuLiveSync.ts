/**
 * useMenuLiveSync — 监听菜单实时变更，自动更新本地菜品状态
 *
 * 订阅 mac-station WebSocket，收到 menu_dish_updated /
 * menu_bulk_availability_updated 事件后更新状态。
 *
 * 使用方式：
 *   const { updatedDishIds, lastUpdate } = useMenuLiveSync();
 *
 * 特性：
 * - 无 WS_URL 时静默跳过（开发环境 / 浏览器预览）
 * - 指数退避自动重连（1s → 2s → 4s → … → 30s）
 * - 心跳 ping/pong 每 30s，防止连接超时断开
 */
import { useEffect, useRef, useState, useCallback } from 'react';

// ─── 类型 ───

export interface DishChange {
  name?: string;
  price?: number;
  description?: string;
  is_available?: boolean;
  daily_limit?: number | null;
  image_url?: string;
}

export interface MenuUpdateEvent {
  dish_id: string;
  changes: DishChange;
  updated_by: string;
  updated_at: string;
}

export interface BulkAvailabilityEvent {
  dish_ids: string[];
  is_available: boolean;
  reason: string;
  updated_by: string;
  updated_at: string;
}

export interface UseMenuLiveSyncReturn {
  /** 本次会话中收到更新的 dish_id 列表（去重） */
  updatedDishIds: string[];
  /** 最新一条单品更新事件 */
  lastUpdate: MenuUpdateEvent | null;
  /** 最新一条批量更新事件 */
  lastBulkUpdate: BulkAvailabilityEvent | null;
  /** WebSocket 是否已连接 */
  connected: boolean;
}

// ─── 内部工具 ───

function getWsUrl(): string {
  return (window as unknown as Record<string, unknown>).__KDS_WS_URL__ as string || '';
}

// ─── Hook ───

export function useMenuLiveSync(): UseMenuLiveSyncReturn {
  const [updatedDishIds, setUpdatedDishIds] = useState<string[]>([]);
  const [lastUpdate, setLastUpdate] = useState<MenuUpdateEvent | null>(null);
  const [lastBulkUpdate, setLastBulkUpdate] = useState<BulkAvailabilityEvent | null>(null);
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const retryCountRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  const clearHeartbeat = useCallback(() => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  }, []);

  const startHeartbeat = useCallback((ws: WebSocket) => {
    clearHeartbeat();
    heartbeatRef.current = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping');
      }
    }, 30_000);
  }, [clearHeartbeat]);

  const handleMessage = useCallback((event: MessageEvent) => {
    if (!mountedRef.current) return;
    if (event.data === 'pong') return;

    let msg: { event?: string; type?: string; data?: unknown };
    try {
      msg = JSON.parse(event.data as string) as { event?: string; type?: string; data?: unknown };
    } catch {
      return;
    }

    const eventType = (msg.event || msg.type || '') as string;

    if (eventType === 'menu_dish_updated') {
      const data = msg.data as MenuUpdateEvent;
      if (!data?.dish_id) return;

      setLastUpdate(data);
      setUpdatedDishIds(prev => {
        if (prev.includes(data.dish_id)) return prev;
        return [...prev, data.dish_id];
      });
    }

    if (eventType === 'menu_bulk_availability_updated') {
      const data = msg.data as BulkAvailabilityEvent;
      if (!Array.isArray(data?.dish_ids)) return;

      setLastBulkUpdate(data);
      setUpdatedDishIds(prev => {
        const toAdd = data.dish_ids.filter(id => !prev.includes(id));
        return toAdd.length > 0 ? [...prev, ...toAdd] : prev;
      });
    }
  }, []);

  const connect = useCallback(() => {
    const WS_URL = getWsUrl();
    if (!WS_URL) return;          // 开发环境无 URL，静默跳过
    if (!mountedRef.current) return;

    // 清理旧连接
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      if (
        wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING
      ) {
        wsRef.current.close();
      }
    }

    // mac-station 通用菜单频道
    const url = `${WS_URL}/ws/menu`;

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      scheduleRetry();
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setConnected(true);
      retryCountRef.current = 0;
      startHeartbeat(ws);
    };

    ws.onmessage = handleMessage;

    ws.onerror = () => {
      // onerror 之后必跟 onclose，重连逻辑在 onclose 里
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setConnected(false);
      clearHeartbeat();
      scheduleRetry();
    };

    function scheduleRetry() {
      if (!mountedRef.current) return;
      const delay = Math.min(1_000 * Math.pow(2, retryCountRef.current), 30_000);
      retryCountRef.current += 1;
      retryTimerRef.current = setTimeout(() => {
        if (mountedRef.current) connect();
      }, delay);
    }
  }, [handleMessage, startHeartbeat, clearHeartbeat]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      clearHeartbeat();
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
      if (wsRef.current) {
        wsRef.current.onopen = null;
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.onmessage = null;
        wsRef.current.close();
      }
    };
  }, [connect, clearHeartbeat]);

  return { updatedDishIds, lastUpdate, lastBulkUpdate, connected };
}
