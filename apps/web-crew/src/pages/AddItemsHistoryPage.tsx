/**
 * AddItemsHistoryPage — 服务员端今日加菜记录
 * Store-Crew 终端，手机竖屏 PWA，无Ant Design
 * 最小点击区48px，最小字体16px，inline style
 * 背景 #f5f5f5，30s自动刷新
 */
import { useState, useEffect, useCallback } from 'react';
import { txFetch } from '../api/index';

// ── 类型 ──────────────────────────────────────────────────
interface AddItemRecord {
  id: string;
  tableNo: string;
  time: string;
  crewName: string;
  items: { name: string; qty: number; price: number }[];
  status: 'served' | 'pending';
}

// API 响应类型
interface AddItemsHistoryResponse {
  items: AddItemRecord[];
  total: number;
}

// ── 按桌台分组 ────────────────────────────────────────────
function groupByTable(records: AddItemRecord[]): Map<string, AddItemRecord[]> {
  const map = new Map<string, AddItemRecord[]>();
  for (const r of records) {
    const existing = map.get(r.tableNo) ?? [];
    existing.push(r);
    map.set(r.tableNo, existing);
  }
  return map;
}

function calcTotal(items: AddItemRecord['items']): number {
  return items.reduce((sum, item) => sum + item.price * item.qty, 0);
}

// ── 触控按钮辅助 ──────────────────────────────────────────
const btnBase: React.CSSProperties = {
  border: 'none', cursor: 'pointer',
  fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
  fontWeight: 600, WebkitTapHighlightColor: 'transparent', outline: 'none',
};

// ── 详情弹窗 ──────────────────────────────────────────────
interface DetailModalProps {
  record: AddItemRecord;
  onClose: () => void;
}

function DetailModal({ record, onClose }: DetailModalProps) {
  const total = calcTotal(record.items);

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        width: '100%', maxWidth: 480, background: '#fff',
        borderRadius: '16px 16px 0 0',
        padding: '0 0 24px',
        boxShadow: '0 -4px 24px rgba(0,0,0,0.12)',
        animation: 'slideUp 300ms ease-out',
      }}>
        {/* 拖动条 */}
        <div style={{ display: 'flex', justifyContent: 'center', padding: '12px 0 8px' }}>
          <div style={{ width: 40, height: 4, borderRadius: 2, background: '#E8E6E1' }} />
        </div>

        {/* 标题 */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 20px 16px',
          borderBottom: '1px solid #E8E6E1',
        }}>
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#2C2C2A' }}>
              {record.tableNo}桌 加菜详情
            </div>
            <div style={{ fontSize: 16, color: '#5F5E5A', marginTop: 4 }}>
              {record.time} · {record.crewName}
            </div>
          </div>
          <span style={{
            display: 'inline-flex', alignItems: 'center',
            padding: '4px 12px', borderRadius: 20, fontSize: 15, fontWeight: 600,
            background: record.status === 'served' ? '#EEF7F3' : '#FFF3ED',
            color: record.status === 'served' ? '#0F6E56' : '#BA7517',
          }}>
            {record.status === 'served' ? '已出' : '待出'}
          </span>
        </div>

        {/* 菜品明细 */}
        <div style={{ padding: '16px 20px' }}>
          {record.items.map((item, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '10px 0', borderBottom: i < record.items.length - 1 ? '1px solid #F0EDE6' : 'none',
            }}>
              <div>
                <span style={{ fontSize: 18, color: '#2C2C2A', fontWeight: 500 }}>{item.name}</span>
                <span style={{ fontSize: 16, color: '#B4B2A9', marginLeft: 8 }}>×{item.qty}</span>
              </div>
              <span style={{ fontSize: 18, color: '#2C2C2A', fontWeight: 600 }}>
                ¥{(item.price * item.qty).toFixed(0)}
              </span>
            </div>
          ))}
        </div>

        {/* 合计 */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '12px 20px 16px',
          borderTop: '2px solid #F0EDE6',
        }}>
          <span style={{ fontSize: 17, color: '#5F5E5A', fontWeight: 600 }}>加菜合计</span>
          <span style={{ fontSize: 22, color: '#FF6B35', fontWeight: 700 }}>¥{total.toFixed(0)}</span>
        </div>

        {/* 关闭按钮 */}
        <div style={{ padding: '0 20px' }}>
          <button
            onClick={onClose}
            style={{
              ...btnBase, width: '100%', height: 52, borderRadius: 12,
              background: '#F0EDE6', color: '#5F5E5A', fontSize: 17,
            }}
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 单条记录卡片 ──────────────────────────────────────────
interface RecordCardProps {
  record: AddItemRecord;
  onPress: (r: AddItemRecord) => void;
}

function RecordCard({ record, onPress }: RecordCardProps) {
  const [pressed, setPressed] = useState(false);
  const total = calcTotal(record.items);
  const itemSummary = record.items.map(i => `${i.name}×${i.qty}`).join('、');

  return (
    <div
      onTouchStart={() => setPressed(true)}
      onTouchEnd={() => setPressed(false)}
      onMouseDown={() => setPressed(true)}
      onMouseUp={() => setPressed(false)}
      onMouseLeave={() => setPressed(false)}
      onClick={() => onPress(record)}
      style={{
        background: '#fff', borderRadius: 12, padding: '16px',
        marginBottom: 10,
        boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        transform: pressed ? 'scale(0.98)' : 'scale(1)',
        transition: 'transform 200ms ease',
        cursor: 'pointer', WebkitTapHighlightColor: 'transparent',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
        <div>
          <span style={{ fontSize: 18, fontWeight: 700, color: '#2C2C2A' }}>{record.time}</span>
          <span style={{ fontSize: 16, color: '#5F5E5A', marginLeft: 10 }}>{record.crewName}</span>
        </div>
        <span style={{
          display: 'inline-flex', alignItems: 'center',
          padding: '3px 10px', borderRadius: 20, fontSize: 14, fontWeight: 600,
          background: record.status === 'served' ? '#EEF7F3' : '#FFF3ED',
          color: record.status === 'served' ? '#0F6E56' : '#BA7517',
        }}>
          {record.status === 'served' ? '已出' : '待出'}
        </span>
      </div>
      <div style={{ fontSize: 16, color: '#5F5E5A', marginBottom: 8, lineHeight: 1.5 }}>
        {itemSummary.length > 30 ? itemSummary.slice(0, 30) + '...' : itemSummary}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 16, color: '#B4B2A9' }}>共{record.items.length}道菜</span>
        <span style={{ fontSize: 18, fontWeight: 700, color: '#FF6B35' }}>+¥{total.toFixed(0)}</span>
      </div>
    </div>
  );
}

// ── 按桌台分组区块 ────────────────────────────────────────
interface TableGroupProps {
  tableNo: string;
  records: AddItemRecord[];
  onPressRecord: (r: AddItemRecord) => void;
}

function TableGroup({ tableNo, records, onPressRecord }: TableGroupProps) {
  const tableTotal = records.reduce((sum, r) => sum + calcTotal(r.items), 0);

  return (
    <div style={{ marginBottom: 20 }}>
      {/* 分组标题 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 16px 8px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%', background: '#FF6B35',
          }} />
          <span style={{ fontSize: 18, fontWeight: 700, color: '#2C2C2A' }}>{tableNo}桌</span>
          <span style={{
            background: '#FFF3ED', color: '#FF6B35', borderRadius: 10,
            padding: '2px 8px', fontSize: 14, fontWeight: 600,
          }}>
            {records.length}次加菜
          </span>
        </div>
        <span style={{ fontSize: 17, color: '#5F5E5A', fontWeight: 600 }}>
          ¥{tableTotal.toFixed(0)}
        </span>
      </div>

      {/* 该桌记录列表 */}
      <div style={{ padding: '0 12px' }}>
        {records.map(r => (
          <RecordCard key={r.id} record={r} onPress={onPressRecord} />
        ))}
      </div>
    </div>
  );
}

// ── 主页面 ────────────────────────────────────────────────
export function AddItemsHistoryPage() {
  const [records, setRecords] = useState<AddItemRecord[]>([]);
  const [detailModal, setDetailModal] = useState<AddItemRecord | null>(null);
  const [lastRefresh, setLastRefresh] = useState(new Date());
  const [loading, setLoading] = useState(false);

  // 加载今日加菜历史
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await txFetch<AddItemsHistoryResponse>(
        '/api/v1/trade/orders/add-items-history?date=today'
      );
      setRecords(data.items ?? []);
      setLastRefresh(new Date());
    } catch {
      // 失败时保留上次数据，不崩溃
    } finally {
      setLoading(false);
    }
  }, []);

  // 首次加载 + 30秒自动刷新
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => {
      void refresh();
    }, 30_000);
    return () => clearInterval(timer);
  }, [refresh]);

  // 统计
  const totalTimes = records.length;
  const totalAmount = records.reduce((sum, r) => sum + calcTotal(r.items), 0);
  const pendingCount = records.filter(r => r.status === 'pending').length;

  // 按桌台分组，有待出单的桌台排前面
  const grouped = groupByTable(records);
  const tableOrder = Array.from(grouped.keys()).sort((a, b) => {
    const aPending = (grouped.get(a) ?? []).some(r => r.status === 'pending') ? 0 : 1;
    const bPending = (grouped.get(b) ?? []).some(r => r.status === 'pending') ? 0 : 1;
    return aPending - bPending;
  });

  const formatTime = (d: Date) =>
    `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;

  return (
    <div style={{
      minHeight: '100vh', background: '#f5f5f5',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
    }}>
      {/* ── 顶部栏 ──────────────────────────────────────── */}
      <div style={{
        background: '#112228',
        padding: '16px 16px 12px',
        position: 'sticky', top: 0, zIndex: 50,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: '#fff' }}>今日加菜记录</div>
          <button
            onClick={refresh}
            disabled={loading}
            style={{
              ...btnBase, height: 40, padding: '0 16px', borderRadius: 20,
              background: loading ? '#1a2a33' : 'rgba(255,107,53,0.15)',
              color: loading ? '#5F5E5A' : '#FF6B35',
              fontSize: 16, display: 'flex', alignItems: 'center', gap: 6,
            }}
          >
            {loading ? (
              '刷新中...'
            ) : (
              <>
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <path d="M13 7A6 6 0 1 1 7 1" stroke="#FF6B35" strokeWidth="1.8" strokeLinecap="round" />
                  <path d="M13 1v6h-6" stroke="#FF6B35" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                刷新
              </>
            )}
          </button>
        </div>

        {/* 汇总卡片 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
          <div style={{
            background: 'rgba(255,255,255,0.07)', borderRadius: 12, padding: '12px 14px',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: 26, fontWeight: 700, color: '#FF6B35' }}>{totalTimes}</div>
            <div style={{ fontSize: 15, color: '#B4B2A9', marginTop: 2 }}>加菜次数</div>
          </div>
          <div style={{
            background: 'rgba(255,255,255,0.07)', borderRadius: 12, padding: '12px 14px',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: 26, fontWeight: 700, color: '#FF6B35' }}>¥{totalAmount.toFixed(0)}</div>
            <div style={{ fontSize: 15, color: '#B4B2A9', marginTop: 2 }}>加菜金额</div>
          </div>
          <div style={{
            background: pendingCount > 0 ? 'rgba(186,117,23,0.15)' : 'rgba(255,255,255,0.07)',
            borderRadius: 12, padding: '12px 14px', textAlign: 'center',
          }}>
            <div style={{ fontSize: 26, fontWeight: 700, color: pendingCount > 0 ? '#BA7517' : '#B4B2A9' }}>
              {pendingCount}
            </div>
            <div style={{ fontSize: 15, color: '#B4B2A9', marginTop: 2 }}>待出单</div>
          </div>
        </div>

        {/* 刷新时间 */}
        <div style={{ fontSize: 14, color: '#5F5E5A', marginTop: 10, textAlign: 'right' }}>
          最后更新 {formatTime(lastRefresh)} · 30秒自动刷新
        </div>
      </div>

      {/* ── 记录列表区 ──────────────────────────────────── */}
      <div style={{ padding: '12px 0 80px' }}>
        {records.length === 0 ? (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            padding: '60px 20px', color: '#B4B2A9',
          }}>
            <div style={{ fontSize: 40, marginBottom: 16 }}>📋</div>
            <div style={{ fontSize: 18, color: '#B4B2A9' }}>今日暂无加菜记录</div>
          </div>
        ) : (
          tableOrder.map(tableNo => (
            <TableGroup
              key={tableNo}
              tableNo={tableNo}
              records={grouped.get(tableNo) ?? []}
              onPressRecord={setDetailModal}
            />
          ))
        )}
      </div>

      {/* ── 详情弹窗 ──────────────────────────────────── */}
      {detailModal && (
        <DetailModal record={detailModal} onClose={() => setDetailModal(null)} />
      )}
    </div>
  );
}

export default AddItemsHistoryPage;
