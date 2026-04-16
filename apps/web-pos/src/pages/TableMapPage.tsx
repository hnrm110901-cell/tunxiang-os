/**
 * 桌台地图可视化 — POS主屏核心页面
 * 网格布局 · 颜色编码 · 点击弹出操作面板 · 实时状态
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchTableStatus, type TableStatus } from '../api/posOpsApi';
import { OrderActionPanel } from './OrderActionPanel';
import { StatusBar, TableCard } from '@tx-ds/biz';
import type { StatusBarItem, TableCardData } from '@tx-ds/biz';

/* ─── 样式常量 ─── */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1A3A48',
  accent: '#FF6B35',
  green: '#0F6E56',
  blue: '#185FA5',
  red: '#A32D2D',
  yellow: '#BA7517',
  purple: '#722ed1',
  muted: '#64748b',
  text: '#E0E0E0',
  white: '#FFFFFF',
};

/** 图例（用于区域过滤旁的可视化说明） */
const LEGEND = [
  { color: C.green, label: '空闲' },
  { color: C.blue, label: '就餐中' },
  { color: C.red, label: '超时' },
  { color: C.yellow, label: '预订' },
  { color: C.purple, label: 'VIP' },
];

/* ─── Mock 数据（离线/开发时使用） ─── */
const MOCK_TABLES: TableStatus[] = [
  { table_no: 'A01', area: '大厅', seats: 4, status: 'free', guest_count: 0 },
  { table_no: 'A02', area: '大厅', seats: 4, status: 'occupied', guest_count: 3, order_id: 'ord_001', order_amount_fen: 36800, dining_minutes: 28, waiter_name: '小王' },
  { table_no: 'A03', area: '大厅', seats: 6, status: 'overtime', guest_count: 5, order_id: 'ord_002', order_amount_fen: 88600, dining_minutes: 95, waiter_name: '小李' },
  { table_no: 'A04', area: '大厅', seats: 4, status: 'free', guest_count: 0 },
  { table_no: 'A05', area: '大厅', seats: 2, status: 'occupied', guest_count: 2, order_id: 'ord_003', order_amount_fen: 15600, dining_minutes: 12, waiter_name: '小王' },
  { table_no: 'A06', area: '大厅', seats: 4, status: 'reserved', guest_count: 0 },
  { table_no: 'B01', area: '包间', seats: 8, status: 'vip', guest_count: 6, order_id: 'ord_004', order_amount_fen: 268000, dining_minutes: 45, waiter_name: '小张' },
  { table_no: 'B02', area: '包间', seats: 10, status: 'free', guest_count: 0 },
  { table_no: 'B03', area: '包间', seats: 12, status: 'occupied', guest_count: 10, order_id: 'ord_005', order_amount_fen: 158800, dining_minutes: 55, waiter_name: '小李' },
  { table_no: 'B04', area: '包间', seats: 8, status: 'free', guest_count: 0 },
  { table_no: 'C01', area: '露台', seats: 4, status: 'occupied', guest_count: 2, order_id: 'ord_006', order_amount_fen: 24200, dining_minutes: 18, waiter_name: '小陈' },
  { table_no: 'C02', area: '露台', seats: 4, status: 'free', guest_count: 0 },
];

/* ─── 组件 ─── */
export function TableMapPage() {
  const navigate = useNavigate();
  const [tables, setTables] = useState<TableStatus[]>(MOCK_TABLES);
  const [selectedTable, setSelectedTable] = useState<TableStatus | null>(null);
  const [filterArea, setFilterArea] = useState<string>('全部');
  const [showPanel, setShowPanel] = useState(false);

  /** 从后端加载桌台状态 */
  const loadTables = useCallback(async () => {
    try {
      const storeId = import.meta.env.VITE_STORE_ID || '';
      const data = await fetchTableStatus(storeId);
      if (data.tables && data.tables.length > 0) {
        setTables(data.tables);
      }
    } catch {
      // 离线模式使用 mock 数据
    }
  }, []);

  useEffect(() => {
    loadTables();
    // 每 30 秒刷新一次桌台状态
    const timer = setInterval(loadTables, 30_000);
    return () => clearInterval(timer);
  }, [loadTables]);

  /** 获取所有区域 */
  const areas = ['全部', ...Array.from(new Set(tables.map(t => t.area)))];

  /** 过滤后的桌台 */
  const filtered = filterArea === '全部' ? tables : tables.filter(t => t.area === filterArea);

  /** 统计数据 */
  const stats = {
    total: tables.length,
    free: tables.filter(t => t.status === 'free').length,
    occupied: tables.filter(t => t.status === 'occupied' || t.status === 'overtime' || t.status === 'vip').length,
    reserved: tables.filter(t => t.status === 'reserved').length,
  };

  /** TableStatus → TableCardData 映射 */
  const toCardData = useCallback((t: TableStatus): TableCardData => ({
    tableNo: t.table_no,
    area: t.area,
    seats: t.seats,
    status: t.status as TableCardData['status'],
    guestCount: t.guest_count || undefined,
    diningMinutes: t.dining_minutes || undefined,
    orderAmountFen: t.order_amount_fen || undefined,
    waiterName: t.waiter_name || undefined,
  }), []);

  const handleTableClick = (table: TableStatus) => {
    if (table.status === 'free') {
      navigate(`/open-table/${table.table_no}`);
    } else if (table.status === 'reserved') {
      navigate('/reservations');
    } else {
      setSelectedTable(table);
      setShowPanel(true);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: C.bg, color: C.text }}>
      {/* 顶部栏 */}
      <div style={{
        padding: '12px 20px', display: 'flex', justifyContent: 'space-between',
        alignItems: 'center', borderBottom: `1px solid ${C.border}`, flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <button
            onClick={() => navigate('/dashboard')}
            style={{
              minHeight: 48, minWidth: 48, padding: '8px 16px',
              background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
              color: C.text, fontSize: 16, cursor: 'pointer',
            }}
          >
            {'<'} 返回
          </button>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: C.white }}>桌台总览</h1>
        </div>

        {/* 统计 */}
        <StatusBar
          size="compact"
          items={[
            { label: '总', value: stats.total, color: C.white },
            { label: '空', value: stats.free, color: C.green },
            { label: '用', value: stats.occupied, color: C.blue },
            { label: '订', value: stats.reserved, color: C.yellow },
          ] satisfies StatusBarItem[]}
        />

        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => navigate('/quick-cashier')}
            style={{
              minHeight: 48, padding: '8px 20px',
              background: C.accent, border: 'none', borderRadius: 8,
              color: C.white, fontSize: 16, fontWeight: 700, cursor: 'pointer',
            }}
          >
            快速收银
          </button>
          <button
            onClick={loadTables}
            style={{
              minHeight: 48, padding: '8px 16px',
              background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
              color: C.text, fontSize: 16, cursor: 'pointer',
            }}
          >
            刷新
          </button>
        </div>
      </div>

      {/* 区域过滤 + 图例 */}
      <div style={{
        padding: '12px 20px', display: 'flex', justifyContent: 'space-between',
        alignItems: 'center', flexShrink: 0,
      }}>
        {/* 区域Tab */}
        <div style={{ display: 'flex', gap: 0, borderRadius: 12, overflow: 'hidden' }}>
          {areas.map(area => (
            <button
              key={area}
              onClick={() => setFilterArea(area)}
              style={{
                minHeight: 48, padding: '8px 20px', border: 'none',
                background: filterArea === area ? C.accent : C.card,
                color: filterArea === area ? C.white : C.muted,
                fontSize: 16, fontWeight: filterArea === area ? 700 : 400,
                cursor: 'pointer', transition: 'background 200ms ease',
              }}
            >
              {area}
            </button>
          ))}
        </div>

        {/* 图例 */}
        <div style={{ display: 'flex', gap: 16 }}>
          {LEGEND.map(l => (
            <span key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 16 }}>
              <span style={{
                width: 16, height: 16, borderRadius: 4,
                background: `${l.color}44`, border: `2px solid ${l.color}`,
                display: 'inline-block',
              }} />
              {l.label}
            </span>
          ))}
        </div>
      </div>

      {/* 桌台网格 */}
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', padding: '0 20px 20px' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))',
          gap: 12,
        }}>
          {filtered.map(table => (
            <TableCard
              key={table.table_no}
              table={toCardData(table)}
              selected={selectedTable?.table_no === table.table_no}
              onClick={() => handleTableClick(table)}
            />
          ))}
        </div>
      </div>

      {/* 操作面板 */}
      {showPanel && selectedTable && (
        <OrderActionPanel
          tableNo={selectedTable.table_no}
          orderId={selectedTable.order_id}
          onClose={() => { setShowPanel(false); setSelectedTable(null); }}
          onRefresh={loadTables}
        />
      )}
    </div>
  );
}
