import { useState, useEffect, useRef, useCallback } from 'react';
import { txFetch } from '../api/index';

// ─── Types ───

interface PatrolCheckinResponse {
  checkin_id: string;
  table_no: string;
  checked_at: string;
}

interface PatrolTimelineItem {
  checkin_id: string;
  table_no: string;
  beacon_id: string | null;
  signal_strength: number | null;
  checked_at: string;
}

interface PatrolSummary {
  tables_visited_count: number;
  timeline: PatrolTimelineItem[];
}

interface BLEBeacon {
  beacon_id: string;
  table_no: string;
  signal_strength: number;
}

interface Toast {
  id: number;
  table_no: string;
}

// ─── Helpers ───

function getCrewId(): string {
  try {
    return localStorage.getItem('crew_operator_id') || '00000000-0000-0000-0000-000000000000';
  } catch {
    return '00000000-0000-0000-0000-000000000000';
  }
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    return `${h}:${m}`;
  } catch {
    return '--:--';
  }
}

// ─── BLE Scanner ───

async function scanBLEBeacons(): Promise<BLEBeacon[]> {
  // 方案B：安卓壳层 JS Bridge 优先
  try {
    const bridge = (window as any).TXBridge;
    if (bridge?.getBLEBeacons) {
      const raw = bridge.getBLEBeacons();
      const list: BLEBeacon[] = typeof raw === 'string' ? JSON.parse(raw) : raw;
      return Array.isArray(list) ? list : [];
    }
  } catch {
    // ignore bridge errors
  }

  // 方案A：Web Bluetooth requestLEScan (Chrome Android 实验性)
  try {
    const nav = navigator as any;
    if (nav.bluetooth?.requestLEScan) {
      // 只做一次短暂扫描
      const scan = await nav.bluetooth.requestLEScan({
        filters: [{ services: ['txos-table-beacon'] }],
        keepRepeatedDevices: false,
      });
      const results: BLEBeacon[] = [];
      const onAdv = (evt: any) => {
        results.push({
          beacon_id: evt.device?.id ?? '',
          table_no: evt.device?.name ?? '',
          signal_strength: evt.rssi ?? -99,
        });
      };
      nav.bluetooth.addEventListener('advertisementreceived', onAdv);
      await new Promise<void>(r => setTimeout(r, 2000));
      scan.stop();
      nav.bluetooth.removeEventListener('advertisementreceived', onAdv);
      return results;
    }
  } catch {
    // Web Bluetooth not supported or denied
  }

  return [];
}

// ─── Toast Component ───

function CheckinToast({ toasts }: { toasts: Toast[] }) {
  if (toasts.length === 0) return null;
  return (
    <div style={{ position: 'fixed', top: 72, right: 16, zIndex: 1100, display: 'flex', flexDirection: 'column', gap: 8 }}>
      {toasts.map(t => (
        <div
          key={t.id}
          style={{
            background: '#15803D',
            color: '#fff',
            borderRadius: 10,
            padding: '12px 18px',
            fontSize: 16,
            fontWeight: 600,
            boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <span style={{ fontSize: 18 }}>✓</span>
          已到达 {t.table_no}
        </div>
      ))}
    </div>
  );
}

// ─── Timeline Panel ───

function PatrolTimeline({
  summary,
  onClose,
}: {
  summary: PatrolSummary | null;
  onClose: () => void;
}) {
  return (
    <div style={{
      position: 'fixed',
      right: 16,
      bottom: 212,
      width: 300,
      maxHeight: '55vh',
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
          今日巡台记录
          {summary && (
            <span style={{ marginLeft: 8, fontSize: 16, color: '#FF6B35', fontWeight: 400 }}>
              共{summary.tables_visited_count}桌
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

      {/* Timeline list */}
      <div style={{ overflowY: 'auto', flex: 1, padding: '8px 0' }}>
        {!summary ? (
          <div style={{ padding: '24px 16px', textAlign: 'center', color: '#64748b', fontSize: 16 }}>
            加载中…
          </div>
        ) : summary.timeline.length === 0 ? (
          <div style={{ padding: '24px 16px', textAlign: 'center', color: '#64748b', fontSize: 16 }}>
            今日暂无巡台记录
          </div>
        ) : (
          <div style={{ padding: '0 16px' }}>
            {summary.timeline.map((item, idx) => (
              <div
                key={item.checkin_id}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 12,
                  paddingBottom: idx < summary.timeline.length - 1 ? 16 : 8,
                }}
              >
                {/* Timeline dot + line */}
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
                  <div style={{
                    width: 10,
                    height: 10,
                    borderRadius: '50%',
                    background: '#FF6B35',
                    marginTop: 4,
                  }} />
                  {idx < summary.timeline.length - 1 && (
                    <div style={{ width: 2, flex: 1, minHeight: 16, background: '#1a3040', marginTop: 2 }} />
                  )}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 16, fontWeight: 600, color: '#fff' }}>
                    {item.table_no}
                  </div>
                  <div style={{ fontSize: 14, color: '#64748b', marginTop: 2 }}>
                    {formatTime(item.checked_at)}
                    {item.signal_strength != null && (
                      <span style={{ marginLeft: 8 }}>信号 {item.signal_strength} dBm</span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── PatrolAutoCheckin (Main Component) ───

export function PatrolAutoCheckin({
  storeId,
  crewId: crewIdProp,
}: {
  storeId: string;
  crewId?: string;
}) {
  const crewId = crewIdProp || getCrewId();

  const [bleStatus, setBleStatus] = useState<'scanning' | 'detected' | 'none'>('none');
  const [visitedCount, setVisitedCount] = useState(0);
  const [summary, setSummary] = useState<PatrolSummary | null>(null);
  const [open, setOpen] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [manualLoading, setManualLoading] = useState(false);

  // Track beacons recently checked in (deduplicate within 5 min)
  const recentCheckinsRef = useRef<Map<string, number>>(new Map());
  const toastCounterRef = useRef(0);
  const mountedRef = useRef(true);

  // ── Fetch summary ──
  const fetchSummary = useCallback(async () => {
    if (!storeId) return;
    try {
      const today = new Date().toISOString().slice(0, 10);
      const data = await txFetch<{ ok: boolean; data: PatrolSummary }>(
        `/api/v1/crew/patrol-summary?date=${today}`
      );
      if (mountedRef.current && data?.data) {
        setSummary(data.data);
        setVisitedCount(data.data.tables_visited_count);
      }
    } catch {
      // ignore fetch errors
    }
  }, [storeId]);

  // ── Checkin ──
  const doCheckin = useCallback(async (beacon: BLEBeacon) => {
    if (!storeId) return;
    const key = `${crewId}:${beacon.table_no}`;
    const last = recentCheckinsRef.current.get(key) ?? 0;
    if (Date.now() - last < 5 * 60 * 1000) return; // 5-min dedup

    try {
      const result = await txFetch<{ ok: boolean; data: PatrolCheckinResponse }>(
        '/api/v1/crew/patrol-checkin',
        {
          method: 'POST',
          body: JSON.stringify({
            table_no: beacon.table_no,
            beacon_id: beacon.beacon_id,
            signal_strength: beacon.signal_strength,
          }),
        }
      );
      if (!mountedRef.current) return;
      if (result?.ok) {
        recentCheckinsRef.current.set(key, Date.now());
        setVisitedCount(prev => prev + 1);
        // Show toast
        const toastId = ++toastCounterRef.current;
        setToasts(prev => [...prev, { id: toastId, table_no: beacon.table_no }]);
        setTimeout(() => {
          if (mountedRef.current) {
            setToasts(prev => prev.filter(t => t.id !== toastId));
          }
        }, 3000);
        // Refresh summary if panel open
        if (open) fetchSummary();
      }
    } catch {
      // ignore checkin errors
    }
  }, [storeId, crewId, open, fetchSummary]);

  // ── BLE scan loop (every 10s) ──
  useEffect(() => {
    mountedRef.current = true;
    if (!storeId) return;

    let cancelled = false;

    async function runScan() {
      if (cancelled) return;
      setBleStatus('scanning');
      try {
        const beacons = await scanBLEBeacons();
        if (cancelled) return;
        if (beacons.length > 0) {
          setBleStatus('detected');
          // Checkin for strongest signal beacon
          const best = beacons.reduce((a, b) =>
            (b.signal_strength ?? -999) > (a.signal_strength ?? -999) ? b : a
          );
          await doCheckin(best);
        } else {
          setBleStatus('none');
        }
      } catch {
        if (!cancelled) setBleStatus('none');
      }
    }

    runScan();
    const intervalId = setInterval(runScan, 10_000);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [storeId, doCheckin]);

  // ── Initial summary fetch ──
  useEffect(() => {
    mountedRef.current = true;
    fetchSummary();
    return () => { mountedRef.current = false; };
  }, [fetchSummary]);

  // ── Open panel: fetch summary ──
  useEffect(() => {
    if (open) fetchSummary();
  }, [open, fetchSummary]);

  // ── Manual checkin ──
  async function handleManualCheckin() {
    if (!storeId || manualLoading) return;
    setManualLoading(true);
    try {
      const result = await txFetch<{ ok: boolean; data: PatrolCheckinResponse }>(
        '/api/v1/crew/patrol-checkin',
        {
          method: 'POST',
          body: JSON.stringify({
            table_no: '手动',
            beacon_id: null,
            signal_strength: null,
          }),
        }
      );
      if (!mountedRef.current) return;
      if (result?.ok) {
        setVisitedCount(prev => prev + 1);
        const toastId = ++toastCounterRef.current;
        setToasts(prev => [...prev, { id: toastId, table_no: '手动打卡' }]);
        setTimeout(() => {
          if (mountedRef.current) {
            setToasts(prev => prev.filter(t => t.id !== toastId));
          }
        }, 3000);
        if (open) fetchSummary();
      }
    } catch {
      // ignore
    } finally {
      if (mountedRef.current) setManualLoading(false);
    }
  }

  // ─── BLE status dot ───
  const statusDot = bleStatus === 'detected'
    ? '#22C55E'
    : bleStatus === 'scanning'
    ? '#F59E0B'
    : '#475569';

  const statusLabel = bleStatus === 'detected'
    ? '已感应到桌台'
    : bleStatus === 'scanning'
    ? '扫描中'
    : '未检测到信标';

  return (
    <>
      <CheckinToast toasts={toasts} />

      {open && (
        <PatrolTimeline summary={summary} onClose={() => setOpen(false)} />
      )}

      {/* Floating badge — positioned above ServiceBellBadge (bottom: 144 vs 80) */}
      <div style={{
        position: 'fixed',
        right: 16,
        bottom: 148,
        zIndex: 998,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        gap: 6,
      }}>
        {/* Stats pill (tap to expand timeline) */}
        <button
          onClick={() => setOpen(prev => !prev)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            background: '#112228',
            border: '1px solid #1a3040',
            borderRadius: 20,
            padding: '6px 12px 6px 10px',
            cursor: 'pointer',
            boxShadow: '0 2px 8px rgba(0,0,0,0.4)',
          }}
        >
          <span style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: statusDot,
            flexShrink: 0,
          }} />
          <span style={{ fontSize: 16, color: '#94a3b8', whiteSpace: 'nowrap' }}>
            {statusLabel}
          </span>
          <span style={{ fontSize: 16, fontWeight: 700, color: '#FF6B35', marginLeft: 4 }}>
            {visitedCount}桌
          </span>
        </button>

        {/* Main patrol FAB */}
        <button
          onClick={() => setOpen(prev => !prev)}
          aria-label="巡台签到"
          style={{
            width: 56,
            height: 56,
            minWidth: 56,
            minHeight: 56,
            borderRadius: '50%',
            background: bleStatus === 'detected' ? '#15803D' : '#1a3040',
            border: `2px solid ${bleStatus === 'detected' ? '#22C55E' : '#1a3040'}`,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 26,
            boxShadow: bleStatus === 'detected'
              ? '0 4px 16px rgba(34,197,94,0.4)'
              : '0 2px 8px rgba(0,0,0,0.4)',
            transition: 'background 0.3s, border-color 0.3s',
          }}
        >
          🗺️
        </button>

        {/* Manual checkin fallback */}
        <button
          onClick={handleManualCheckin}
          disabled={manualLoading}
          style={{
            fontSize: 14,
            color: manualLoading ? '#475569' : '#64748b',
            background: 'transparent',
            border: 'none',
            cursor: manualLoading ? 'default' : 'pointer',
            padding: '4px 0',
            textDecoration: 'underline',
            minHeight: 32,
          }}
        >
          {manualLoading ? '记录中…' : '记录巡台'}
        </button>
      </div>
    </>
  );
}
