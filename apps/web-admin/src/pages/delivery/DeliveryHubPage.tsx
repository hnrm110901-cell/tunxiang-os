/**
 * DeliveryHubPage — 外卖聚合管理页
 * 统一管理美团/饿了么/抖音/自营四平台外卖订单、平台状态、配送分析
 */
import { useEffect, useState, useCallback, useRef } from 'react';

// ─── Constants ───

const BASE = 'http://localhost:8001';
const REFRESH_MS = 30_000;
const BRAND = '#FF6B35';

// ─── Types ───

type PlatformKey = 'meituan' | 'eleme' | 'douyin' | 'self';
type OrderStatus = 'pending' | 'confirmed' | 'delivering' | 'completed' | 'cancelled' | 'anomaly';
type TabKey = 'orders' | 'platforms' | 'analytics';

interface DeliveryOrder {
  id: string;
  order_no: string;
  platform: PlatformKey;
  created_at: string;
  dish_count: number;
  amount_fen: number;
  status: OrderStatus;
  rider_name: string;
}

interface PlatformInfo {
  key: PlatformKey;
  connected: boolean;
  today_orders: number;
  today_revenue_fen: number;
  commission_rate: number;
  shop_open: boolean;
}

interface DailyTrend {
  date: string;
  meituan: number;
  eleme: number;
  douyin: number;
  self: number;
}

interface RiderPerf {
  rider_name: string;
  order_count: number;
  avg_minutes: number;
  good_rate: number;
}

interface TopStats {
  today_total: number;
  delivering: number;
  completed: number;
  anomaly: number;
  avg_delivery_min: number;
}

// ─── Platform & Status Metadata ───

const PLATFORM_META: Record<PlatformKey, { label: string; dot: string; color: string }> = {
  meituan: { label: '美团', dot: '\uD83D\uDFE1', color: '#FAAD14' },
  eleme:   { label: '饿了么', dot: '\uD83D\uDD35', color: '#1677FF' },
  douyin:  { label: '抖音', dot: '\u26AB', color: '#222' },
  self:    { label: '自营', dot: '\uD83D\uDFE0', color: '#FF6B35' },
};

const STATUS_META: Record<OrderStatus, { label: string; color: string; bg: string }> = {
  pending:    { label: '待接单', color: '#E8820C', bg: '#E8820C20' },
  confirmed:  { label: '已接单', color: '#1677FF', bg: '#1677FF20' },
  delivering: { label: '配送中', color: '#722ED1', bg: '#722ED120' },
  completed:  { label: '已完成', color: '#52C41A', bg: '#52C41A20' },
  cancelled:  { label: '已取消', color: '#8C8C8C', bg: '#8C8C8C20' },
  anomaly:    { label: '异常',   color: '#FF4D4F', bg: '#FF4D4F20' },
};

// ─── Mock Data Generators ───

function mockTopStats(): TopStats {
  return { today_total: 186, delivering: 12, completed: 158, anomaly: 3, avg_delivery_min: 34 };
}

function mockOrders(): DeliveryOrder[] {
  const platforms: PlatformKey[] = ['meituan', 'eleme', 'douyin', 'self'];
  const statuses: OrderStatus[] = ['pending', 'confirmed', 'delivering', 'completed', 'cancelled', 'anomaly'];
  const riders = ['张伟', '李强', '王刚', '赵磊', '陈龙', '刘洋', '黄鹏', ''];
  const now = Date.now();
  return Array.from({ length: 30 }, (_, i) => ({
    id: `do-${1000 + i}`,
    order_no: `WM${String(20260402000 + i)}`,
    platform: platforms[i % 4],
    created_at: new Date(now - i * 180_000).toISOString(),
    dish_count: 1 + (i % 6),
    amount_fen: (2000 + i * 350) % 15000 + 1500,
    status: statuses[i % 6],
    rider_name: riders[i % riders.length],
  }));
}

function mockPlatforms(): PlatformInfo[] {
  return [
    { key: 'meituan', connected: true,  today_orders: 82, today_revenue_fen: 1_456_200, commission_rate: 0.18, shop_open: true },
    { key: 'eleme',   connected: true,  today_orders: 54, today_revenue_fen: 876_400,   commission_rate: 0.20, shop_open: true },
    { key: 'douyin',  connected: false, today_orders: 27, today_revenue_fen: 423_800,   commission_rate: 0.15, shop_open: false },
    { key: 'self',    connected: true,  today_orders: 23, today_revenue_fen: 345_600,   commission_rate: 0,    shop_open: true },
  ];
}

function mockTrends(): DailyTrend[] {
  const base = Date.now();
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(base - (6 - i) * 86_400_000);
    return {
      date: `${d.getMonth() + 1}/${d.getDate()}`,
      meituan: 60 + Math.floor(Math.random() * 40),
      eleme: 40 + Math.floor(Math.random() * 30),
      douyin: 15 + Math.floor(Math.random() * 25),
      self: 10 + Math.floor(Math.random() * 20),
    };
  });
}

function mockRiders(): RiderPerf[] {
  return [
    { rider_name: '张伟', order_count: 38, avg_minutes: 28, good_rate: 0.97 },
    { rider_name: '李强', order_count: 34, avg_minutes: 31, good_rate: 0.94 },
    { rider_name: '王刚', order_count: 29, avg_minutes: 35, good_rate: 0.91 },
    { rider_name: '赵磊', order_count: 25, avg_minutes: 33, good_rate: 0.96 },
    { rider_name: '陈龙', order_count: 22, avg_minutes: 29, good_rate: 0.98 },
    { rider_name: '刘洋', order_count: 18, avg_minutes: 42, good_rate: 0.88 },
  ];
}

function mockTimeBuckets(): { label: string; count: number; color: string }[] {
  return [
    { label: '15-30 min', count: 64, color: '#52C41A' },
    { label: '30-45 min', count: 78, color: '#1677FF' },
    { label: '45-60 min', count: 31, color: '#FAAD14' },
    { label: '>60 min',   count: 13, color: '#FF4D4F' },
  ];
}

// ─── Fetch helpers ───

async function fetchJSON<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${BASE}${path}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json() as { ok: boolean; data: T };
    return body.data ?? (body as unknown as T);
  } catch (_e: unknown) {
    return fallback;
  }
}

// ─── Utility ───

function fenToYuan(fen: number): string {
  return (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function relativeTime(iso: string): string {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins}分钟前`;
  if (mins < 1440) return `${Math.floor(mins / 60)}小时前`;
  return `${Math.floor(mins / 1440)}天前`;
}

// ─── Style helpers ───

const card = (extra?: React.CSSProperties): React.CSSProperties => ({
  background: '#fff', borderRadius: 8, padding: 20,
  boxShadow: '0 1px 3px rgba(0,0,0,0.06)', ...extra,
});

const badge = (color: string, bg: string): React.CSSProperties => ({
  display: 'inline-block', padding: '2px 10px', borderRadius: 12,
  fontSize: 12, fontWeight: 500, color, background: bg,
});

// ─────────────────────────────────────────────────
// TopStatsBar
// ─────────────────────────────────────────────────

function TopStatsBar({ stats }: { stats: TopStats }) {
  const items: { label: string; value: string | number; color?: string }[] = [
    { label: '今日外卖单数', value: stats.today_total },
    { label: '配送中', value: stats.delivering, color: '#722ED1' },
    { label: '已完成', value: stats.completed, color: '#52C41A' },
    { label: '异常单', value: stats.anomaly, color: '#FF4D4F' },
    { label: '平均配送时长', value: `${stats.avg_delivery_min} min` },
  ];
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16, marginBottom: 20 }}>
      {items.map((it) => (
        <div key={it.label} style={card({ textAlign: 'center' })}>
          <div style={{ fontSize: 13, color: '#8C8C8C', marginBottom: 6 }}>{it.label}</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: it.color ?? '#262626' }}>{it.value}</div>
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────
// Tab1: Order Table
// ─────────────────────────────────────────────────

function OrderTable({
  orders, onAccept, onReject, onMarkAnomaly, onBatchAccept, selectedIds, toggleSelect, toggleAll,
}: {
  orders: DeliveryOrder[];
  onAccept: (id: string) => void;
  onReject: (id: string) => void;
  onMarkAnomaly: (id: string) => void;
  onBatchAccept: () => void;
  selectedIds: Set<string>;
  toggleSelect: (id: string) => void;
  toggleAll: () => void;
}) {
  const pendingOrders = orders.filter(o => o.status === 'pending');
  const [filterPlatform, setFilterPlatform] = useState<PlatformKey | 'all'>('all');
  const [filterStatus, setFilterStatus] = useState<OrderStatus | 'all'>('all');
  const [detailOrder, setDetailOrder] = useState<DeliveryOrder | null>(null);

  const filtered = orders.filter(o => {
    if (filterPlatform !== 'all' && o.platform !== filterPlatform) return false;
    if (filterStatus !== 'all' && o.status !== filterStatus) return false;
    return true;
  });

  const selectStyle: React.CSSProperties = {
    padding: '4px 10px', borderRadius: 6, border: '1px solid #d9d9d9',
    fontSize: 13, background: '#fff', cursor: 'pointer',
  };

  return (
    <div>
      {/* Toolbar */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
        <select
          style={selectStyle}
          value={filterPlatform}
          onChange={e => setFilterPlatform(e.target.value as PlatformKey | 'all')}
        >
          <option value="all">全部平台</option>
          {(Object.keys(PLATFORM_META) as PlatformKey[]).map(k => (
            <option key={k} value={k}>{PLATFORM_META[k].label}</option>
          ))}
        </select>
        <select
          style={selectStyle}
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value as OrderStatus | 'all')}
        >
          <option value="all">全部状态</option>
          {(Object.keys(STATUS_META) as OrderStatus[]).map(k => (
            <option key={k} value={k}>{STATUS_META[k].label}</option>
          ))}
        </select>

        {pendingOrders.length > 0 && (
          <button
            onClick={onBatchAccept}
            style={{
              marginLeft: 'auto', padding: '6px 18px', borderRadius: 6,
              background: BRAND, color: '#fff', border: 'none', fontWeight: 600,
              fontSize: 13, cursor: 'pointer',
            }}
          >
            批量接单 ({selectedIds.size > 0 ? selectedIds.size : pendingOrders.length})
          </button>
        )}
      </div>

      {/* Table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#FAFAFA', borderBottom: '1px solid #F0F0F0' }}>
              <th style={{ padding: '10px 12px', textAlign: 'left' }}>
                <input type="checkbox" onChange={toggleAll} checked={selectedIds.size === pendingOrders.length && pendingOrders.length > 0} />
              </th>
              <th style={{ padding: '10px 12px', textAlign: 'left', fontWeight: 600 }}>订单号</th>
              <th style={{ padding: '10px 12px', textAlign: 'left', fontWeight: 600 }}>平台</th>
              <th style={{ padding: '10px 12px', textAlign: 'left', fontWeight: 600 }}>下单时间</th>
              <th style={{ padding: '10px 12px', textAlign: 'right', fontWeight: 600 }}>菜品数</th>
              <th style={{ padding: '10px 12px', textAlign: 'right', fontWeight: 600 }}>金额</th>
              <th style={{ padding: '10px 12px', textAlign: 'center', fontWeight: 600 }}>状态</th>
              <th style={{ padding: '10px 12px', textAlign: 'left', fontWeight: 600 }}>配送员</th>
              <th style={{ padding: '10px 12px', textAlign: 'center', fontWeight: 600 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(o => {
              const pm = PLATFORM_META[o.platform];
              const sm = STATUS_META[o.status];
              return (
                <tr key={o.id} style={{ borderBottom: '1px solid #F0F0F0' }}>
                  <td style={{ padding: '10px 12px' }}>
                    {o.status === 'pending' && (
                      <input type="checkbox" checked={selectedIds.has(o.id)} onChange={() => toggleSelect(o.id)} />
                    )}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>{o.order_no}</td>
                  <td style={{ padding: '10px 12px' }}>
                    <span style={{ marginRight: 4 }}>{pm.dot}</span>
                    <span style={{ color: pm.color, fontWeight: 500 }}>{pm.label}</span>
                  </td>
                  <td style={{ padding: '10px 12px', color: '#8C8C8C' }}>{relativeTime(o.created_at)}</td>
                  <td style={{ padding: '10px 12px', textAlign: 'right' }}>{o.dish_count}</td>
                  <td style={{ padding: '10px 12px', textAlign: 'right', fontWeight: 600 }}>{'\u00A5'}{fenToYuan(o.amount_fen)}</td>
                  <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                    <span style={badge(sm.color, sm.bg)}>{sm.label}</span>
                  </td>
                  <td style={{ padding: '10px 12px' }}>{o.rider_name || '-'}</td>
                  <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                    <div style={{ display: 'flex', gap: 6, justifyContent: 'center' }}>
                      {o.status === 'pending' && (
                        <>
                          <ActionBtn label="接单" color="#52C41A" onClick={() => onAccept(o.id)} />
                          <ActionBtn label="拒单" color="#FF4D4F" onClick={() => onReject(o.id)} />
                        </>
                      )}
                      <ActionBtn label="详情" color="#1677FF" onClick={() => setDetailOrder(o)} />
                      {o.status !== 'anomaly' && o.status !== 'cancelled' && o.status !== 'completed' && (
                        <ActionBtn label="异常" color="#FF4D4F" onClick={() => onMarkAnomaly(o.id)} />
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr><td colSpan={9} style={{ padding: 40, textAlign: 'center', color: '#8C8C8C' }}>暂无订单</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Detail Modal */}
      {detailOrder && (
        <DetailModal order={detailOrder} onClose={() => setDetailOrder(null)} />
      )}
    </div>
  );
}

function ActionBtn({ label, color, onClick }: { label: string; color: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '2px 10px', borderRadius: 4, border: `1px solid ${color}`,
        background: 'transparent', color, fontSize: 12, cursor: 'pointer', fontWeight: 500,
      }}
    >
      {label}
    </button>
  );
}

function DetailModal({ order, onClose }: { order: DeliveryOrder; onClose: () => void }) {
  const pm = PLATFORM_META[order.platform];
  const sm = STATUS_META[order.status];
  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        style={{ background: '#fff', borderRadius: 12, padding: 28, minWidth: 400, maxWidth: 520 }}
        onClick={e => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>订单详情</h3>
        <table style={{ width: '100%', fontSize: 13 }}>
          <tbody>
            {([
              ['订单号', order.order_no],
              ['平台', `${pm.dot} ${pm.label}`],
              ['下单时间', new Date(order.created_at).toLocaleString('zh-CN')],
              ['菜品数', String(order.dish_count)],
              ['金额', `\u00A5${fenToYuan(order.amount_fen)}`],
              ['状态', sm.label],
              ['配送员', order.rider_name || '-'],
            ] as [string, string][]).map(([k, v]) => (
              <tr key={k}>
                <td style={{ padding: '6px 0', color: '#8C8C8C', width: 80 }}>{k}</td>
                <td style={{ padding: '6px 0', fontWeight: 500 }}>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ textAlign: 'right', marginTop: 20 }}>
          <button
            onClick={onClose}
            style={{
              padding: '6px 20px', borderRadius: 6, border: '1px solid #d9d9d9',
              background: '#fff', cursor: 'pointer', fontSize: 13,
            }}
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────
// Tab2: Platform Management
// ─────────────────────────────────────────────────

function PlatformPanel({ platforms }: { platforms: PlatformInfo[] }) {
  const [toggling, setToggling] = useState<string | null>(null);

  const handleToggleShop = (key: PlatformKey) => {
    setToggling(key);
    setTimeout(() => setToggling(null), 800);
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 16 }}>
      {platforms.map(p => {
        const meta = PLATFORM_META[p.key];
        return (
          <div key={p.key} style={card({ position: 'relative', overflow: 'hidden' })}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
              <span style={{ fontSize: 28 }}>{meta.dot}</span>
              <div>
                <div style={{ fontWeight: 700, fontSize: 16 }}>{meta.label}</div>
                <div style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{
                    width: 8, height: 8, borderRadius: '50%', display: 'inline-block',
                    background: p.connected ? '#52C41A' : '#FF4D4F',
                  }} />
                  {p.connected ? '已连接' : '已断开'}
                </div>
              </div>
            </div>

            {/* Stats */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 12, color: '#8C8C8C' }}>今日订单</div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{p.today_orders}</div>
              </div>
              <div>
                <div style={{ fontSize: 12, color: '#8C8C8C' }}>今日收入</div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{'\u00A5'}{fenToYuan(p.today_revenue_fen)}</div>
              </div>
              <div>
                <div style={{ fontSize: 12, color: '#8C8C8C' }}>佣金率</div>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{(p.commission_rate * 100).toFixed(0)}%</div>
              </div>
              <div>
                <div style={{ fontSize: 12, color: '#8C8C8C' }}>营业状态</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: p.shop_open ? '#52C41A' : '#FF4D4F' }}>
                  {p.shop_open ? '营业中' : '已休息'}
                </div>
              </div>
            </div>

            {/* Actions */}
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => handleToggleShop(p.key)}
                disabled={toggling === p.key}
                style={{
                  flex: 1, padding: '6px 0', borderRadius: 6,
                  border: `1px solid ${p.shop_open ? '#FF4D4F' : '#52C41A'}`,
                  background: 'transparent', cursor: 'pointer', fontSize: 12,
                  color: p.shop_open ? '#FF4D4F' : '#52C41A', fontWeight: 500,
                }}
              >
                {p.shop_open ? '关店' : '开店'}
              </button>
              <button style={{
                flex: 1, padding: '6px 0', borderRadius: 6,
                border: '1px solid #d9d9d9', background: 'transparent',
                cursor: 'pointer', fontSize: 12, color: '#595959', fontWeight: 500,
              }}>
                菜单同步
              </button>
              <button style={{
                flex: 1, padding: '6px 0', borderRadius: 6,
                border: '1px solid #d9d9d9', background: 'transparent',
                cursor: 'pointer', fontSize: 12, color: '#595959', fontWeight: 500,
              }}>
                设置
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────
// Tab3: Analytics — SVG Charts
// ─────────────────────────────────────────────────

function TrendLineChart({ data }: { data: DailyTrend[] }) {
  const W = 560;
  const H = 240;
  const PAD = { top: 20, right: 20, bottom: 30, left: 40 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const allVals = data.flatMap(d => [d.meituan, d.eleme, d.douyin, d.self]);
  const maxVal = Math.max(...allVals, 1);

  const x = (i: number) => PAD.left + (i / (data.length - 1)) * plotW;
  const y = (v: number) => PAD.top + plotH - (v / maxVal) * plotH;

  const line = (key: PlatformKey) => {
    const pts = data.map((d, i) => `${x(i)},${y(d[key])}`);
    return `M${pts.join('L')}`;
  };

  const platforms: PlatformKey[] = ['meituan', 'eleme', 'douyin', 'self'];

  return (
    <div style={card()}>
      <div style={{ fontWeight: 600, marginBottom: 12, fontSize: 14 }}>近7天各平台订单趋势</div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: W }}>
        {/* Grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map(f => {
          const yy = PAD.top + plotH * (1 - f);
          return (
            <g key={f}>
              <line x1={PAD.left} y1={yy} x2={PAD.left + plotW} y2={yy} stroke="#F0F0F0" />
              <text x={PAD.left - 6} y={yy + 4} textAnchor="end" fontSize={10} fill="#8C8C8C">
                {Math.round(maxVal * f)}
              </text>
            </g>
          );
        })}
        {/* X labels */}
        {data.map((d, i) => (
          <text key={d.date} x={x(i)} y={H - 6} textAnchor="middle" fontSize={10} fill="#8C8C8C">{d.date}</text>
        ))}
        {/* Lines */}
        {platforms.map(pk => (
          <path key={pk} d={line(pk)} fill="none" stroke={PLATFORM_META[pk].color} strokeWidth={2} />
        ))}
      </svg>
      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, marginTop: 8, justifyContent: 'center' }}>
        {platforms.map(pk => (
          <div key={pk} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
            <span style={{ width: 12, height: 3, background: PLATFORM_META[pk].color, display: 'inline-block', borderRadius: 2 }} />
            {PLATFORM_META[pk].label}
          </div>
        ))}
      </div>
    </div>
  );
}

function RevenuePieChart({ platforms }: { platforms: PlatformInfo[] }) {
  const total = platforms.reduce((s, p) => s + p.today_revenue_fen, 0) || 1;
  const R = 70;
  const CX = 90;
  const CY = 90;
  let cumAngle = -Math.PI / 2;

  const slices = platforms.map(p => {
    const frac = p.today_revenue_fen / total;
    const startAngle = cumAngle;
    cumAngle += frac * 2 * Math.PI;
    const endAngle = cumAngle;
    const largeArc = frac > 0.5 ? 1 : 0;
    const x1 = CX + R * Math.cos(startAngle);
    const y1 = CY + R * Math.sin(startAngle);
    const x2 = CX + R * Math.cos(endAngle);
    const y2 = CY + R * Math.sin(endAngle);
    return { key: p.key, frac, d: `M${CX},${CY} L${x1},${y1} A${R},${R} 0 ${largeArc},1 ${x2},${y2} Z` };
  });

  return (
    <div style={card()}>
      <div style={{ fontWeight: 600, marginBottom: 12, fontSize: 14 }}>平台收入占比</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        <svg viewBox="0 0 180 180" width={180} height={180}>
          {slices.map(s => (
            <path key={s.key} d={s.d} fill={PLATFORM_META[s.key].color} opacity={0.85} />
          ))}
        </svg>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {platforms.map(p => (
            <div key={p.key} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              <span style={{ width: 12, height: 12, borderRadius: 3, background: PLATFORM_META[p.key].color, display: 'inline-block' }} />
              <span>{PLATFORM_META[p.key].label}</span>
              <span style={{ color: '#8C8C8C', marginLeft: 4 }}>{((p.today_revenue_fen / total) * 100).toFixed(1)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TimeBucketChart({ buckets }: { buckets: { label: string; count: number; color: string }[] }) {
  const maxVal = Math.max(...buckets.map(b => b.count), 1);
  const BAR_W = 56;
  const GAP = 32;
  const H = 160;
  const W = buckets.length * (BAR_W + GAP);

  return (
    <div style={card()}>
      <div style={{ fontWeight: 600, marginBottom: 12, fontSize: 14 }}>配送时效分布</div>
      <svg viewBox={`0 0 ${W} ${H + 30}`} width="100%" style={{ maxWidth: W }}>
        {buckets.map((b, i) => {
          const barH = (b.count / maxVal) * H;
          const xPos = i * (BAR_W + GAP) + GAP / 2;
          return (
            <g key={b.label}>
              <rect x={xPos} y={H - barH} width={BAR_W} height={barH} rx={4} fill={b.color} opacity={0.85} />
              <text x={xPos + BAR_W / 2} y={H - barH - 6} textAnchor="middle" fontSize={11} fontWeight={600} fill="#262626">
                {b.count}
              </text>
              <text x={xPos + BAR_W / 2} y={H + 16} textAnchor="middle" fontSize={10} fill="#8C8C8C">
                {b.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function RiderTable({ riders }: { riders: RiderPerf[] }) {
  return (
    <div style={card()}>
      <div style={{ fontWeight: 600, marginBottom: 12, fontSize: 14 }}>骑手绩效</div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: '#FAFAFA', borderBottom: '1px solid #F0F0F0' }}>
            <th style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 600 }}>配送员</th>
            <th style={{ padding: '8px 12px', textAlign: 'right', fontWeight: 600 }}>接单数</th>
            <th style={{ padding: '8px 12px', textAlign: 'right', fontWeight: 600 }}>平均时效</th>
            <th style={{ padding: '8px 12px', textAlign: 'right', fontWeight: 600 }}>好评率</th>
          </tr>
        </thead>
        <tbody>
          {riders.map(r => (
            <tr key={r.rider_name} style={{ borderBottom: '1px solid #F0F0F0' }}>
              <td style={{ padding: '8px 12px', fontWeight: 500 }}>{r.rider_name}</td>
              <td style={{ padding: '8px 12px', textAlign: 'right' }}>{r.order_count}</td>
              <td style={{ padding: '8px 12px', textAlign: 'right' }}>{r.avg_minutes} min</td>
              <td style={{ padding: '8px 12px', textAlign: 'right' }}>
                <span style={{ color: r.good_rate >= 0.95 ? '#52C41A' : r.good_rate >= 0.9 ? '#FAAD14' : '#FF4D4F' }}>
                  {(r.good_rate * 100).toFixed(1)}%
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AnalyticsPanel({ platforms }: { platforms: PlatformInfo[] }) {
  const [trends] = useState<DailyTrend[]>(() => mockTrends());
  const [riders] = useState<RiderPerf[]>(() => mockRiders());
  const [buckets] = useState(() => mockTimeBuckets());

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <TrendLineChart data={trends} />
      <RevenuePieChart platforms={platforms} />
      <TimeBucketChart buckets={buckets} />
      <RiderTable riders={riders} />
    </div>
  );
}

// ─────────────────────────────────────────────────
// Main Page
// ─────────────────────────────────────────────────

export function DeliveryHubPage() {
  const [tab, setTab] = useState<TabKey>('orders');
  const [stats, setStats] = useState<TopStats>(mockTopStats);
  const [orders, setOrders] = useState<DeliveryOrder[]>(() => mockOrders());
  const [platforms, setPlatforms] = useState<PlatformInfo[]>(() => mockPlatforms());
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadData = useCallback(async () => {
    const [s, o, p] = await Promise.all([
      fetchJSON<TopStats>('/api/v1/delivery/stats', mockTopStats()),
      fetchJSON<DeliveryOrder[]>('/api/v1/delivery/orders', mockOrders()),
      fetchJSON<PlatformInfo[]>('/api/v1/delivery/platforms', mockPlatforms()),
    ]);
    setStats(s);
    setOrders(o);
    setPlatforms(p);
  }, []);

  useEffect(() => {
    loadData();
    timerRef.current = setInterval(loadData, REFRESH_MS);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [loadData]);

  // Order actions
  const handleAccept = useCallback((id: string) => {
    setOrders(prev => prev.map(o => o.id === id ? { ...o, status: 'confirmed' as OrderStatus } : o));
    fetchJSON(`/api/v1/delivery/orders/${id}/accept`, null);
  }, []);

  const handleReject = useCallback((id: string) => {
    setOrders(prev => prev.map(o => o.id === id ? { ...o, status: 'cancelled' as OrderStatus } : o));
    fetchJSON(`/api/v1/delivery/orders/${id}/reject`, null);
  }, []);

  const handleMarkAnomaly = useCallback((id: string) => {
    setOrders(prev => prev.map(o => o.id === id ? { ...o, status: 'anomaly' as OrderStatus } : o));
    fetchJSON(`/api/v1/delivery/orders/${id}/anomaly`, null);
  }, []);

  const handleBatchAccept = useCallback(() => {
    const ids = selectedIds.size > 0
      ? Array.from(selectedIds)
      : orders.filter(o => o.status === 'pending').map(o => o.id);
    setOrders(prev => prev.map(o => ids.includes(o.id) ? { ...o, status: 'confirmed' as OrderStatus } : o));
    setSelectedIds(new Set());
    fetchJSON('/api/v1/delivery/orders/batch-accept', null);
  }, [selectedIds, orders]);

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    const pendingIds = orders.filter(o => o.status === 'pending').map(o => o.id);
    setSelectedIds(prev => prev.size === pendingIds.length ? new Set() : new Set(pendingIds));
  }, [orders]);

  // Tab styling
  const tabBtn = (key: TabKey, label: string): React.CSSProperties => ({
    padding: '8px 20px', borderRadius: '8px 8px 0 0', border: 'none',
    background: tab === key ? '#fff' : 'transparent',
    color: tab === key ? BRAND : '#8C8C8C',
    fontWeight: tab === key ? 700 : 400,
    fontSize: 14, cursor: 'pointer',
    borderBottom: tab === key ? `2px solid ${BRAND}` : '2px solid transparent',
  });

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#F5F5F5' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>外卖聚合管理</h2>
        <span style={{ fontSize: 12, color: '#8C8C8C' }}>自动刷新 30s</span>
      </div>

      {/* Top Stats */}
      <TopStatsBar stats={stats} />

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid #E8E8E8', marginBottom: 20 }}>
        <button style={tabBtn('orders', '订单总览')} onClick={() => setTab('orders')}>订单总览</button>
        <button style={tabBtn('platforms', '平台管理')} onClick={() => setTab('platforms')}>平台管理</button>
        <button style={tabBtn('analytics', '配送分析')} onClick={() => setTab('analytics')}>配送分析</button>
      </div>

      {/* Tab Content */}
      {tab === 'orders' && (
        <OrderTable
          orders={orders}
          onAccept={handleAccept}
          onReject={handleReject}
          onMarkAnomaly={handleMarkAnomaly}
          onBatchAccept={handleBatchAccept}
          selectedIds={selectedIds}
          toggleSelect={toggleSelect}
          toggleAll={toggleAll}
        />
      )}
      {tab === 'platforms' && <PlatformPanel platforms={platforms} />}
      {tab === 'analytics' && <AnalyticsPanel platforms={platforms} />}
    </div>
  );
}
