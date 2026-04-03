/**
 * 实时营业巡航页 -- E2 店长/总部
 * 功能: 实时KPI卡片 + 桌台巡航状态 + 出餐巡航 + 沽清巡航 + 巡台记录列表
 * 调用 GET /api/v1/daily-ops/dashboard
 */
import { useState } from 'react';
import { ChartPlaceholder } from '../../../components/ChartPlaceholder';

// ---------- 类型 ----------
type TableAlertType = 'overtime-bill' | 'uncleared' | 'normal';
type DishAlertType = 'overtime' | 'pile-up' | 'normal';
type SoldOutLevel = 'sold-out' | 'soon' | 'ok';

interface KPICard {
  label: string;
  value: string;
  sub: string;
  trend?: string;
  up?: boolean;
}

interface TableStatus {
  id: string;
  name: string;
  zone: string;
  status: TableAlertType;
  occupiedMin: number;
  guestCount: number;
  alert?: string;
}

interface DishQueue {
  id: string;
  dish: string;
  table: string;
  waitMin: number;
  alert: DishAlertType;
  qty: number;
}

interface SoldOutItem {
  id: string;
  dish: string;
  remaining: number;
  level: SoldOutLevel;
  estimateRunOut?: string;
}

interface PatrolRecord {
  id: string;
  time: string;
  zone: string;
  inspector: string;
  type: string;
  result: 'normal' | 'issue';
  note: string;
}

// ---------- 配色 ----------
const TABLE_ALERT_CONFIG: Record<TableAlertType, { label: string; color: string; bg: string }> = {
  'overtime-bill': { label: '超时未结', color: '#A32D2D', bg: '#A32D2D30' },
  'uncleared':     { label: '空桌未清', color: '#BA7517', bg: '#BA751730' },
  'normal':        { label: '正常', color: '#0F6E56', bg: '#0F6E5630' },
};

const DISH_ALERT_CONFIG: Record<DishAlertType, { label: string; color: string }> = {
  'overtime':  { label: '超时', color: '#A32D2D' },
  'pile-up':   { label: '堆积', color: '#BA7517' },
  'normal':    { label: '正常', color: '#0F6E56' },
};

const SOLD_OUT_CONFIG: Record<SoldOutLevel, { label: string; color: string; bg: string }> = {
  'sold-out': { label: '已沽清', color: '#A32D2D', bg: '#A32D2D20' },
  'soon':     { label: '即将沽清', color: '#BA7517', bg: '#BA751720' },
  'ok':       { label: '充足', color: '#0F6E56', bg: '#0F6E5620' },
};

// ---------- Mock 数据 ----------
const MOCK_KPI: KPICard[] = [
  { label: '实时营收', value: '\u00A518,360', sub: '元', trend: '+15.2%', up: true },
  { label: '订单数', value: '267', sub: '单', trend: '+9.8%', up: true },
  { label: '桌台利用率', value: '78.6', sub: '%', trend: '+5.1%', up: true },
  { label: '平均等待', value: '12.3', sub: '分钟', trend: '-2.1', up: true },
];

const MOCK_TABLES: TableStatus[] = [
  { id: 'A01', name: 'A01', zone: 'A区大厅', status: 'overtime-bill', occupiedMin: 125, guestCount: 4, alert: '已超时25分钟未结账' },
  { id: 'A02', name: 'A02', zone: 'A区大厅', status: 'normal', occupiedMin: 35, guestCount: 3 },
  { id: 'A03', name: 'A03', zone: 'A区大厅', status: 'uncleared', occupiedMin: 0, guestCount: 0, alert: '客离15分钟未清台' },
  { id: 'B01', name: 'B01', zone: 'B区包间', status: 'normal', occupiedMin: 60, guestCount: 8 },
  { id: 'B02', name: 'B02', zone: 'B区包间', status: 'overtime-bill', occupiedMin: 140, guestCount: 6, alert: '已超时40分钟未结账' },
  { id: 'C01', name: 'C01', zone: 'C区露台', status: 'normal', occupiedMin: 20, guestCount: 2 },
  { id: 'C02', name: 'C02', zone: 'C区露台', status: 'uncleared', occupiedMin: 0, guestCount: 0, alert: '客离8分钟未清台' },
  { id: 'A04', name: 'A04', zone: 'A区大厅', status: 'normal', occupiedMin: 45, guestCount: 5 },
  { id: 'B03', name: 'B03', zone: 'B区包间', status: 'normal', occupiedMin: 30, guestCount: 10 },
  { id: 'C03', name: 'C03', zone: 'C区露台', status: 'normal', occupiedMin: 55, guestCount: 2 },
];

const MOCK_DISH_QUEUE: DishQueue[] = [
  { id: 'd1', dish: '剁椒鱼头', table: 'B01', waitMin: 28, alert: 'overtime', qty: 1 },
  { id: 'd2', dish: '小炒黄牛肉', table: 'A02', waitMin: 22, alert: 'overtime', qty: 2 },
  { id: 'd3', dish: '口味虾', table: 'B02', waitMin: 18, alert: 'pile-up', qty: 3 },
  { id: 'd4', dish: '辣椒炒肉', table: 'A04', waitMin: 15, alert: 'pile-up', qty: 2 },
  { id: 'd5', dish: '蒸鲈鱼', table: 'C01', waitMin: 8, alert: 'normal', qty: 1 },
  { id: 'd6', dish: '毛氏红烧肉', table: 'B03', waitMin: 6, alert: 'normal', qty: 1 },
];

const MOCK_SOLD_OUT: SoldOutItem[] = [
  { id: 'so1', dish: '澳洲龙虾', remaining: 0, level: 'sold-out' },
  { id: 'so2', dish: '清蒸大闸蟹', remaining: 0, level: 'sold-out' },
  { id: 'so3', dish: '波士顿龙虾', remaining: 2, level: 'soon', estimateRunOut: '约30分钟' },
  { id: 'so4', dish: '剁椒鱼头', remaining: 3, level: 'soon', estimateRunOut: '约45分钟' },
  { id: 'so5', dish: '口味虾(大)', remaining: 5, level: 'soon', estimateRunOut: '约1小时' },
];

const MOCK_PATROL: PatrolRecord[] = [
  { id: 'p1', time: '15:30', zone: 'A区大厅', inspector: '王芳', type: '桌台巡查', result: 'issue', note: 'A03桌面未清理，已通知保洁' },
  { id: 'p2', time: '15:15', zone: 'B区包间', inspector: '李伟', type: '出品巡查', result: 'normal', note: '出品正常，温度达标' },
  { id: 'p3', time: '14:50', zone: 'C区露台', inspector: '王芳', type: '环境巡查', result: 'normal', note: '地面清洁，灯光正常' },
  { id: 'p4', time: '14:30', zone: 'A区大厅', inspector: '张伟', type: '服务巡查', result: 'issue', note: 'A01催菜2次未响应，已跟进' },
  { id: 'p5', time: '14:00', zone: 'B区包间', inspector: '李伟', type: '安全巡查', result: 'normal', note: '消防通道畅通，设备正常' },
];

// ---------- 组件 ----------
export function CruiseMonitorPage() {
  const [tableFilter, setTableFilter] = useState<'all' | TableAlertType>('all');

  const filteredTables = tableFilter === 'all'
    ? MOCK_TABLES
    : MOCK_TABLES.filter((t) => t.status === tableFilter);

  const alertTableCount = MOCK_TABLES.filter((t) => t.status !== 'normal').length;

  return (
    <div>
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>营业巡航</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: '#999' }}>实时刷新 15s</span>
          <span style={{
            width: 8, height: 8, borderRadius: '50%', background: '#0F6E56',
            display: 'inline-block', animation: 'cruise-pulse 2s infinite',
          }} />
        </div>
      </div>

      {/* 实时KPI卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
        {MOCK_KPI.map((kpi) => (
          <div key={kpi.label} style={{
            background: '#112228', borderRadius: 8, padding: 16,
            borderLeft: '3px solid #FF6B2C',
          }}>
            <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>{kpi.label}</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
              <span style={{ fontSize: 26, fontWeight: 'bold', color: '#fff' }}>{kpi.value}</span>
              <span style={{ fontSize: 12, color: '#999' }}>{kpi.sub}</span>
            </div>
            {kpi.trend && (
              <div style={{ fontSize: 11, marginTop: 4, color: kpi.up ? '#0F6E56' : '#A32D2D' }}>
                {kpi.up ? '\u2191' : '\u2193'} {kpi.trend} 较昨日同期
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 桌台巡航状态 */}
      <div style={{ background: '#112228', borderRadius: 8, padding: 20, marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>
            桌台巡航
            {alertTableCount > 0 && (
              <span style={{
                fontSize: 11, marginLeft: 8, padding: '2px 8px', borderRadius: 10,
                background: '#A32D2D20', color: '#A32D2D', fontWeight: 600,
              }}>
                {alertTableCount} 桌异常
              </span>
            )}
          </h3>
          <div style={{ display: 'flex', gap: 6 }}>
            {[
              { key: 'all' as const, label: '全部' },
              { key: 'overtime-bill' as const, label: '超时未结' },
              { key: 'uncleared' as const, label: '空桌未清' },
              { key: 'normal' as const, label: '正常' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setTableFilter(key)}
                style={{
                  padding: '4px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
                  fontSize: 11, fontWeight: 600,
                  background: tableFilter === key ? '#FF6B2C' : '#0B1A20',
                  color: tableFilter === key ? '#fff' : '#999',
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10 }}>
          {filteredTables.map((table) => {
            const cfg = TABLE_ALERT_CONFIG[table.status];
            return (
              <div
                key={table.id}
                style={{
                  padding: 12, borderRadius: 8,
                  background: table.status !== 'normal' ? cfg.bg : '#0B1A20',
                  border: `1px solid ${table.status !== 'normal' ? cfg.color + '60' : '#1a2a33'}`,
                  cursor: 'pointer',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <span style={{ fontSize: 15, fontWeight: 'bold', color: '#fff' }}>{table.name}</span>
                  <span style={{
                    fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
                    color: cfg.color,
                    background: table.status === 'normal' ? cfg.bg : 'transparent',
                  }}>
                    {cfg.label}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: '#999', marginBottom: 2 }}>{table.zone}</div>
                {table.status === 'normal' && table.occupiedMin > 0 && (
                  <div style={{ fontSize: 11, color: '#ccc' }}>
                    {table.guestCount}人 | {table.occupiedMin}分钟
                  </div>
                )}
                {table.alert && (
                  <div style={{
                    fontSize: 11, color: cfg.color, marginTop: 4, fontWeight: 600,
                  }}>
                    {table.alert}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* 出餐巡航 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>
            出餐巡航
            <span style={{
              fontSize: 11, marginLeft: 8, padding: '2px 8px', borderRadius: 10,
              background: '#A32D2D20', color: '#A32D2D', fontWeight: 600,
            }}>
              {MOCK_DISH_QUEUE.filter((d) => d.alert !== 'normal').length} 项异常
            </span>
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {MOCK_DISH_QUEUE.map((item) => {
              const cfg = DISH_ALERT_CONFIG[item.alert];
              return (
                <div key={item.id} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: 10, borderRadius: 8, background: '#0B1A20',
                  borderLeft: `3px solid ${cfg.color}`,
                }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{
                        fontSize: 10, padding: '1px 6px', borderRadius: 4, fontWeight: 600,
                        background: cfg.color + '20', color: cfg.color,
                      }}>
                        {cfg.label}
                      </span>
                      <span style={{ fontSize: 13, fontWeight: 600, color: '#fff' }}>{item.dish}</span>
                      <span style={{ fontSize: 11, color: '#999' }}>x{item.qty}</span>
                    </div>
                    <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
                      {item.table} | 等待 {item.waitMin} 分钟
                    </div>
                  </div>
                  {item.alert !== 'normal' && (
                    <button style={{
                      padding: '4px 12px', borderRadius: 6, border: 'none',
                      background: cfg.color + '20', color: cfg.color,
                      cursor: 'pointer', fontWeight: 600, fontSize: 11,
                    }}>
                      催菜
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* 沽清巡航 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>
            沽清巡航
            <span style={{
              fontSize: 11, marginLeft: 8, padding: '2px 8px', borderRadius: 10,
              background: '#A32D2D20', color: '#A32D2D', fontWeight: 600,
            }}>
              {MOCK_SOLD_OUT.filter((s) => s.level === 'sold-out').length} 项已沽清
            </span>
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {MOCK_SOLD_OUT.map((item) => {
              const cfg = SOLD_OUT_CONFIG[item.level];
              return (
                <div key={item.id} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: 12, borderRadius: 8, background: '#0B1A20',
                  borderLeft: `3px solid ${cfg.color}`,
                  opacity: item.level === 'sold-out' ? 0.7 : 1,
                }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{
                        fontSize: 13, fontWeight: 600,
                        color: item.level === 'sold-out' ? '#999' : '#fff',
                        textDecoration: item.level === 'sold-out' ? 'line-through' : 'none',
                      }}>
                        {item.dish}
                      </span>
                      <span style={{
                        fontSize: 10, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
                        background: cfg.bg, color: cfg.color,
                      }}>
                        {cfg.label}
                      </span>
                    </div>
                    {item.level !== 'sold-out' && (
                      <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
                        剩余 {item.remaining} 份 | {item.estimateRunOut}后售罄
                      </div>
                    )}
                  </div>
                  <span style={{
                    fontSize: 22, fontWeight: 'bold',
                    color: item.level === 'sold-out' ? '#A32D2D' : cfg.color,
                  }}>
                    {item.remaining}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* 巡台记录列表 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>巡台记录</h3>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ color: '#999', fontSize: 11, textAlign: 'left' }}>
                <th style={{ padding: '8px 4px' }}>时间</th>
                <th style={{ padding: '8px 4px' }}>区域</th>
                <th style={{ padding: '8px 4px' }}>巡检人</th>
                <th style={{ padding: '8px 4px' }}>类型</th>
                <th style={{ padding: '8px 4px' }}>结果</th>
                <th style={{ padding: '8px 4px' }}>备注</th>
              </tr>
            </thead>
            <tbody>
              {MOCK_PATROL.map((r) => (
                <tr key={r.id} style={{ borderTop: '1px solid #1a2a33' }}>
                  <td style={{ padding: '10px 4px', color: '#ccc' }}>{r.time}</td>
                  <td style={{ padding: '10px 4px', color: '#ccc' }}>{r.zone}</td>
                  <td style={{ padding: '10px 4px', color: '#ccc' }}>{r.inspector}</td>
                  <td style={{ padding: '10px 4px', color: '#ccc' }}>{r.type}</td>
                  <td style={{ padding: '10px 4px' }}>
                    <span style={{
                      fontSize: 10, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
                      background: r.result === 'issue' ? '#A32D2D20' : '#0F6E5620',
                      color: r.result === 'issue' ? '#A32D2D' : '#0F6E56',
                    }}>
                      {r.result === 'issue' ? '异常' : '正常'}
                    </span>
                  </td>
                  <td style={{ padding: '10px 4px', color: '#999', maxWidth: 200 }}>{r.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 图表占位 */}
        <ChartPlaceholder
          title="营业时段客流热力图"
          chartType="Heatmap"
          apiEndpoint="GET /api/v1/daily-ops/dashboard"
          height={320}
        />
      </div>

      {/* 动画 */}
      <style>{`
        @keyframes cruise-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
}
