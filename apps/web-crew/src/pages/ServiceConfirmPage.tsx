/**
 * 服务确认页面 — 管辖桌台列表 + 每桌服务状态 + 巡台记录
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState } from 'react';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  warning: '#BA7517',
  info: '#185FA5',
};

/* ---------- 类型 ---------- */
type OrderStatusType = 'ordered' | 'all_served' | 'pending_checkout';

interface TableService {
  tableNo: string;
  guestCount: number;
  orderStatus: OrderStatusType;
  totalYuan: number;
  elapsedMin: number;
  lastPatrol: string | null;
}

/* ---------- Mock 数据 ---------- */
const now = new Date();
const fmt = (d: Date) => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;

const INITIAL_TABLES: TableService[] = [
  { tableNo: 'A01', guestCount: 3, orderStatus: 'ordered', totalYuan: 168, elapsedMin: 12, lastPatrol: fmt(new Date(now.getTime() - 8 * 60000)) },
  { tableNo: 'A03', guestCount: 5, orderStatus: 'all_served', totalYuan: 285, elapsedMin: 38, lastPatrol: fmt(new Date(now.getTime() - 15 * 60000)) },
  { tableNo: 'B01', guestCount: 8, orderStatus: 'pending_checkout', totalYuan: 520, elapsedMin: 55, lastPatrol: null },
  { tableNo: 'B03', guestCount: 6, orderStatus: 'ordered', totalYuan: 356, elapsedMin: 22, lastPatrol: fmt(new Date(now.getTime() - 5 * 60000)) },
];

function statusLabel(s: OrderStatusType): string {
  const map: Record<OrderStatusType, string> = { ordered: '已点单', all_served: '已上齐', pending_checkout: '待结账' };
  return map[s];
}

function statusColor(s: OrderStatusType): string {
  const map: Record<OrderStatusType, string> = { ordered: C.accent, all_served: C.green, pending_checkout: C.warning };
  return map[s];
}

/* ---------- 组件 ---------- */
export function ServiceConfirmPage() {
  const [tables, setTables] = useState<TableService[]>(INITIAL_TABLES);

  const handlePatrol = (tableNo: string) => {
    const time = fmt(new Date());
    setTables(prev => prev.map(t =>
      t.tableNo === tableNo ? { ...t, lastPatrol: time } : t,
    ));
  };

  // 统计
  const orderedCount = tables.filter(t => t.orderStatus === 'ordered').length;
  const servedCount = tables.filter(t => t.orderStatus === 'all_served').length;
  const checkoutCount = tables.filter(t => t.orderStatus === 'pending_checkout').length;

  return (
    <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 4px' }}>
        服务确认
      </h1>
      <p style={{ fontSize: 16, color: C.muted, margin: '0 0 16px' }}>
        我管辖的桌台服务状态
      </p>

      {/* 状态汇总 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 20 }}>
        <div style={{
          background: C.card, borderRadius: 10, padding: '12px 10px', textAlign: 'center',
          border: `1px solid ${C.border}`,
        }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: C.accent }}>{orderedCount}</div>
          <div style={{ fontSize: 16, color: C.muted, marginTop: 2 }}>已点单</div>
        </div>
        <div style={{
          background: C.card, borderRadius: 10, padding: '12px 10px', textAlign: 'center',
          border: `1px solid ${C.border}`,
        }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: C.green }}>{servedCount}</div>
          <div style={{ fontSize: 16, color: C.muted, marginTop: 2 }}>已上齐</div>
        </div>
        <div style={{
          background: C.card, borderRadius: 10, padding: '12px 10px', textAlign: 'center',
          border: `1px solid ${C.border}`,
        }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: C.warning }}>{checkoutCount}</div>
          <div style={{ fontSize: 16, color: C.muted, marginTop: 2 }}>待结账</div>
        </div>
      </div>

      {/* 桌台列表 */}
      {tables.map(table => {
        const needsAttention = !table.lastPatrol || table.elapsedMin > 30;
        return (
          <div key={table.tableNo} style={{
            background: C.card, borderRadius: 12, padding: 16, marginBottom: 10,
            border: `1px solid ${C.border}`,
            borderLeft: `4px solid ${statusColor(table.orderStatus)}`,
          }}>
            {/* 桌头 */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 20, fontWeight: 700, color: C.white }}>{table.tableNo}</span>
                <span style={{
                  fontSize: 16, padding: '2px 8px', borderRadius: 6,
                  background: `${statusColor(table.orderStatus)}22`,
                  color: statusColor(table.orderStatus),
                  fontWeight: 600,
                }}>
                  {statusLabel(table.orderStatus)}
                </span>
              </div>
              <span style={{ fontSize: 16, color: C.accent, fontWeight: 700 }}>
                {'\u00A5'}{table.totalYuan}
              </span>
            </div>

            {/* 信息行 */}
            <div style={{
              display: 'flex', justifyContent: 'space-between', fontSize: 16,
              color: C.muted, marginBottom: 12,
            }}>
              <span>{table.guestCount}人 | {table.elapsedMin}分钟</span>
              <span>
                {table.lastPatrol
                  ? `上次巡台 ${table.lastPatrol}`
                  : '未巡台'}
              </span>
            </div>

            {/* 需要关注提示 */}
            {needsAttention && (
              <div style={{
                fontSize: 16, padding: '8px 12px', borderRadius: 8, marginBottom: 12,
                background: `${C.warning}22`, color: C.warning,
              }}>
                {!table.lastPatrol ? '该桌尚未巡台' : '超过30分钟未巡台'}
              </div>
            )}

            {/* 巡台按钮 */}
            <button
              onClick={() => handlePatrol(table.tableNo)}
              style={{
                width: '100%', minHeight: 48, borderRadius: 12,
                background: `${C.green}22`, border: `1px solid ${C.green}`,
                color: C.green, fontSize: 16, fontWeight: 600, cursor: 'pointer',
              }}
            >
              记录巡台
            </button>
          </div>
        );
      })}

      {tables.length === 0 && (
        <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
          当前没有管辖的桌台
        </div>
      )}
    </div>
  );
}
