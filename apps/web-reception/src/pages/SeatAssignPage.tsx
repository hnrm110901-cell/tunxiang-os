/**
 * 桌台分配 — 桌台平面图，按区域/状态着色，点击确认入座
 */
import { useState } from 'react';

type TableStatus = 'available' | 'occupied' | 'reserved' | 'cleaning';

interface TableInfo {
  id: string;
  name: string;
  zone: string;        // 区域
  capacity: number;
  status: TableStatus;
  guestName?: string;
  guestCount?: number;
  occupiedSince?: string;
  minSpend?: number;   // 包厢低消
  isRoom: boolean;     // 是否包厢
}

const STATUS_CONFIG: Record<TableStatus, { label: string; color: string; bg: string; border: string }> = {
  available: { label: '空闲', color: 'var(--tx-success)', bg: '#DCFCE7', border: 'var(--tx-success)' },
  occupied:  { label: '占用', color: '#fff',              bg: 'var(--tx-danger)', border: 'var(--tx-danger)' },
  reserved:  { label: '预留', color: '#6B4E00',           bg: '#FEF3C7', border: 'var(--tx-warning)' },
  cleaning:  { label: '清台', color: 'var(--tx-text-2)',  bg: '#E5E7EB', border: 'var(--tx-text-3)' },
};

const MOCK_TABLES: TableInfo[] = [
  // 大厅A区
  { id: 'A1', name: 'A1', zone: '大厅A区', capacity: 4, status: 'occupied', guestName: '刘先生', guestCount: 3, occupiedSince: '11:20', isRoom: false },
  { id: 'A2', name: 'A2', zone: '大厅A区', capacity: 4, status: 'available', isRoom: false },
  { id: 'A3', name: 'A3', zone: '大厅A区', capacity: 6, status: 'reserved', guestName: '李女士(预)', isRoom: false },
  { id: 'A4', name: 'A4', zone: '大厅A区', capacity: 4, status: 'cleaning', isRoom: false },
  { id: 'A5', name: 'A5', zone: '大厅A区', capacity: 4, status: 'available', isRoom: false },
  { id: 'A6', name: 'A6', zone: '大厅A区', capacity: 6, status: 'occupied', guestName: '马女士', guestCount: 5, occupiedSince: '11:05', isRoom: false },
  // 大厅B区
  { id: 'B1', name: 'B1', zone: '大厅B区', capacity: 4, status: 'available', isRoom: false },
  { id: 'B2', name: 'B2', zone: '大厅B区', capacity: 4, status: 'occupied', guestName: '周先生', guestCount: 2, occupiedSince: '11:30', isRoom: false },
  { id: 'B3', name: 'B3', zone: '大厅B区', capacity: 8, status: 'available', isRoom: false },
  { id: 'B4', name: 'B4', zone: '大厅B区', capacity: 4, status: 'available', isRoom: false },
  { id: 'B5', name: 'B5', zone: '大厅B区', capacity: 4, status: 'occupied', guestName: '许先生', guestCount: 4, occupiedSince: '10:55', isRoom: false },
  // 包厢区
  { id: 'R1', name: '牡丹厅', zone: '包厢区', capacity: 12, status: 'reserved', guestName: '张总(VIP)', minSpend: 3000, isRoom: true },
  { id: 'R2', name: '芙蓉厅', zone: '包厢区', capacity: 12, status: 'available', minSpend: 2800, isRoom: true },
  { id: 'R3', name: '兰花厅', zone: '包厢区', capacity: 8, status: 'occupied', guestName: '黄总', guestCount: 6, occupiedSince: '11:00', minSpend: 2000, isRoom: true },
  { id: 'R4', name: '梅花厅', zone: '包厢区', capacity: 8, status: 'available', minSpend: 2000, isRoom: true },
  { id: 'R5', name: '国宾厅', zone: '包厢区', capacity: 16, status: 'reserved', guestName: '陈总(VIP)', minSpend: 5000, isRoom: true },
];

export function SeatAssignPage() {
  const [tables, setTables] = useState<TableInfo[]>(MOCK_TABLES);
  const [selectedTable, setSelectedTable] = useState<TableInfo | null>(null);
  const [zoneFilter, setZoneFilter] = useState<string>('all');
  const [confirmAssign, setConfirmAssign] = useState(false);
  const [assignName, setAssignName] = useState('');
  const [assignCount, setAssignCount] = useState(2);

  const zones = ['all', ...Array.from(new Set(tables.map(t => t.zone)))];

  const filteredTables = zoneFilter === 'all' ? tables : tables.filter(t => t.zone === zoneFilter);
  const groupedByZone = filteredTables.reduce<Record<string, TableInfo[]>>((acc, t) => {
    (acc[t.zone] = acc[t.zone] || []).push(t);
    return acc;
  }, {});

  const counts = {
    available: tables.filter(t => t.status === 'available').length,
    occupied: tables.filter(t => t.status === 'occupied').length,
    reserved: tables.filter(t => t.status === 'reserved').length,
    cleaning: tables.filter(t => t.status === 'cleaning').length,
  };

  const handleAssign = () => {
    if (!selectedTable || !assignName.trim()) return;
    setTables(prev => prev.map(t =>
      t.id === selectedTable.id
        ? { ...t, status: 'occupied' as TableStatus, guestName: assignName, guestCount: assignCount, occupiedSince: new Date().toTimeString().slice(0, 5) }
        : t
    ));
    setConfirmAssign(false);
    setSelectedTable(null);
    setAssignName('');
    setAssignCount(2);
  };

  return (
    <div style={{ padding: 24, height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* 顶部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ fontSize: 32, fontWeight: 800 }}>桌台分配</h1>
        <div style={{ display: 'flex', gap: 16 }}>
          {(Object.entries(STATUS_CONFIG) as [TableStatus, typeof STATUS_CONFIG[TableStatus]][]).map(([key, cfg]) => (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{
                width: 20, height: 20, borderRadius: 4,
                background: cfg.bg, border: `2px solid ${cfg.border}`,
              }} />
              <span style={{ fontSize: 18 }}>{cfg.label} {counts[key]}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 区域筛选 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        {zones.map(z => (
          <button
            key={z}
            onClick={() => setZoneFilter(z)}
            style={{
              minHeight: 48,
              padding: '0 20px',
              borderRadius: 'var(--tx-radius-sm)',
              border: `2px solid ${zoneFilter === z ? 'var(--tx-primary)' : 'var(--tx-border)'}`,
              background: zoneFilter === z ? 'var(--tx-primary-light)' : '#fff',
              color: zoneFilter === z ? 'var(--tx-primary)' : 'var(--tx-text-2)',
              fontSize: 18,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            {z === 'all' ? '全部区域' : z}
          </button>
        ))}
      </div>

      {/* 桌台平面图 */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        WebkitOverflowScrolling: 'touch',
        display: 'flex',
        flexDirection: 'column',
        gap: 28,
        paddingBottom: 40,
      }}>
        {Object.entries(groupedByZone).map(([zone, zoneTables]) => (
          <div key={zone}>
            <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 12, color: 'var(--tx-text-2)' }}>
              {zone}
            </h2>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))',
              gap: 16,
            }}>
              {zoneTables.map(table => {
                const cfg = STATUS_CONFIG[table.status];
                const isSelected = selectedTable?.id === table.id;
                return (
                  <button
                    key={table.id}
                    onClick={() => {
                      setSelectedTable(table);
                      if (table.status === 'available' || table.status === 'reserved') {
                        setConfirmAssign(true);
                      }
                    }}
                    style={{
                      minHeight: table.isRoom ? 140 : 120,
                      borderRadius: 'var(--tx-radius-md)',
                      border: `3px solid ${isSelected ? 'var(--tx-primary)' : cfg.border}`,
                      background: cfg.bg,
                      color: cfg.color,
                      cursor: 'pointer',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 4,
                      padding: 12,
                      transition: 'transform 200ms',
                      position: 'relative',
                    }}
                  >
                    <div style={{ fontSize: table.isRoom ? 22 : 24, fontWeight: 800 }}>{table.name}</div>
                    <div style={{ fontSize: 16, fontWeight: 600 }}>{table.capacity}人桌</div>
                    {table.guestName && (
                      <div style={{ fontSize: 16, marginTop: 2 }}>{table.guestName}</div>
                    )}
                    {table.occupiedSince && (
                      <div style={{ fontSize: 16, opacity: 0.8 }}>入座 {table.occupiedSince}</div>
                    )}
                    {table.minSpend && table.minSpend > 0 && (
                      <div style={{ fontSize: 16, opacity: 0.8 }}>低消 ￥{table.minSpend}</div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* 入座确认弹层 */}
      {confirmAssign && selectedTable && (
        <div style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,0.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 100,
        }}>
          <div style={{
            background: '#fff',
            borderRadius: 'var(--tx-radius-lg)',
            padding: 32,
            width: 420,
            boxShadow: 'var(--tx-shadow-md)',
          }}>
            <h2 style={{ fontSize: 24, fontWeight: 800, marginBottom: 8 }}>确认入座</h2>
            <div style={{ fontSize: 20, color: 'var(--tx-text-2)', marginBottom: 24 }}>
              {selectedTable.name} ({selectedTable.capacity}人{selectedTable.isRoom ? '包厢' : '桌'})
              {selectedTable.minSpend ? ` | 低消 ￥${selectedTable.minSpend}` : ''}
            </div>

            {selectedTable.status === 'reserved' && selectedTable.guestName && (
              <div style={{
                background: '#FEF3C7',
                padding: 12,
                borderRadius: 'var(--tx-radius-sm)',
                fontSize: 18,
                color: '#6B4E00',
                marginBottom: 16,
              }}>
                已预留给: {selectedTable.guestName}
              </div>
            )}

            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginBottom: 8 }}>客户称呼</div>
              <input
                value={assignName}
                onChange={e => setAssignName(e.target.value)}
                placeholder="客户称呼"
                style={{
                  width: '100%', height: 56,
                  borderRadius: 'var(--tx-radius-md)',
                  border: '2px solid var(--tx-border)',
                  padding: '0 16px', fontSize: 20, outline: 'none',
                }}
              />
            </div>

            <div style={{ marginBottom: 24 }}>
              <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginBottom: 8 }}>用餐人数</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <button onClick={() => setAssignCount(Math.max(1, assignCount - 1))} style={{
                  width: 56, height: 56, borderRadius: 'var(--tx-radius-md)',
                  border: '2px solid var(--tx-border)', background: '#fff', fontSize: 24, fontWeight: 700, cursor: 'pointer',
                }}>-</button>
                <span style={{ fontSize: 32, fontWeight: 800, minWidth: 40, textAlign: 'center' }}>{assignCount}</span>
                <button onClick={() => setAssignCount(Math.min(selectedTable.capacity, assignCount + 1))} style={{
                  width: 56, height: 56, borderRadius: 'var(--tx-radius-md)',
                  border: '2px solid var(--tx-border)', background: '#fff', fontSize: 24, fontWeight: 700, cursor: 'pointer',
                }}>+</button>
                <span style={{ fontSize: 18, color: 'var(--tx-text-3)' }}>/ 最多{selectedTable.capacity}人</span>
              </div>
            </div>

            {selectedTable.minSpend && selectedTable.minSpend > 0 && (
              <div style={{
                background: 'var(--tx-primary-light)',
                padding: 12,
                borderRadius: 'var(--tx-radius-sm)',
                fontSize: 18,
                color: 'var(--tx-primary)',
                fontWeight: 600,
                marginBottom: 16,
              }}>
                请提醒客户: 本包厢低消 ￥{selectedTable.minSpend}
              </div>
            )}

            <div style={{ display: 'flex', gap: 12 }}>
              <button onClick={() => { setConfirmAssign(false); setAssignName(''); setAssignCount(2); }} style={{
                flex: 1, height: 56, borderRadius: 'var(--tx-radius-md)',
                border: '2px solid var(--tx-border)', background: '#fff',
                fontSize: 20, fontWeight: 700, cursor: 'pointer', color: 'var(--tx-text-2)',
              }}>取消</button>
              <button onClick={handleAssign} style={{
                flex: 1, height: 56, borderRadius: 'var(--tx-radius-md)',
                border: 'none', background: 'var(--tx-primary)', color: '#fff',
                fontSize: 20, fontWeight: 700, cursor: 'pointer',
              }}>确认入座</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
