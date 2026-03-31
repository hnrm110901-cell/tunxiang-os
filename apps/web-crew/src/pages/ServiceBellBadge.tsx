import { useState, useEffect, useRef, useCallback } from 'react';
import { txFetch } from '../api/index';

// ─── Types ───

interface ServiceBellCall {
  call_id: string;
  store_id: string;
  table_no: string;
  call_type: string;
  call_type_label: string | null;
  status: string;
  operator_id: string | null;
  called_at: string;
  responded_at: string | null;
}

interface ServiceBellCalledEvent {
  type: 'service_bell_called';
  store_id: string;
  data: {
    call_id: string;
    table_no: string;
    call_type: string;
    call_type_label: string | null;
    called_at: string;
  };
}

// ─── Audio ───

function playAlertTone(): void {
  try {
    const ctx = new AudioContext();
    const times = [0, 0.3];
    times.forEach(offset => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 880;
      osc.type = 'sine';
      gain.gain.setValueAtTime(0.4, ctx.currentTime + offset);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + offset + 0.25);
      osc.start(ctx.currentTime + offset);
      osc.stop(ctx.currentTime + offset + 0.25);
    });
  } catch {
    // AudioContext not available
  }
}

// ─── Utils ───

function getCrewConfig() {
  try {
    return {
      host: localStorage.getItem('crew_mac_host') || localStorage.getItem('kds_mac_host') || '',
      storeId: localStorage.getItem('crew_store_id') || '',
    };
  } catch {
    return { host: '', storeId: '' };
  }
}

function elapsedMin(calledAt: string): number {
  return Math.floor((Date.now() - new Date(calledAt).getTime()) / 60_000);
}

function urgencyDot(mins: number): string {
  if (mins < 2) return '#EF4444';
  if (mins < 5) return '#F59E0B';
  return '#6B7280';
}

// ─── ServiceBellQueue Panel ───

function ServiceBellQueue({
  calls,
  onRespond,
  onClose,
}: {
  calls: ServiceBellCall[];
  onRespond: (callId: string) => void;
  onClose: () => void;
}) {
  const [respondingIds, setRespondingIds] = useState<Set<string>>(new Set());

  async function handleRespond(callId: string) {
    setRespondingIds(prev => new Set(prev).add(callId));
    try {
      const operatorId = localStorage.getItem('crew_operator_id') || '00000000-0000-0000-0000-000000000000';
      await txFetch(`/api/v1/service-bell/${callId}/respond`, {
        method: 'POST',
        body: JSON.stringify({ operator_id: operatorId }),
      });
      onRespond(callId);
    } finally {
      setRespondingIds(prev => {
        const s = new Set(prev);
        s.delete(callId);
        return s;
      });
    }
  }

  return (
    <div style={{
      position: 'fixed',
      right: 16,
      bottom: 148,
      width: 320,
      maxHeight: '60vh',
      background: '#112228',
      border: '1px solid #1a3040',
      borderRadius: 12,
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
      zIndex: 1000,
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '14px 16px',
        borderBottom: '1px solid #1a3040',
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 17, fontWeight: 700, color: '#fff' }}>
          服务呼叫
          {calls.length > 0 && (
            <span style={{ marginLeft: 8, fontSize: 16, color: '#FF6B35', fontWeight: 400 }}>
              ({calls.length}个待响应)
            </span>
          )}
        </span>
        <button
          onClick={onClose}
          style={{
            minWidth: 48,
            minHeight: 48,
            background: 'transparent',
            border: 'none',
            color: '#64748b',
            fontSize: 20,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: 8,
          }}
        >
          ✕
        </button>
      </div>

      {/* List */}
      <div style={{ overflowY: 'auto', flex: 1 }}>
        {calls.length === 0 ? (
          <div style={{ padding: '24px 16px', textAlign: 'center', color: '#64748b', fontSize: 16 }}>
            暂无待响应呼叫
          </div>
        ) : (
          calls.map((call, idx) => {
            const mins = elapsedMin(call.called_at);
            const dot = urgencyDot(mins);
            return (
              <div
                key={call.call_id}
                style={{
                  padding: '14px 16px',
                  borderBottom: idx < calls.length - 1 ? '1px solid #1a3040' : 'none',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                }}
              >
                <span style={{
                  width: 12,
                  height: 12,
                  borderRadius: '50%',
                  background: dot,
                  flexShrink: 0,
                }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 17, fontWeight: 600, color: '#fff' }}>
                    {call.table_no}桌&nbsp;&nbsp;{call.call_type_label || call.call_type}
                  </div>
                  <div style={{ fontSize: 14, color: '#64748b', marginTop: 2 }}>
                    {mins < 1 ? '刚刚' : `${mins}分钟前`}
                  </div>
                </div>
                <button
                  disabled={respondingIds.has(call.call_id)}
                  onClick={() => handleRespond(call.call_id)}
                  style={{
                    minWidth: 72,
                    minHeight: 48,
                    background: respondingIds.has(call.call_id) ? '#1a3040' : '#FF6B35',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 8,
                    fontSize: 16,
                    fontWeight: 600,
                    cursor: respondingIds.has(call.call_id) ? 'default' : 'pointer',
                    flexShrink: 0,
                  }}
                >
                  {respondingIds.has(call.call_id) ? '…' : '已响应'}
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ─── ServiceBellBadge ───

export function ServiceBellBadge({ storeId }: { storeId: string }) {
  const [pendingCalls, setPendingCalls] = useState<ServiceBellCall[]>([]);
  const [open, setOpen] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const config = getCrewConfig();

  // Initial fetch of pending calls
  useEffect(() => {
    if (!storeId) return;
    txFetch<{ items: ServiceBellCall[]; total: number }>(
      `/api/v1/service-bell/pending?store_id=${encodeURIComponent(storeId)}`
    )
      .then(data => {
        if (mountedRef.current) setPendingCalls(data.items);
      })
      .catch(() => {});
  }, [storeId]);

  // Refresh elapsed times every 30s to re-render urgency dots
  useEffect(() => {
    const t = setInterval(() => {
      setPendingCalls(prev => [...prev]);
    }, 30_000);
    return () => clearInterval(t);
  }, []);

  const handleNewCall = useCallback((event: ServiceBellCalledEvent) => {
    setPendingCalls(prev => {
      if (prev.some(c => c.call_id === event.data.call_id)) return prev;
      const newCall: ServiceBellCall = {
        call_id: event.data.call_id,
        store_id: event.store_id,
        table_no: event.data.table_no,
        call_type: event.data.call_type,
        call_type_label: event.data.call_type_label,
        status: 'pending',
        operator_id: null,
        called_at: event.data.called_at,
        responded_at: null,
      };
      return [newCall, ...prev];
    });

    try {
      navigator.vibrate([200, 100, 200]);
    } catch {
      // vibrate not supported
    }
    playAlertTone();
  }, []);

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

    ws.onmessage = (evt: MessageEvent) => {
      if (!mountedRef.current) return;
      if (evt.data === 'pong') return;
      try {
        const msg = JSON.parse(evt.data) as { type: string; [key: string]: unknown };
        if (msg.type === 'service_bell_called') {
          handleNewCall(msg as unknown as ServiceBellCalledEvent);
        }
      } catch {
        // ignore
      }
    };

    ws.onerror = () => {};

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
  }, [config.host, config.storeId, handleNewCall]);

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

  function handleRespond(callId: string) {
    setPendingCalls(prev => prev.filter(c => c.call_id !== callId));
  }

  if (pendingCalls.length === 0 && !open) return null;

  return (
    <>
      {open && (
        <ServiceBellQueue
          calls={pendingCalls}
          onRespond={handleRespond}
          onClose={() => setOpen(false)}
        />
      )}

      {pendingCalls.length > 0 && (
        <button
          onClick={() => setOpen(prev => !prev)}
          style={{
            position: 'fixed',
            right: 16,
            bottom: 80,
            width: 56,
            height: 56,
            minWidth: 56,
            minHeight: 56,
            borderRadius: '50%',
            background: '#FF6B35',
            border: 'none',
            cursor: 'pointer',
            zIndex: 999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 26,
            boxShadow: '0 4px 16px rgba(255,107,53,0.5)',
          }}
        >
          🔔
          <span style={{
            position: 'absolute',
            top: 0,
            right: 0,
            width: 20,
            height: 20,
            borderRadius: '50%',
            background: '#EF4444',
            color: '#fff',
            fontSize: 12,
            fontWeight: 700,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            lineHeight: 1,
          }}>
            {pendingCalls.length > 9 ? '9+' : pendingCalls.length}
          </span>
        </button>
      )}
    </>
  );
}
