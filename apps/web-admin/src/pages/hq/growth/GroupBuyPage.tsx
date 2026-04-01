/**
 * GroupBuyPage — 拼团活动管理
 * 路由: /hq/growth/group-buy
 * 拼团活动列表 + 开团记录 + 数据概览
 */
import { useState, useEffect } from 'react';

const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

type TabKey = 'activities' | 'teams' | 'analytics';

interface GroupBuyActivity {
  id: string;
  name: string;
  productName: string;
  groupSize: number;
  originalPriceFen: number;
  groupPriceFen: number;
  status: '进行中' | '已结束' | '待启动';
  startDate: string;
  endDate: string;
  teamCount: number;
  successCount: number;
  expireMinutes: number;
}

interface GroupBuyTeam {
  id: string;
  activityName: string;
  leaderName: string;
  leaderPhone: string;
  currentSize: number;
  targetSize: number;
  status: '拼团中' | '已成团' | '已过期';
  createdAt: string;
  completedAt?: string;
}

interface KPI {
  label: string;
  value: string;
  sub: string;
  trend?: 'up' | 'down' | 'flat';
}

// ── Mock Data ──
const MOCK_KPIS: KPI[] = [
  { label: '进行中活动', value: '4', sub: '本月新增 2 个', trend: 'up' },
  { label: '开团总数', value: '286', sub: '本周 +47', trend: 'up' },
  { label: '成团率', value: '73.2%', sub: '较上周 +5.1%', trend: 'up' },
  { label: '拼团GMV', value: '¥8.6万', sub: '本月累计', trend: 'up' },
];

const MOCK_ACTIVITIES: GroupBuyActivity[] = [
  { id: 'ga-001', name: '双人拼团·招牌酸菜鱼', productName: '酸菜鱼套餐', groupSize: 2, originalPriceFen: 12800, groupPriceFen: 8800, status: '进行中', startDate: '2026-03-20', endDate: '2026-04-20', teamCount: 156, successCount: 118, expireMinutes: 30 },
  { id: 'ga-002', name: '三人团·火锅套餐', productName: '鸳鸯锅三人套餐', groupSize: 3, originalPriceFen: 29800, groupPriceFen: 19800, status: '进行中', startDate: '2026-03-25', endDate: '2026-04-25', teamCount: 89, successCount: 62, expireMinutes: 60 },
  { id: 'ga-003', name: '五人特惠·烤鱼', productName: '碳烤鱼五人套餐', groupSize: 5, originalPriceFen: 39800, groupPriceFen: 24800, status: '待启动', startDate: '2026-04-05', endDate: '2026-05-05', teamCount: 0, successCount: 0, expireMinutes: 120 },
  { id: 'ga-004', name: '双人午餐特惠', productName: '工作日午餐双人套餐', groupSize: 2, originalPriceFen: 6800, groupPriceFen: 3900, status: '已结束', startDate: '2026-02-01', endDate: '2026-03-01', teamCount: 320, successCount: 248, expireMinutes: 30 },
];

const MOCK_TEAMS: GroupBuyTeam[] = [
  { id: 'gt-001', activityName: '双人拼团·招牌酸菜鱼', leaderName: '王**', leaderPhone: '138****8001', currentSize: 2, targetSize: 2, status: '已成团', createdAt: '2026-03-31 14:23', completedAt: '2026-03-31 14:35' },
  { id: 'gt-002', activityName: '三人团·火锅套餐', leaderName: '李**', leaderPhone: '139****9002', currentSize: 1, targetSize: 3, status: '拼团中', createdAt: '2026-04-01 10:15' },
  { id: 'gt-003', activityName: '双人拼团·招牌酸菜鱼', leaderName: '张**', leaderPhone: '137****7003', currentSize: 1, targetSize: 2, status: '已过期', createdAt: '2026-03-30 18:40' },
  { id: 'gt-004', activityName: '三人团·火锅套餐', leaderName: '赵**', leaderPhone: '136****6004', currentSize: 3, targetSize: 3, status: '已成团', createdAt: '2026-04-01 09:00', completedAt: '2026-04-01 09:28' },
  { id: 'gt-005', activityName: '双人拼团·招牌酸菜鱼', leaderName: '陈**', leaderPhone: '135****5005', currentSize: 2, targetSize: 2, status: '已成团', createdAt: '2026-04-01 11:30', completedAt: '2026-04-01 11:42' },
];

const fen = (v: number) => `¥${(v / 100).toFixed(2)}`;

export function GroupBuyPage() {
  const [tab, setTab] = useState<TabKey>('activities');

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'activities', label: '拼团活动' },
    { key: 'teams', label: '开团记录' },
    { key: 'analytics', label: '数据概览' },
  ];

  return (
    <div style={{ padding: 24, background: BG_1, minHeight: '100vh', color: TEXT_1, fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif' }}>
      {/* Header */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>拼团活动管理</h1>
          <div style={{ fontSize: 13, color: TEXT_3, marginTop: 4 }}>社交裂变·以团代促·引流到店</div>
        </div>
        <button style={{ background: BRAND, color: '#fff', border: 'none', borderRadius: 6, padding: '8px 20px', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>+ 创建拼团活动</button>
      </div>

      {/* KPI Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {MOCK_KPIS.map(k => (
          <div key={k.label} style={{ background: BG_2, borderRadius: 8, padding: 16 }}>
            <div style={{ fontSize: 13, color: TEXT_3 }}>{k.label}</div>
            <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{k.value}</div>
            <div style={{ fontSize: 12, color: k.trend === 'up' ? GREEN : k.trend === 'down' ? RED : TEXT_4, marginTop: 4 }}>
              {k.trend === 'up' ? '↑' : k.trend === 'down' ? '↓' : '−'} {k.sub}
            </div>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, background: BG_2, borderRadius: 8, padding: 4, width: 'fit-content' }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            style={{
              padding: '8px 20px', fontSize: 14, fontWeight: tab === t.key ? 600 : 400, cursor: 'pointer',
              border: 'none', borderRadius: 6,
              background: tab === t.key ? BRAND : 'transparent',
              color: tab === t.key ? '#fff' : TEXT_3,
            }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {tab === 'activities' && <ActivitiesTab />}
      {tab === 'teams' && <TeamsTab />}
      {tab === 'analytics' && <AnalyticsTab />}
    </div>
  );
}

function ActivitiesTab() {
  return (
    <div style={{ background: BG_2, borderRadius: 8, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ background: 'rgba(255,255,255,0.04)' }}>
            {['活动名称', '商品', '拼团人数', '原价/团价', '状态', '有效期', '开团数', '成团率', '操作'].map(h => (
              <th key={h} style={{ padding: '12px 16px', textAlign: 'left', color: TEXT_3, fontWeight: 500, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {MOCK_ACTIVITIES.map(a => (
            <tr key={a.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <td style={{ padding: '14px 16px', fontWeight: 500 }}>{a.name}</td>
              <td style={{ padding: '14px 16px', color: TEXT_2 }}>{a.productName}</td>
              <td style={{ padding: '14px 16px' }}>{a.groupSize}人团</td>
              <td style={{ padding: '14px 16px' }}>
                <span style={{ textDecoration: 'line-through', color: TEXT_4, marginRight: 8 }}>{fen(a.originalPriceFen)}</span>
                <span style={{ color: RED, fontWeight: 600 }}>{fen(a.groupPriceFen)}</span>
              </td>
              <td style={{ padding: '14px 16px' }}>
                <span style={{
                  display: 'inline-block', padding: '2px 10px', borderRadius: 12, fontSize: 12, fontWeight: 500,
                  background: a.status === '进行中' ? 'rgba(82,196,26,0.15)' : a.status === '待启动' ? 'rgba(250,173,20,0.15)' : 'rgba(255,255,255,0.06)',
                  color: a.status === '进行中' ? GREEN : a.status === '待启动' ? YELLOW : TEXT_4,
                }}>{a.status}</span>
              </td>
              <td style={{ padding: '14px 16px', color: TEXT_3, fontSize: 13 }}>{a.startDate} ~ {a.endDate}</td>
              <td style={{ padding: '14px 16px' }}>{a.teamCount}</td>
              <td style={{ padding: '14px 16px' }}>{a.teamCount > 0 ? `${((a.successCount / a.teamCount) * 100).toFixed(1)}%` : '-'}</td>
              <td style={{ padding: '14px 16px' }}>
                <span style={{ color: BLUE, cursor: 'pointer', marginRight: 12 }}>详情</span>
                {a.status === '待启动' && <span style={{ color: GREEN, cursor: 'pointer' }}>启动</span>}
                {a.status === '进行中' && <span style={{ color: YELLOW, cursor: 'pointer' }}>暂停</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TeamsTab() {
  return (
    <div style={{ background: BG_2, borderRadius: 8, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ background: 'rgba(255,255,255,0.04)' }}>
            {['团号', '活动', '团长', '进度', '状态', '开团时间', '成团时间'].map(h => (
              <th key={h} style={{ padding: '12px 16px', textAlign: 'left', color: TEXT_3, fontWeight: 500, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {MOCK_TEAMS.map(t => (
            <tr key={t.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <td style={{ padding: '14px 16px', fontFamily: 'monospace', fontSize: 13 }}>{t.id}</td>
              <td style={{ padding: '14px 16px' }}>{t.activityName}</td>
              <td style={{ padding: '14px 16px' }}>{t.leaderName} <span style={{ color: TEXT_4 }}>{t.leaderPhone}</span></td>
              <td style={{ padding: '14px 16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ width: 80, height: 6, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ width: `${(t.currentSize / t.targetSize) * 100}%`, height: '100%', background: t.status === '已成团' ? GREEN : BRAND, borderRadius: 3 }} />
                  </div>
                  <span style={{ fontSize: 12, color: TEXT_3 }}>{t.currentSize}/{t.targetSize}</span>
                </div>
              </td>
              <td style={{ padding: '14px 16px' }}>
                <span style={{
                  display: 'inline-block', padding: '2px 10px', borderRadius: 12, fontSize: 12,
                  background: t.status === '已成团' ? 'rgba(82,196,26,0.15)' : t.status === '拼团中' ? 'rgba(24,144,255,0.15)' : 'rgba(255,255,255,0.06)',
                  color: t.status === '已成团' ? GREEN : t.status === '拼团中' ? BLUE : TEXT_4,
                }}>{t.status}</span>
              </td>
              <td style={{ padding: '14px 16px', color: TEXT_3, fontSize: 13 }}>{t.createdAt}</td>
              <td style={{ padding: '14px 16px', color: TEXT_3, fontSize: 13 }}>{t.completedAt || '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AnalyticsTab() {
  const dailyData = [
    { date: '03-26', teams: 12, success: 9 },
    { date: '03-27', teams: 18, success: 14 },
    { date: '03-28', teams: 15, success: 11 },
    { date: '03-29', teams: 22, success: 17 },
    { date: '03-30', teams: 28, success: 21 },
    { date: '03-31', teams: 35, success: 26 },
    { date: '04-01', teams: 19, success: 14 },
  ];

  const max = Math.max(...dailyData.map(d => d.teams));

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>
      <div style={{ background: BG_2, borderRadius: 8, padding: 20 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 600 }}>近7日开团趋势</h3>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, height: 160 }}>
          {dailyData.map(d => (
            <div key={d.date} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <div style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                <div style={{ width: '60%', height: (d.teams / max) * 120, background: BLUE, borderRadius: '4px 4px 0 0', opacity: 0.6 }} />
                <div style={{ width: '60%', height: (d.success / max) * 120, background: GREEN, borderRadius: '4px 4px 0 0', marginTop: -((d.success / max) * 120) }} />
              </div>
              <span style={{ fontSize: 11, color: TEXT_4 }}>{d.date}</span>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 16, marginTop: 12, fontSize: 12, color: TEXT_3 }}>
          <span><span style={{ display: 'inline-block', width: 10, height: 10, background: BLUE, borderRadius: 2, marginRight: 4 }} />开团数</span>
          <span><span style={{ display: 'inline-block', width: 10, height: 10, background: GREEN, borderRadius: 2, marginRight: 4 }} />成团数</span>
        </div>
      </div>
      <div style={{ background: BG_2, borderRadius: 8, padding: 20 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 600 }}>热门拼团TOP3</h3>
        {MOCK_ACTIVITIES.filter(a => a.status === '进行中').slice(0, 3).map((a, i) => (
          <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: i < 2 ? '1px solid rgba(255,255,255,0.04)' : 'none' }}>
            <div style={{ width: 28, height: 28, borderRadius: 6, background: i === 0 ? BRAND : i === 1 ? BLUE : 'rgba(255,255,255,0.08)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700 }}>{i + 1}</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 500 }}>{a.name}</div>
              <div style={{ fontSize: 12, color: TEXT_4 }}>{a.successCount} 成团</div>
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, color: GREEN }}>{a.teamCount > 0 ? `${((a.successCount / a.teamCount) * 100).toFixed(0)}%` : '-'}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
