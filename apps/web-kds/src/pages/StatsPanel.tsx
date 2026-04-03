/**
 * StatsPanel — 出品统计
 *
 * 今日出品数量/平均出餐时间/超时次数
 * 按档口统计
 * 深色背景，触控优化（最小48x48按钮，最小16px字体）
 */
import { useState } from 'react';

// ─── Types ───

interface OverallStats {
  todayTotal: number;
  todayCompleted: number;
  avgCookTimeSec: number;
  overtimeCount: number;
  overtimeRate: number;
  currentPending: number;
  currentCooking: number;
  peakHour: string;
  peakHourCount: number;
}

interface DeptStats {
  deptId: string;
  deptName: string;
  totalOrders: number;
  completedOrders: number;
  avgTimeSec: number;
  overtimeCount: number;
  overtimeRate: number;
  topDish: string;
  topDishCount: number;
  fastestTimeSec: number;
  slowestTimeSec: number;
}

interface HourlyData {
  hour: string;
  count: number;
  avgTimeSec: number;
}

// ─── Mock Data ───

const MOCK_OVERALL: OverallStats = {
  todayTotal: 128,
  todayCompleted: 112,
  avgCookTimeSec: 888, // 14.8min
  overtimeCount: 16,
  overtimeRate: 12.5,
  currentPending: 8,
  currentCooking: 6,
  peakHour: '12:00-13:00',
  peakHourCount: 32,
};

const MOCK_DEPTS: DeptStats[] = [
  { deptId: 'hot', deptName: '炒炉', totalOrders: 52, completedOrders: 45, avgTimeSec: 1092, overtimeCount: 10, overtimeRate: 19.2, topDish: '剁椒鱼头', topDishCount: 28, fastestTimeSec: 360, slowestTimeSec: 2100 },
  { deptId: 'cold', deptName: '凉菜', totalOrders: 22, completedOrders: 22, avgTimeSec: 390, overtimeCount: 1, overtimeRate: 4.5, topDish: '凉拌黄瓜', topDishCount: 15, fastestTimeSec: 120, slowestTimeSec: 780 },
  { deptId: 'steam', deptName: '蒸菜', totalOrders: 18, completedOrders: 15, avgTimeSec: 1350, overtimeCount: 5, overtimeRate: 27.8, topDish: '外婆鸡', topDishCount: 18, fastestTimeSec: 600, slowestTimeSec: 2400 },
  { deptId: 'staple', deptName: '主食', totalOrders: 58, completedOrders: 58, avgTimeSec: 252, overtimeCount: 0, overtimeRate: 0, topDish: '米饭', topDishCount: 86, fastestTimeSec: 60, slowestTimeSec: 480 },
  { deptId: 'bar', deptName: '吧台', totalOrders: 15, completedOrders: 14, avgTimeSec: 180, overtimeCount: 0, overtimeRate: 0, topDish: '柠檬茶', topDishCount: 12, fastestTimeSec: 60, slowestTimeSec: 360 },
];

const MOCK_HOURLY: HourlyData[] = [
  { hour: '10:00', count: 4, avgTimeSec: 600 },
  { hour: '11:00', count: 18, avgTimeSec: 720 },
  { hour: '12:00', count: 32, avgTimeSec: 960 },
  { hour: '13:00', count: 24, avgTimeSec: 900 },
  { hour: '14:00', count: 8, avgTimeSec: 540 },
  { hour: '15:00', count: 3, avgTimeSec: 420 },
  { hour: '16:00', count: 2, avgTimeSec: 360 },
  { hour: '17:00', count: 12, avgTimeSec: 660 },
  { hour: '18:00', count: 28, avgTimeSec: 1020 },
  { hour: '19:00', count: 22, avgTimeSec: 960 },
  { hour: '20:00', count: 14, avgTimeSec: 780 },
  { hour: '21:00', count: 5, avgTimeSec: 540 },
];

// ─── Helpers ───

function fmtSec(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (s === 0) return `${m}分`;
  return `${m}分${s}秒`;
}

function fmtMin(sec: number): string {
  return `${(sec / 60).toFixed(1)}`;
}

function kpiColor(val: number, thresholdBad: number): string {
  if (val >= thresholdBad) return '#A32D2D';
  if (val >= thresholdBad * 0.7) return '#BA7517';
  return '#0F6E56';
}

// ─── Component ───

export function StatsPanel() {
  const [overall] = useState<OverallStats>(MOCK_OVERALL);
  const [depts] = useState<DeptStats[]>(MOCK_DEPTS);
  const [hourly] = useState<HourlyData[]>(MOCK_HOURLY);
  const maxHourlyCount = Math.max(...hourly.map(h => h.count), 1);

  return (
    <div style={{
      background: '#0A0A0A', minHeight: '100vh', color: '#E0E0E0',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
      padding: 20,
    }}>
      {/* 顶栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 28, color: '#FF6B35' }}>出品统计</h1>
        <span style={{ fontSize: 18, color: '#666' }}>
          今日已完成 <b style={{ color: '#0F6E56', fontSize: 24 }}>{overall.todayCompleted}</b> / {overall.todayTotal} 单
        </span>
      </div>

      {/* KPI 卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 28 }}>
        <KPICard
          label="平均出餐时长"
          value={fmtMin(overall.avgCookTimeSec)}
          unit="分钟"
          color={kpiColor(overall.avgCookTimeSec / 60, 20)}
          topColor="#1890ff"
        />
        <KPICard
          label="超时次数"
          value={String(overall.overtimeCount)}
          unit={`超时率 ${overall.overtimeRate}%`}
          color={kpiColor(overall.overtimeRate, 15)}
          topColor="#A32D2D"
        />
        <KPICard
          label="当前排队"
          value={String(overall.currentPending)}
          unit={`制作中 ${overall.currentCooking}`}
          color="#BA7517"
          topColor="#BA7517"
        />
        <KPICard
          label="高峰时段"
          value={overall.peakHour}
          unit={`${overall.peakHourCount} 单`}
          color="#E0C97F"
          topColor="#E0C97F"
          valueSize={24}
        />
      </div>

      {/* 时段分布图（简易柱状图） */}
      <div style={{ marginBottom: 28 }}>
        <h2 style={{ fontSize: 22, color: '#fff', marginBottom: 14 }}>时段出品分布</h2>
        <div style={{
          background: '#111', borderRadius: 12, padding: 20,
          display: 'flex', alignItems: 'flex-end', gap: 6, height: 180,
        }}>
          {hourly.map(h => {
            const barH = (h.count / maxHourlyCount) * 140;
            const avgMin = h.avgTimeSec / 60;
            const barColor = avgMin >= 15 ? '#A32D2D' : avgMin >= 10 ? '#BA7517' : '#0F6E56';
            return (
              <div key={h.hour} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                <span style={{ fontSize: 16, color: '#888', marginBottom: 4, fontFamily: 'JetBrains Mono, monospace' }}>
                  {h.count}
                </span>
                <div style={{
                  width: '100%', maxWidth: 40, height: barH, borderRadius: '4px 4px 0 0',
                  background: barColor, transition: 'height 300ms ease',
                }} />
                <span style={{ fontSize: 16, color: '#666', marginTop: 6 }}>
                  {h.hour.split(':')[0]}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* 按档口统计 */}
      <h2 style={{ fontSize: 22, color: '#fff', marginBottom: 14 }}>按档口统计</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 14 }}>
        {depts.map(dept => {
          const avgMin = dept.avgTimeSec / 60;
          const barWidth = (avgMin / 30) * 100;

          return (
            <div key={dept.deptId} style={{
              background: '#111', borderRadius: 12, padding: 20,
              borderLeft: `6px solid ${dept.overtimeRate > 20 ? '#A32D2D' : dept.overtimeRate > 10 ? '#BA7517' : '#0F6E56'}`,
            }}>
              {/* 标题行 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                <span style={{ fontSize: 22, fontWeight: 'bold', color: '#fff' }}>{dept.deptName}</span>
                <span style={{ fontSize: 16, color: '#888' }}>
                  {dept.completedOrders}/{dept.totalOrders} 单
                </span>
              </div>

              {/* 平均出餐进度条 */}
              <div style={{ marginBottom: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, marginBottom: 6 }}>
                  <span style={{ color: '#888' }}>平均出餐</span>
                  <span style={{
                    fontWeight: 'bold', fontSize: 22,
                    color: kpiColor(avgMin, 20),
                    fontFamily: 'JetBrains Mono, monospace',
                  }}>
                    {fmtMin(dept.avgTimeSec)}'
                  </span>
                </div>
                <div style={{ height: 10, background: '#1a1a1a', borderRadius: 5, overflow: 'hidden' }}>
                  <div style={{
                    width: `${Math.min(barWidth, 100)}%`, height: '100%', borderRadius: 5,
                    background: kpiColor(avgMin, 20),
                    transition: 'width 300ms ease',
                  }} />
                </div>
              </div>

              {/* 快慢极值 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, marginBottom: 8 }}>
                <span style={{ color: '#888' }}>
                  最快 <span style={{ color: '#0F6E56' }}>{fmtSec(dept.fastestTimeSec)}</span>
                </span>
                <span style={{ color: '#888' }}>
                  最慢 <span style={{ color: '#A32D2D' }}>{fmtSec(dept.slowestTimeSec)}</span>
                </span>
              </div>

              {/* 超时 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, marginBottom: 8 }}>
                <span style={{ color: '#888' }}>超时</span>
                <span style={{ color: dept.overtimeRate > 15 ? '#A32D2D' : '#888' }}>
                  {dept.overtimeCount}单 ({dept.overtimeRate}%)
                </span>
              </div>

              {/* 热门菜 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16 }}>
                <span style={{ color: '#888' }}>热门菜</span>
                <span style={{ color: '#E0C97F' }}>{dept.topDish} x{dept.topDishCount}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── KPI 卡片子组件 ───

function KPICard({ label, value, unit, color, topColor, valueSize }: {
  label: string; value: string; unit: string; color: string; topColor: string; valueSize?: number;
}) {
  return (
    <div style={{
      background: '#111', borderRadius: 12, padding: 20, textAlign: 'center',
      borderTop: `4px solid ${topColor}`,
    }}>
      <div style={{ fontSize: 16, color: '#888', marginBottom: 10 }}>{label}</div>
      <div style={{
        fontSize: valueSize || 44, fontWeight: 'bold', color,
        fontFamily: 'JetBrains Mono, monospace',
        marginBottom: 6,
      }}>
        {value}
      </div>
      <div style={{ fontSize: 16, color: '#666' }}>{unit}</div>
    </div>
  );
}
