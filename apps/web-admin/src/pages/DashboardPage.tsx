/**
 * 经营驾驶舱 — 总部首屏
 * 多店 KPI 概览 + 今日经营简报 + Top3 决策 + 告警
 */

const fen2yuan = (fen: number) => `¥${(fen / 100).toLocaleString()}`;

// Mock 数据（接入 tx-analytics BFF 后替换）
const MOCK_KPI = [
  { label: '今日营收', value: fen2yuan(2856000), trend: '+12.3%', color: '#FF6B2C' },
  { label: '成本率', value: '31.2%', trend: '-1.5pp', color: '#52c41a' },
  { label: '客流', value: '426 人', trend: '+8%', color: '#1890ff' },
  { label: '客单价', value: fen2yuan(6700), trend: '+3.2%', color: '#722ed1' },
];

const MOCK_STORES = [
  { name: '芙蓉路店', score: 88, status: 'excellent', revenue: 856000, weakest: '人效' },
  { name: '岳麓店', score: 72, status: 'good', revenue: 640000, weakest: '成本率' },
  { name: '星沙店', score: 55, status: 'warning', revenue: 520000, weakest: '客诉率' },
  { name: '河西店', score: 45, status: 'critical', revenue: 380000, weakest: '翻台率' },
];

const MOCK_DECISIONS = [
  { rank: 1, title: '减少鲈鱼采购30%', saving_yuan: 1200, confidence: 0.85, source: '库存预警' },
  { rank: 2, title: '周末增加2名服务员', saving_yuan: 800, confidence: 0.78, source: '出餐调度' },
  { rank: 3, title: '下架低毛利菜品3道', saving_yuan: 650, confidence: 0.72, source: '智能排菜' },
];

const statusColor: Record<string, string> = {
  excellent: '#52c41a', good: '#1890ff', warning: '#faad14', critical: '#ff4d4f',
};

export function DashboardPage() {
  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 20 }}>经营驾驶舱</h2>

      {/* KPI 卡片行 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {MOCK_KPI.map((kpi) => (
          <div key={kpi.label} style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
            <div style={{ fontSize: 12, color: '#999' }}>{kpi.label}</div>
            <div style={{ fontSize: 28, fontWeight: 'bold', color: kpi.color, margin: '4px 0' }}>{kpi.value}</div>
            <div style={{ fontSize: 12, color: kpi.trend.startsWith('+') ? '#52c41a' : '#ff4d4f' }}>{kpi.trend}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* 左：门店健康排名 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>门店健康度排名</h3>
          {MOCK_STORES.map((store, i) => (
            <div key={store.name} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '10px 0', borderBottom: i < MOCK_STORES.length - 1 ? '1px solid #1a2a33' : 'none',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{
                  width: 28, height: 28, borderRadius: '50%',
                  background: statusColor[store.status], color: '#fff',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 14, fontWeight: 'bold',
                }}>{store.score}</span>
                <div>
                  <div style={{ fontSize: 14 }}>{store.name}</div>
                  <div style={{ fontSize: 11, color: '#666' }}>最弱：{store.weakest}</div>
                </div>
              </div>
              <div style={{ fontSize: 14, color: '#999' }}>{fen2yuan(store.revenue)}</div>
            </div>
          ))}
        </div>

        {/* 右：Top3 AI 决策 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>今日 AI 决策推荐</h3>
          {MOCK_DECISIONS.map((d) => (
            <div key={d.rank} style={{
              padding: 12, marginBottom: 8, borderRadius: 8, background: '#0B1A20',
              border: '1px solid #1a2a33',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{
                    width: 24, height: 24, borderRadius: '50%', background: '#FF6B2C',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 12, fontWeight: 'bold',
                  }}>#{d.rank}</span>
                  <span style={{ fontSize: 14 }}>{d.title}</span>
                </div>
                <span style={{ color: '#52c41a', fontWeight: 'bold' }}>+¥{d.saving_yuan}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 11, color: '#666' }}>
                <span>来源: {d.source}</span>
                <span>置信度: {(d.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>
          ))}
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            <span style={{ color: '#52c41a', fontSize: 16, fontWeight: 'bold' }}>
              预期日节省: ¥{MOCK_DECISIONS.reduce((s, d) => s + d.saving_yuan, 0).toLocaleString()}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
