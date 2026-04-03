/**
 * POS 实时预警 Hook
 * 连接 Mac mini WebSocket，接收折扣守护预警和运营通知
 *
 * 连接 URL: ws://{TX_MAC_URL}/ws/pos/{storeId}/{terminalId}
 *
 * 消息类型：
 *   discount_alert   — 折扣守护 Agent 检测到异常折扣
 *   operation_alert  — 运营通知（库存低/临期/班次/销售里程碑）
 *
 * 特性：
 *   - 心跳：每 25 秒发一次 "ping"，服务端回 "pong"
 *   - 断线重连：5 秒后自动重连（unmount 时停止）
 *   - 最多保留最近 20 条预警，避免内存无限增长
 */
import { useCallback, useEffect, useRef, useState } from 'react';

// ─── 类型定义 ───

export interface DiscountAlert {
  alert_id: string;
  order_id: string;
  employee_id: string;
  employee_name: string;
  discount_rate: number;    // 0.0-1.0
  threshold: number;        // 允许的最大折扣率
  amount_fen: number;       // 折扣金额（分）
  risk_level: 'medium' | 'high' | 'critical';
  message: string;
  timestamp: string;        // ISO 8601
}

export interface OperationAlert {
  alert_id: string;
  alert_type: 'stock_low' | 'expiry_warning' | 'shift_reminder' | 'sales_milestone';
  title: string;
  body: string;
  severity: 'info' | 'warning' | 'critical';
  timestamp: string;        // ISO 8601
}

export interface UsePOSAlertsReturn {
  discountAlerts: DiscountAlert[];
  operationAlerts: OperationAlert[];
  connected: boolean;
  dismissAlert: (alertId: string) => void;
}

// ─── 常量 ───

const MAX_ALERTS = 20;
const HEARTBEAT_INTERVAL_MS = 25_000;
const RECONNECT_DELAY_MS = 5_000;

// ─── Hook ───

export function usePOSAlerts(
  storeId: string,
  terminalId: string,
): UsePOSAlertsReturn {
  const [discountAlerts, setDiscountAlerts] = useState<DiscountAlert[]>([]);
  const [operationAlerts, setOperationAlerts] = useState<OperationAlert[]>([]);
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 标记组件已卸载，阻止 unmount 后的重连
  const destroyedRef = useRef(false);

  const clearHeartbeat = () => {
    if (heartbeatRef.current !== null) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  };

  const clearReconnect = () => {
    if (reconnectRef.current !== null) {
      clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }
  };

  const connect = useCallback(() => {
    if (destroyedRef.current) return;
    if (!storeId || !terminalId) return;

    const macUrl =
      (window as unknown as Record<string, string>).TX_MAC_URL ??
      'ws://localhost:8000';

    const ws = new WebSocket(
      `${macUrl}/ws/pos/${storeId}/${terminalId}`,
    );
    wsRef.current = ws;

    ws.onopen = () => {
      if (destroyedRef.current) {
        ws.close();
        return;
      }
      setConnected(true);
      clearReconnect();

      // 启动心跳
      heartbeatRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, HEARTBEAT_INTERVAL_MS);
    };

    ws.onclose = () => {
      setConnected(false);
      clearHeartbeat();

      if (!destroyedRef.current) {
        // 5 秒后重连
        reconnectRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
      }
    };

    ws.onerror = () => {
      // onerror 之后必然触发 onclose，重连逻辑交给 onclose 处理
      setConnected(false);
    };

    ws.onmessage = (e: MessageEvent<string>) => {
      if (e.data === 'pong') {
        // 心跳回包，忽略
        return;
      }

      let msg: { type: string; data: unknown };
      try {
        msg = JSON.parse(e.data) as { type: string; data: unknown };
      } catch {
        // 非 JSON 消息（如裸文本），直接忽略
        return;
      }

      if (msg.type === 'discount_alert') {
        setDiscountAlerts((prev) =>
          [msg.data as DiscountAlert, ...prev].slice(0, MAX_ALERTS),
        );
      } else if (msg.type === 'operation_alert') {
        setOperationAlerts((prev) =>
          [msg.data as OperationAlert, ...prev].slice(0, MAX_ALERTS),
        );
      }
    };
  }, [storeId, terminalId]);

  useEffect(() => {
    destroyedRef.current = false;
    connect();

    return () => {
      destroyedRef.current = true;
      clearHeartbeat();
      clearReconnect();
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  /** 收银员点击「已知晓」后从列表中移除对应预警 */
  const dismissAlert = useCallback((alertId: string) => {
    setDiscountAlerts((prev) => prev.filter((a) => a.alert_id !== alertId));
    setOperationAlerts((prev) => prev.filter((a) => a.alert_id !== alertId));
  }, []);

  return { discountAlerts, operationAlerts, connected, dismissAlert };
}
