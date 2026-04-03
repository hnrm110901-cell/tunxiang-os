/**
 * CustomerCallingScreen — 快餐顾客叫号屏
 *
 * 适用场景：快餐/档口餐厅的顾客端取餐叫号展示屏。
 *
 * 布局：
 *   上半屏：正在叫号（大字，橙色，自动循环播报）
 *   下半屏：即将叫号（待取餐号码列表）
 *   底部：广告/品牌信息轮播
 *
 * 实时性：
 *   通过 WebSocket 订阅叫号事件，无需手动刷新。
 *   断线自动重连。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

// ─── Types ───

interface CallingItem {
  call_no: string;       // 取餐号（如 "A023"）
  counter: string;       // 取餐窗口（如 "1号窗口"）
  called_at: string;
}

// ─── Constants ───

const WS_URL = (window as any).__KDS_WS_URL__ || '';
const STORE_NAME = (window as any).__STORE_NAME__ || '屯象餐厅';
const BRAND_LOGO = (window as any).__BRAND_LOGO__ || '';

// 叫号播报停留时间
const CALLING_DISPLAY_SEC = 15;

// ─── Helpers ───

function useVoiceAnnounce() {
  return useCallback((callNo: string, counter: string) => {
    if (!('speechSynthesis' in window)) return;
    const utterance = new SpeechSynthesisUtterance(
      `${callNo}，请到${counter}取餐`
    );
    utterance.lang = 'zh-CN';
    utterance.rate = 0.85;
    window.speechSynthesis.speak(utterance);
  }, []);
}

// ─── Sub-components ───

function CurrentCallDisplay({ item }: { item: CallingItem | null }) {
  if (!item) {
    return (
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#0A0A0A',
        }}
      >
        <div style={{ fontSize: 48, color: '#333', marginBottom: 16 }}>🍽</div>
        <div style={{ fontSize: 28, color: '#444' }}>等待叫号中…</div>
      </div>
    );
  }

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#1A0800',
        borderBottom: '2px solid #FF6B35',
      }}
    >
      <div style={{ fontSize: 22, color: '#888', marginBottom: 8 }}>请取餐</div>
      <div
        style={{
          fontSize: 120,
          fontWeight: 900,
          color: '#FF6B35',
          fontFamily: 'monospace',
          lineHeight: 1,
          letterSpacing: 8,
          animation: 'callPulse 0.5s ease-out',
        }}
      >
        {item.call_no}
      </div>
      <div
        style={{
          fontSize: 32,
          color: '#FF9F0A',
          marginTop: 16,
          fontWeight: 700,
        }}
      >
        {item.counter}
      </div>
    </div>
  );
}

function UpNextList({ items }: { items: CallingItem[] }) {
  return (
    <div
      style={{
        height: 200,
        background: '#111',
        padding: '12px 20px',
        flexShrink: 0,
      }}
    >
      <div style={{ fontSize: 16, color: '#555', marginBottom: 12 }}>即将叫号</div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {items.length === 0 ? (
          <span style={{ color: '#333', fontSize: 18 }}>暂无等待</span>
        ) : (
          items.slice(0, 12).map((item) => (
            <div
              key={item.call_no}
              style={{
                background: '#1A1A1A',
                border: '1px solid #2A2A2A',
                borderRadius: 8,
                padding: '8px 16px',
                fontSize: 24,
                fontWeight: 700,
                color: '#ccc',
                fontFamily: 'monospace',
              }}
            >
              {item.call_no}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ─── Main ───

export function CustomerCallingScreen() {
  const [currentCall, setCurrentCall] = useState<CallingItem | null>(null);
  const [upNext, setUpNext] = useState<CallingItem[]>([]);
  const [connected, setConnected] = useState(false);
  const announce = useVoiceAnnounce();
  const wsRef = useRef<WebSocket | null>(null);
  const callTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearCurrentCallTimer = useCallback(() => {
    if (callTimerRef.current) {
      clearTimeout(callTimerRef.current);
      callTimerRef.current = null;
    }
  }, []);

  const showCall = useCallback((item: CallingItem) => {
    setCurrentCall(item);
    announce(item.call_no, item.counter);

    clearCurrentCallTimer();
    // 15秒后清除当前叫号
    callTimerRef.current = setTimeout(() => {
      setCurrentCall(null);
    }, CALLING_DISPLAY_SEC * 1000);
  }, [announce, clearCurrentCallTimer]);

  const connectWS = useCallback(() => {
    if (!WS_URL) {
      // 开发模式：mock 定时叫号
      const mockNos = ['A018', 'A019', 'A020', 'B003'];
      let idx = 0;
      const timer = setInterval(() => {
        const no = mockNos[idx % mockNos.length];
        showCall({ call_no: no, counter: '1号窗口', called_at: new Date().toISOString() });
        setUpNext(mockNos.filter((n) => n !== no).slice(0, 4).map((n, i) => ({
          call_no: n,
          counter: `${i + 1}号窗口`,
          called_at: new Date().toISOString(),
        })));
        idx++;
      }, 8000);
      setConnected(true);
      return () => clearInterval(timer);
    }

    const ws = new WebSocket(`${WS_URL}/ws/calling`);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.event === 'call_number') {
          showCall(msg.data as CallingItem);
        } else if (msg.event === 'up_next') {
          setUpNext(msg.data as CallingItem[]);
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onclose = () => {
      setConnected(false);
      // 3秒后重连
      setTimeout(connectWS, 3000);
    };

    return () => {
      ws.close();
    };
  }, [showCall]);

  useEffect(() => {
    const cleanup = connectWS();
    return () => {
      clearCurrentCallTimer();
      if (typeof cleanup === 'function') cleanup();
      wsRef.current?.close();
    };
  }, [connectWS, clearCurrentCallTimer]);

  return (
    <div
      style={{
        background: '#000',
        width: '100vw',
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: 'Noto Sans SC, sans-serif',
        overflow: 'hidden',
        userSelect: 'none',
      }}
    >
      {/* 顶部品牌栏 */}
      <div
        style={{
          background: '#FF6B35',
          height: 56,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 20px',
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 22, fontWeight: 700, color: '#fff' }}>
          {STORE_NAME}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div
            style={{
              width: 10,
              height: 10,
              borderRadius: 5,
              background: connected ? '#30D158' : '#FF3B30',
            }}
          />
          <span style={{ fontSize: 13, color: 'rgba(255,255,255,0.7)' }}>
            {connected ? '叫号中' : '连接中…'}
          </span>
        </div>
      </div>

      {/* 当前叫号（大屏主体） */}
      <CurrentCallDisplay item={currentCall} />

      {/* 即将叫号列表 */}
      <UpNextList items={upNext} />

      {/* CSS 动画 */}
      <style>{`
        @keyframes callPulse {
          0%   { transform: scale(0.85); opacity: 0; }
          60%  { transform: scale(1.05); }
          100% { transform: scale(1);   opacity: 1; }
        }
      `}</style>
    </div>
  );
}
