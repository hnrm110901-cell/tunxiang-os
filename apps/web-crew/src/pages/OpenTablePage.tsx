/**
 * 开台页面 — 选择空闲桌台 → 输入人数 → 确认开台 → 跳转点菜
 * 移动端竖屏优先，最小字体16px，热区>=48px
 */
import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { fetchTables, openTable } from '../api/tablesApi';
import type { TableInfo } from '../api/tablesApi';
import { updateReservationStatus } from '../api/reservationApi';

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
  const [searchParams] = useSearchParams();
  const prefilledTable = searchParams.get('table') || '';
  const isPrefilled = searchParams.get('prefilled') === 'true';

  const storeId = (window as any).__STORE_ID__ || 'store_001';

  // 预订直通车参数
  const reservationId = searchParams.get('reservation_id') || '';
  const reservationName = searchParams.get('name') || '';
  const prefilledGuests = parseInt(searchParams.get('guests') || '0', 10);
  const isFromReservation = Boolean(reservationId);

  const [tables, setTables] = useState<TableInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(prefilledTable || null);
  const [guestCount, setGuestCount] = useState(prefilledGuests > 0 ? prefilledGuests : 2);
  const [seatModeEnabled, setSeatModeEnabled] = useState(false);
  const [seatCount, setSeatCount] = useState(2);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
    fetchTables(storeId)
      .then(res => setTables(res.items))
      .catch(err => setError(err instanceof Error ? err.message : '加载桌台失败'))
      .finally(() => setLoading(false));
  }, [storeId]);

  const idleTables = tables.filter(t => t.status === 'idle');
  const otherTables = tables.filter(t => t.status !== 'idle');

  const handleConfirm = async () => {
    if (!selected) return;
    setConfirming(true);
    setError('');
    try {
      const result = await openTable(storeId, selected, guestCount);

      // 如果来自预订直通车，同步将预订状态更新为 'seated'
      if (isFromReservation && reservationId) {
        try {
          await updateReservationStatus(reservationId, 'seat', { table_no: selected });
        } catch {
          // 预订状态更新失败不阻断开台流程，静默处理
        }
      }

      const remarkParam = isFromReservation && reservationName
        ? `&remark=${encodeURIComponent(`预订顾客：${reservationName}`)}`
        : '';
      const url = `/order-full?table=${selected}&guests=${guestCount}&order_id=${result.order_id}${seatModeEnabled ? `&seat_count=${seatCount}` : ''}${remarkParam}`;
      navigate(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : '开台失败，请重试');
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div style={{ padding: '16px 12px 160px', background: C.bg, minHeight: '100vh' }}>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 4px' }}>
        开台
      </h1>
      <p style={{ fontSize: 16, color: C.muted, margin: '0 0 16px' }}>
        选择空闲桌台并确认开台
      </p>

      {isPrefilled && !isFromReservation && (
        <div style={{
          background: 'rgba(255, 107, 53, 0.15)',
          border: '1px solid #FF6B35',
          borderRadius: 8,
          padding: '10px 14px',
          marginBottom: 12,
          fontSize: 14,
          color: '#FF9F0A',
        }}>
          已扫码识别桌台 {prefilledTable}，请确认人数后开台
        </div>
      )}

      {isFromReservation && (
        <div style={{
          background: 'rgba(255, 107, 53, 0.12)',
          border: '1px solid #FF6B35',
          borderRadius: 8,
          padding: '12px 14px',
          marginBottom: 12,
          fontSize: 15,
          color: '#FF9F0A',
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>预订直通车</div>
          <div>
            顾客：<strong>{reservationName}</strong> · {guestCount}人
            {prefilledTable ? `  桌台：${prefilledTable}` : ''}
          </div>
          <div style={{ fontSize: 13, marginTop: 4, color: '#94a3b8' }}>
            开台后将自动同步预订状态为"已入座"
          </div>
        </div>
      )}

      {/* 桌台列表 */}
      {loading ? (
        <div style={{ padding: '40px 0', textAlign: 'center', color: C.muted, fontSize: 16 }}>
          加载中...
        </div>
      ) : (
        <>
          {/* 可选桌台（空闲） */}
          <h2 style={{ fontSize: 17, fontWeight: 600, color: C.white, margin: '0 0 10px' }}>
            空闲桌台（{idleTables.length}）
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 20 }}>
            {idleTables.map(t => {
              const isSelected = selected === t.table_no;
              const isPrefilledThis = isPrefilled && prefilledTable === t.table_no;
              return (
                <button
                  key={t.table_no}
                  onClick={() => !isPrefilled && setSelected(isSelected ? null : t.table_no)}
                  disabled={isPrefilled && !isPrefilledThis}
                  style={{
                    minHeight: 80,
                    padding: 12,
                    background: isSelected ? `${C.accent}22` : C.card,
                    border: isSelected ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                    borderRadius: 12,
                    color: C.white,
                    cursor: isPrefilled ? (isPrefilledThis ? 'default' : 'not-allowed') : 'pointer',
                    textAlign: 'center',
                    transition: 'transform .15s',
                    opacity: isPrefilled && !isPrefilledThis ? 0.4 : 1,
                  }}
                >
                  <div style={{ fontSize: 20, fontWeight: 700 }}>{t.table_no}</div>
                  <div style={{ fontSize: 16, color: C.muted, marginTop: 4 }}>{t.capacity}人桌</div>
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
                    key={t.table_no}
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
                    <div style={{ fontSize: 20, fontWeight: 700, color: C.white }}>{t.table_no}</div>
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

          {/* 座位模式（AA制分账） */}
          <div style={{
            background: C.card,
            border: `1px solid ${seatModeEnabled ? C.accent : C.border}`,
            borderRadius: 12,
            padding: '12px 14px',
            marginBottom: 12,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 600, color: C.text }}>座位模式（AA制分账）</div>
                <div style={{ fontSize: 14, color: C.muted, marginTop: 2 }}>每道菜可指定归属座位</div>
              </div>
              <button
                onClick={() => setSeatModeEnabled(v => !v)}
                style={{
                  width: 56, height: 30, borderRadius: 15,
                  background: seatModeEnabled ? C.accent : C.muted,
                  border: 'none', cursor: 'pointer', position: 'relative',
                  transition: 'background 0.2s',
                  flexShrink: 0,
                }}
              >
                <div style={{
                  position: 'absolute', top: 3,
                  left: seatModeEnabled ? 28 : 4,
                  width: 24, height: 24, borderRadius: '50%',
                  background: C.white, transition: 'left 0.2s',
                }} />
              </button>
            </div>

            {seatModeEnabled && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12 }}>
                <span style={{ fontSize: 16, color: C.text }}>座位数</span>
                <button
                  onClick={() => setSeatCount(Math.max(1, seatCount - 1))}
                  style={{
                    width: 48, height: 48, borderRadius: 12,
                    background: '#0B1A20', border: `1px solid ${C.border}`,
                    color: C.white, fontSize: 24, cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  -
                </button>
                <span style={{ fontSize: 24, fontWeight: 700, color: C.accent, minWidth: 32, textAlign: 'center' }}>
                  {seatCount}
                </span>
                <button
                  onClick={() => setSeatCount(Math.min(20, seatCount + 1))}
                  style={{
                    width: 48, height: 48, borderRadius: 12,
                    background: '#0B1A20', border: `1px solid ${C.border}`,
                    color: C.white, fontSize: 24, cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  +
                </button>
              </div>
            )}
          </div>
          {error ? (
            <div style={{
              marginBottom: 10,
              padding: '10px 14px',
              background: 'rgba(163, 45, 45, 0.15)',
              border: `1px solid ${C.danger}`,
              borderRadius: 8,
              fontSize: 16,
              color: '#f87171',
            }}>
              {error}
            </div>
          ) : null}
          <button
            onClick={handleConfirm}
            disabled={confirming}
            style={{
              width: '100%', minHeight: 56, borderRadius: 12,
              background: confirming ? C.muted : C.accent,
              color: C.white, border: 'none', fontSize: 18, fontWeight: 700,
              cursor: confirming ? 'not-allowed' : 'pointer',
              opacity: confirming ? 0.6 : 1,
              transition: 'transform .15s',
            }}
          >
            {confirming ? '开台中...' : '确认开台'}
          </button>
        </div>
      )}
    </div>
  );
}
