/**
 * 店长日报 — /manager/daily-brief
 * P1: AI生成的每日经营简报，关键指标+异常+建议
 * 竖屏PWA布局，遵循Store-Crew TXTouch规范
 *
 * API: GET /api/v1/analytics/daily-brief?store_id=&date=
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../../api';

// ─── 类型 ──────────────────────────────────────────────────────────────────────

interface DailyBrief {
  date: string;
  storeName: string;
  // 核心 KPI
  revenueFen: number;
  revenueGrowth: number;
  orderCount: number;
  guestCount: number;
  avgCheckFen: number;
  tableTurnRate: number;
  grossMargin: number;
  // 异常
  anomalies: { type: string; title: string; severity: 'high' | 'medium' | 'low' }[];
  // AI 建议
  suggestions: string[];
  // 时段最佳
  bestPeriod: string;
  bestPeriodRevenueFen: number;
  // 热销/冷门
  topDishes: { name: string; count: number }[];
  coldDishes: { name: string; count: number }[];
  // 员工
  staffOnDuty: number;
  staffAbsent: number;
  // 客诉
  complaintCount: number;
}

// ─── Fallback ──────────────────────────────────────────────────────────────────

const FALLBACK: DailyBrief = {
  date: new Date().toISOString().slice(0, 10),
  storeName: '徐记海鲜·芙蓉店',
  revenueFen: 8560000, revenueGrowth: 0.08,
  orderCount: 420, guestCount: 1260, avgCheckFen: 6800,
  tableTurnRate: 3.2, grossMargin: 0.62,
  anomalies: [
    { type: 'discount', title: '12:30 A05桌折扣率超60%，已由折扣守护Agent拦截', severity: 'high' },
    { type: 'overtime', title: '14:15 后厨3号工位出餐超时（口味虾等候28分钟）', severity: 'medium' },
  ],
  suggestions: [
    '午餐时段客流集中在12:00-12:30，建议11:45提前开放排队叫号',
    '活鲜鲈鱼库存偏低（剩余3.2kg），建议明日采购量增加50%',
    '晚餐剁椒鱼头连续3日排名第1，建议作为今日推荐菜品置顶',
    '本周三为会员日，预计客流增长15%，建议安排加班1人',
  ],
  bestPeriod: '晚餐', bestPeriodRevenueFen: 4280000,
  topDishes: [
    { name: '剁椒鱼头', count: 140 },
    { name: '口味虾', count: 130 },
    { name: '农家小炒肉', count: 95 },
  ],
  coldDishes: [
    { name: '皮蛋豆腐', count: 3 },
    { name: '蛋炒饭', count: 5 },
  ],
  staffOnDuty: 18, staffAbsent: 1,
  complaintCount: 1,
};

const STORE_ID = import.meta.env.VITE_STORE_ID || '';
const fen2yuan = (fen: number) => `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 })}`;
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function DailyBriefPage() {
  const navigate = useNavigate();
  const [brief, setBrief] = useState<DailyBrief>(FALLBACK);
  const [loading, setLoading] = useState(false);

  const loadBrief = useCallback(async () => {
    setLoading(true);
    try {
      const data = await txFetch<DailyBrief>(`/api/v1/analytics/daily-brief?store_id=${STORE_ID}&date=${new Date().toISOString().slice(0, 10)}`);
      if (data) setBrief(data);
    } catch { /* fallback */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadBrief(); }, [loadBrief]);

  return (
    <div style={pageStyle}>
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>AI 经营日报</div>
          <div style={{ fontSize: 13, color: '#9CA3AF', marginTop: 2 }}>{brief.storeName} · {brief.date}</div>
        </div>
        <button type="button" onClick={() => navigate(-1)} style={backBtnStyle}>← 返回</button>
      </div>

      {loading && <div style={{ textAlign: 'center', color: '#9CA3AF', padding: 20 }}>加载中...</div>}

      {/* 核心 KPI */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10, marginBottom: 16 }}>
        <KPICard label="今日营收" value={fen2yuan(brief.revenueFen)} sub={`环比 ${brief.revenueGrowth >= 0 ? '+' : ''}${pct(brief.revenueGrowth)}`} subColor={brief.revenueGrowth >= 0 ? '#0F6E56' : '#A32D2D'} highlight />
        <KPICard label="订单/客流" value={`${brief.orderCount}单 / ${brief.guestCount}人`} sub={`客单价 ${fen2yuan(brief.avgCheckFen)}`} />
        <KPICard label="翻台率" value={brief.tableTurnRate.toFixed(1)} sub={`最佳: ${brief.bestPeriod}`} />
        <KPICard label="毛利率" value={pct(brief.grossMargin)} sub={brief.grossMargin < 0.55 ? '低于阈值' : '正常'} subColor={brief.grossMargin < 0.55 ? '#A32D2D' : '#0F6E56'} />
      </div>

      {/* 异常预警 */}
      {brief.anomalies.length > 0 && (
        <Section title={`异常预警 (${brief.anomalies.length})`} icon="🚨">
          {brief.anomalies.map((a, i) => (
            <div key={i} style={{
              padding: '10px 12px', borderRadius: 8, marginBottom: 6,
              background: a.severity === 'high' ? 'rgba(163,45,45,0.08)' : 'rgba(186,117,23,0.08)',
              borderLeft: `4px solid ${a.severity === 'high' ? '#A32D2D' : '#BA7517'}`,
            }}>
              <div style={{ fontSize: 14, color: a.severity === 'high' ? '#A32D2D' : '#BA7517' }}>{a.title}</div>
            </div>
          ))}
        </Section>
      )}

      {/* AI 建议 */}
      <Section title="AI 建议" icon="💡">
        {brief.suggestions.map((s, i) => (
          <div key={i} style={{
            padding: '10px 12px', borderRadius: 8, marginBottom: 6,
            background: 'rgba(24,95,165,0.06)', fontSize: 14, color: '#ccc',
            display: 'flex', gap: 8,
          }}>
            <span style={{ color: '#185FA5', fontWeight: 600, flexShrink: 0 }}>{i + 1}.</span>
            {s}
          </div>
        ))}
      </Section>

      {/* 热销/冷门 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
        <Section title="热销 TOP3" icon="🔥" compact>
          {brief.topDishes.map((d, i) => (
            <div key={d.name} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', fontSize: 14, borderBottom: '1px solid #1a2a33' }}>
              <span><span style={{ color: '#FF6B35', fontWeight: 600, marginRight: 6 }}>{i + 1}</span>{d.name}</span>
              <span style={{ color: '#9CA3AF' }}>{d.count}份</span>
            </div>
          ))}
        </Section>
        <Section title="滞销菜品" icon="❄️" compact>
          {brief.coldDishes.map(d => (
            <div key={d.name} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', fontSize: 14, borderBottom: '1px solid #1a2a33' }}>
              <span>{d.name}</span>
              <span style={{ color: '#A32D2D' }}>{d.count}份</span>
            </div>
          ))}
        </Section>
      </div>

      {/* 人员 & 客诉 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 16 }}>
        <div style={cardStyle}>
          <div style={{ fontSize: 12, color: '#9CA3AF' }}>当班人员</div>
          <div style={{ fontSize: 18, fontWeight: 600, marginTop: 4 }}>
            {brief.staffOnDuty}人
            {brief.staffAbsent > 0 && <span style={{ fontSize: 13, color: '#A32D2D', marginLeft: 6 }}>缺勤{brief.staffAbsent}</span>}
          </div>
        </div>
        <div style={cardStyle}>
          <div style={{ fontSize: 12, color: '#9CA3AF' }}>客诉</div>
          <div style={{ fontSize: 18, fontWeight: 600, marginTop: 4, color: brief.complaintCount > 0 ? '#A32D2D' : '#0F6E56' }}>
            {brief.complaintCount > 0 ? `${brief.complaintCount}件` : '0 件 ✓'}
          </div>
        </div>
      </div>

      {/* 操作 */}
      <div style={{ display: 'flex', gap: 10, paddingBottom: 20 }}>
        <button type="button" onClick={() => navigate('/manager-dashboard')}
          style={{ flex: 1, padding: '14px 0', background: '#1a2a33', color: '#fff', border: '1px solid #333', borderRadius: 8, fontSize: 16, cursor: 'pointer', minHeight: 52 }}>
          实时看板
        </button>
        <button type="button" onClick={() => navigate('/manager/opening-checklist')}
          style={{ flex: 1, padding: '14px 0', background: '#FF6B35', color: '#fff', border: 'none', borderRadius: 8, fontSize: 16, fontWeight: 500, cursor: 'pointer', minHeight: 52 }}>
          开始今日检查
        </button>
      </div>
    </div>
  );
}

// ─── 子组件 ──────────────────────────────────────────────────────────────────

function KPICard({ label, value, sub, subColor, highlight }: { label: string; value: string; sub?: string; subColor?: string; highlight?: boolean }) {
  return (
    <div style={cardStyle}>
      <div style={{ fontSize: 12, color: '#9CA3AF' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: highlight ? '#FF6B35' : '#fff', marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: subColor || '#6B7280', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function Section({ title, icon, children, compact }: { title: string; icon: string; children: React.ReactNode; compact?: boolean }) {
  return (
    <div style={{ background: '#112228', borderRadius: 10, padding: compact ? 12 : 14, marginBottom: compact ? 0 : 16 }}>
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span>{icon}</span> {title}
      </div>
      {children}
    </div>
  );
}

const pageStyle: React.CSSProperties = {
  padding: 16, background: '#0B1A20', minHeight: '100vh', color: '#fff',
  fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
  maxWidth: 500, margin: '0 auto',
};

const backBtnStyle: React.CSSProperties = {
  padding: '6px 14px', background: '#1a2a33', color: '#9CA3AF', border: '1px solid #333',
  borderRadius: 6, fontSize: 14, cursor: 'pointer', minHeight: 36,
};

const cardStyle: React.CSSProperties = {
  background: '#112228', borderRadius: 10, padding: 14,
};
