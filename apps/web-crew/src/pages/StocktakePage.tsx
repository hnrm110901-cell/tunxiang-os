/**
 * 移动盘点 — 实时录入实盘数量，完成后汇总差异并更新库存
 */
import { useState, useMemo, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../api/index';

const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  green: '#22c55e',
  red: '#ef4444',
  yellow: '#f59e0b',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
};

interface StocktakeItem {
  id: string;
  ingredient_name: string;
  unit: string;
  system_qty: number;
  actual_qty: number | null;
  unit_cost: number;
}

// API 返回的盘点单结构
interface StocktakeSession {
  id: string;
  store_id: string;
  status: 'open' | 'completed';
  items: StocktakeItem[];
}

function varianceInfo(item: StocktakeItem) {
  if (item.actual_qty === null) return null;
  const v = item.actual_qty - item.system_qty;
  const vv = v * item.unit_cost;
  return { variance: v, variance_value: vv };
}

function VarianceBadge({ item }: { item: StocktakeItem }) {
  if (item.actual_qty === null) {
    return <span style={{ fontSize: 13, color: C.muted }}>待盘点</span>;
  }
  const info = varianceInfo(item)!;
  if (info.variance === 0) {
    return <span style={{ fontSize: 13, color: C.green }}>✓ 一致</span>;
  }
  const isPlus = info.variance > 0;
  return (
    <span style={{ fontSize: 13, color: isPlus ? C.green : C.red, fontWeight: 600 }}>
      {isPlus ? '▲' : '▼'} {isPlus ? '+' : ''}{info.variance.toFixed(2)}{item.unit}
      （{isPlus ? '盘盈' : '盘亏'}¥{Math.abs(info.variance_value).toFixed(0)}）
    </span>
  );
}

interface SummaryModalProps {
  items: StocktakeItem[];
  onConfirm: () => void;
  onCancel: () => void;
  submitting: boolean;
}

function SummaryModal({ items, onConfirm, onCancel, submitting }: SummaryModalProps) {
  const surplus = items.filter(i => i.actual_qty !== null && i.actual_qty > i.system_qty);
  const shortage = items.filter(i => i.actual_qty !== null && i.actual_qty < i.system_qty);
  const totalVarianceValue = items.reduce((sum, i) => {
    const info = varianceInfo(i);
    return sum + (info ? info.variance_value : 0);
  }, 0);

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'flex-end', zIndex: 100,
    }}>
      <div style={{
        background: C.card, borderRadius: '16px 16px 0 0', padding: 24,
        width: '100%', boxSizing: 'border-box',
      }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: C.white, marginBottom: 20 }}>
          确认完成盘点？
        </div>
        <div style={{ display: 'flex', gap: 20, marginBottom: 20 }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 28, fontWeight: 800, color: C.green }}>{surplus.length}</div>
            <div style={{ fontSize: 13, color: C.muted }}>盘盈项</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 28, fontWeight: 800, color: C.red }}>{shortage.length}</div>
            <div style={{ fontSize: 13, color: C.muted }}>盘亏项</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{
              fontSize: 28, fontWeight: 800,
              color: totalVarianceValue >= 0 ? C.green : C.red,
            }}>
              {totalVarianceValue >= 0 ? '+' : ''}¥{Math.abs(totalVarianceValue).toFixed(0)}
            </div>
            <div style={{ fontSize: 13, color: C.muted }}>总差异金额</div>
          </div>
        </div>
        <div style={{ fontSize: 14, color: C.muted, marginBottom: 20 }}>
          提交后将自动更新库存为实盘数量
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1, height: 52,
              background: C.border, border: 'none', borderRadius: 12,
              fontSize: 17, color: C.text, cursor: 'pointer',
            }}
          >
            返回
          </button>
          <button
            onClick={onConfirm}
            disabled={submitting}
            style={{
              flex: 2, height: 52,
              background: submitting ? C.muted : C.accent,
              border: 'none', borderRadius: 12,
              fontSize: 17, fontWeight: 700, color: C.white,
              cursor: submitting ? 'not-allowed' : 'pointer',
            }}
          >
            {submitting ? '提交中...' : '确认提交'}
          </button>
        </div>
      </div>
    </div>
  );
}

export function StocktakePage() {
  const navigate = useNavigate();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [items, setItems] = useState<StocktakeItem[]>([]);
  const [search, setSearch] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);

  const storeId: string = (window as unknown as Record<string, string>).__STORE_ID__ || localStorage.getItem('store_id') || '';

  // 开始盘点会话
  const startSession = useCallback(async () => {
    setLoading(true);
    try {
      const session = await txFetch<StocktakeSession>('/api/v1/supply/stocktake/start', {
        method: 'POST',
        body: JSON.stringify({ store_id: storeId }),
      });
      setSessionId(session.id);
      setItems((session.items ?? []).map(i => ({ ...i, actual_qty: null })));
    } catch {
      // 失败降级：空列表，让用户知道
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => { void startSession(); }, [startSession]);

  const filteredItems = useMemo(
    () => items.filter(i => i.ingredient_name.includes(search)),
    [items, search]
  );

  const countedCount = items.filter(i => i.actual_qty !== null).length;

  const updateActual = (id: string, val: string) => {
    const newQty = val === '' ? null : Number(val);
    setItems(prev => prev.map(i =>
      i.id === id ? { ...i, actual_qty: newQty } : i
    ));
    // 实时提交单项数量到后端（fire-and-forget）
    if (sessionId && val !== '') {
      const item = items.find(i => i.id === id);
      if (item) {
        void txFetch(`/api/v1/supply/stocktake/${sessionId}/count`, {
          method: 'POST',
          body: JSON.stringify({ ingredient_id: id, actual_qty: Number(val), unit: item.unit }),
        }).catch(() => { /* 静默失败 */ });
      }
    }
  };

  const handleComplete = async () => {
    if (!sessionId) return;
    setSubmitting(true);
    try {
      await txFetch(`/api/v1/supply/stocktake/${sessionId}/complete`, { method: 'POST' });
      alert('盘点完成！库存已更新。');
      navigate(-1);
    } catch {
      alert('提交失败，请重试');
    } finally {
      setSubmitting(false);
      setShowModal(false);
    }
  };

  if (loading) {
    return (
      <div style={{ background: C.bg, minHeight: '100vh', color: C.white, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18 }}>
        <span style={{ color: C.muted }}>正在开启盘点...</span>
      </div>
    );
  }

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.white }}>
      {/* 顶栏 */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 10,
        background: C.bg, borderBottom: `1px solid ${C.border}`,
        padding: '0 16px',
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', height: 56,
        }}>
          <button onClick={() => navigate(-1)} style={{
            background: 'none', border: 'none', color: C.text, fontSize: 22,
            cursor: 'pointer', padding: '8px 8px 8px 0', minWidth: 48, minHeight: 48,
            display: 'flex', alignItems: 'center',
          }}>←</button>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 17, fontWeight: 700, color: C.white }}>库存盘点</div>
            <div style={{ fontSize: 12, color: C.muted }}>
              进度：{countedCount}/{items.length} 项已盘点
            </div>
          </div>
          <button
            onClick={() => setShowModal(true)}
            style={{
              height: 40, padding: '0 16px',
              background: C.accent, border: 'none', borderRadius: 10,
              fontSize: 15, fontWeight: 700, color: C.white, cursor: 'pointer',
              minWidth: 88,
            }}
          >
            完成盘点
          </button>
        </div>

        {/* 进度条 */}
        <div style={{ height: 3, background: C.border, marginBottom: 0 }}>
          <div style={{
            height: '100%', background: C.accent,
            width: `${(countedCount / items.length) * 100}%`,
            transition: 'width 0.3s',
          }} />
        </div>
      </div>

      {/* 搜索 */}
      <div style={{ padding: '12px 16px 4px' }}>
        <div style={{
          background: C.card, border: `1px solid ${C.border}`,
          borderRadius: 10, display: 'flex', alignItems: 'center', padding: '0 14px',
          height: 48,
        }}>
          <span style={{ fontSize: 16, color: C.muted, marginRight: 8 }}>🔍</span>
          <input
            type="text"
            placeholder="搜索食材..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{
              flex: 1, background: 'none', border: 'none', outline: 'none',
              fontSize: 16, color: C.white,
            }}
          />
        </div>
      </div>

      {/* 列表 */}
      <div style={{ padding: '8px 16px 24px' }}>
        {filteredItems.map(item => {
          const info = varianceInfo(item);
          const borderColor = info === null
            ? C.border
            : info.variance === 0 ? C.border
            : info.variance > 0 ? C.green : C.red;

          return (
            <div key={item.id} style={{
              background: C.card, borderRadius: 12, padding: 14, marginBottom: 10,
              border: `1px solid ${borderColor}`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                <span style={{ fontSize: 17, fontWeight: 600, color: C.white }}>{item.ingredient_name}</span>
                <span style={{ fontSize: 14, color: C.muted }}>{item.unit}</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, color: C.muted, marginBottom: 3 }}>账面</div>
                  <div style={{ fontSize: 16, color: C.muted }}>{item.system_qty}{item.unit}</div>
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, color: C.muted, marginBottom: 3 }}>实盘</div>
                  <input
                    type="number"
                    inputMode="decimal"
                    placeholder="—"
                    value={item.actual_qty ?? ''}
                    onChange={e => updateActual(item.id, e.target.value)}
                    style={{
                      width: '100%', boxSizing: 'border-box',
                      background: '#0B1A20',
                      border: `1px solid ${item.actual_qty !== null ? borderColor : C.border}`,
                      borderRadius: 8, padding: '10px 12px',
                      fontSize: 18, fontWeight: 700,
                      color: item.actual_qty !== null ? C.white : C.muted,
                      outline: 'none', textAlign: 'center', minHeight: 48,
                    }}
                  />
                </div>
              </div>
              <div style={{ marginTop: 8 }}>
                <VarianceBadge item={item} />
              </div>
            </div>
          );
        })}
      </div>

      {showModal && (
        <SummaryModal
          items={items}
          onConfirm={handleComplete}
          onCancel={() => setShowModal(false)}
          submitting={submitting}
        />
      )}
    </div>
  );
}
