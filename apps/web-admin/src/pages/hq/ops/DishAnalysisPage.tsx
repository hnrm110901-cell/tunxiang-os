/**
 * 菜品分析 — 销量/毛利排行、四象限散点图、退菜率、菜单优化建议
 * 调用 GET /api/v1/analysis/dish/*
 */
import { useState } from 'react';
import { TxScatterChart } from '../../../components/charts';

const MOCK_SALES_RANK = [
  { rank: 1, name: '剁椒鱼头', sales: 128, revenue: 12800, trend: '+15%' },
  { rank: 2, name: '小炒黄牛肉', sales: 96, revenue: 9600, trend: '+8%' },
  { rank: 3, name: '口味虾', sales: 84, revenue: 10080, trend: '+22%' },
  { rank: 4, name: '辣椒炒肉', sales: 76, revenue: 3800, trend: '-2%' },
  { rank: 5, name: '红烧肉', sales: 68, revenue: 5440, trend: '+5%' },
];

const MOCK_MARGIN_RANK = [
  { rank: 1, name: '口味虾', margin: 72.5, revenue: 10080, sales: 84 },
  { rank: 2, name: '剁椒鱼头', margin: 68.2, revenue: 12800, sales: 128 },
  { rank: 3, name: '红烧肉', margin: 65.0, revenue: 5440, sales: 68 },
  { rank: 4, name: '小炒黄牛肉', margin: 58.3, revenue: 9600, sales: 96 },
  { rank: 5, name: '辣椒炒肉', margin: 45.2, revenue: 3800, sales: 76 },
];

const MOCK_RETURN_RANK = [
  { name: '水煮鱼', returnRate: 5.2, returnCount: 8, reason: '口味偏咸' },
  { name: '酸菜鱼', returnRate: 3.8, returnCount: 5, reason: '等待时间过长' },
  { name: '蒜蓉虾', returnRate: 2.5, returnCount: 3, reason: '分量不足' },
  { name: '干锅牛蛙', returnRate: 2.1, returnCount: 2, reason: '口味不符预期' },
];

const MOCK_SUGGESTIONS = [
  { type: 'promote', icon: '🔝', title: '推荐主推：口味虾', desc: '高毛利(72.5%) + 销量增长22%，建议增加曝光位' },
  { type: 'optimize', icon: '🔧', title: '优化：辣椒炒肉', desc: '销量高但毛利仅45.2%，建议调整配方或定价' },
  { type: 'remove', icon: '⚠️', title: '关注：水煮鱼', desc: '退菜率5.2%居首，建议优化口味或调整备餐流程' },
  { type: 'new', icon: '✨', title: '新品机会：酸汤肥牛', desc: '竞品热销单品，预估毛利率68%，建议试推' },
];

const marginColor = (m: number) => m >= 65 ? '#52c41a' : m >= 50 ? '#faad14' : '#ff4d4f';

export function DishAnalysisPage() {
  const [tab, setTab] = useState<'overview' | 'quadrant'>('overview');

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>菜品分析</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {([['overview', '总览'], ['quadrant', '四象限']] as const).map(([key, label]) => (
            <button key={key} onClick={() => setTab(key)} style={{
              padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: tab === key ? '#FF6B2C' : '#1a2a33',
              color: tab === key ? '#fff' : '#999',
            }}>{label}</button>
          ))}
        </div>
      </div>

      {tab === 'overview' ? (
        <>
          {/* 双列表：销量排行 + 毛利排行 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            {/* 销量排行 */}
            <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
              <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>销量排行 TOP5</h3>
              {MOCK_SALES_RANK.map((d) => (
                <div key={d.rank} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '10px 0', borderBottom: '1px solid #1a2a33',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{
                      width: 24, height: 24, borderRadius: '50%', fontSize: 11, fontWeight: 700,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      background: d.rank <= 3 ? '#FF6B2C' : '#1a2a33',
                      color: d.rank <= 3 ? '#fff' : '#999',
                    }}>{d.rank}</span>
                    <span style={{ fontSize: 13 }}>{d.name}</span>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 14, fontWeight: 600 }}>{d.sales} 份</div>
                    <div style={{ fontSize: 11, color: d.trend.startsWith('+') ? '#52c41a' : '#ff4d4f' }}>{d.trend}</div>
                  </div>
                </div>
              ))}
            </div>

            {/* 毛利排行 */}
            <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
              <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>毛利排行 TOP5</h3>
              {MOCK_MARGIN_RANK.map((d) => (
                <div key={d.rank} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '10px 0', borderBottom: '1px solid #1a2a33',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{
                      width: 24, height: 24, borderRadius: '50%', fontSize: 11, fontWeight: 700,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      background: d.rank <= 3 ? '#FF6B2C' : '#1a2a33',
                      color: d.rank <= 3 ? '#fff' : '#999',
                    }}>{d.rank}</span>
                    <span style={{ fontSize: 13 }}>{d.name}</span>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 14, fontWeight: 600, color: marginColor(d.margin) }}>{d.margin}%</div>
                    <div style={{ fontSize: 11, color: '#999' }}>{d.sales} 份</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 退菜率排行 */}
          <div style={{ background: '#112228', borderRadius: 8, padding: 20, marginBottom: 16 }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>退菜率排行</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
              {MOCK_RETURN_RANK.map((d) => (
                <div key={d.name} style={{
                  padding: 14, borderRadius: 8, background: '#0B1A20',
                  borderTop: '2px solid #ff4d4f',
                }}>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{d.name}</div>
                  <div style={{ fontSize: 22, fontWeight: 'bold', color: '#ff4d4f' }}>{d.returnRate}%</div>
                  <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>退菜 {d.returnCount} 份</div>
                  <div style={{ fontSize: 11, color: '#666', marginTop: 2 }}>主因：{d.reason}</div>
                </div>
              ))}
            </div>
          </div>

          {/* 菜单优化建议 */}
          <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>菜单优化建议</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              {MOCK_SUGGESTIONS.map((s) => (
                <div key={s.title} style={{
                  padding: 14, borderRadius: 8, background: '#0B1A20',
                  border: '1px solid #1a2a33',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <span style={{ fontSize: 18 }}>{s.icon}</span>
                    <span style={{ fontSize: 13, fontWeight: 600 }}>{s.title}</span>
                  </div>
                  <div style={{ fontSize: 12, color: '#999', lineHeight: 1.6 }}>{s.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </>
      ) : (
        /* 四象限散点图 */
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 4px', fontSize: 16 }}>菜品四象限分析</h3>
          <div style={{ fontSize: 12, color: '#666', marginBottom: 16 }}>X轴：销量 / Y轴：毛利率 / 气泡大小：营收</div>
          <TxScatterChart
            data={[
              { name: '剁椒鱼头', x: 128, y: 68.2, size: 128 },
              { name: '小炒黄牛肉', x: 96, y: 58.3, size: 96 },
              { name: '口味虾', x: 84, y: 72.5, size: 100 },
              { name: '辣椒炒肉', x: 76, y: 45.2, size: 38 },
              { name: '红烧肉', x: 68, y: 65.0, size: 54 },
              { name: '酸菜鱼', x: 52, y: 55.0, size: 46 },
              { name: '蒜蓉虾', x: 45, y: 70.0, size: 63 },
              { name: '干锅牛蛙', x: 38, y: 48.5, size: 30 },
              { name: '水煮鱼', x: 32, y: 42.0, size: 25 },
              { name: '凉拌黄瓜', x: 120, y: 35.0, size: 18 },
              { name: '老鸭汤', x: 28, y: 62.0, size: 35 },
              { name: '清蒸鲈鱼', x: 22, y: 75.0, size: 55 },
            ]}
            height={480}
            xLabel="销量(份)"
            yLabel="毛利率(%)"
            xUnit="份"
            yUnit="%"
            showQuadrants
            quadrantLabels={['明星(高销高利)', '问号(低销高利)', '瘦狗(低销低利)', '金牛(高销低利)']}
          />
        </div>
      )}
    </div>
  );
}
