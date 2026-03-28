/**
 * 开台页面 — 选择空闲桌台 → 输入人数 → 确认开台 → 跳转点菜
 * 移动端竖屏优先，最小字体16px，热区>=48px
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  accentActive: '#E55A28',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  danger: '#A32D2D',
};

/* ---------- Mock 数据 ---------- */
const MOCK_TABLES = [
  { no: 'A01', seats: 4, status: 'idle' as const },
  { no: 'A02', seats: 4, status: 'occupied' as const },
  { no: 'A03', seats: 6, status: 'idle' as const },
  { no: 'A04', seats: 4, status: 'idle' as const },
  { no: 'B01', seats: 8, status: 'occupied' as const },
  { no: 'B02', seats: 10, status: 'idle' as const },
  { no: 'B03', seats: 8, status: 'reserved' as const },
  { no: 'B04', seats: 6, status: 'idle' as const },
  { no: 'C01', seats: 12, status: 'idle' as const },
  { no: 'C02', seats: 10, status: 'occupied' as const },
];

type TableStatus = 'idle' | 'occupied' | 'reserved' | 'cleaning';

function statusLabel(s: TableStatus): string {
  const map: Record<TableStatus, string> = { idle: '空闲', occupied: '就餐中', reserved: '已预定', cleaning: '清台中' };
  return map[s];
}

function statusColor(s: TableStatus): string {
  const map: Record<TableStatus, string> = { idle: C.green, occupied: C.accent, reserved: '#facc15', cleaning: C.muted };
  return map[s];
}

/* ---------- 组件 ---------- */
export function OpenTablePage() {
  const navigate = useNavigate();
  const [selected, setSelected] = useState<string | null>(null);
  const [guestCount, setGuestCount] = useState(2);
  const [confirming, setConfirming] = useState(false);

  const idleTables = MOCK_TABLES.filter(t => t.status === 'idle');
  const otherTables = MOCK_TABLES.filter(t => t.status !== 'idle');

  const handleConfirm = () => {
    if (!selected) return;
    setConfirming(true);
    // 模拟 API 调用
    setTimeout(() => {
      navigate(`/order-full?table=${selected}&guests=${guestCount}`);
    }, 600);
  };

  return (
    <div style={{ padding: '16px 12px 160px', background: C.bg, minHeight: '100vh' }}>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 4px' }}>
        开台
      </h1>
      <p style={{ fontSize: 16, color: C.muted, margin: '0 0 16px' }}>
        选择空闲桌台并确认开台
      </p>

      {/* 可选桌台（空闲） */}
      <h2 style={{ fontSize: 17, fontWeight: 600, color: C.white, margin: '0 0 10px' }}>
        空闲桌台（{idleTables.length}）
      </h2>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 20 }}>
        {idleTables.map(t => {
          const isSelected = selected === t.no;
          return (
            <button
              key={t.no}
              onClick={() => setSelected(isSelected ? null : t.no)}
              style={{
                minHeight: 80,
                padding: 12,
                background: isSelected ? `${C.accent}22` : C.card,
                border: isSelected ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                borderRadius: 12,
                color: C.white,
                cursor: 'pointer',
                textAlign: 'center',
                transition: 'transform .15s',
              }}
            >
              <div style={{ fontSize: 20, fontWeight: 700 }}>{t.no}</div>
              <div style={{ fontSize: 16, color: C.muted, marginTop: 4 }}>{t.seats}人桌</div>
            </button>
          );
        })}
      </div>

      {/* 其他桌台（不可选） */}
      {otherTables.length > 0 && (
        <>
          <h2 style={{ fontSize: 17, fontWeight: 600, color: C.muted, margin: '0 0 10px' }}>
            其他桌台
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 20 }}>
            {otherTables.map(t => (
              <div
                key={t.no}
                style={{
                  minHeight: 80,
                  padding: 12,
                  background: C.card,
                  border: `1px solid ${C.border}`,
                  borderRadius: 12,
                  textAlign: 'center',
                  opacity: 0.5,
                }}
              >
                <div style={{ fontSize: 20, fontWeight: 700, color: C.white }}>{t.no}</div>
                <div style={{
                  fontSize: 16, marginTop: 4,
                  color: statusColor(t.status),
                }}>
                  {statusLabel(t.status)}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* 底部操作区 - 人数 + 确认 */}
      {selected && (
        <div style={{
          position: 'fixed', bottom: 56, left: 0, right: 0,
          padding: '14px 16px', background: C.bg,
          borderTop: `1px solid ${C.border}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <span style={{ fontSize: 16, color: C.text }}>
              桌号 <span style={{ fontWeight: 700, color: C.accent }}>{selected}</span>
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: 16, color: C.text }}>人数</span>
              <button
                onClick={() => setGuestCount(Math.max(1, guestCount - 1))}
                style={{
                  width: 48, height: 48, borderRadius: 12,
                  background: C.card, border: `1px solid ${C.border}`,
                  color: C.white, fontSize: 24, cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                -
              </button>
              <span style={{ fontSize: 24, fontWeight: 700, color: C.white, minWidth: 32, textAlign: 'center' }}>
                {guestCount}
              </span>
              <button
                onClick={() => setGuestCount(guestCount + 1)}
                style={{
                  width: 48, height: 48, borderRadius: 12,
                  background: C.card, border: `1px solid ${C.border}`,
                  color: C.white, fontSize: 24, cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                +
              </button>
            </div>
          </div>
          <button
            onClick={handleConfirm}
            disabled={confirming}
            style={{
              width: '100%', minHeight: 56, borderRadius: 12,
              background: confirming ? C.muted : C.accent,
              color: C.white, border: 'none', fontSize: 18, fontWeight: 700,
              cursor: confirming ? 'not-allowed' : 'pointer',
              opacity: confirming ? 0.6 : 1,
            }}
          >
            {confirming ? '开台中...' : '确认开台'}
          </button>
        </div>
      )}
    </div>
  );
}
