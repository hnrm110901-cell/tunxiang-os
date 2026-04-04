/**
 * 桌台分配 — 桌台平面图，按区域/状态着色，点击确认入座
 */
import { useState, useEffect, useCallback } from 'react';
import {
  fetchTables,
  seatAtTable,
  clearTable,
  type TableInfo,
  type TableStatus,
} from '../api/tablesApi';

const STORE_ID = import.meta.env.VITE_STORE_ID || 'default-store';
const POLL_INTERVAL_MS = 30_000; // 30秒轮询刷新桌台状态

const STATUS_CONFIG: Record<TableStatus, { label: string; color: string; bg: string; border: string }> = {
  available: { label: '空闲', color: 'var(--tx-success)', bg: '#DCFCE7', border: 'var(--tx-success)' },
  occupied:  { label: '占用', color: '#fff',              bg: 'var(--tx-danger)', border: 'var(--tx-danger)' },
  reserved:  { label: '预留', color: '#6B4E00',           bg: '#FEF3C7', border: 'var(--tx-warning)' },
  cleaning:  { label: '清台', color: 'var(--tx-text-2)',  bg: '#E5E7EB', border: 'var(--tx-text-3)' },
};

export function SeatAssignPage() {
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTable, setSelectedTable] = useState<TableInfo | null>(null);
  const [zoneFilter, setZoneFilter] = useState<string>('all');
  const [confirmAssign, setConfirmAssign] = useState(false);
  const [assignName, setAssignName] = useState('');
  const [assignCount, setAssignCount] = useState(2);
  const [actionLoading, setActionLoading] = useState(false);

  const loadTables = useCallback(async (showLoadingSpinner = false) => {
    try {
      if (showLoadingSpinner) setLoading(true);
      setError(null);
      const result = await fetchTables(STORE_ID);
      setTables(result.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载桌台数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadTables(true);
  }, [loadTables]);

  // Polling for auto-refresh
  useEffect(() => {
    const timer = setInterval(() => loadTables(false), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [loadTables]);

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

  const handleAssign = async () => {
    if (!selectedTable || !assignName.trim()) return;
    try {
      setActionLoading(true);
      setError(null);
      await seatAtTable(
        STORE_ID,
        selectedTable.table_id,
        assignCount,
        assignName.trim(),
      );
      setConfirmAssign(false);
      setSelectedTable(null);
      setAssignName('');
      setAssignCount(2);
      await loadTables(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '入座分配失败');
    } finally {
      setActionLoading(false);
    }
  };

  const handleClearTable = async (tableId: string) => {
    try {
      setActionLoading(true);
      setError(null);
      await clearTable(STORE_ID, tableId);
      await loadTables(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '清台失败');
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 24, display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <div style={{ fontSize: 22, color: 'var(--tx-text-3)' }}>加载桌台数据中...</div>
      </div>
    );
  }

  return (
    <div style={{ padding: 24, height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* 错误提示 */}
      {error && (
        <div style={{
          background: '#FFF5F5', border: '1px solid var(--tx-danger)', borderRadius: 'var(--tx-radius-sm)',
          padding: '12px 20px', marginBottom: 16, color: 'var(--tx-danger)', fontSize: 18,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span>{error}</span>
          <button onClick={() => setError(null)} style={{
            border: 'none', background: 'transparent', color: 'var(--tx-danger)',
            fontSize: 18, cursor: 'pointer', fontWeight: 700,
          }}>关闭</button>
        </div>
      )}

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
                const isSelected = selectedTable?.table_id === table.table_id;
                return (
                  <button
                    key={table.table_id}
                    onClick={() => {
                      setSelectedTable(table);
                      if (table.status === 'available' || table.status === 'reserved') {
                        setConfirmAssign(true);
                        // Pre-fill guest name if table has a reservation
                        if (table.guest_name) {
                          setAssignName(table.guest_name);
                        }
                        if (table.guest_count) {
                          setAssignCount(table.guest_count);
                        }
                      } else if (table.status === 'occupied') {
                        // Show option to clear table
                        if (confirm(`确认清台 ${table.table_name}？`)) {
                          handleClearTable(table.table_id);
                        }
                      }
                    }}
                    style={{
                      minHeight: table.is_room ? 140 : 120,
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
                    <div style={{ fontSize: table.is_room ? 22 : 24, fontWeight: 800 }}>{table.table_name}</div>
                    <div style={{ fontSize: 16, fontWeight: 600 }}>{table.capacity}人桌</div>
                    {table.guest_name && (
                      <div style={{ fontSize: 16, marginTop: 2 }}>{table.guest_name}</div>
                    )}
                    {table.occupied_since && (
                      <div style={{ fontSize: 16, opacity: 0.8 }}>入座 {table.occupied_since}</div>
                    )}
                    {table.min_spend_fen != null && table.min_spend_fen > 0 && (
                      <div style={{ fontSize: 16, opacity: 0.8 }}>低消 ￥{(table.min_spend_fen / 100).toFixed(0)}</div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}

        {Object.keys(groupedByZone).length === 0 && (
          <div style={{
            textAlign: 'center',
            padding: 80,
            fontSize: 20,
            color: 'var(--tx-text-3)',
          }}>
            暂无桌台数据
          </div>
        )}
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
              {selectedTable.table_name} ({selectedTable.capacity}人{selectedTable.is_room ? '包厢' : '桌'})
              {selectedTable.min_spend_fen ? ` | 低消 ￥${(selectedTable.min_spend_fen / 100).toFixed(0)}` : ''}
            </div>

            {selectedTable.status === 'reserved' && selectedTable.guest_name && (
              <div style={{
                background: '#FEF3C7',
                padding: 12,
                borderRadius: 'var(--tx-radius-sm)',
                fontSize: 18,
                color: '#6B4E00',
                marginBottom: 16,
              }}>
                已预留给: {selectedTable.guest_name}
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

            {selectedTable.min_spend_fen != null && selectedTable.min_spend_fen > 0 && (
              <div style={{
                background: 'var(--tx-primary-light)',
                padding: 12,
                borderRadius: 'var(--tx-radius-sm)',
                fontSize: 18,
                color: 'var(--tx-primary)',
                fontWeight: 600,
                marginBottom: 16,
              }}>
                请提醒客户: 本包厢低消 ￥{(selectedTable.min_spend_fen / 100).toFixed(0)}
              </div>
            )}

            <div style={{ display: 'flex', gap: 12 }}>
              <button onClick={() => { setConfirmAssign(false); setAssignName(''); setAssignCount(2); }} style={{
                flex: 1, height: 56, borderRadius: 'var(--tx-radius-md)',
                border: '2px solid var(--tx-border)', background: '#fff',
                fontSize: 20, fontWeight: 700, cursor: 'pointer', color: 'var(--tx-text-2)',
              }}>取消</button>
              <button onClick={handleAssign} disabled={actionLoading} style={{
                flex: 1, height: 56, borderRadius: 'var(--tx-radius-md)',
                border: 'none', background: 'var(--tx-primary)', color: '#fff',
                fontSize: 20, fontWeight: 700,
                cursor: actionLoading ? 'not-allowed' : 'pointer',
                opacity: actionLoading ? 0.6 : 1,
              }}>{actionLoading ? '处理中...' : '确认入座'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
