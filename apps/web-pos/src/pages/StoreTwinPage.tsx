/**
 * StoreTwinPage — 门店数字孪生页面 /store-twin
 *
 * 2D 鸟瞰 + 热力图 + 桌台状态实时监控
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { StoreHeatmap, type TableInfo } from '../components/StoreHeatmap';

// ─── Mock 数据 ──────────────────────────────────────────────────────────────────

const MOCK_TABLES: TableInfo[] = [
  { tableNo: 'A01', area: '大厅', seats: 4, status: 'free', guestCount: 0 },
  { tableNo: 'A02', area: '大厅', seats: 4, status: 'occupied', guestCount: 3, orderId: 'ord_001', revenueFen: 36800, diningMinutes: 28, waiterName: '小王', turnoverCount: 3 },
  { tableNo: 'A03', area: '大厅', seats: 6, status: 'overtime', guestCount: 5, orderId: 'ord_002', revenueFen: 88600, diningMinutes: 95, waiterName: '小李', turnoverCount: 2 },
  { tableNo: 'A04', area: '大厅', seats: 4, status: 'free', guestCount: 0, turnoverCount: 4 },
  { tableNo: 'A05', area: '大厅', seats: 2, status: 'occupied', guestCount: 2, orderId: 'ord_003', revenueFen: 15600, diningMinutes: 12, waiterName: '小王', turnoverCount: 1 },
  { tableNo: 'A06', area: '大厅', seats: 4, status: 'reserved', guestCount: 0 },
  { tableNo: 'B01', area: '包间', seats: 8, status: 'vip', guestCount: 6, orderId: 'ord_004', revenueFen: 268000, diningMinutes: 45, waiterName: '小张', turnoverCount: 1 },
  { tableNo: 'B02', area: '包间', seats: 10, status: 'free', guestCount: 0, turnoverCount: 2 },
  { tableNo: 'B03', area: '包间', seats: 12, status: 'occupied', guestCount: 10, orderId: 'ord_005', revenueFen: 158800, diningMinutes: 55, waiterName: '小李', turnoverCount: 1 },
  { tableNo: 'B04', area: '包间', seats: 8, status: 'free', guestCount: 0, turnoverCount: 3 },
  { tableNo: 'C01', area: '露台', seats: 4, status: 'occupied', guestCount: 2, orderId: 'ord_006', revenueFen: 24200, diningMinutes: 18, waiterName: '小陈', turnoverCount: 2 },
  { tableNo: 'C02', area: '露台', seats: 4, status: 'free', guestCount: 0, turnoverCount: 1 },
];

// ─── Component ──────────────────────────────────────────────────────────────────

export function StoreTwinPage() {
  const navigate = useNavigate();
  const [tables, setTables] = useState<TableInfo[]>(MOCK_TABLES);
  const [selectedTable, setSelectedTable] = useState<TableInfo | null>(null);

  // 30s 轮询刷新
  const refresh = useCallback(async () => {
    try {
      const storeId = import.meta.env.VITE_STORE_ID || '';
      const res = await fetch(`/api/v1/tables/status?store_id=${storeId}`, {
        headers: { 'X-Tenant-ID': import.meta.env.VITE_TENANT_ID || '' },
      });
      if (res.ok) {
        const data = await res.json();
        if (data.ok && data.data?.tables) {
          setTables(data.data.tables as TableInfo[]);
        }
      }
    } catch {
      // 离线时保留 mock 数据
    }
  }, []);

  useEffect(() => {
    const timer = setInterval(refresh, 30_000);
    return () => clearInterval(timer);
  }, [refresh]);

  const handleSelectTable = useCallback(
    (table: TableInfo) => {
      setSelectedTable(table);
      if (table.orderId) {
        navigate(`/order/${table.orderId}`);
      } else if (table.status === 'free') {
        navigate(`/open-table/${table.tableNo}`);
      }
    },
    [navigate],
  );

  return (
    <div style={{
      background: '#0B1A20', minHeight: '100vh', color: '#E0E0E0',
      fontFamily: 'Noto Sans SC, sans-serif', padding: 20,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 20, color: '#fff' }}>门店数字孪生</h1>
          <div style={{ fontSize: 12, color: '#8899A6', marginTop: 4 }}>
            2D 鸟瞰 · 桌台状态 · 热力图分析
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => navigate('/tables')}
            style={{
              padding: '8px 16px', minHeight: 40,
              background: '#1A3A48', color: '#aaa', border: 'none',
              borderRadius: 8, cursor: 'pointer', fontSize: 13, fontWeight: 600,
            }}
          >
            ← 返回桌台
          </button>
          <button
            onClick={refresh}
            style={{
              padding: '8px 16px', minHeight: 40,
              background: '#185FA5', color: '#fff', border: 'none',
              borderRadius: 8, cursor: 'pointer', fontSize: 13, fontWeight: 600,
            }}
          >
            刷新
          </button>
        </div>
      </div>

      {/* 选中桌台信息 */}
      {selectedTable && (
        <div style={{
          padding: '10px 16px', borderRadius: 8,
          background: 'rgba(255,107,53,0.08)', border: '1px solid rgba(255,107,53,0.2)',
          marginBottom: 16,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span style={{ fontSize: 13, color: '#FF6B35' }}>
            选中: {selectedTable.tableNo}（{selectedTable.area} · {selectedTable.seats}人台）— 点击进入详情
          </span>
          <button
            onClick={() => setSelectedTable(null)}
            style={{
              background: 'transparent', border: 'none', color: '#999',
              cursor: 'pointer', fontSize: 16,
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* 数字孪生画布 */}
      <StoreHeatmap
        tables={tables}
        onSelectTable={handleSelectTable}
        defaultMode="status"
      />
    </div>
  );
}
