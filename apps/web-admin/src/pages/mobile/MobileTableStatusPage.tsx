/**
 * 移动端实时桌态
 * 路由: /m/tables
 * API: tx-trade :8001
 */
import { useState, useEffect, useRef } from 'react';
import { MobileLayout } from '../../components/MobileLayout';
import { txFetchData } from '../../api/client';

// ─── 类型 ───

type TableStatus = 'idle' | 'occupied' | 'billing' | 'reserved';

interface TableItem {
  table_id: string;
  table_no: string;
  status: TableStatus;
  guest_count: number;
  elapsed_minutes: number; // 就餐时长（分钟）
}

interface StoreOption {
  store_id: string;
  store_name: string;
}

// ─── Mock 数据 ───

const MOCK_STORES: StoreOption[] = [
  { store_id: 's1', store_name: '五一广场店' },
  { store_id: 's2', store_name: '解放西路店' },
  { store_id: 's3', store_name: '湘江新区店' },
];

function generateMockTables(storeId: string): TableItem[] {
  const statuses: TableStatus[] = ['idle', 'occupied', 'occupied', 'billing', 'occupied', 'idle', 'reserved', 'occupied', 'idle', 'occupied'];
  return Array.from({ length: 10 }, (_, i) => ({
    table_id: `${storeId}-t${i + 1}`,
    table_no: `${i + 1}号桌`,
    status: statuses[i],
    guest_count: statuses[i] === 'idle' || statuses[i] === 'reserved' ? 0 : Math.floor(Math.random() * 6) + 1,
    elapsed_minutes: statuses[i] === 'idle' || statuses[i] === 'reserved' ? 0 : Math.floor(Math.random() * 90) + 10,
  }));
}

// ─── 配置 ───

const STATUS_CONFIG: Record<TableStatus, { label: string; color: string; bg: string; textColor: string }> = {
  idle:     { label: '空闲', color: '#B4B2A9', bg: '#F0EDE6', textColor: '#5F5E5A' },
  occupied: { label: '占用', color: '#FF6B35', bg: '#FFF3ED', textColor: '#E55A28' },
  billing:  { label: '埋单', color: '#0F6E56', bg: '#ECFDF5', textColor: '#0F6E56' },
  reserved: { label: '预订', color: '#185FA5', bg: '#EFF6FF', textColor: '#185FA5' },
};

const REFRESH_INTERVAL = 30000; // 30秒

// ─── 桌台格子 ───

function TableCell({ table }: { table: TableItem }) {
  const cfg = STATUS_CONFIG[table.status];

  return (
    <div style={{
      background: cfg.bg,
      borderRadius: 10,
      padding: '10px 8px',
      border: `1.5px solid ${cfg.color}`,
      minHeight: 80,
      display: 'flex',
      flexDirection: 'column',
      gap: 4,
    }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: '#2C2C2A' }}>{table.table_no}</div>
      <div style={{
        fontSize: 11,
        fontWeight: 600,
        color: cfg.textColor,
        background: cfg.color + '22',
        borderRadius: 4,
        padding: '2px 4px',
        width: 'fit-content',
      }}>
        {cfg.label}
      </div>
      {table.guest_count > 0 && (
        <div style={{ fontSize: 11, color: '#5F5E5A' }}>{table.guest_count}人</div>
      )}
      {table.elapsed_minutes > 0 && (
        <div style={{ fontSize: 10, color: '#B4B2A9' }}>
          {table.elapsed_minutes >= 60
            ? `${Math.floor(table.elapsed_minutes / 60)}h${table.elapsed_minutes % 60}m`
            : `${table.elapsed_minutes}分钟`
          }
        </div>
      )}
    </div>
  );
}

// ─── 主组件 ───

export function MobileTableStatusPage() {
  const [stores] = useState<StoreOption[]>(MOCK_STORES);
  const [selectedStore, setSelectedStore] = useState<string>(MOCK_STORES[0].store_id);
  const [tables, setTables] = useState<TableItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [countdown, setCountdown] = useState(30);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchTables = (storeId: string) => {
    setLoading(true);

    txFetchData<TableItem[]>(`/api/v1/trade/tables?store_id=${storeId}`)
      .then(res => {
        setTables(res.data ?? generateMockTables(storeId));
      })
      .catch(() => {
        setTables(generateMockTables(storeId));
      })
      .finally(() => {
        setLoading(false);
        setLastRefresh(new Date());
        setCountdown(30);
      });
  };

  useEffect(() => {
    fetchTables(selectedStore);

    // 30秒自动刷新
    timerRef.current = setInterval(() => {
      fetchTables(selectedStore);
    }, REFRESH_INTERVAL);

    // 倒计时
    countdownRef.current = setInterval(() => {
      setCountdown(prev => (prev <= 1 ? 30 : prev - 1));
    }, 1000);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (countdownRef.current) clearInterval(countdownRef.current);
    };
  }, [selectedStore]);

  // 统计
  const stats = {
    idle: tables.filter(t => t.status === 'idle').length,
    occupied: tables.filter(t => t.status === 'occupied').length,
    billing: tables.filter(t => t.status === 'billing').length,
    reserved: tables.filter(t => t.status === 'reserved').length,
  };

  return (
    <MobileLayout title="实时桌态">
      <div style={{ padding: '12px 16px 0' }}>

        {/* 门店选择 */}
        <div style={{ marginBottom: 12 }}>
          <select
            value={selectedStore}
            onChange={e => setSelectedStore(e.target.value)}
            style={{
              width: '100%',
              padding: '10px 12px',
              borderRadius: 10,
              border: '1.5px solid #E8E6E1',
              fontSize: 14,
              color: '#2C2C2A',
              background: '#fff',
              appearance: 'none',
              backgroundImage: 'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 24 24\'%3E%3Cpath d=\'M7 10l5 5 5-5z\' fill=\'%23B4B2A9\'/%3E%3C/svg%3E")',
              backgroundRepeat: 'no-repeat',
              backgroundPosition: 'right 10px center',
              backgroundSize: 20,
            }}
          >
            {stores.map(s => (
              <option key={s.store_id} value={s.store_id}>{s.store_name}</option>
            ))}
          </select>
        </div>

        {/* 状态统计条 */}
        <div style={{
          display: 'flex',
          gap: 8,
          marginBottom: 12,
          padding: '10px 14px',
          background: '#fff',
          borderRadius: 10,
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        }}>
          {([
            ['空闲', stats.idle, '#B4B2A9'],
            ['占用', stats.occupied, '#FF6B35'],
            ['埋单', stats.billing, '#0F6E56'],
            ['预订', stats.reserved, '#185FA5'],
          ] as [string, number, string][]).map(([label, count, color]) => (
            <div key={label} style={{ flex: 1, textAlign: 'center' }}>
              <div style={{ fontSize: 18, fontWeight: 700, color }}>{count}</div>
              <div style={{ fontSize: 11, color: '#B4B2A9' }}>{label}</div>
            </div>
          ))}
        </div>

        {/* 刷新状态 */}
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 10,
          fontSize: 11,
          color: '#B4B2A9',
        }}>
          <span>更新于 {lastRefresh.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
          <button
            onClick={() => fetchTables(selectedStore)}
            style={{
              fontSize: 12,
              color: '#FF6B35',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              padding: 0,
            }}
          >
            {countdown}s 后刷新 · 点击立即刷新
          </button>
        </div>
      </div>

      {/* 桌态网格 */}
      <div style={{ padding: '0 16px 16px' }}>
        {loading ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} style={{
                height: 80,
                background: '#E8E6E1',
                borderRadius: 10,
                animation: 'pulse 1.5s ease-in-out infinite',
              }} />
            ))}
            <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }`}</style>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
            {tables.map(table => (
              <TableCell key={table.table_id} table={table} />
            ))}
          </div>
        )}
      </div>
    </MobileLayout>
  );
}
