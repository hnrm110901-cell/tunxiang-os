/**
 * ChannelCenterPage — 触达渠道中心
 * 路由: /hq/growth/channels
 * 渠道概览卡片 + 渠道配置与发送统计 + 频控规则 + 发送日志
 */
import { useState } from 'react';

const BG_0 = '#0B1A20';
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const CYAN = '#13c2c2';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

type TabKey = 'overview' | 'config' | 'frequency' | 'logs';

interface ChannelCard {
  id: string;
  name: string;
  code: string;
  status: '正常' | '维护中' | '未开通';
  totalSent: number;
  openRate: number;
  clickRate: number;
  conversionRate: number;
  cost: number;
  costUnit: string;
  todaySent: number;
  color: string;
}

interface FrequencyRule {
  id: string;
  channel: string;
  ruleName: string;
  maxPerDay: number;
  maxPerWeek: number;
  maxPerMonth: number;
  cooldownHours: number;
  quietStart: string;
  quietEnd: string;
  status: '生效' | '暂停';
}

interface SendLog {
  id: string;
  channel: string;
  campaign: string;
  targetCount: number;
  successCount: number;
  failCount: number;
  sendTime: string;
  status: '已完成' | '发送中' | '失败';
  operator: string;
}

const MOCK_CHANNELS: ChannelCard[] = [
  { id: 'ch1', name: '企业微信', code: 'wecom', status: '正常', totalSent: 125600, openRate: 85.2, clickRate: 34.1, conversionRate: 12.3, cost: 0, costUnit: '免费', todaySent: 1240, color: GREEN },
  { id: 'ch2', name: '短信', code: 'sms', status: '正常', totalSent: 89400, openRate: 72.3, clickRate: 18.5, conversionRate: 8.7, cost: 0.045, costUnit: '元/条', todaySent: 860, color: BLUE },
  { id: 'ch3', name: '小程序', code: 'miniapp', status: '正常', totalSent: 234500, openRate: 0, clickRate: 42.8, conversionRate: 22.1, cost: 0, costUnit: '免费', todaySent: 3420, color: BRAND },
  { id: 'ch4', name: 'APP Push', code: 'push', status: '正常', totalSent: 67800, openRate: 45.6, clickRate: 12.3, conversionRate: 5.8, cost: 0, costUnit: '免费', todaySent: 520, color: PURPLE },
  { id: 'ch5', name: 'POS小票', code: 'receipt', status: '正常', totalSent: 156000, openRate: 0, clickRate: 0, conversionRate: 3.2, cost: 0.02, costUnit: '元/张', todaySent: 2180, color: YELLOW },
  { id: 'ch6', name: '预订页', code: 'booking', status: '正常', totalSent: 34200, openRate: 0, clickRate: 28.4, conversionRate: 18.5, cost: 0, costUnit: '免费', todaySent: 460, color: CYAN },
  { id: 'ch7', name: '门店任务', code: 'store_task', status: '正常', totalSent: 12800, openRate: 0, clickRate: 0, conversionRate: 45.2, cost: 0, costUnit: '免费', todaySent: 180, color: RED },
];

const MOCK_FREQUENCY_RULES: FrequencyRule[] = [
  { id: 'f1', channel: '企业微信', ruleName: '日常推送频控', maxPerDay: 2, maxPerWeek: 5, maxPerMonth: 12, cooldownHours: 4, quietStart: '22:00', quietEnd: '08:00', status: '生效' },
  { id: 'f2', channel: '短信', ruleName: '短信频控', maxPerDay: 1, maxPerWeek: 3, maxPerMonth: 8, cooldownHours: 24, quietStart: '21:00', quietEnd: '09:00', status: '生效' },
  { id: 'f3', channel: '小程序', ruleName: '弹窗频控', maxPerDay: 3, maxPerWeek: 10, maxPerMonth: 25, cooldownHours: 2, quietStart: '23:00', quietEnd: '07:00', status: '生效' },
  { id: 'f4', channel: 'APP Push', ruleName: 'Push推送频控', maxPerDay: 2, maxPerWeek: 6, maxPerMonth: 15, cooldownHours: 6, quietStart: '22:00', quietEnd: '08:00', status: '生效' },
  { id: 'f5', channel: 'POS小票', ruleName: '小票尾部广告', maxPerDay: 999, maxPerWeek: 999, maxPerMonth: 999, cooldownHours: 0, quietStart: '-', quietEnd: '-', status: '生效' },
  { id: 'f6', channel: '门店任务', ruleName: '到店任务', maxPerDay: 1, maxPerWeek: 3, maxPerMonth: 8, cooldownHours: 12, quietStart: '-', quietEnd: '-', status: '暂停' },
];

const MOCK_LOGS: SendLog[] = [
  { id: 'l1', channel: '企业微信', campaign: '春季回归召回', targetCount: 1240, successCount: 1218, failCount: 22, sendTime: '2026-03-26 10:30', status: '已完成', operator: '系统自动' },
  { id: 'l2', channel: '短信', campaign: '新客欢迎短信', targetCount: 860, successCount: 845, failCount: 15, sendTime: '2026-03-26 09:00', status: '已完成', operator: '系统自动' },
  { id: 'l3', channel: '小程序', campaign: '会员日弹窗', targetCount: 3420, successCount: 3420, failCount: 0, sendTime: '2026-03-26 11:00', status: '发送中', operator: '李晓雯' },
  { id: 'l4', channel: 'APP Push', campaign: '新品上线通知', targetCount: 520, successCount: 498, failCount: 22, sendTime: '2026-03-26 12:00', status: '已完成', operator: '系统自动' },
  { id: 'l5', channel: '企业微信', campaign: '复购召回', targetCount: 1856, successCount: 1823, failCount: 33, sendTime: '2026-03-25 14:30', status: '已完成', operator: '王芳' },
  { id: 'l6', channel: '短信', campaign: '沉睡唤醒', targetCount: 450, successCount: 0, failCount: 450, sendTime: '2026-03-25 15:00', status: '失败', operator: '张明' },
  { id: 'l7', channel: '门店任务', campaign: '新品推荐任务', targetCount: 180, successCount: 156, failCount: 24, sendTime: '2026-03-25 08:00', status: '已完成', operator: '系统自动' },
  { id: 'l8', channel: '预订页', campaign: '预订确认推荐', targetCount: 460, successCount: 455, failCount: 5, sendTime: '2026-03-24 18:00', status: '已完成', operator: '系统自动' },
];

function ChannelOverview({ channels }: { channels: ChannelCard[] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
      {channels.map(ch => {
        const statusColors: Record<string, string> = { '正常': GREEN, '维护中': YELLOW, '未开通': TEXT_4 };
        return (
          <div key={ch.id} style={{
            background: BG_1, borderRadius: 10, padding: 16,
            border: `1px solid ${BG_2}`, cursor: 'pointer',
            borderTop: `3px solid ${ch.color}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <span style={{ fontSize: 16, fontWeight: 700, color: TEXT_1 }}>{ch.name}</span>
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 4,
                background: statusColors[ch.status] + '22', color: statusColors[ch.status], fontWeight: 600,
              }}>{ch.status}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 10, color: TEXT_4 }}>总发送</div>
                <div style={{ fontSize: 15, fontWeight: 600, color: TEXT_1 }}>{(ch.totalSent / 10000).toFixed(1)}万</div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: TEXT_4 }}>今日发送</div>
                <div style={{ fontSize: 15, fontWeight: 600, color: BRAND }}>{ch.todaySent.toLocaleString()}</div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: TEXT_4 }}>打开率</div>
                <div style={{ fontSize: 15, fontWeight: 600, color: ch.openRate > 50 ? GREEN : TEXT_2 }}>
                  {ch.openRate > 0 ? `${ch.openRate}%` : '-'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: TEXT_4 }}>转化率</div>
                <div style={{ fontSize: 15, fontWeight: 600, color: ch.conversionRate > 15 ? GREEN : ch.conversionRate > 8 ? YELLOW : TEXT_2 }}>
                  {ch.conversionRate}%
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: TEXT_4 }}>
              <span>点击率: {ch.clickRate > 0 ? `${ch.clickRate}%` : '-'}</span>
              <span>成本: {ch.cost > 0 ? `${ch.cost}${ch.costUnit}` : ch.costUnit}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ChannelConfig({ channels }: { channels: ChannelCard[] }) {
  const [selected, setSelected] = useState(channels[0].code);
  const ch = channels.find(c => c.code === selected) || channels[0];

  return (
    <div style={{ display: 'flex', gap: 16 }}>
      {/* 左侧渠道列表 */}
      <div style={{
        width: 200, background: BG_1, borderRadius: 10, padding: 10,
        border: `1px solid ${BG_2}`, flexShrink: 0,
      }}>
        {channels.map(c => (
          <div key={c.code} onClick={() => setSelected(c.code)} style={{
            padding: '10px 12px', borderRadius: 6, cursor: 'pointer',
            background: selected === c.code ? BRAND + '22' : 'transparent',
            borderLeft: selected === c.code ? `3px solid ${BRAND}` : '3px solid transparent',
            marginBottom: 2,
          }}>
            <span style={{ fontSize: 13, color: selected === c.code ? TEXT_1 : TEXT_3, fontWeight: selected === c.code ? 600 : 400 }}>
              {c.name}
            </span>
          </div>
        ))}
      </div>

      {/* 右侧配置面板 */}
      <div style={{
        flex: 1, background: BG_1, borderRadius: 10, padding: 20,
        border: `1px solid ${BG_2}`,
      }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 17, fontWeight: 700, color: TEXT_1 }}>{ch.name} 配置</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
          {[
            { label: '累计发送', value: `${(ch.totalSent / 10000).toFixed(1)}万`, color: TEXT_1 },
            { label: '打开率', value: ch.openRate > 0 ? `${ch.openRate}%` : '-', color: ch.openRate > 50 ? GREEN : TEXT_2 },
            { label: '点击率', value: ch.clickRate > 0 ? `${ch.clickRate}%` : '-', color: ch.clickRate > 25 ? GREEN : TEXT_2 },
            { label: '转化率', value: `${ch.conversionRate}%`, color: ch.conversionRate > 15 ? GREEN : YELLOW },
          ].map((item, i) => (
            <div key={i} style={{ background: BG_2, borderRadius: 8, padding: 12 }}>
              <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: item.color }}>{item.value}</div>
            </div>
          ))}
        </div>

        <div style={{
          padding: '14px 16px', background: BG_2, borderRadius: 8, marginBottom: 12,
          fontSize: 12, color: TEXT_3, lineHeight: 1.8,
        }}>
          <div>渠道编码: <strong style={{ color: TEXT_1 }}>{ch.code}</strong></div>
          <div>单条成本: <strong style={{ color: TEXT_1 }}>{ch.cost > 0 ? `${ch.cost}${ch.costUnit}` : '免费'}</strong></div>
          <div>状态: <strong style={{ color: ch.status === '正常' ? GREEN : YELLOW }}>{ch.status}</strong></div>
          <div>今日发送: <strong style={{ color: BRAND }}>{ch.todaySent.toLocaleString()}</strong></div>
        </div>

        <button style={{
          padding: '8px 20px', borderRadius: 6, border: 'none',
          background: BRAND, color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer',
        }}>编辑配置</button>
      </div>
    </div>
  );
}

function FrequencyRulesTable({ rules }: { rules: FrequencyRule[] }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: TEXT_1 }}>频控规则</h3>
        <button style={{
          padding: '6px 14px', borderRadius: 6, border: 'none',
          background: BRAND, color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer',
        }}>新增规则</button>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
            {['渠道', '规则名称', '日上限', '周上限', '月上限', '冷却(h)', '静默时段', '状态', '操作'].map(h => (
              <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rules.map(r => (
            <tr key={r.id} style={{ borderBottom: `1px solid ${BG_2}` }}>
              <td style={{ padding: '10px', color: TEXT_1, fontWeight: 500 }}>{r.channel}</td>
              <td style={{ padding: '10px', color: TEXT_2 }}>{r.ruleName}</td>
              <td style={{ padding: '10px', color: TEXT_2 }}>{r.maxPerDay === 999 ? '不限' : r.maxPerDay}</td>
              <td style={{ padding: '10px', color: TEXT_2 }}>{r.maxPerWeek === 999 ? '不限' : r.maxPerWeek}</td>
              <td style={{ padding: '10px', color: TEXT_2 }}>{r.maxPerMonth === 999 ? '不限' : r.maxPerMonth}</td>
              <td style={{ padding: '10px', color: TEXT_2 }}>{r.cooldownHours || '-'}</td>
              <td style={{ padding: '10px', color: TEXT_3, fontSize: 11 }}>
                {r.quietStart === '-' ? '无' : `${r.quietStart}-${r.quietEnd}`}
              </td>
              <td style={{ padding: '10px' }}>
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 4,
                  background: (r.status === '生效' ? GREEN : TEXT_4) + '22',
                  color: r.status === '生效' ? GREEN : TEXT_4, fontWeight: 600,
                }}>{r.status}</span>
              </td>
              <td style={{ padding: '10px' }}>
                <button style={{
                  padding: '3px 10px', borderRadius: 4, border: 'none',
                  background: BG_2, color: TEXT_3, fontSize: 11, cursor: 'pointer',
                }}>编辑</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SendLogs({ logs }: { logs: SendLog[] }) {
  const [channelFilter, setChannelFilter] = useState('全部');
  const [statusFilter, setStatusFilter] = useState('全部');
  const channelNames = ['全部', ...Array.from(new Set(logs.map(l => l.channel)))];
  const filtered = logs.filter(l =>
    (channelFilter === '全部' || l.channel === channelFilter) &&
    (statusFilter === '全部' || l.status === statusFilter)
  );
  const statusColors: Record<string, string> = { '已完成': GREEN, '发送中': BLUE, '失败': RED };

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: TEXT_1 }}>发送日志</h3>
        <div style={{ display: 'flex', gap: 4 }}>
          {channelNames.map(c => (
            <button key={c} onClick={() => setChannelFilter(c)} style={{
              padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: channelFilter === c ? BLUE : BG_2, color: channelFilter === c ? '#fff' : TEXT_3,
              fontSize: 11, fontWeight: 600,
            }}>{c}</button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
          {['全部', '已完成', '发送中', '失败'].map(s => (
            <button key={s} onClick={() => setStatusFilter(s)} style={{
              padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: statusFilter === s ? BRAND : BG_2, color: statusFilter === s ? '#fff' : TEXT_3,
              fontSize: 11, fontWeight: 600,
            }}>{s}</button>
          ))}
        </div>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
            {['渠道', '活动名称', '目标数', '成功', '失败', '发送时间', '操作人', '状态'].map(h => (
              <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filtered.map(l => {
            const successRate = l.targetCount > 0 ? (l.successCount / l.targetCount * 100).toFixed(1) : '0';
            return (
              <tr key={l.id} style={{ borderBottom: `1px solid ${BG_2}` }}>
                <td style={{ padding: '10px', color: TEXT_1, fontWeight: 500 }}>{l.channel}</td>
                <td style={{ padding: '10px', color: TEXT_2 }}>{l.campaign}</td>
                <td style={{ padding: '10px', color: TEXT_2 }}>{l.targetCount.toLocaleString()}</td>
                <td style={{ padding: '10px', color: GREEN }}>{l.successCount.toLocaleString()}</td>
                <td style={{ padding: '10px', color: l.failCount > 0 ? RED : TEXT_4 }}>{l.failCount}</td>
                <td style={{ padding: '10px', color: TEXT_3, fontSize: 11 }}>{l.sendTime}</td>
                <td style={{ padding: '10px', color: TEXT_3 }}>{l.operator}</td>
                <td style={{ padding: '10px' }}>
                  <span style={{
                    fontSize: 10, padding: '2px 8px', borderRadius: 4,
                    background: statusColors[l.status] + '22', color: statusColors[l.status], fontWeight: 600,
                  }}>{l.status}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---- 主页面 ----

export function ChannelCenterPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const tabs: { key: TabKey; label: string }[] = [
    { key: 'overview', label: '渠道概览' },
    { key: 'config', label: '渠道配置' },
    { key: 'frequency', label: '频控规则' },
    { key: 'logs', label: '发送日志' },
  ];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700 }}>触达渠道中心</h2>

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

      {activeTab === 'overview' && <ChannelOverview channels={MOCK_CHANNELS} />}
      {activeTab === 'config' && <ChannelConfig channels={MOCK_CHANNELS} />}
      {activeTab === 'frequency' && <FrequencyRulesTable rules={MOCK_FREQUENCY_RULES} />}
      {activeTab === 'logs' && <SendLogs logs={MOCK_LOGS} />}
    </div>
  );
}
