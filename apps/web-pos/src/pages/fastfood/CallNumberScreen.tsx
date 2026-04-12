/**
 * CallNumberScreen — 快餐叫号屏 /fastfood/call-screen
 *
 * 全屏展示当前叫号，适合放在门店大屏/顾客等待区。
 * - 大字显示当前叫号 + 请取餐提示
 * - 最近5个叫过的号排队显示（灰色）
 * - WebSocket 订阅取餐号就绪事件
 * - 断线自动重连（5秒间隔）
 *
 * Store-POS 终端规范（TXTouch）：
 *   - 深色主题，字体超大（顾客远距离可读）
 *   - 无交互按钮（纯展示屏）
 */
import { useState, useEffect, useRef, useCallback } from 'react';

// ─── Design Tokens ───
const C = {
  bg: '#040D12',
  card: '#0A1A24',
  border: '#1A3A48',
  accent: '#FF6B35',
  success: '#10B981',
  muted: '#64748b',
  text: '#E0E0E0',
  white: '#FFFFFF',
  dimText: '#4B5563',
};

interface CallEvent {
  call_number: string;
  quick_order_id: string;
  called_at: string;
}

const STORE_ID = (window as unknown as Record<string, unknown>).__STORE_ID__ as string || 'demo-store';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';
const WS_BASE = import.meta.env.VITE_WS_BASE_URL || `ws://${window.location.host}`;

const MAX_RECENT = 5;

export function CallNumberScreen() {
  const [currentCall, setCurrentCall] = useState<CallEvent | null>(null);
  const [recentCalls, setRecentCalls] = useState<CallEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [blink, setBlink] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ─── Blink animation on new call ───
  const triggerBlink = useCallback(() => {
    setBlink(true);
    setTimeout(() => setBlink(false), 1000);
  }, []);

  // ─── WebSocket connect ───
  const connect = useCallback(() => {
    const url = `${WS_BASE}/ws/calling-screen/${STORE_ID}${TENANT_ID ? `?tenantId=${TENANT_ID}` : ''}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      ws.send(JSON.stringify({ action: 'subscribe' }));
    };

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data as string) as { event: string; data: unknown };
        if (msg.event === 'call_number') {
          const data = msg.data as CallEvent;
          setCurrentCall(data);
          setRecentCalls(prev => [data, ...prev].slice(0, MAX_RECENT));
          triggerBlink();
        } else if (msg.event === 'complete') {
          // keep showing but mark as done; current stays until next call
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      // Auto-reconnect after 5 seconds
      reconnectTimer.current = setTimeout(connect, 5000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [triggerBlink]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  // ─── Ping keepalive ───
  useEffect(() => {
    const timer = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ action: 'ping' }));
      }
    }, 25000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div style={{
      height: '100vh',
      background: C.bg,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      overflow: 'hidden',
      userSelect: 'none',
      position: 'relative',
    }}>

      {/* Connection status dot */}
      <div style={{
        position: 'absolute',
        top: 20,
        right: 24,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
      }}>
        <div style={{
          width: 10, height: 10, borderRadius: '50%',
          background: connected ? C.success : C.muted,
        }} />
        <span style={{ color: C.muted, fontSize: 13 }}>
          {connected ? '已连接' : '连接中...'}
        </span>
      </div>

      {/* Store title */}
      <div style={{ color: C.muted, fontSize: 22, marginBottom: 40, letterSpacing: 4 }}>
        取 餐 叫 号
      </div>

      {/* Current call number — main display */}
      {currentCall ? (
        <div style={{
          textAlign: 'center',
          animation: blink ? 'none' : undefined,
          background: blink ? 'rgba(255,107,53,0.15)' : 'transparent',
          borderRadius: 24,
          padding: '24px 60px',
          transition: 'background 200ms',
        }}>
          <div style={{ color: C.muted, fontSize: 24, marginBottom: 8 }}>请取餐</div>
          <div style={{
            color: C.accent,
            fontSize: 140,
            fontWeight: 900,
            lineHeight: 1,
            letterSpacing: -2,
          }}>
            #{currentCall.call_number}
          </div>
          <div style={{ color: C.muted, fontSize: 22, marginTop: 16 }}>
            请到取餐台取餐
          </div>
        </div>
      ) : (
        <div style={{ textAlign: 'center' }}>
          <div style={{ color: C.dimText, fontSize: 48, marginBottom: 16 }}>—</div>
          <div style={{ color: C.muted, fontSize: 22 }}>等待叫号中...</div>
        </div>
      )}

      {/* Recent calls queue */}
      {recentCalls.length > 0 && (
        <div style={{ marginTop: 60, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
          <div style={{ color: C.dimText, fontSize: 16, marginBottom: 8 }}>最近叫号</div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', justifyContent: 'center' }}>
            {recentCalls.map((c, idx) => (
              <div
                key={`${c.call_number}-${c.called_at}`}
                style={{
                  background: C.card,
                  border: `1px solid ${idx === 0 ? C.accent : C.border}`,
                  borderRadius: 12,
                  padding: '10px 20px',
                  textAlign: 'center',
                  opacity: idx === 0 ? 1 : 0.5,
                }}
              >
                <div style={{
                  color: idx === 0 ? C.accent : C.muted,
                  fontSize: idx === 0 ? 36 : 28,
                  fontWeight: 700,
                }}>
                  #{c.call_number}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default CallNumberScreen;
