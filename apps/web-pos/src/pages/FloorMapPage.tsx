/**
 * 桌台总览地图 — 全屏大屏管理
 * 区域Tab · 状态色编码 · 开台/详情/清台弹窗
 * 换桌/并桌模式 · 底部统计 · 15s自动刷新
 */
import { useState, useEffect, useCallback, useRef, type CSSProperties } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../api/index';

/* ─── 颜色常量 ─── */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1A3A48',
  accent: '#FF6B35',
  green: '#10B981',
  orange: '#FF6B35',
  red: '#EF4444',
  blue: '#3B82F6',
  gray: '#6B7280',
  muted: '#64748b',
  text: '#E0E0E0',
  white: '#FFFFFF',
};

/* ─── 类型定义 ─── */
type TableStatusCode = 'free' | 'occupied' | 'pending_clean' | 'reserved' | 'disabled';

interface FloorTable {
  table_no: string;
  area: string;
  seats: number;
  status: TableStatusCode;
  guest_count: number;
  order_id?: string;
  order_amount_fen?: number;
  dining_minutes?: number;
  waiter_name?: string;
}

type InteractionMode = 'normal' | 'transfer' | 'merge';

/* ─── 状态映射 ─── */
const STATUS_MAP: Record<TableStatusCode, { bg: string; border: string; label: string }> = {
  free:          { bg: `${C.green}22`, border: C.green,  label: '空闲' },
  occupied:      { bg: `${C.orange}22`, border: C.orange, label: '用餐中' },
  pending_clean: { bg: `${C.red}22`,   border: C.red,    label: '待清台' },
  reserved:      { bg: `${C.blue}22`,  border: C.blue,   label: '已预约' },
  disabled:      { bg: `${C.gray}22`,  border: C.gray,   label: '停用' },
};

const LEGEND_ITEMS: Array<{ color: string; label: string }> = [
  { color: C.green,  label: '空闲' },
  { color: C.orange, label: '用餐中' },
  { color: C.red,    label: '待清台' },
  { color: C.blue,   label: '已预约' },
  { color: C.gray,   label: '停用' },
];

const AREAS = ['大厅', '包厢A', '包厢B', '室外', '吧台'];


/* ─── 工具函数 ─── */
const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(0)}`;
const formatMin = (min: number) => (min < 60 ? `${min}分钟` : `${Math.floor(min / 60)}时${min % 60}分`);
const vibrate = () => { try { navigator.vibrate?.(50); } catch { /* no-op */ } };

const BASE = 'http://localhost:8001';

/* ─── 服务员列表（Mock） ─── */
const WAITERS = ['小王', '小李', '小张', '小陈', '小赵'];

/* ─── 组件 ─── */
export function FloorMapPage() {
  const navigate = useNavigate();
  const [tables, setTables] = useState<FloorTable[]>([]);
  const [loadingInitial, setLoadingInitial] = useState(true);
  const [activeArea, setActiveArea] = useState<string>('全部');
  const [mode, setMode] = useState<InteractionMode>('normal');
  const [selectedTable, setSelectedTable] = useState<FloorTable | null>(null);

  // 开台面板
  const [openPanel, setOpenPanel] = useState<FloorTable | null>(null);
  const [openGuests, setOpenGuests] = useState(2);
  const [openWaiter, setOpenWaiter] = useState(WAITERS[0]);
  const [openRemark, setOpenRemark] = useState('');

  // 详情面板
  const [detailPanel, setDetailPanel] = useState<FloorTable | null>(null);

  // 换桌
  const [transferSource, setTransferSource] = useState<FloorTable | null>(null);

  // 并桌
  const [mergeSelections, setMergeSelections] = useState<FloorTable[]>([]);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ─── 加载桌台 ─── */
  const loadTables = useCallback(async () => {
    try {
      const storeId = import.meta.env.VITE_STORE_ID || 'default';
      const resp = await fetch(`${BASE}/api/v1/trade/tables?store_id=${encodeURIComponent(storeId)}`, {
        headers: { 'Content-Type': 'application/json' },
      });
      const json: unknown = await resp.json();
      const typed = json as { ok: boolean; data?: { tables?: FloorTable[] } };
      if (typed.ok && typed.data?.tables && typed.data.tables.length > 0) {
        setTables(typed.data.tables);
      }
    } catch (e) {
      console.error('加载桌台状态失败', e);
    } finally {
      setLoadingInitial(false);
    }
  }, []);

  useEffect(() => {
    loadTables();
    timerRef.current = setInterval(loadTables, 15_000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [loadTables]);

  /* ─── 区域列表（动态） ─── */
  const allAreas = Array.from(new Set(tables.map(t => t.area)));
  const areaList = ['全部', ...AREAS.filter(a => allAreas.includes(a)), ...allAreas.filter(a => !AREAS.includes(a))];

  /* ─── 过滤 ─── */
  const filtered = activeArea === '全部' ? tables : tables.filter(t => t.area === activeArea);

  /* ─── 统计 ─── */
  const freeCount = tables.filter(t => t.status === 'free').length;
  const occupiedCount = tables.filter(t => t.status === 'occupied').length;
  const pendingCount = tables.filter(t => t.status === 'pending_clean').length;
  const totalUsable = tables.filter(t => t.status !== 'disabled').length;
  const turnoverRate = totalUsable > 0 ? Math.round((occupiedCount / totalUsable) * 100) : 0;

  /* ─── 清台 ─── */
  const handleCleanTable = async (table: FloorTable) => {
    vibrate();
    try {
      await txFetch(`/api/v1/trade/tables/${encodeURIComponent(table.table_no)}/close`, { method: 'POST' });
    } catch {
      // Mock: 本地更新
    }
    setTables(prev => prev.map(t => t.table_no === table.table_no ? { ...t, status: 'free' as TableStatusCode, guest_count: 0, order_id: undefined, order_amount_fen: undefined, dining_minutes: undefined, waiter_name: undefined } : t));
    setSelectedTable(null);
  };

  /* ─── 开台提交 ─── */
  const handleOpenTable = async () => {
    if (!openPanel) return;
    vibrate();
    try {
      await fetch(`${BASE}/api/v1/trade/tables/${encodeURIComponent(openPanel.table_no)}/open`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ guest_count: openGuests, waiter_name: openWaiter, remark: openRemark }),
      });
    } catch {
      // Mock: 本地更新
    }
    setTables(prev => prev.map(t =>
      t.table_no === openPanel.table_no
        ? { ...t, status: 'occupied' as TableStatusCode, guest_count: openGuests, waiter_name: openWaiter, dining_minutes: 0, order_amount_fen: 0 }
        : t,
    ));
    setOpenPanel(null);
    setOpenGuests(2);
    setOpenRemark('');
  };

  /* ─── 换桌确认 ─── */
  const handleTransferConfirm = async (target: FloorTable) => {
    if (!transferSource) return;
    vibrate();
    try {
      if (transferSource.order_id) {
        await txFetch(`/api/v1/trade/orders/${encodeURIComponent(transferSource.order_id)}/transfer-table`, {
          method: 'POST',
          body: JSON.stringify({ target_table_no: target.table_no }),
        });
      }
    } catch {
      // Mock
    }
    setTables(prev => prev.map(t => {
      if (t.table_no === transferSource.table_no) return { ...t, status: 'free' as TableStatusCode, guest_count: 0, order_id: undefined, order_amount_fen: undefined, dining_minutes: undefined, waiter_name: undefined };
      if (t.table_no === target.table_no) return { ...t, status: transferSource.status, guest_count: transferSource.guest_count, order_id: transferSource.order_id, order_amount_fen: transferSource.order_amount_fen, dining_minutes: transferSource.dining_minutes, waiter_name: transferSource.waiter_name };
      return t;
    }));
    setTransferSource(null);
    setMode('normal');
  };

  /* ─── 并桌确认 ─── */
  const handleMergeConfirm = async () => {
    if (mergeSelections.length < 2) return;
    vibrate();
    const orderIds = mergeSelections.filter(t => t.order_id).map(t => t.order_id as string);
    if (orderIds.length >= 2) {
      try {
        await txFetch('/api/v1/trade/orders/merge', {
          method: 'POST',
          body: JSON.stringify({ order_ids: orderIds, main_order_id: orderIds[0] }),
        });
      } catch {
        // Mock
      }
    }
    // 本地模拟：把所有选中桌合并到第一桌
    const main = mergeSelections[0];
    const totalAmount = mergeSelections.reduce((s, t) => s + (t.order_amount_fen ?? 0), 0);
    const totalGuests = mergeSelections.reduce((s, t) => s + t.guest_count, 0);
    setTables(prev => prev.map(t => {
      if (t.table_no === main.table_no) return { ...t, guest_count: totalGuests, order_amount_fen: totalAmount };
      if (mergeSelections.some(m => m.table_no === t.table_no) && t.table_no !== main.table_no) {
        return { ...t, status: 'free' as TableStatusCode, guest_count: 0, order_id: undefined, order_amount_fen: undefined, dining_minutes: undefined, waiter_name: undefined };
      }
      return t;
    }));
    setMergeSelections([]);
    setMode('normal');
  };

  /* ─── 桌台点击处理 ─── */
  const handleTableClick = (table: FloorTable) => {
    vibrate();

    if (mode === 'transfer') {
      if (!transferSource) {
        if (table.status === 'occupied') {
          setTransferSource(table);
        }
      } else if (table.status === 'free') {
        handleTransferConfirm(table);
      }
      return;
    }

    if (mode === 'merge') {
      if (table.status === 'occupied') {
        setMergeSelections(prev =>
          prev.some(t => t.table_no === table.table_no)
            ? prev.filter(t => t.table_no !== table.table_no)
            : [...prev, table],
        );
      }
      return;
    }

    // 普通模式
    if (table.status === 'free') {
      setOpenPanel(table);
      setOpenGuests(2);
      setOpenRemark('');
    } else if (table.status === 'pending_clean') {
      setSelectedTable(table);
    } else if (table.status === 'occupied') {
      setDetailPanel(table);
    } else if (table.status === 'reserved') {
      navigate('/reservations');
    }
  };

  /* ─── 是否被选中（换桌/并桌模式高亮） ─── */
  const isHighlighted = (table: FloorTable): boolean => {
    if (mode === 'transfer') return transferSource?.table_no === table.table_no;
    if (mode === 'merge') return mergeSelections.some(t => t.table_no === table.table_no);
    return false;
  };

  /* ─── 模式提示文字 ─── */
  const getModeHint = (): string => {
    if (mode === 'transfer') {
      if (!transferSource) return '请选择源桌（用餐中）';
      return `已选源桌 ${transferSource.table_no}，请选择空闲目标桌`;
    }
    if (mode === 'merge') {
      return `已选 ${mergeSelections.length} 桌，选择至少2桌后确认`;
    }
    return '';
  };

  /* ─── 按钮基础样式 ─── */
  const btnBase: CSSProperties = {
    minHeight: 48, minWidth: 48, padding: '8px 20px',
    border: 'none', borderRadius: 8, cursor: 'pointer',
    fontSize: 16, fontWeight: 700,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: C.bg, color: C.text }}>
      {/* 顶部导航 */}
      <div style={{
        padding: '12px 20px', display: 'flex', justifyContent: 'space-between',
        alignItems: 'center', borderBottom: `1px solid ${C.border}`, flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <button onClick={() => { vibrate(); navigate('/dashboard'); }} style={{ ...btnBase, background: C.card, border: `1px solid ${C.border}`, color: C.text }}>
            {'<'} 返回
          </button>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: C.white }}>全场桌台地图</h1>
        </div>

        {/* 图例 */}
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
          {LEGEND_ITEMS.map(l => (
            <span key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 14 }}>
              <span style={{ width: 14, height: 14, borderRadius: 3, background: `${l.color}44`, border: `2px solid ${l.color}`, display: 'inline-block' }} />
              {l.label}
            </span>
          ))}
        </div>

        <button onClick={() => { vibrate(); loadTables(); }} style={{ ...btnBase, background: C.card, border: `1px solid ${C.border}`, color: C.text }}>
          刷新
        </button>
      </div>

      {/* 区域Tab */}
      <div style={{ padding: '10px 20px', display: 'flex', gap: 0, borderRadius: 12, overflow: 'hidden', flexShrink: 0, alignSelf: 'flex-start', marginLeft: 20 }}>
        {areaList.map(area => (
          <button
            key={area}
            onClick={() => { vibrate(); setActiveArea(area); }}
            style={{
              ...btnBase, padding: '8px 24px', borderRadius: 0,
              background: activeArea === area ? C.accent : C.card,
              color: activeArea === area ? C.white : C.muted,
              fontWeight: activeArea === area ? 700 : 400,
            }}
          >
            {area}
          </button>
        ))}
      </div>

      {/* 模式提示条 */}
      {mode !== 'normal' && (
        <div style={{
          padding: '10px 20px', background: '#1E3A5F', fontSize: 16, fontWeight: 600,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span>{getModeHint()}</span>
          <button onClick={() => { vibrate(); setMode('normal'); setTransferSource(null); setMergeSelections([]); }} style={{ ...btnBase, background: C.red, color: C.white, padding: '6px 16px' }}>
            取消
          </button>
        </div>
      )}

      {/* 桌台网格 */}
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', padding: '12px 20px' }}>
        {loadingInitial && (
          <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>加载中...</div>
        )}
        {!loadingInitial && filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>暂无桌台数据</div>
        )}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, 100px)',
          gap: 12,
          justifyContent: 'start',
        }}>
          {filtered.map(table => {
            const sc = STATUS_MAP[table.status];
            const hl = isHighlighted(table);
            return (
              <button
                key={table.table_no}
                onClick={() => handleTableClick(table)}
                style={{
                  width: 100, height: 100, borderRadius: 10, textAlign: 'center',
                  background: hl ? `${C.accent}33` : sc.bg,
                  border: `2px solid ${hl ? C.accent : sc.border}`,
                  color: C.white, cursor: table.status === 'disabled' ? 'not-allowed' : 'pointer',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                  gap: 2, padding: 4, transition: 'transform 150ms ease',
                  opacity: table.status === 'disabled' ? 0.5 : 1,
                }}
                onPointerDown={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(0.95)'; }}
                onPointerUp={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
                onPointerLeave={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
              >
                <div style={{ fontSize: 20, fontWeight: 700, lineHeight: 1 }}>{table.table_no}</div>
                <div style={{ fontSize: 11, color: sc.border, fontWeight: 600 }}>{sc.label}</div>
                {table.status === 'occupied' && (
                  <>
                    {table.dining_minutes != null && (
                      <div style={{ fontSize: 10, color: C.muted }}>{formatMin(table.dining_minutes)}</div>
                    )}
                    <div style={{ fontSize: 10, color: C.muted }}>{table.guest_count}人</div>
                  </>
                )}
                {table.status === 'free' && (
                  <div style={{ fontSize: 10, color: C.muted }}>{table.seats}座</div>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* 底部工具栏 */}
      <div style={{
        padding: '12px 20px', borderTop: `1px solid ${C.border}`, flexShrink: 0,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        background: C.card,
      }}>
        {/* 全场概览 */}
        <div style={{ display: 'flex', gap: 20, fontSize: 15 }}>
          <span>空闲 <b style={{ color: C.green }}>{freeCount}</b></span>
          <span>用餐 <b style={{ color: C.orange }}>{occupiedCount}</b></span>
          <span>待清 <b style={{ color: C.red }}>{pendingCount}</b></span>
          <span>翻台率 <b style={{ color: C.accent }}>{turnoverRate}%</b></span>
        </div>

        {/* 操作按钮 */}
        <div style={{ display: 'flex', gap: 10 }}>
          {mode === 'merge' && mergeSelections.length >= 2 && (
            <button onClick={() => { vibrate(); handleMergeConfirm(); }} style={{ ...btnBase, background: C.accent, color: C.white }}>
              确认并桌 ({mergeSelections.length}桌)
            </button>
          )}
          <button
            onClick={() => { vibrate(); setMode(mode === 'transfer' ? 'normal' : 'transfer'); setTransferSource(null); setMergeSelections([]); }}
            style={{ ...btnBase, background: mode === 'transfer' ? C.accent : C.card, color: mode === 'transfer' ? C.white : C.text, border: `1px solid ${C.border}` }}
          >
            换桌
          </button>
          <button
            onClick={() => { vibrate(); setMode(mode === 'merge' ? 'normal' : 'merge'); setTransferSource(null); setMergeSelections([]); }}
            style={{ ...btnBase, background: mode === 'merge' ? C.accent : C.card, color: mode === 'merge' ? C.white : C.text, border: `1px solid ${C.border}` }}
          >
            并桌
          </button>
          <button onClick={() => { vibrate(); navigate('/quick-open'); }} style={{ ...btnBase, background: C.accent, color: C.white }}>
            快速开台
          </button>
        </div>
      </div>

      {/* ─── 弹出面板：开台 ─── */}
      {openPanel && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
        }} onClick={() => setOpenPanel(null)}>
          <div style={{
            background: C.card, borderRadius: 16, padding: 24, width: 420, maxHeight: '80vh',
            overflowY: 'auto', border: `1px solid ${C.border}`,
          }} onClick={e => e.stopPropagation()}>
            <h2 style={{ margin: '0 0 16px', fontSize: 22, color: C.white }}>
              开台 — {openPanel.table_no}（{openPanel.seats}座）
            </h2>

            {/* 人数 */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 14, color: C.muted, marginBottom: 8 }}>用餐人数</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {[1, 2, 3, 4, 5, 6, 7, 8, 10, 12].map(n => (
                  <button
                    key={n}
                    onClick={() => { vibrate(); setOpenGuests(n); }}
                    style={{
                      ...btnBase, width: 56, height: 56, padding: 0,
                      background: openGuests === n ? C.accent : `${C.border}44`,
                      color: openGuests === n ? C.white : C.text,
                      fontSize: 18, borderRadius: 10,
                    }}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>

            {/* 服务员 */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 14, color: C.muted, marginBottom: 8 }}>服务员</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {WAITERS.map(w => (
                  <button
                    key={w}
                    onClick={() => { vibrate(); setOpenWaiter(w); }}
                    style={{
                      ...btnBase, padding: '8px 16px',
                      background: openWaiter === w ? C.accent : `${C.border}44`,
                      color: openWaiter === w ? C.white : C.text,
                    }}
                  >
                    {w}
                  </button>
                ))}
              </div>
            </div>

            {/* 备注 */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 14, color: C.muted, marginBottom: 8 }}>备注</div>
              <input
                value={openRemark}
                onChange={e => setOpenRemark(e.target.value)}
                placeholder="选填，如生日/忌口等"
                style={{
                  width: '100%', padding: 12, borderRadius: 8,
                  background: C.bg, border: `1px solid ${C.border}`,
                  color: C.white, fontSize: 16, outline: 'none', boxSizing: 'border-box',
                }}
              />
            </div>

            {/* 确认按钮 */}
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={() => setOpenPanel(null)} style={{ ...btnBase, flex: 1, background: `${C.border}44`, color: C.text }}>
                取消
              </button>
              <button onClick={handleOpenTable} style={{ ...btnBase, flex: 2, height: 56, background: C.accent, color: C.white, fontSize: 18 }}>
                确认开台
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── 弹出面板：待清台一键清台 ─── */}
      {selectedTable && selectedTable.status === 'pending_clean' && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
        }} onClick={() => setSelectedTable(null)}>
          <div style={{
            background: C.card, borderRadius: 16, padding: 24, width: 340,
            border: `1px solid ${C.border}`, textAlign: 'center',
          }} onClick={e => e.stopPropagation()}>
            <h2 style={{ margin: '0 0 16px', fontSize: 22, color: C.white }}>
              清台 — {selectedTable.table_no}
            </h2>
            <p style={{ color: C.muted, fontSize: 16, marginBottom: 24 }}>确认该桌已清理完成？</p>
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={() => setSelectedTable(null)} style={{ ...btnBase, flex: 1, background: `${C.border}44`, color: C.text }}>
                取消
              </button>
              <button onClick={() => handleCleanTable(selectedTable)} style={{ ...btnBase, flex: 2, height: 56, background: C.green, color: C.white, fontSize: 18 }}>
                清台完成
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── 弹出面板：用餐中详情 ─── */}
      {detailPanel && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
        }} onClick={() => setDetailPanel(null)}>
          <div style={{
            background: C.card, borderRadius: 16, padding: 24, width: 400,
            border: `1px solid ${C.border}`,
          }} onClick={e => e.stopPropagation()}>
            <h2 style={{ margin: '0 0 20px', fontSize: 22, color: C.white }}>
              {detailPanel.table_no} — 用餐详情
            </h2>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
              <div style={{ background: C.bg, borderRadius: 8, padding: 12, textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: C.muted }}>消费金额</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: C.accent }}>
                  {detailPanel.order_amount_fen != null ? fen2yuan(detailPanel.order_amount_fen) : '--'}
                </div>
              </div>
              <div style={{ background: C.bg, borderRadius: 8, padding: 12, textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: C.muted }}>用餐时长</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: C.white }}>
                  {detailPanel.dining_minutes != null ? formatMin(detailPanel.dining_minutes) : '--'}
                </div>
              </div>
              <div style={{ background: C.bg, borderRadius: 8, padding: 12, textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: C.muted }}>人数</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: C.white }}>{detailPanel.guest_count}</div>
              </div>
              <div style={{ background: C.bg, borderRadius: 8, padding: 12, textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: C.muted }}>服务员</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: C.white }}>{detailPanel.waiter_name ?? '--'}</div>
              </div>
            </div>

            {/* 操作按钮 */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <button
                onClick={() => { vibrate(); if (detailPanel.order_id) navigate(`/cashier/${detailPanel.table_no}`); setDetailPanel(null); }}
                style={{ ...btnBase, background: C.accent, color: C.white, height: 56 }}
              >
                加菜
              </button>
              <button
                onClick={() => { vibrate(); if (detailPanel.order_id) navigate(`/settle/${detailPanel.order_id}`); setDetailPanel(null); }}
                style={{ ...btnBase, background: C.green, color: C.white, height: 56 }}
              >
                结账
              </button>
              <button
                onClick={() => { vibrate(); setDetailPanel(null); setTransferSource(detailPanel); setMode('transfer'); }}
                style={{ ...btnBase, background: `${C.border}44`, color: C.text, border: `1px solid ${C.border}` }}
              >
                换桌
              </button>
              <button
                onClick={() => { vibrate(); setDetailPanel(null); setMergeSelections([detailPanel]); setMode('merge'); }}
                style={{ ...btnBase, background: `${C.border}44`, color: C.text, border: `1px solid ${C.border}` }}
              >
                并桌
              </button>
            </div>

            <button onClick={() => setDetailPanel(null)} style={{ ...btnBase, width: '100%', marginTop: 12, background: `${C.border}44`, color: C.muted }}>
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
