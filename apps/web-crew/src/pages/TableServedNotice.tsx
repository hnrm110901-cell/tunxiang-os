/**
 * TableServedNotice — 本桌已上菜完毕通知组件
 *
 * 当传菜员确认同一订单所有菜品全部送达时，
 * Mac mini 通过 WebSocket 推送 table_all_served 事件，
 * 此组件在服务员手机端显示"本桌已上齐"横幅通知。
 *
 * 使用方式：
 *   在 TablesView 或 App 顶层挂载 <TableServedNotice />，
 *   它会自动连接 WebSocket 并在收到通知时展示横幅。
 *
 * Store-Crew 终端规范：
 *   - 竖屏 PWA，最小字体 16px，热区 ≥ 48px
 *   - 深色主题，颜色复用 web-crew 的 C 常量
 */
import { useState, useEffect, useRef, useCallback } from 'react';

// ─── Types ───

interface TableServedEvent {
  type: 'table_all_served';
  order_id: string;
  table_number: string;
  tenant_id: string;
  served_at: string;
  message: string;
}

interface NoticeItem {
  id: string;          // order_id
  table_number: string;
  message: string;
  served_at: string;
  dismissAt: number;   // 自动消失时间戳（ms）
}

// ─── 配置 ───

function getCrewConfig() {
  try {
    return {
      host: localStorage.getItem('crew_mac_host') || localStorage.getItem('kds_mac_host') || '',
      storeId: localStorage.getItem('crew_store_id') || '',
      tenantId: localStorage.getItem('crew_tenant_id') || '',
    };
  } catch {
    return { host: '', storeId: '', tenantId: '' };
  }
}

const AUTO_DISMISS_MS = 30_000; // 30 秒自动消失

// ─── 主组件 ───

export function TableServedNotice() {
  const [notices, setNotices] = useState<NoticeItem[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const config = getCrewConfig();

  const addNotice = useCallback((event: TableServedEvent) => {
    setNotices(prev => {
      // 同一订单不重复
      if (prev.some(n => n.id === event.order_id)) return prev;
      return [
        {
          id: event.order_id,
          table_number: event.table_number,
          message: event.message || `${event.table_number} 桌所有菜品已上齐`,
          served_at: event.served_at,
          dismissAt: Date.now() + AUTO_DISMISS_MS,
        },
        ...prev,
      ];
    });
  }, []);

  const dismiss = useCallback((orderId: string) => {
    setNotices(prev => prev.filter(n => n.id !== orderId));
  }, []);

  // 自动消失定时检查
  useEffect(() => {
    const timer = setInterval(() => {
      const now = Date.now();
      setNotices(prev => prev.filter(n => n.dismissAt > now));
    }, 5_000);
    return () => clearInterval(timer);
  }, []);

  // WebSocket 连接
  const connect = useCallback(() => {
    if (!config.host || !config.storeId || !mountedRef.current) return;

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

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    let ws: WebSocket;
    try {
      ws = new WebSocket(
        `${protocol}//${config.host}/ws/crew/${encodeURIComponent(config.storeId)}`,
      );
    } catch {
      scheduleRetry();
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      retryRef.current = 0;
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      if (event.data === 'pong') return;
      try {
        const msg = JSON.parse(event.data) as { type: string; [key: string]: unknown };
        if (msg.type === 'table_all_served') {
          addNotice(msg as unknown as TableServedEvent);
        }
      } catch {
        // 忽略非法消息
      }
    };

    ws.onerror = () => {
      // 错误将触发 onclose
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      scheduleRetry();
    };

    function scheduleRetry() {
      if (!mountedRef.current) return;
      const delay = Math.min(1000 * Math.pow(2, retryRef.current), 30_000);
      retryRef.current += 1;
      timerRef.current = setTimeout(() => {
        if (mountedRef.current) connect();
      }, delay);
    }
  }, [config.host, config.storeId, addNotice]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      if (wsRef.current) {
        wsRef.current.onopen = null;
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.onmessage = null;
        wsRef.current.close();
      }
    };
  }, [connect]);

  if (notices.length === 0) return null;

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      zIndex: 999,
      display: 'flex',
      flexDirection: 'column',
      gap: 0,
      pointerEvents: 'none',
    }}>
      {notices.map(notice => (
        <NoticeBar
          key={notice.id}
          notice={notice}
          onDismiss={() => dismiss(notice.id)}
        />
      ))}
    </div>
  );
}

// ─── 单条通知横幅 ───

function NoticeBar({ notice, onDismiss }: {
  notice: NoticeItem;
  onDismiss: () => void;
}) {
  const remainSec = Math.max(0, Math.ceil((notice.dismissAt - Date.now()) / 1000));

  return (
    <div style={{
      background: '#0F6E56',
      color: '#fff',
      padding: '14px 16px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
      pointerEvents: 'auto',
      animation: 'crew-slide-in 0.3s ease-out',
      borderBottom: '1px solid rgba(255,255,255,0.1)',
    }}>
      <style>{`
        @keyframes crew-slide-in {
          from { opacity: 0; transform: translateY(-100%); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      {/* 图标 + 文字 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1 }}>
        <span style={{ fontSize: 24 }}>✓</span>
        <div>
          <div style={{ fontSize: 18, fontWeight: 'bold' }}>
            {notice.table_number} 桌 · 已上齐
          </div>
          <div style={{ fontSize: 16, opacity: 0.85, marginTop: 2 }}>
            {notice.message}
          </div>
        </div>
      </div>

      {/* 倒计时 + 关闭 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <span style={{ fontSize: 16, opacity: 0.7 }}>{remainSec}s</span>
        <button
          onClick={onDismiss}
          style={{
            minWidth: 48,
            minHeight: 48,
            background: 'rgba(255,255,255,0.2)',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            fontSize: 20,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'transform 200ms ease',
          }}
          onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.95)')}
          onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
        >
          ✕
        </button>
      </div>
    </div>
  );
}
