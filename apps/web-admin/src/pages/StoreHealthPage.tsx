/**
 * 门店健康度详情页
 * 5维雷达图 + 门店对比 + 趋势
 */

const MOCK_STORE_HEALTH = {
  store_name: '芙蓉路店',
  score: 88,
  status: 'excellent',
  dimensions: {
    revenue_completion: { score: 92, label: '营收完成率', weight: '30%' },
    table_turnover: { score: 85, label: '翻台率', weight: '20%' },
    cost_rate: { score: 78, label: '成本率', weight: '25%' },
    complaint_rate: { score: 95, label: '客诉率', weight: '15%' },
    staff_efficiency: { score: 82, label: '人效', weight: '10%' },
  },
  weakest: 'cost_rate',
  brief: '芙蓉路店今日营收¥8,560，成本率32.5%（偏高）\n⚠️ 食材成本偏高：32.5%，关注趋势\n⚠️ 鲈鱼损耗¥320居首，建议调整备餐量\n✅ 明日建议：关注成本率变化，确认备料量是否合理',
};

const statusColor: Record<string, string> = {
  excellent: '#52c41a', good: '#1890ff', warning: '#faad14', critical: '#ff4d4f',
};

export function StoreHealthPage() {
  const h = MOCK_STORE_HEALTH;

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 20 }}>门店健康度</h2>

      {/* 门店卡片 */}
      <div style={{ background: '#112228', borderRadius: 8, padding: 24, marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 20 }}>{h.store_name}</h3>
            <span style={{ color: statusColor[h.status], fontSize: 14 }}>
              {h.status === 'excellent' ? '优秀' : h.status === 'good' ? '良好' : h.status === 'warning' ? '警告' : '危急'}
            </span>
          </div>
          <div style={{
            width: 80, height: 80, borderRadius: '50%',
            border: `4px solid ${statusColor[h.status]}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 28, fontWeight: 'bold', color: statusColor[h.status],
          }}>
            {h.score}
          </div>
        </div>

        {/* 5 维度得分条 */}
        <div style={{ display: 'grid', gap: 8 }}>
          {Object.entries(h.dimensions).map(([key, dim]) => (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ width: 80, fontSize: 12, color: '#999', textAlign: 'right' }}>{dim.label}</span>
              <div style={{ flex: 1, height: 8, background: '#1a2a33', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{
                  width: `${dim.score}%`, height: '100%', borderRadius: 4,
                  background: key === h.weakest ? '#ff4d4f' : dim.score >= 85 ? '#52c41a' : dim.score >= 70 ? '#1890ff' : '#faad14',
                }} />
              </div>
              <span style={{ width: 40, fontSize: 12, textAlign: 'right', color: key === h.weakest ? '#ff4d4f' : '#999' }}>
                {dim.score}
              </span>
              <span style={{ width: 30, fontSize: 10, color: '#666' }}>{dim.weight}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 经营简报 */}
      <div style={{ background: '#112228', borderRadius: 8, padding: 24 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>今日经营简报</h3>
        <pre style={{
          whiteSpace: 'pre-wrap', fontFamily: "'Noto Sans SC', sans-serif",
          fontSize: 14, lineHeight: 1.8, color: '#ccc', margin: 0,
        }}>
          {h.brief}
        </pre>
      </div>
    </div>
  );
}
