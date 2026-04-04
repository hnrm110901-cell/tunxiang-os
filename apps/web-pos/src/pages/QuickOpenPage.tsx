/**
 * 快速开台页 — 选桌 → 选人数/服务员 → 开台并点餐
 * 只显示空闲桌 · 大按钮触控优先 · 88px高主操作
 */
import { useState, useEffect, useCallback, type CSSProperties } from 'react';
import { useNavigate } from 'react-router-dom';

/* ─── 颜色常量 ─── */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1A3A48',
  accent: '#FF6B35',
  green: '#10B981',
  muted: '#64748b',
  text: '#E0E0E0',
  white: '#FFFFFF',
};

/* ─── 类型 ─── */
interface FreeTable {
  table_no: string;
  area: string;
  seats: number;
}

/* ─── Mock空闲桌 ─── */
const MOCK_FREE: FreeTable[] = [
  { table_no: 'A01', area: '大厅', seats: 4 },
  { table_no: 'A04', area: '大厅', seats: 4 },
  { table_no: 'B02', area: '包厢A', seats: 10 },
  { table_no: 'B04', area: '包厢A', seats: 8 },
  { table_no: 'C03', area: '包厢B', seats: 6 },
  { table_no: 'D01', area: '室外', seats: 4 },
  { table_no: 'E01', area: '吧台', seats: 1 },
  { table_no: 'E03', area: '吧台', seats: 1 },
];

const WAITERS = ['小王', '小李', '小张', '小陈', '小赵'];
const GUEST_OPTIONS = Array.from({ length: 20 }, (_, i) => i + 1);

const BASE = 'http://localhost:8001';
const vibrate = () => { try { navigator.vibrate?.(50); } catch { /* no-op */ } };

/* ─── 组件 ─── */
export function QuickOpenPage() {
  const navigate = useNavigate();
  const [freeTables, setFreeTables] = useState<FreeTable[]>(MOCK_FREE);
  const [selected, setSelected] = useState<FreeTable | null>(null);
  const [guests, setGuests] = useState(2);
  const [waiter, setWaiter] = useState(WAITERS[0]);
  const [loading, setLoading] = useState(false);

  /* 加载空闲桌台 */
  const loadFree = useCallback(async () => {
    try {
      const resp = await fetch(`${BASE}/api/v1/trade/tables?store_id=default`, {
        headers: { 'Content-Type': 'application/json' },
      });
      const json: unknown = await resp.json();
      const typed = json as { ok: boolean; data?: { tables?: Array<{ table_no: string; area: string; seats: number; status: string }> } };
      if (typed.ok && typed.data?.tables) {
        const free = typed.data.tables
          .filter(t => t.status === 'free')
          .map(t => ({ table_no: t.table_no, area: t.area, seats: t.seats }));
        if (free.length > 0) setFreeTables(free);
      }
    } catch {
      // Mock fallback
    }
  }, []);

  useEffect(() => { loadFree(); }, [loadFree]);

  /* 开台并跳转点餐 */
  const handleOpenAndOrder = async () => {
    if (!selected || loading) return;
    vibrate();
    setLoading(true);
    try {
      await fetch(`${BASE}/api/v1/trade/tables/${encodeURIComponent(selected.table_no)}/open`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ guest_count: guests, waiter_name: waiter }),
      });
    } catch {
      // Mock: 仍然跳转
    }
    setLoading(false);
    navigate(`/open-table/${selected.table_no}`);
  };

  const btnBase: CSSProperties = {
    minHeight: 48, minWidth: 48, border: 'none', borderRadius: 8,
    cursor: 'pointer', fontSize: 16, fontWeight: 700,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: C.bg, color: C.text }}>
      {/* 顶部 */}
      <div style={{
        padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 16,
        borderBottom: `1px solid ${C.border}`, flexShrink: 0,
      }}>
        <button onClick={() => { vibrate(); navigate(-1); }} style={{ ...btnBase, padding: '8px 16px', background: C.card, border: `1px solid ${C.border}`, color: C.text }}>
          {'<'} 返回
        </button>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: C.white }}>快速开台</h1>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
        {/* 第一步：选桌 */}
        <div style={{ marginBottom: 24 }}>
          <h2 style={{ margin: '0 0 12px', fontSize: 18, color: C.muted }}>
            第一步：选择空闲桌台
          </h2>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))',
            gap: 10,
          }}>
            {freeTables.map(t => {
              const isSel = selected?.table_no === t.table_no;
              return (
                <button
                  key={t.table_no}
                  onClick={() => { vibrate(); setSelected(t); }}
                  style={{
                    ...btnBase, height: 80, padding: 8, textAlign: 'center',
                    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                    background: isSel ? `${C.accent}33` : `${C.green}22`,
                    border: `2px solid ${isSel ? C.accent : C.green}`,
                    color: C.white, borderRadius: 10,
                    transition: 'transform 150ms ease',
                  }}
                  onPointerDown={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(0.95)'; }}
                  onPointerUp={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
                  onPointerLeave={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
                >
                  <div style={{ fontSize: 20, fontWeight: 700 }}>{t.table_no}</div>
                  <div style={{ fontSize: 11, color: C.muted }}>{t.area} · {t.seats}座</div>
                </button>
              );
            })}
          </div>
        </div>

        {/* 选桌后展开人数+服务员 */}
        {selected && (
          <>
            {/* 第二步：人数 */}
            <div style={{ marginBottom: 24 }}>
              <h2 style={{ margin: '0 0 12px', fontSize: 18, color: C.muted }}>
                第二步：用餐人数 — 已选 <span style={{ color: C.accent }}>{selected.table_no}</span>
              </h2>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {GUEST_OPTIONS.map(n => (
                  <button
                    key={n}
                    onClick={() => { vibrate(); setGuests(n); }}
                    style={{
                      ...btnBase, width: 56, height: 56, padding: 0, fontSize: 18,
                      background: guests === n ? C.accent : `${C.border}44`,
                      color: guests === n ? C.white : C.text,
                      borderRadius: 10,
                    }}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>

            {/* 第三步：服务员 */}
            <div style={{ marginBottom: 24 }}>
              <h2 style={{ margin: '0 0 12px', fontSize: 18, color: C.muted }}>
                第三步：选择服务员
              </h2>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {WAITERS.map(w => (
                  <button
                    key={w}
                    onClick={() => { vibrate(); setWaiter(w); }}
                    style={{
                      ...btnBase, padding: '10px 24px',
                      background: waiter === w ? C.accent : `${C.border}44`,
                      color: waiter === w ? C.white : C.text,
                    }}
                  >
                    {w}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      {/* 底部大按钮 */}
      <div style={{ padding: '16px 20px', borderTop: `1px solid ${C.border}`, flexShrink: 0 }}>
        <button
          onClick={handleOpenAndOrder}
          disabled={!selected || loading}
          style={{
            width: '100%', height: 88, border: 'none', borderRadius: 12,
            background: selected ? C.accent : C.border,
            color: C.white, fontSize: 22, fontWeight: 700, cursor: selected ? 'pointer' : 'not-allowed',
            opacity: loading ? 0.6 : 1,
            transition: 'background 200ms ease',
          }}
        >
          {loading
            ? '开台中...'
            : selected
              ? `开台并点餐 — ${selected.table_no}（${guests}人）`
              : '请先选择桌台'}
        </button>
      </div>
    </div>
  );
}
