/**
 * useKdsWebSocket -- KDS 实时 WebSocket Hook
 *
 * 连接 Mac mini 的 ws://host:8000/ws/kds/{stationId}
 * 自动重连（指数退避 1s->2s->4s->8s->max 30s）
 * 心跳 ping/pong（每 30 秒）
 *
 * 消息类型：
 *   new_ticket     -> 添加新订单到看板
 *   status_change  -> 更新菜品状态
 *   rush_order     -> 标记为催单（闪烁+声音）
 *   remake_order   -> 弹出重做提示
 *   timeout_alert  -> 变红+声音告警
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { playNewOrder, playRush, playTimeout } from '../utils/audio';

// ─── Types ───

export interface TicketItem {
  name: string;
  qty: number;
  notes: string;
  spec?: string;
}

export interface KDSTicket {
  id: string;
  orderNo: string;
  tableNo: string;
  items: TicketItem[];
  createdAt: number;        // timestamp ms
  status: 'pending' | 'cooking' | 'done';
  priority: 'normal' | 'rush' | 'vip';
  deptId: string;
  startedAt?: number;
  completedAt?: number;
  /** 订单类型：dine-in / delivery */
  orderType?: string;
  /** 配送平台（外卖订单专用） */
  platform?: 'grabfood' | 'foodpanda' | 'shopeefood';
}

export interface RushAlert {
  ticketId: string;
  timestamp: number;
  dishName?: string;
  tableNumber?: string;
}

export interface RemakeAlert {
  taskId: string;
  dishName: string;
  reason: string;
  tableNumber: string;
  remakeCount: number;
  timestamp: number;
}

export interface TimeoutAlertInfo {
  ticketId?: string;
  stationId: string;
  status?: string;
  dish?: string;
  waitMinutes?: number;
  timestamp: number;
}

export interface WsMessage {
  type: string;
  [key: string]: unknown;
}

export interface UseKdsWebSocketReturn {
  connected: boolean;
  tickets: KDSTicket[];
  rushAlerts: RushAlert[];
  remakeAlerts: RemakeAlert[];
  timeoutAlerts: TimeoutAlertInfo[];
  lastMessage: WsMessage | null;
  setTickets: React.Dispatch<React.SetStateAction<KDSTicket[]>>;
  dismissRemakeAlert: (taskId: string) => void;
  dismissTimeoutAlert: (index: number) => void;
}

// ─── 配置 ───

interface KdsWsConfig {
  host: string;       // e.g. "192.168.1.100:8000"
  stationId: string;
  soundEnabled: boolean;
  timeoutMinutes: number;
}

// ─── 从服务端 payload 转换为前端 KDSTicket ───

function payloadToTicket(payload: Record<string, unknown>): KDSTicket {
  const items = Array.isArray(payload.items)
    ? (payload.items as Record<string, unknown>[]).map(i => ({
        name: (i.dish_name || i.name || '') as string,
        qty: (i.quantity || i.qty || 1) as number,
        notes: (i.special_notes || i.notes || '') as string,
        spec: (i.spec || '') as string,
      }))
    : [];

  const createdAtRaw = payload.created_at as string | number | undefined;
  const createdAt = typeof createdAtRaw === 'string'
    ? new Date(createdAtRaw).getTime()
    : typeof createdAtRaw === 'number'
      ? createdAtRaw
      : Date.now();

  return {
    id: (payload.ticket_id || payload.id || `ws-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`) as string,
    orderNo: (payload.order_number || payload.order_no || payload.orderNo || '') as string,
    tableNo: (payload.table_number || payload.table_no || payload.tableNo || '') as string,
    items,
    createdAt,
    status: 'pending',
    priority: (payload.priority || 'normal') as KDSTicket['priority'],
    deptId: (payload.station_id || payload.dept_id || payload.deptId || '') as string,
    orderType: (payload.order_type || payload.orderType || 'dine-in') as string | undefined,
    platform: (payload.platform || undefined) as 'grabfood' | 'foodpanda' | 'shopeefood' | undefined,
  };
}

// ─── Hook ───

export function useKdsWebSocket(config: KdsWsConfig): UseKdsWebSocketReturn {
  const { host, stationId, soundEnabled, timeoutMinutes: _timeoutMinutes } = config;

  const [connected, setConnected] = useState(false);
  const [tickets, setTickets] = useState<KDSTicket[]>([]);
  const [rushAlerts, setRushAlerts] = useState<RushAlert[]>([]);
  const [remakeAlerts, setRemakeAlerts] = useState<RemakeAlert[]>([]);
  const [timeoutAlerts, setTimeoutAlerts] = useState<TimeoutAlertInfo[]>([]);
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const retryCountRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  // ─── 清理心跳 ───

  const clearHeartbeat = useCallback(() => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  }, []);

  // ─── 启动心跳 ───

  const startHeartbeat = useCallback((ws: WebSocket) => {
    clearHeartbeat();
    heartbeatRef.current = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping');
      }
    }, 30_000);
  }, [clearHeartbeat]);

  // ─── 消息处理 ───

  const handleMessage = useCallback((event: MessageEvent) => {
    if (!mountedRef.current) return;

    // pong 心跳响应，忽略
    if (event.data === 'pong') return;

    let msg: WsMessage;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }

    setLastMessage(msg);

    const msgType = msg.type as string;

    switch (msgType) {
      case 'new_ticket': {
        const payload = (msg.payload || msg) as Record<string, unknown>;
        const ticket = payloadToTicket(payload);
        setTickets(prev => [ticket, ...prev]);
        if (soundEnabled) playNewOrder();
        break;
      }

      case 'status_change': {
        const ticketId = msg.ticket_id as string;
        const newStatus = msg.new_status as KDSTicket['status'];
        setTickets(prev => prev.map(t => {
          if (t.id !== ticketId) return t;
          const update: Partial<KDSTicket> = { status: newStatus };
          if (newStatus === 'cooking') update.startedAt = Date.now();
          if (newStatus === 'done') update.completedAt = Date.now();
          return { ...t, ...update };
        }));
        break;
      }

      case 'rush_order': {
        const ticketId = msg.ticket_id as string;
        // 标记 ticket 为催单
        setTickets(prev => prev.map(t =>
          t.id === ticketId ? { ...t, priority: 'rush' as const } : t,
        ));
        // 添加催单告警
        setRushAlerts(prev => [
          ...prev,
          {
            ticketId,
            timestamp: Date.now(),
            dishName: msg.dish_name as string | undefined,
            tableNumber: msg.table_number as string | undefined,
          },
        ]);
        if (soundEnabled) playRush();
        break;
      }

      case 'remake_order': {
        const alert: RemakeAlert = {
          taskId: msg.task_id as string,
          dishName: msg.dish_name as string,
          reason: msg.reason as string,
          tableNumber: (msg.table_number || '') as string,
          remakeCount: (msg.remake_count || 1) as number,
          timestamp: Date.now(),
        };
        setRemakeAlerts(prev => [...prev, alert]);
        if (soundEnabled) playRush();
        break;
      }

      case 'timeout_alert': {
        const payload = (msg.payload || msg) as Record<string, unknown>;
        const alert: TimeoutAlertInfo = {
          ticketId: payload.ticket_id as string | undefined,
          stationId: (msg.station_id || '') as string,
          status: payload.status as string | undefined,
          dish: payload.dish as string | undefined,
          waitMinutes: payload.wait_minutes as number | undefined,
          timestamp: Date.now(),
        };
        setTimeoutAlerts(prev => [...prev, alert]);
        if (soundEnabled) playTimeout();
        break;
      }

      default:
        break;
    }
  }, [soundEnabled]);

  // ─── 连接 ───

  const connect = useCallback(() => {
    if (!host || !stationId) return;
    if (!mountedRef.current) return;

    // 清理旧连接
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      if (wsRef.current.readyState === WebSocket.OPEN ||
          wsRef.current.readyState === WebSocket.CONNECTING) {
        wsRef.current.close();
      }
    }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${host}/ws/kds/${encodeURIComponent(stationId)}`;

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      // URL 无效等
      scheduleRetry();
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setConnected(true);
      retryCountRef.current = 0;
      startHeartbeat(ws);
      console.log(`[KDS-WS] Connected: station=${stationId}`);
    };

    ws.onmessage = handleMessage;

    ws.onerror = () => {
      console.warn('[KDS-WS] WebSocket error');
    };

    ws.onclose = (event: CloseEvent) => {
      if (!mountedRef.current) return;
      setConnected(false);
      clearHeartbeat();
      console.warn(`[KDS-WS] Closed: code=${event.code}`);
      scheduleRetry();
    };

    function scheduleRetry() {
      if (!mountedRef.current) return;
      const delay = Math.min(1000 * Math.pow(2, retryCountRef.current), 30_000);
      retryCountRef.current += 1;
      console.log(`[KDS-WS] Retry in ${delay}ms (attempt #${retryCountRef.current})`);
      retryTimerRef.current = setTimeout(() => {
        if (mountedRef.current) connect();
      }, delay);
    }
  }, [host, stationId, handleMessage, startHeartbeat, clearHeartbeat]);

  // ─── 生命周期 ───

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      clearHeartbeat();
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.onopen = null;
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.onmessage = null;
        wsRef.current.close();
      }
    };
  }, [connect, clearHeartbeat]);

  // ─── 操作方法 ───

  const dismissRemakeAlert = useCallback((taskId: string) => {
    setRemakeAlerts(prev => prev.filter(a => a.taskId !== taskId));
  }, []);

  const dismissTimeoutAlert = useCallback((index: number) => {
    setTimeoutAlerts(prev => prev.filter((_, i) => i !== index));
  }, []);

  return {
    connected,
    tickets,
    rushAlerts,
    remakeAlerts,
    timeoutAlerts,
    lastMessage,
    setTickets,
    dismissRemakeAlert,
    dismissTimeoutAlert,
  };
}
