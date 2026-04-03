/**
 * W6 服务员绩效实时看板
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

/* ---------- 颜色常量 ---------- */
const C = {
  bg: '#0B0B0B',
  card: '#111',
  border: '#1A1A1A',
  text: '#E0E0E0',
  muted: '#555',
  primary: '#FF6B35',
  gold: '#FFD700',
  silver: '#C0C0C0',
  bronze: '#CD7F32',
  success: '#30D158',
  warning: '#FF9F0A',
};

/* ---------- Mock 数据 ---------- */
const MOCK_STATS = {
  operator_name: '张三',
  rank: 2,
  total_staff: 5,
  table_turns: 3,
  revenue_contributed: 428000,
  avg_check: 20000,
  upsell_rate: 22,
  bell_response_avg_sec: 45,
  complaint_count: 0,
  rush_handled: 3,
};

const MOCK_LEADERBOARD: {
  rank: number;
  operator_name: string;
  value: number;
  badge: 'gold' | 'silver' | 'bronze' | null;
  is_me?: boolean;
}[] = [
  { rank: 1, operator_name: '李四',      value: 682000, badge: 'gold' },
  { rank: 2, operator_name: '张三（你）', value: 428000, badge: 'silver', is_me: true },
  { rank: 3, operator_name: '王五',      value: 392000, badge: 'bronze' },
  { rank: 4, operator_name: '赵六',      value: 210000, badge: null },
  { rank: 5, operator_name: '孙七',      value: 156000, badge: null },
];

const MOCK_TREND = [
  { date: '03-25', table_turns: 2 },
  { date: '03-26', table_turns: 4 },
  { date: '03-27', table_turns: 3 },
  { date: '03-28', table_turns: 5 },
  { date: '03-29', table_turns: 2 },
  { date: '03-30', table_turns: 4 },
  { date: '03-31', table_turns: 3 },
];

/* ---------- 工具函数 ---------- */
function formatRevenue(val: number): string {
  if (val >= 10000) return `¥${(val / 10000).toFixed(1)}w`;
  return `¥${(val / 100).toFixed(0)}`;
}

function getBadgeEmoji(badge: 'gold' | 'silver' | 'bronze' | null): string {
  if (badge === 'gold') return '🥇';
  if (badge === 'silver') return '🥈';
  if (badge === 'bronze') return '🥉';
  return '   ';
}

function getRankEmoji(rank: number): string {
  if (rank === 1) return '🥇';
  if (rank === 2) return '🥈';
  if (rank === 3) return '🥉';
  return `#${rank}`;
}

function getMotivation(rank: number, total: number, trend: 'up' | 'down' | 'same'): string {
  if (rank === 1) return '今日最佳！继续保持 🏆';
  if (rank <= Math.ceil(total / 2)) {
    if (trend === 'up') return `比昨天提升了，继续加油！距第${rank - 1}名只差一点 💪`;
    return `排名第${rank}，今天可以更好！`;
  }
  return `还有提升空间，加油冲上去！`;
}

type Period = 'shift' | 'today' | 'month';
type LeaderMetric = 'revenue' | 'turns' | 'upsell' | 'response';

const PERIOD_LABELS: Record<Period, string> = {
  shift: '当班',
  today: '今日',
  month: '本月',
};

const METRIC_LABELS: Record<LeaderMetric, string> = {
  revenue: '营收',
  turns: '翻台',
  upsell: '加菜',
  response: '响应',
};

/* ---------- 趋势柱状图 ---------- */
function TrendBar({ data, todayLabel }: { data: typeof MOCK_TREND; todayLabel: string }) {
  const maxVal = Math.max(...data.map(d => d.table_turns), 1);
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: 80, paddingBottom: 0 }}>
      {data.map((d, i) => {
        const isToday = i === data.length - 1;
        const heightPct = (d.table_turns / maxVal) * 100;
        return (
          <div
            key={d.date}
            style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}
          >
            <div style={{ fontSize: 11, color: isToday ? C.primary : C.muted, fontWeight: isToday ? 700 : 400 }}>
              {d.table_turns}
            </div>
            <div
              style={{
                width: '100%',
                height: `${Math.max(heightPct * 0.6, 4)}px`,
                background: isToday ? C.primary : '#2A2A2A',
                borderRadius: '3px 3px 0 0',
                transition: 'height 0.3s',
              }}
            />
            <div style={{ fontSize: 10, color: C.muted, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%' }}>
              {isToday ? todayLabel : d.date.slice(3)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ---------- 主组件 ---------- */
export function CrewStatsPage() {
  const navigate = useNavigate();
  const [period, setPeriod] = useState<Period>('today');
  const [metric, setMetric] = useState<LeaderMetric>('revenue');

  const stats = MOCK_STATS;
  const leaderboard = MOCK_LEADERBOARD;
  const trend = MOCK_TREND;

  // 激励文案：rank 2 → 比排名昨天 rank 3 提升了
  const motivationTrend: 'up' | 'down' | 'same' = 'up';
  const motivation = getMotivation(stats.rank, stats.total_staff, motivationTrend);

  const coreMetrics = [
    { label: '翻台数',   value: `${stats.table_turns}次`,                  color: C.text },
    { label: '贡献营收', value: formatRevenue(stats.revenue_contributed),   color: C.success },
    { label: '人均客单', value: formatRevenue(stats.avg_check),             color: C.text },
    { label: '加菜转化', value: `${stats.upsell_rate}%`,                   color: C.warning },
    { label: '铃响应速', value: `${stats.bell_response_avg_sec}秒`,         color: stats.bell_response_avg_sec <= 60 ? C.success : C.warning },
    { label: '投诉数',   value: `${stats.complaint_count}次`,               color: stats.complaint_count === 0 ? C.success : '#ef4444' },
  ];

  return (
    <div style={{ padding: '0 0 80px', background: C.bg, minHeight: '100vh', color: C.text }}>
      {/* 顶部导航栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '16px 16px 12px', borderBottom: `1px solid ${C.border}`,
        position: 'sticky', top: 0, background: C.bg, zIndex: 10,
      }}>
        <button
          onClick={() => navigate('/profile')}
          style={{
            background: 'none', border: 'none', color: C.text, fontSize: 18,
            cursor: 'pointer', padding: '4px 8px 4px 0', minWidth: 48, minHeight: 48,
            display: 'flex', alignItems: 'center',
          }}
        >
          ←
        </button>
        <span style={{ fontSize: 18, fontWeight: 700, color: '#fff' }}>我的绩效</span>
        <div style={{ display: 'flex', gap: 6 }}>
          {(Object.keys(PERIOD_LABELS) as Period[]).map(p => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              style={{
                padding: '6px 12px', borderRadius: 20, fontSize: 14, cursor: 'pointer',
                border: `1px solid ${period === p ? C.primary : C.border}`,
                background: period === p ? `${C.primary}22` : 'transparent',
                color: period === p ? C.primary : C.muted,
                minHeight: 36,
              }}
            >
              {PERIOD_LABELS[p]}
            </button>
          ))}
        </div>
      </div>

      <div style={{ padding: '16px 16px 0' }}>
        {/* 排名卡 */}
        <div style={{
          background: C.card, borderRadius: 16, padding: '20px 20px 16px',
          border: `1px solid ${C.border}`, marginBottom: 16,
          borderLeft: `4px solid ${C.gold}`,
        }}>
          <div style={{ fontSize: 14, color: C.muted, marginBottom: 8 }}>
            {PERIOD_LABELS[period]}排名
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
            <span style={{ fontSize: 40 }}>{getRankEmoji(stats.rank)}</span>
            <div>
              <div style={{ fontSize: 28, fontWeight: 800, color: '#fff', lineHeight: 1.1 }}>
                今日第 {stats.rank} 名
              </div>
              <div style={{ fontSize: 14, color: C.muted, marginTop: 2 }}>
                共 {stats.total_staff} 人在班
              </div>
            </div>
          </div>
          <div style={{
            fontSize: 15, color: C.warning, fontWeight: 500,
            background: `${C.warning}11`, borderRadius: 8,
            padding: '8px 12px',
          }}>
            {motivation}
          </div>
        </div>

        {/* 核心指标网格 */}
        <h2 style={{ fontSize: 16, fontWeight: 600, color: '#fff', margin: '0 0 10px' }}>
          核心指标
        </h2>
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 8, marginBottom: 16,
        }}>
          {coreMetrics.map(m => (
            <div
              key={m.label}
              style={{
                background: C.card, borderRadius: 12, padding: '12px 10px',
                border: `1px solid ${C.border}`, textAlign: 'center',
              }}
            >
              <div style={{ fontSize: 20, fontWeight: 800, color: m.color, marginBottom: 4 }}>
                {m.value}
              </div>
              <div style={{ fontSize: 12, color: C.muted }}>{m.label}</div>
            </div>
          ))}
        </div>

        {/* 排行榜 */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginBottom: 10,
        }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: '#fff', margin: 0 }}>
            {PERIOD_LABELS[period]}排行榜
          </h2>
          <div style={{ display: 'flex', gap: 4 }}>
            {(Object.keys(METRIC_LABELS) as LeaderMetric[]).map(m => (
              <button
                key={m}
                onClick={() => setMetric(m)}
                style={{
                  padding: '4px 10px', borderRadius: 16, fontSize: 12, cursor: 'pointer',
                  border: `1px solid ${metric === m ? C.primary : C.border}`,
                  background: metric === m ? `${C.primary}22` : 'transparent',
                  color: metric === m ? C.primary : C.muted,
                  minHeight: 32,
                }}
              >
                {METRIC_LABELS[m]}{metric === m ? ' ▾' : ''}
              </button>
            ))}
          </div>
        </div>
        <div style={{
          background: C.card, borderRadius: 12, border: `1px solid ${C.border}`,
          overflow: 'hidden', marginBottom: 16,
        }}>
          {leaderboard.map((row, idx) => (
            <div
              key={row.rank}
              style={{
                display: 'flex', alignItems: 'center', padding: '14px 16px',
                borderBottom: idx < leaderboard.length - 1 ? `1px solid ${C.border}` : 'none',
                background: row.is_me ? `${C.primary}11` : 'transparent',
                minHeight: 52,
              }}
            >
              <span style={{ fontSize: 22, width: 32, flexShrink: 0 }}>
                {getBadgeEmoji(row.badge)}
              </span>
              <span style={{
                flex: 1, fontSize: 16,
                color: row.is_me ? C.primary : C.text,
                fontWeight: row.is_me ? 700 : 400,
              }}>
                {row.operator_name}
                {row.is_me && (
                  <span style={{
                    marginLeft: 6, fontSize: 11, color: C.primary,
                    border: `1px solid ${C.primary}`, borderRadius: 4,
                    padding: '1px 4px',
                  }}>
                    你
                  </span>
                )}
              </span>
              <span style={{
                fontSize: 16, fontWeight: 600,
                color: row.badge === 'gold' ? C.gold
                  : row.badge === 'silver' ? C.silver
                  : row.badge === 'bronze' ? C.bronze
                  : C.text,
              }}>
                {metric === 'revenue'
                  ? formatRevenue(row.value)
                  : metric === 'response'
                  ? `${row.value}秒`
                  : `${row.value}次`}
              </span>
            </div>
          ))}
        </div>

        {/* 近7日趋势 */}
        <h2 style={{ fontSize: 16, fontWeight: 600, color: '#fff', margin: '0 0 12px' }}>
          近7日翻台趋势
        </h2>
        <div style={{
          background: C.card, borderRadius: 12, padding: '16px 12px 12px',
          border: `1px solid ${C.border}`, marginBottom: 16,
        }}>
          <TrendBar data={trend} todayLabel="今天" />
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: C.primary, display: 'inline-block' }} />
            <span style={{ fontSize: 12, color: C.muted }}>今天</span>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: '#2A2A2A', display: 'inline-block', marginLeft: 8 }} />
            <span style={{ fontSize: 12, color: C.muted }}>其他日</span>
          </div>
        </div>
      </div>
    </div>
  );
}
