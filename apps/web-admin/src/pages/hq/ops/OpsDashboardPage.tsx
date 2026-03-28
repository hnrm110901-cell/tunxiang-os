/**
 * 经营驾驶舱 — 今日营业总览
 * 调用 GET /api/v1/dashboard/*
 */
import { useState } from 'react';

// ---------- Mock 数据（接 API 后替换）----------
const MOCK_OVERVIEW = [
  { label: '今日营收', value: '¥28,560', trend: '+12.3%', up: true },
  { label: '订单量', value: '426', trend: '+8.1%', up: true },
  { label: '客单价', value: '¥67.0', trend: '+3.2%', up: true },
  { label: '翻台率', value: '2.8', trend: '-0.2', up: false },
];

const MOCK_STORE_RANK = [
  { rank: 1, name: '芙蓉路店', revenue: 85600, orders: 128, turnover: 3.2, score: 92 },
  { rank: 2, name: '岳麓店', revenue: 64000, orders: 96, turnover: 2.8, score: 78 },
  { rank: 3, name: '星沙店', revenue: 52000, orders: 78, turnover: 2.4, score: 65 },
  { rank: 4, name: '河西店', revenue: 38000, orders: 57, turnover: 1.9, score: 45 },
  { rank: 5, name: '开福店', revenue: 34200, orders: 51, turnover: 2.1, score: 58 },
];

const MOCK_ALERTS = [
  { id: 1, level: 'critical', store: '河西店', msg: '翻台率连续3天低于2.0，建议关注', time: '10:32' },
  { id: 2, level: 'warning', store: '星沙店', msg: '午市出餐超时4单，平均超时8分钟', time: '12:15' },
  { id: 3, level: 'warning', store: '岳麓店', msg: '鲈鱼库存仅剩2份，建议补货', time: '14:20' },
  { id: 4, level: 'info', store: '芙蓉路店', msg: '今日营收已超目标 120%', time: '15:00' },
];

const alertColor: Record<string, string> = {
  critical: '#ff4d4f', warning: '#faad14', info: '#1890ff',
};

const scoreColor = (s: number) => s >= 80 ? '#52c41a' : s >= 60 ? '#faad14' : '#ff4d4f';

export function OpsDashboardPage() {
  const [dateRange] = useState('今日');

  return (
    <div>
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>经营驾驶舱</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {['今日', '本周', '本月'].map((d) => (
            <button key={d} style={{
              padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: dateRange === d ? '#FF6B2C' : '#1a2a33',
              color: dateRange === d ? '#fff' : '#999',
            }}>{d}</button>
          ))}
        </div>
      </div>

      {/* 营业总览卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {MOCK_OVERVIEW.map((kpi) => (
          <div key={kpi.label} style={{
            background: '#112228', borderRadius: 8, padding: 20,
            borderLeft: '3px solid #FF6B2C',
          }}>
            <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>{kpi.label}</div>
            <div style={{ fontSize: 28, fontWeight: 'bold', color: '#fff' }}>{kpi.value}</div>
            <div style={{
              fontSize: 12, marginTop: 4,
              color: kpi.up ? '#52c41a' : '#ff4d4f',
            }}>
              {kpi.up ? '↑' : '↓'} {kpi.trend} 较昨日
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* 门店排行表格 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>门店排行</h3>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ color: '#999', fontSize: 11, textAlign: 'left' }}>
                <th style={{ padding: '8px 4px' }}>#</th>
                <th style={{ padding: '8px 4px' }}>门店</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>营收</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>单量</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>翻台</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>评分</th>
              </tr>
            </thead>
            <tbody>
              {MOCK_STORE_RANK.map((s) => (
                <tr key={s.rank} style={{ borderTop: '1px solid #1a2a33' }}>
                  <td style={{ padding: '10px 4px', fontWeight: 'bold', color: '#FF6B2C' }}>{s.rank}</td>
                  <td style={{ padding: '10px 4px' }}>{s.name}</td>
                  <td style={{ padding: '10px 4px', textAlign: 'right' }}>¥{(s.revenue / 100).toLocaleString()}</td>
                  <td style={{ padding: '10px 4px', textAlign: 'right' }}>{s.orders}</td>
                  <td style={{ padding: '10px 4px', textAlign: 'right' }}>{s.turnover}</td>
                  <td style={{ padding: '10px 4px', textAlign: 'right' }}>
                    <span style={{
                      padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600,
                      background: `${scoreColor(s.score)}20`, color: scoreColor(s.score),
                    }}>{s.score}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 异常摘要列表 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>异常摘要</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {MOCK_ALERTS.map((a) => (
              <div key={a.id} style={{
                padding: 12, borderRadius: 8, background: '#0B1A20',
                borderLeft: `3px solid ${alertColor[a.level]}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{
                    fontSize: 10, padding: '1px 6px', borderRadius: 4, fontWeight: 600,
                    background: `${alertColor[a.level]}20`, color: alertColor[a.level],
                  }}>
                    {a.level === 'critical' ? '严重' : a.level === 'warning' ? '警告' : '提示'}
                  </span>
                  <span style={{ fontSize: 11, color: '#666' }}>{a.time}</span>
                </div>
                <div style={{ fontSize: 13 }}>
                  <span style={{ color: '#FF6B2C', fontWeight: 600 }}>{a.store}</span>
                  {' '}{a.msg}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ECharts 接入点：营收趋势折线图 */}
      <div style={{
        background: '#112228', borderRadius: 8, padding: 20, marginTop: 16,
        minHeight: 240, display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{ textAlign: 'center', color: '#666' }}>
          <div style={{ fontSize: 40, marginBottom: 8 }}>📈</div>
          <div style={{ fontSize: 13 }}>营收趋势图 — ECharts 接入点</div>
          <div style={{ fontSize: 11, color: '#555', marginTop: 4 }}>GET /api/v1/dashboard/revenue-trend</div>
        </div>
      </div>
    </div>
  );
}
