/**
 * KDS 出餐统计 — KPI + 按档口分组统计
 * 大字号设计，厨房友好
 */

/* ---------- Mock Data ---------- */
const mockKPI = {
  avgTime: 14.8,
  overtimeRate: 12.5,
  totalCount: 86,
};

interface StallStats {
  name: string;
  totalOrders: number;
  avgTime: number;
  overtimeCount: number;
  overtimeRate: number;
  topDish: string;
  topDishCount: number;
}

const mockStalls: StallStats[] = [
  { name: '热菜档口', totalOrders: 42, avgTime: 18.2, overtimeCount: 8, overtimeRate: 19.0, topDish: '剁椒鱼头', topDishCount: 28 },
  { name: '凉菜档口', totalOrders: 18, avgTime: 6.5, overtimeCount: 1, overtimeRate: 5.6, topDish: '凉拌黄瓜', topDishCount: 13 },
  { name: '主食档口', totalOrders: 52, avgTime: 4.2, overtimeCount: 0, overtimeRate: 0, topDish: '米饭', topDishCount: 68 },
  { name: '蒸菜档口', totalOrders: 15, avgTime: 22.5, overtimeCount: 4, overtimeRate: 26.7, topDish: '外婆鸡', topDishCount: 18 },
];

/* ---------- Component ---------- */
export function StatsPage() {
  const kpiColor = (val: number, thresholdBad: number) =>
    val >= thresholdBad ? '#ff4d4f' : val >= thresholdBad * 0.7 ? '#faad14' : '#52c41a';

  return (
    <div style={{
      background: '#0B1A20', minHeight: '100vh', color: '#E0E0E0',
      fontFamily: 'Noto Sans SC, sans-serif', padding: 16,
    }}>
      <h1 style={{ margin: '0 0 16px', fontSize: 28, color: '#fff' }}>出餐统计</h1>

      {/* KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 24 }}>
        <div style={{
          background: '#112B36', borderRadius: 10, padding: 20, textAlign: 'center',
          borderTop: '4px solid #1890ff',
        }}>
          <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 8 }}>平均出餐时长</div>
          <div style={{ fontSize: 48, fontWeight: 'bold', color: kpiColor(mockKPI.avgTime, 20), fontFamily: 'JetBrains Mono, monospace' }}>
            {mockKPI.avgTime}
          </div>
          <div style={{ fontSize: 16, color: '#666' }}>分钟</div>
        </div>

        <div style={{
          background: '#112B36', borderRadius: 10, padding: 20, textAlign: 'center',
          borderTop: '4px solid #ff4d4f',
        }}>
          <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 8 }}>超时率</div>
          <div style={{ fontSize: 48, fontWeight: 'bold', color: kpiColor(mockKPI.overtimeRate, 15), fontFamily: 'JetBrains Mono, monospace' }}>
            {mockKPI.overtimeRate}%
          </div>
          <div style={{ fontSize: 16, color: '#666' }}>超时 / 总数</div>
        </div>

        <div style={{
          background: '#112B36', borderRadius: 10, padding: 20, textAlign: 'center',
          borderTop: '4px solid #52c41a',
        }}>
          <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 8 }}>总出餐数</div>
          <div style={{ fontSize: 48, fontWeight: 'bold', color: '#52c41a', fontFamily: 'JetBrains Mono, monospace' }}>
            {mockKPI.totalCount}
          </div>
          <div style={{ fontSize: 16, color: '#666' }}>单</div>
        </div>
      </div>

      {/* Stats by Stall */}
      <h2 style={{ fontSize: 22, color: '#fff', marginBottom: 12 }}>按档口统计</h2>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
        {mockStalls.map(stall => {
          const barWidth = (stall.avgTime / 30) * 100;
          return (
            <div key={stall.name} style={{
              background: '#112B36', borderRadius: 10, padding: 18,
              borderLeft: `4px solid ${stall.overtimeRate > 20 ? '#ff4d4f' : stall.overtimeRate > 10 ? '#faad14' : '#52c41a'}`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <span style={{ fontSize: 20, fontWeight: 'bold', color: '#fff' }}>{stall.name}</span>
                <span style={{ fontSize: 14, color: '#8899A6' }}>{stall.totalOrders} 单</span>
              </div>

              {/* Avg time bar */}
              <div style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 4 }}>
                  <span style={{ color: '#8899A6' }}>平均出餐</span>
                  <span style={{
                    fontWeight: 'bold', fontSize: 20,
                    color: kpiColor(stall.avgTime, 20),
                    fontFamily: 'JetBrains Mono, monospace',
                  }}>
                    {stall.avgTime}'
                  </span>
                </div>
                <div style={{ height: 8, background: '#1A3A48', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{
                    width: `${Math.min(barWidth, 100)}%`, height: '100%', borderRadius: 4,
                    background: kpiColor(stall.avgTime, 20),
                  }} />
                </div>
              </div>

              {/* Overtime */}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 6 }}>
                <span style={{ color: '#8899A6' }}>超时</span>
                <span style={{ color: stall.overtimeRate > 15 ? '#ff4d4f' : '#666' }}>
                  {stall.overtimeCount}单 ({stall.overtimeRate}%)
                </span>
              </div>

              {/* Top dish */}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14 }}>
                <span style={{ color: '#8899A6' }}>热门菜</span>
                <span style={{ color: '#E0C97F' }}>{stall.topDish} x{stall.topDishCount}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
