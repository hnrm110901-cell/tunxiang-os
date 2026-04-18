/**
 * WineStorageQuickView — 存酒快查弹窗组件
 * 终端：Store-POS（安卓 POS / iPad）
 * 场景：开台时若台位有存酒记录，显示橙色角标提示，点击展开存酒列表
 *
 * 设计决策：
 *   - 核心用户动作：收银员快速确认/取出存酒，不打断开台流程
 *   - 物理环境：站在收银台，可能戴手套，必须大按钮大字体
 *   - 最可能出错：取酒数量填错 → 二次确认 + 数字键盘
 *   - 不使用 Ant Design；全部 TXTouch 风格
 */
import React, { useCallback, useEffect, useState } from 'react';
import { txFetch } from '../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface WineRecord {
  id: string;
  wine_name: string;
  wine_brand: string | null;
  wine_spec: string | null;
  remaining_quantity: number;
  unit: string;
  stored_at: string;
  expiry_date: string | null;
  expiry_warning: boolean;
  days_until_expiry: number | null;
  status: string;
  member_name: string | null;
  cabinet_position: string | null;
}

interface WineStorageSummary {
  table_id: string;
  table_name: string;
  active_count: number;
  total_remaining: number;
  records: WineRecord[];
}

interface TakeWineState {
  record: WineRecord;
  quantity: string;
  loading: boolean;
}

interface Props {
  tableId: string;
  tableName: string;
  /** 取酒成功后的回调，父组件可刷新桌台状态 */
  onTakeSuccess?: (recordId: string, qty: number) => void;
}

// ─── 样式常量（TXTouch 规范：最小字体16px，最小点击区域48×48px） ─────────────

const CSS = {
  // 角标容器（绝对定位用于叠加在开台确认按钮旁）
  badge: {
    position: 'relative' as const,
    display: 'inline-flex',
    alignItems: 'center',
    gap: 8,
    background: '#FF6B35',
    color: '#FFFFFF',
    padding: '10px 16px',
    borderRadius: 12,
    fontSize: 16,
    fontWeight: 700,
    cursor: 'pointer',
    minHeight: 48,
    userSelect: 'none' as const,
    transition: 'transform 200ms ease, background 200ms ease',
    WebkitTapHighlightColor: 'transparent',
    boxShadow: '0 4px 12px rgba(255,107,53,0.35)',
  },
  dot: {
    width: 10,
    height: 10,
    borderRadius: '50%',
    background: '#FFFFFF',
    flexShrink: 0,
  },
  // 底部半屏弹窗
  overlay: {
    position: 'fixed' as const,
    inset: 0,
    background: 'rgba(0,0,0,0.45)',
    zIndex: 1200,
    display: 'flex',
    alignItems: 'flex-end',
  },
  sheet: {
    width: '100%',
    maxHeight: '72vh',
    background: '#FFFFFF',
    borderRadius: '20px 20px 0 0',
    display: 'flex',
    flexDirection: 'column' as const,
    boxShadow: '0 -8px 24px rgba(0,0,0,0.12)',
    animation: 'slideUp 300ms ease-out',
  },
  sheetHeader: {
    padding: '20px 20px 12px',
    borderBottom: '1px solid #E8E6E1',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexShrink: 0,
  },
  sheetTitle: {
    fontSize: 20,
    fontWeight: 700,
    color: '#2C2C2A',
    margin: 0,
  },
  closeBtn: {
    width: 48,
    height: 48,
    borderRadius: 24,
    background: '#F0EDE6',
    border: 'none',
    fontSize: 20,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: '#5F5E5A',
    flexShrink: 0,
  },
  scrollArea: {
    overflowY: 'auto' as const,
    WebkitOverflowScrolling: 'touch' as const,
    padding: '0 20px 20px',
    flex: 1,
  },
  card: (warning: boolean): React.CSSProperties => ({
    background: '#FFFFFF',
    border: `2px solid ${warning ? '#A32D2D' : '#E8E6E1'}`,
    borderRadius: 12,
    padding: '16px',
    marginTop: 12,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  }),
  cardRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  wineName: {
    fontSize: 18,
    fontWeight: 700,
    color: '#2C2C2A',
  },
  wineSpec: {
    fontSize: 16,
    color: '#5F5E5A',
  },
  qtyBadge: (warning: boolean): React.CSSProperties => ({
    background: warning ? '#FEE2E2' : '#FFF3ED',
    color: warning ? '#A32D2D' : '#FF6B35',
    padding: '4px 10px',
    borderRadius: 8,
    fontSize: 16,
    fontWeight: 700,
  }),
  dateRow: {
    display: 'flex',
    gap: 16,
    flexWrap: 'wrap' as const,
  },
  dateLabel: (danger: boolean): React.CSSProperties => ({
    fontSize: 16,
    color: danger ? '#A32D2D' : '#5F5E5A',
    fontWeight: danger ? 700 : 400,
  }),
  expiryWarning: {
    background: '#FEE2E2',
    color: '#A32D2D',
    padding: '6px 10px',
    borderRadius: 8,
    fontSize: 16,
    fontWeight: 600,
  },
  takeBtn: {
    height: 56,
    background: '#FF6B35',
    color: '#FFFFFF',
    border: 'none',
    borderRadius: 12,
    fontSize: 18,
    fontWeight: 700,
    cursor: 'pointer',
    width: '100%',
    marginTop: 12,
    transition: 'transform 200ms ease',
    WebkitTapHighlightColor: 'transparent',
  },
  // 取酒弹窗
  confirmOverlay: {
    position: 'fixed' as const,
    inset: 0,
    background: 'rgba(0,0,0,0.55)',
    zIndex: 1300,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 20,
  },
  confirmBox: {
    background: '#FFFFFF',
    borderRadius: 16,
    padding: 24,
    width: '100%',
    maxWidth: 400,
    boxShadow: '0 8px 24px rgba(0,0,0,0.15)',
  },
  confirmTitle: {
    fontSize: 20,
    fontWeight: 700,
    color: '#2C2C2A',
    marginBottom: 16,
  },
  numInput: {
    width: '100%',
    height: 56,
    fontSize: 24,
    fontWeight: 700,
    textAlign: 'center' as const,
    border: '2px solid #E8E6E1',
    borderRadius: 12,
    color: '#2C2C2A',
    background: '#FFFFFF',
    marginBottom: 16,
    boxSizing: 'border-box' as const,
    outline: 'none',
  },
  btnRow: {
    display: 'flex',
    gap: 12,
  },
  cancelBtn: {
    flex: 1,
    height: 56,
    background: '#F0EDE6',
    color: '#5F5E5A',
    border: 'none',
    borderRadius: 12,
    fontSize: 18,
    fontWeight: 600,
    cursor: 'pointer',
  },
  confirmBtn: (disabled: boolean): React.CSSProperties => ({
    flex: 1,
    height: 56,
    background: disabled ? '#E8E6E1' : '#FF6B35',
    color: disabled ? '#B4B2A9' : '#FFFFFF',
    border: 'none',
    borderRadius: 12,
    fontSize: 18,
    fontWeight: 700,
    cursor: disabled ? 'not-allowed' : 'pointer',
    transition: 'background 200ms ease',
  }),
  emptyState: {
    padding: '40px 20px',
    textAlign: 'center' as const,
    color: '#5F5E5A',
    fontSize: 16,
  },
  loadingState: {
    padding: '40px 20px',
    textAlign: 'center' as const,
    color: '#B4B2A9',
    fontSize: 16,
  },
};

// ─── 工具函数 ────────────────────────────────────────────────────────────────

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    stored: '存储中',
    partial: '部分取出',
    taken: '已取完',
    expired: '已过期',
    written_off: '已核销',
  };
  return map[status] || status;
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function WineStorageQuickView({ tableId, tableName, onTakeSuccess }: Props) {
  const [summary, setSummary] = useState<WineStorageSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [takeState, setTakeState] = useState<TakeWineState | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 加载存酒快查数据
  const loadSummary = useCallback(async () => {
    if (!tableId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await txFetch<WineStorageSummary>(
        `/api/v1/wine-storage/by-table/${encodeURIComponent(tableId)}`
      );
      setSummary(data);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载失败';
      setError(msg);
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [tableId]);

  // 组件挂载或 tableId 变化时加载
  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  const handleOpenSheet = () => {
    setOpen(true);
    void loadSummary();
  };

  const handleTake = (record: WineRecord) => {
    setTakeState({ record, quantity: '1', loading: false });
  };

  const handleTakeConfirm = async () => {
    if (!takeState) return;
    const qty = parseInt(takeState.quantity, 10);
    if (!qty || qty <= 0 || qty > takeState.record.remaining_quantity) return;

    setTakeState(prev => prev ? { ...prev, loading: true } : null);
    try {
      await txFetch(`/api/v1/wine-storage/${takeState.record.id}/take`, {
        method: 'POST',
        body: JSON.stringify({ quantity: qty }),
      });
      onTakeSuccess?.(takeState.record.id, qty);
      setTakeState(null);
      void loadSummary();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '取酒失败';
      alert(msg);
      setTakeState(prev => prev ? { ...prev, loading: false } : null);
    }
  };

  // 没有存酒记录时不显示角标
  if (!loading && (!summary || summary.active_count === 0)) return null;

  const activeRecords = summary?.records.filter(r => r.status === 'stored' || r.status === 'partial') ?? [];
  const hasWarning = activeRecords.some(r => r.expiry_warning);

  return (
    <>
      {/* CSS 动画注入 */}
      <style>{`
        @keyframes slideUp {
          from { transform: translateY(100%); }
          to   { transform: translateY(0); }
        }
        .tx-wine-badge:active {
          transform: scale(0.97);
          background: #E55A28 !important;
        }
        .tx-wine-take-btn:active {
          transform: scale(0.97);
        }
      `}</style>

      {/* 橙色角标触发按钮 */}
      <button
        className="tx-wine-badge"
        style={{
          ...CSS.badge,
          background: hasWarning ? '#A32D2D' : '#FF6B35',
        }}
        onClick={handleOpenSheet}
        aria-label={`${tableName}有${summary?.active_count ?? '...'}瓶存酒待取`}
      >
        <span style={CSS.dot} />
        <span>{tableName} 有 {summary?.active_count ?? '...'} 瓶存酒待取</span>
      </button>

      {/* 底部半屏弹窗 */}
      {open && (
        <div style={CSS.overlay} onClick={e => { if (e.target === e.currentTarget) setOpen(false); }}>
          <div style={CSS.sheet}>
            <div style={CSS.sheetHeader}>
              <h2 style={CSS.sheetTitle}>
                {tableName} · 存酒明细
              </h2>
              <button style={CSS.closeBtn} onClick={() => setOpen(false)} aria-label="关闭">
                ×
              </button>
            </div>

            <div style={CSS.scrollArea}>
              {loading && <p style={CSS.loadingState}>加载中...</p>}
              {error && <p style={{ ...CSS.loadingState, color: '#A32D2D' }}>{error}</p>}
              {!loading && !error && activeRecords.length === 0 && (
                <p style={CSS.emptyState}>暂无存酒记录</p>
              )}
              {activeRecords.map(record => (
                <div key={record.id} style={CSS.card(record.expiry_warning)}>
                  <div style={CSS.cardRow}>
                    <span style={CSS.wineName}>
                      {record.wine_name}
                      {record.wine_brand && (
                        <span style={{ ...CSS.wineSpec, marginLeft: 8 }}>
                          {record.wine_brand}
                        </span>
                      )}
                    </span>
                    <span style={CSS.qtyBadge(record.expiry_warning)}>
                      剩 {record.remaining_quantity} {record.unit}
                    </span>
                  </div>

                  {record.wine_spec && (
                    <span style={CSS.wineSpec}>规格：{record.wine_spec}</span>
                  )}
                  {record.member_name && (
                    <span style={CSS.wineSpec}>会员：{record.member_name}</span>
                  )}
                  {record.cabinet_position && (
                    <span style={CSS.wineSpec}>位置：{record.cabinet_position}</span>
                  )}

                  <div style={CSS.dateRow}>
                    <span style={CSS.dateLabel(false)}>
                      存入：{formatDate(record.stored_at)}
                    </span>
                    {record.expiry_date && (
                      <span style={CSS.dateLabel(record.expiry_warning)}>
                        到期：{formatDate(record.expiry_date)}
                        {record.days_until_expiry !== null && record.days_until_expiry <= 30 && (
                          <span style={{ marginLeft: 6 }}>
                            （{record.days_until_expiry > 0
                              ? `还有${record.days_until_expiry}天`
                              : '已过期'}）
                          </span>
                        )}
                      </span>
                    )}
                  </div>

                  {record.expiry_warning && (
                    <span style={CSS.expiryWarning}>
                      即将过期，请尽快取用
                    </span>
                  )}

                  <button
                    className="tx-wine-take-btn"
                    style={CSS.takeBtn}
                    onClick={() => handleTake(record)}
                  >
                    取酒
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 取酒数量确认弹窗 */}
      {takeState && (
        <div style={CSS.confirmOverlay}>
          <div style={CSS.confirmBox}>
            <p style={CSS.confirmTitle}>
              取酒 · {takeState.record.wine_name}
            </p>
            <p style={{ fontSize: 16, color: '#5F5E5A', marginBottom: 16 }}>
              剩余 {takeState.record.remaining_quantity} {takeState.record.unit}，请输入本次取用数量：
            </p>
            <input
              type="number"
              style={CSS.numInput}
              value={takeState.quantity}
              min={1}
              max={takeState.record.remaining_quantity}
              onChange={e => setTakeState(prev => prev ? { ...prev, quantity: e.target.value } : null)}
              autoFocus
            />
            <div style={CSS.btnRow}>
              <button
                style={CSS.cancelBtn}
                onClick={() => setTakeState(null)}
                disabled={takeState.loading}
              >
                取消
              </button>
              <button
                style={CSS.confirmBtn(
                  takeState.loading ||
                  !takeState.quantity ||
                  parseInt(takeState.quantity, 10) <= 0 ||
                  parseInt(takeState.quantity, 10) > takeState.record.remaining_quantity
                )}
                onClick={handleTakeConfirm}
                disabled={
                  takeState.loading ||
                  !takeState.quantity ||
                  parseInt(takeState.quantity, 10) <= 0 ||
                  parseInt(takeState.quantity, 10) > takeState.record.remaining_quantity
                }
              >
                {takeState.loading ? '处理中...' : '确认取酒'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default WineStorageQuickView;
