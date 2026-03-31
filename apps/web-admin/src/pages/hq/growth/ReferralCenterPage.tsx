/**
 * ReferralCenterPage — 裂变增长中心
 * 路由: /hq/growth/referral
 * 裂变活动列表 + 漏斗分析 + 奖励结算 + 反作弊监控
 */
import { useState } from 'react';

const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

type TabKey = 'campaigns' | 'funnel' | 'rewards' | 'antifraud';

interface ReferralCampaign {
  id: string;
  name: string;
  type: '老带新' | '拼团' | '分享有礼';
  status: '进行中' | '已结束' | '待启动';
  startDate: string;
  endDate: string;
  inviterReward: string;
  inviteeReward: string;
  totalInviters: number;
  totalInvitees: number;
  firstOrders: number;
  repeatOrders: number;
  totalRevenue: number;
}

interface FunnelStep {
  label: string;
  count: number;
  rate: number;
}

interface RewardRecord {
  id: string;
  inviterName: string;
  inviterPhone: string;
  inviteeName: string;
  rewardType: string;
  rewardValue: string;
  status: '已发放' | '待结算' | '冻结';
  date: string;
}

interface FraudAlert {
  id: string;
  type: string;
  severity: 'high' | 'medium' | 'low';
  description: string;
  involvedUsers: number;
  detectedAt: string;
  status: '待处理' | '已处理' | '误报';
}

const MOCK_CAMPAIGNS: ReferralCampaign[] = [
  { id: 'rc1', name: '春季老带新大赏', type: '老带新', status: '进行中', startDate: '2026-03-01', endDate: '2026-03-31', inviterReward: '邀请1人得¥20券', inviteeReward: '新客满60减25', totalInviters: 856, totalInvitees: 1247, firstOrders: 892, repeatOrders: 312, totalRevenue: 186400 },
  { id: 'rc2', name: '3人成团享5折', type: '拼团', status: '进行中', startDate: '2026-03-15', endDate: '2026-04-05', inviterReward: '团长免单一份菜', inviteeReward: '成团5折', totalInviters: 342, totalInvitees: 684, firstOrders: 456, repeatOrders: 128, totalRevenue: 98200 },
  { id: 'rc3', name: '分享有礼·集赞换券', type: '分享有礼', status: '进行中', startDate: '2026-03-10', endDate: '2026-03-31', inviterReward: '集20赞得¥30券', inviteeReward: '点击即得¥10券', totalInviters: 1234, totalInvitees: 3456, firstOrders: 678, repeatOrders: 89, totalRevenue: 72800 },
  { id: 'rc4', name: '年末裂变冲刺', type: '老带新', status: '已结束', startDate: '2025-12-15', endDate: '2026-01-05', inviterReward: '邀请1人得¥30券', inviteeReward: '新客满50减20', totalInviters: 1520, totalInvitees: 2340, firstOrders: 1680, repeatOrders: 520, totalRevenue: 342000 },
  { id: 'rc5', name: '清明踏青拼团', type: '拼团', status: '待启动', startDate: '2026-04-03', endDate: '2026-04-06', inviterReward: '团长得双倍积分', inviteeReward: '成团8折', totalInviters: 0, totalInvitees: 0, firstOrders: 0, repeatOrders: 0, totalRevenue: 0 },
];

const MOCK_FUNNEL: FunnelStep[] = [
  { label: '发起邀请', count: 2432, rate: 100 },
  { label: '受邀注册', count: 5387, rate: 72.4 },
  { label: '首次下单', count: 2026, rate: 37.6 },
  { label: '复购到店', count: 529, rate: 26.1 },
];

const MOCK_REWARDS: RewardRecord[] = [
  { id: 'rw1', inviterName: '张***', inviterPhone: '138****5678', inviteeName: '李***', rewardType: '现金券', rewardValue: '¥20', status: '已发放', date: '2026-03-26' },
  { id: 'rw2', inviterName: '王***', inviterPhone: '159****1234', inviteeName: '赵***', rewardType: '现金券', rewardValue: '¥20', status: '已发放', date: '2026-03-26' },
  { id: 'rw3', inviterName: '陈***', inviterPhone: '186****4567', inviteeName: '孙***', rewardType: '免单券', rewardValue: '免费菜1份', status: '待结算', date: '2026-03-26' },
  { id: 'rw4', inviterName: '刘***', inviterPhone: '137****8901', inviteeName: '周***', rewardType: '现金券', rewardValue: '¥30', status: '待结算', date: '2026-03-25' },
  { id: 'rw5', inviterName: '高***', inviterPhone: '152****2345', inviteeName: '吴***', rewardType: '现金券', rewardValue: '¥20', status: '冻结', date: '2026-03-25' },
  { id: 'rw6', inviterName: '林***', inviterPhone: '188****6789', inviteeName: '黄***', rewardType: '积分', rewardValue: '200积分', status: '已发放', date: '2026-03-24' },
  { id: 'rw7', inviterName: '杨***', inviterPhone: '135****0123', inviteeName: '何***', rewardType: '现金券', rewardValue: '¥20', status: '已发放', date: '2026-03-24' },
];

const MOCK_FRAUD_ALERTS: FraudAlert[] = [
  { id: 'fa1', type: '同设备多账号', severity: 'high', description: '检测到同一设备在24小时内注册了8个新账号，疑似刷单', involvedUsers: 8, detectedAt: '2026-03-26 09:45', status: '待处理' },
  { id: 'fa2', type: '异常邀请频率', severity: 'medium', description: '用户138****5678在1小时内成功邀请23人，远超正常水平', involvedUsers: 24, detectedAt: '2026-03-26 11:20', status: '待处理' },
  { id: 'fa3', type: '虚假消费', severity: 'high', description: '3个关联账号互相邀请，均在最低消费门槛下单后立即退款', involvedUsers: 3, detectedAt: '2026-03-25 16:30', status: '已处理' },
  { id: 'fa4', type: '地址异常', severity: 'low', description: '多个被邀请人填写相同收货地址，可能为同一人操作', involvedUsers: 5, detectedAt: '2026-03-25 14:00', status: '已处理' },
  { id: 'fa5', type: '批量注册', severity: 'medium', description: '同IP段30分钟内出现15个新注册，手机号段连续', involvedUsers: 15, detectedAt: '2026-03-24 20:15', status: '误报' },
];

function CampaignCards({ campaigns }: { campaigns: ReferralCampaign[] }) {
  const statusColors: Record<string, string> = { '进行中': GREEN, '已结束': TEXT_4, '待启动': BLUE };
  const typeColors: Record<string, string> = { '老带新': BRAND, '拼团': PURPLE, '分享有礼': BLUE };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {campaigns.map(c => (
        <div key={c.id} style={{
          background: BG_1, borderRadius: 10, padding: 16,
          border: `1px solid ${BG_2}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 16, fontWeight: 700, color: TEXT_1 }}>{c.name}</span>
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 4,
                background: typeColors[c.type] + '22', color: typeColors[c.type], fontWeight: 600,
              }}>{c.type}</span>
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 4,
                background: statusColors[c.status] + '22', color: statusColors[c.status], fontWeight: 600,
              }}>{c.status}</span>
            </div>
            <span style={{ fontSize: 11, color: TEXT_4 }}>{c.startDate} ~ {c.endDate}</span>
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, fontSize: 11 }}>
            <span style={{ color: TEXT_3, padding: '4px 8px', background: BG_2, borderRadius: 4 }}>
              邀请人奖励: <strong style={{ color: BRAND }}>{c.inviterReward}</strong>
            </span>
            <span style={{ color: TEXT_3, padding: '4px 8px', background: BG_2, borderRadius: 4 }}>
              被邀请人奖励: <strong style={{ color: GREEN }}>{c.inviteeReward}</strong>
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10 }}>
            {[
              { label: '邀请人数', value: c.totalInviters.toLocaleString(), color: TEXT_1 },
              { label: '被邀请人数', value: c.totalInvitees.toLocaleString(), color: TEXT_1 },
              { label: '首单转化', value: c.firstOrders.toLocaleString(), color: GREEN },
              { label: '复购转化', value: c.repeatOrders.toLocaleString(), color: BLUE },
              { label: '总营收', value: c.totalRevenue > 0 ? `\u00A5${(c.totalRevenue / 10000).toFixed(1)}万` : '-', color: BRAND },
              { label: 'K系数', value: c.totalInviters > 0 ? (c.totalInvitees / c.totalInviters).toFixed(2) : '-', color: PURPLE },
            ].map((item, i) => (
              <div key={i} style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: item.color }}>{item.value}</div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function FunnelChart({ steps }: { steps: FunnelStep[] }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 20,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 20px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>裂变转化漏斗</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, alignItems: 'center' }}>
        {steps.map((step, i) => {
          const widthPct = Math.max(30, step.rate);
          return (
            <div key={i} style={{ width: '100%', maxWidth: 600 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: TEXT_1 }}>{step.label}</span>
                <span style={{ fontSize: 13, color: TEXT_2 }}>{step.count.toLocaleString()}</span>
              </div>
              <div style={{ position: 'relative', height: 36 }}>
                <div style={{
                  width: `${widthPct}%`, height: '100%', borderRadius: 6,
                  background: `linear-gradient(90deg, ${BRAND}, ${BRAND}88)`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  margin: '0 auto',
                }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#fff' }}>{step.rate}%</span>
                </div>
              </div>
              {i < steps.length - 1 && (
                <div style={{ textAlign: 'center', fontSize: 11, color: TEXT_4, marginTop: 4 }}>
                  {'\u2193'} 转化率 {((steps[i + 1].count / step.count) * 100).toFixed(1)}%
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 关键指标 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginTop: 20 }}>
        {[
          { label: '总邀请发起', value: '2,432', color: TEXT_1 },
          { label: '注册转化率', value: '72.4%', color: GREEN },
          { label: '首单转化率', value: '37.6%', color: BRAND },
          { label: '复购留存率', value: '26.1%', color: BLUE },
        ].map((item, i) => (
          <div key={i} style={{ background: BG_2, borderRadius: 8, padding: 12, textAlign: 'center' }}>
            <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: item.color }}>{item.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RewardSettlement({ rewards }: { rewards: RewardRecord[] }) {
  const statusColors: Record<string, string> = { '已发放': GREEN, '待结算': YELLOW, '冻结': RED };
  const [filter, setFilter] = useState('全部');
  const filtered = filter === '全部' ? rewards : rewards.filter(r => r.status === filter);

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: TEXT_1 }}>奖励结算</h3>
        {['全部', '已发放', '待结算', '冻结'].map(s => (
          <button key={s} onClick={() => setFilter(s)} style={{
            padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
            background: filter === s ? BRAND : BG_2, color: filter === s ? '#fff' : TEXT_3,
            fontSize: 11, fontWeight: 600,
          }}>{s}</button>
        ))}
      </div>

      {/* 汇总 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 14 }}>
        {[
          { label: '已发放', value: `${rewards.filter(r => r.status === '已发放').length} 笔`, color: GREEN },
          { label: '待结算', value: `${rewards.filter(r => r.status === '待结算').length} 笔`, color: YELLOW },
          { label: '已冻结', value: `${rewards.filter(r => r.status === '冻结').length} 笔`, color: RED },
        ].map((item, i) => (
          <div key={i} style={{ background: BG_2, borderRadius: 8, padding: 10, textAlign: 'center' }}>
            <div style={{ fontSize: 10, color: TEXT_4 }}>{item.label}</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: item.color }}>{item.value}</div>
          </div>
        ))}
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
            {['邀请人', '手机号', '被邀请人', '奖励类型', '奖励值', '状态', '日期'].map(h => (
              <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filtered.map(r => (
            <tr key={r.id} style={{ borderBottom: `1px solid ${BG_2}` }}>
              <td style={{ padding: '10px', color: TEXT_1 }}>{r.inviterName}</td>
              <td style={{ padding: '10px', color: TEXT_3 }}>{r.inviterPhone}</td>
              <td style={{ padding: '10px', color: TEXT_2 }}>{r.inviteeName}</td>
              <td style={{ padding: '10px', color: TEXT_3 }}>{r.rewardType}</td>
              <td style={{ padding: '10px', color: BRAND, fontWeight: 600 }}>{r.rewardValue}</td>
              <td style={{ padding: '10px' }}>
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 4,
                  background: statusColors[r.status] + '22', color: statusColors[r.status], fontWeight: 600,
                }}>{r.status}</span>
              </td>
              <td style={{ padding: '10px', color: TEXT_4 }}>{r.date}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AntiFraudMonitor({ alerts }: { alerts: FraudAlert[] }) {
  const sevColors: Record<string, string> = { high: RED, medium: YELLOW, low: BLUE };
  const sevLabels: Record<string, string> = { high: '严重', medium: '警告', low: '提示' };
  const statusColors: Record<string, string> = { '待处理': RED, '已处理': GREEN, '误报': TEXT_4 };

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: TEXT_1 }}>反作弊监控</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <span style={{ fontSize: 12, color: RED }}>待处理: {alerts.filter(a => a.status === '待处理').length}</span>
          <span style={{ fontSize: 12, color: GREEN }}>已处理: {alerts.filter(a => a.status === '已处理').length}</span>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {alerts.map(a => (
          <div key={a.id} style={{
            padding: '14px 16px', background: BG_2, borderRadius: 8,
            borderLeft: `3px solid ${sevColors[a.severity]}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4,
                  background: sevColors[a.severity] + '22', color: sevColors[a.severity], fontWeight: 700,
                }}>{sevLabels[a.severity]}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: TEXT_1 }}>{a.type}</span>
              </div>
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 4,
                background: statusColors[a.status] + '22', color: statusColors[a.status], fontWeight: 600,
              }}>{a.status}</span>
            </div>
            <div style={{ fontSize: 12, color: TEXT_3, lineHeight: 1.6, marginBottom: 6 }}>{a.description}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: TEXT_4 }}>
              <span>涉及用户: {a.involvedUsers} 人</span>
              <span>{a.detectedAt}</span>
            </div>
            {a.status === '待处理' && (
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <button style={{
                  padding: '4px 12px', borderRadius: 6, border: 'none',
                  background: RED + '22', color: RED, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                }}>冻结奖励</button>
                <button style={{
                  padding: '4px 12px', borderRadius: 6, border: 'none',
                  background: BG_1, color: TEXT_3, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                }}>标记误报</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function ReferralCenterPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('campaigns');
  const tabs: { key: TabKey; label: string }[] = [
    { key: 'campaigns', label: '裂变活动' },
    { key: 'funnel', label: '转化漏斗' },
    { key: 'rewards', label: '奖励结算' },
    { key: 'antifraud', label: '反作弊监控' },
  ];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700 }}>裂变增长中心</h2>

      {/* KPI */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 }}>
        {[
          { label: '活跃裂变活动', value: '3', change: 0, color: GREEN },
          { label: '本月新增邀请', value: '2,432', change: 18.5, color: TEXT_1 },
          { label: '裂变新客', value: '2,026', change: 22.3, color: BRAND },
          { label: 'K系数', value: '1.45', change: 0.12, color: PURPLE },
          { label: '裂变贡献营收', value: '\u00A535.7万', change: 15.2, color: GREEN },
        ].map((kpi, i) => (
          <div key={i} style={{
            background: BG_1, borderRadius: 10, padding: '14px 16px',
            border: `1px solid ${BG_2}`,
          }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{kpi.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: kpi.color }}>{kpi.value}</div>
            {kpi.change !== 0 && (
              <div style={{ fontSize: 11, color: kpi.change > 0 ? GREEN : RED, marginTop: 4 }}>
                {kpi.change > 0 ? '+' : ''}{kpi.change}% 较上期
              </div>
            )}
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
            padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
            background: activeTab === t.key ? BRAND : BG_1,
            color: activeTab === t.key ? '#fff' : TEXT_3,
            fontSize: 13, fontWeight: 600,
          }}>{t.label}</button>
        ))}
      </div>

      {activeTab === 'campaigns' && <CampaignCards campaigns={MOCK_CAMPAIGNS} />}
      {activeTab === 'funnel' && <FunnelChart steps={MOCK_FUNNEL} />}
      {activeTab === 'rewards' && <RewardSettlement rewards={MOCK_REWARDS} />}
      {activeTab === 'antifraud' && <AntiFraudMonitor alerts={MOCK_FRAUD_ALERTS} />}
    </div>
  );
}
