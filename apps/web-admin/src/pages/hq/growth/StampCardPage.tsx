/**
 * StampCardPage — 集点卡管理
 * 路由: /hq/growth/stamp-card
 * 集点卡模板管理 + 活跃数据 + 核销记录
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

type TabKey = 'templates' | 'instances' | 'analytics';

interface StampTemplate {
  id: string;
  name: string;
  targetStamps: number;
  rewardType: '优惠券' | '免费菜品' | '积分' | '储值';
  rewardDesc: string;
  validityDays: number;
  minOrderFen: number;
  autoStamp: boolean;
  status: '进行中' | '已结束' | '待启动';
  issuedCount: number;
  completedCount: number;
  createdAt: string;
}

interface StampInstance {
  id: string;
  templateName: string;
  customerName: string;
  customerPhone: string;
  currentStamps: number;
  targetStamps: number;
  status: '集印中' | '已完成' | '已过期';
  lastStampAt: string;
  redeemed: boolean;
}

interface KPI {
  label: string;
  value: string;
  sub: string;
  trend?: 'up' | 'down' | 'flat';
}

const MOCK_KPIS: KPI[] = [
  { label: '活跃模板', value: '5', sub: '共发放 1,280 张', trend: 'up' },
  { label: '集印中', value: '847', sub: '本月新增 132 张', trend: 'up' },
  { label: '完成率', value: '34.8%', sub: '较上月 +2.3%', trend: 'up' },
  { label: '复购提升', value: '+18.6%', sub: '持卡会员 vs 普通', trend: 'up' },
];

const MOCK_TEMPLATES: StampTemplate[] = [
  { id: 'st-001', name: '集5杯送拿铁', targetStamps: 5, rewardType: '免费菜品', rewardDesc: '免费拿铁一杯', validityDays: 90, minOrderFen: 0, autoStamp: true, status: '进行中', issuedCount: 520, completedCount: 186, createdAt: '2026-02-15' },
  { id: 'st-002', name: '集10次送招牌菜', targetStamps: 10, rewardType: '免费菜品', rewardDesc: '招牌酸菜鱼一份', validityDays: 180, minOrderFen: 5000, autoStamp: true, status: '进行中', issuedCount: 380, completedCount: 95, createdAt: '2026-01-20' },
  { id: 'st-003', name: '集8次送50元券', targetStamps: 8, rewardType: '优惠券', rewardDesc: '50元代金券', validityDays: 60, minOrderFen: 3000, autoStamp: true, status: '进行中', issuedCount: 280, completedCount: 112, createdAt: '2026-03-01' },
  { id: 'st-004', name: '集15次送200积分', targetStamps: 15, rewardType: '积分', rewardDesc: '200积分奖励', validityDays: 120, minOrderFen: 0, autoStamp: false, status: '待启动', issuedCount: 0, completedCount: 0, createdAt: '2026-03-28' },
];

const MOCK_INSTANCES: StampInstance[] = [
  { id: 'si-001', templateName: '集5杯送拿铁', customerName: '王**', customerPhone: '138****8001', currentStamps: 4, targetStamps: 5, status: '集印中', lastStampAt: '2026-03-31 14:20', redeemed: false },
  { id: 'si-002', templateName: '集10次送招牌菜', customerName: '李**', customerPhone: '139****9002', currentStamps: 10, targetStamps: 10, status: '已完成', lastStampAt: '2026-03-30 19:45', redeemed: true },
  { id: 'si-003', templateName: '集8次送50元券', customerName: '张**', customerPhone: '137****7003', currentStamps: 3, targetStamps: 8, status: '集印中', lastStampAt: '2026-03-29 12:10', redeemed: false },
  { id: 'si-004', templateName: '集5杯送拿铁', customerName: '赵**', customerPhone: '136****6004', currentStamps: 5, targetStamps: 5, status: '已完成', lastStampAt: '2026-03-28 16:30', redeemed: false },
  { id: 'si-005', templateName: '集10次送招牌菜', customerName: '陈**', customerPhone: '135****5005', currentStamps: 6, targetStamps: 10, status: '集印中', lastStampAt: '2026-04-01 11:05', redeemed: false },
];

const fen = (v: number) => v > 0 ? `¥${(v / 100).toFixed(0)}起` : '无门槛';

export function StampCardPage() {
  const [tab, setTab] = useState<TabKey>('templates');

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'templates', label: '集点卡模板' },
    { key: 'instances', label: '会员集印' },
    { key: 'analytics', label: '效果分析' },
  ];

  return (
    <div style={{ padding: 24, background: BG_1, minHeight: '100vh', color: TEXT_1, fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif' }}>
      {/* Header */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>集点卡管理</h1>
          <div style={{ fontSize: 13, color: TEXT_3, marginTop: 4 }}>消费集印·到店复购·会员粘性</div>
        </div>
        <button style={{ background: BRAND, color: '#fff', border: 'none', borderRadius: 6, padding: '8px 20px', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>+ 创建集点卡</button>
      </div>

      {/* KPI Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {MOCK_KPIS.map(k => (
          <div key={k.label} style={{ background: BG_2, borderRadius: 8, padding: 16 }}>
            <div style={{ fontSize: 13, color: TEXT_3 }}>{k.label}</div>
            <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{k.value}</div>
            <div style={{ fontSize: 12, color: k.trend === 'up' ? GREEN : RED, marginTop: 4 }}>
              {k.trend === 'up' ? '↑' : '↓'} {k.sub}
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
      {tab === 'templates' && <TemplatesTab />}
      {tab === 'instances' && <InstancesTab />}
      {tab === 'analytics' && <AnalyticsTab />}
    </div>
  );
}

function TemplatesTab() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
      {MOCK_TEMPLATES.map(t => (
        <div key={t.id} style={{ background: BG_2, borderRadius: 12, padding: 20, position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', top: 12, right: 12 }}>
            <span style={{
              padding: '2px 10px', borderRadius: 12, fontSize: 12, fontWeight: 500,
              background: t.status === '进行中' ? 'rgba(82,196,26,0.15)' : t.status === '待启动' ? 'rgba(250,173,20,0.15)' : 'rgba(255,255,255,0.06)',
              color: t.status === '进行中' ? GREEN : t.status === '待启动' ? YELLOW : TEXT_4,
            }}>{t.status}</span>
          </div>

          <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600 }}>{t.name}</h3>

          {/* Stamp visualization */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
            {Array.from({ length: t.targetStamps }).map((_, i) => (
              <div key={i} style={{
                width: 28, height: 28, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14,
                background: i < Math.min(3, t.targetStamps) ? BRAND : 'rgba(255,255,255,0.06)',
                color: i < Math.min(3, t.targetStamps) ? '#fff' : TEXT_4,
              }}>
                {i < Math.min(3, t.targetStamps) ? '✓' : (i + 1)}
              </div>
            ))}
            {t.targetStamps > 8 && <div style={{ width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', color: TEXT_4 }}>...</div>}
          </div>

          <div style={{ fontSize: 13, color: TEXT_2, marginBottom: 4 }}>奖励: <span style={{ color: BRAND, fontWeight: 500 }}>{t.rewardDesc}</span></div>
          <div style={{ fontSize: 13, color: TEXT_3 }}>门槛: {fen(t.minOrderFen)} · 有效期 {t.validityDays} 天 · {t.autoStamp ? '自动集印' : '手动集印'}</div>

          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 16, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
            <div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{t.issuedCount}</div>
              <div style={{ fontSize: 11, color: TEXT_4 }}>已发放</div>
            </div>
            <div>
              <div style={{ fontSize: 20, fontWeight: 700, color: GREEN }}>{t.completedCount}</div>
              <div style={{ fontSize: 11, color: TEXT_4 }}>已完成</div>
            </div>
            <div>
              <div style={{ fontSize: 20, fontWeight: 700, color: BLUE }}>{t.issuedCount > 0 ? `${((t.completedCount / t.issuedCount) * 100).toFixed(1)}%` : '-'}</div>
              <div style={{ fontSize: 11, color: TEXT_4 }}>完成率</div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function InstancesTab() {
  return (
    <div style={{ background: BG_2, borderRadius: 8, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ background: 'rgba(255,255,255,0.04)' }}>
            {['会员', '集点卡', '进度', '状态', '最近集印', '已兑换'].map(h => (
              <th key={h} style={{ padding: '12px 16px', textAlign: 'left', color: TEXT_3, fontWeight: 500, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {MOCK_INSTANCES.map(inst => (
            <tr key={inst.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <td style={{ padding: '14px 16px' }}>{inst.customerName} <span style={{ color: TEXT_4, fontSize: 12 }}>{inst.customerPhone}</span></td>
              <td style={{ padding: '14px 16px' }}>{inst.templateName}</td>
              <td style={{ padding: '14px 16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ width: 100, height: 6, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ width: `${(inst.currentStamps / inst.targetStamps) * 100}%`, height: '100%', background: inst.status === '已完成' ? GREEN : BRAND, borderRadius: 3 }} />
                  </div>
                  <span style={{ fontSize: 12, color: TEXT_3 }}>{inst.currentStamps}/{inst.targetStamps}</span>
                </div>
              </td>
              <td style={{ padding: '14px 16px' }}>
                <span style={{
                  padding: '2px 10px', borderRadius: 12, fontSize: 12,
                  background: inst.status === '已完成' ? 'rgba(82,196,26,0.15)' : inst.status === '集印中' ? 'rgba(24,144,255,0.15)' : 'rgba(255,255,255,0.06)',
                  color: inst.status === '已完成' ? GREEN : inst.status === '集印中' ? BLUE : TEXT_4,
                }}>{inst.status}</span>
              </td>
              <td style={{ padding: '14px 16px', color: TEXT_3, fontSize: 13 }}>{inst.lastStampAt}</td>
              <td style={{ padding: '14px 16px' }}>
                {inst.redeemed
                  ? <span style={{ color: GREEN, fontSize: 12 }}>✓ 已兑换</span>
                  : inst.status === '已完成'
                    ? <span style={{ color: YELLOW, fontSize: 12 }}>待兑换</span>
                    : <span style={{ color: TEXT_4, fontSize: 12 }}>-</span>
                }
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AnalyticsTab() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <div style={{ background: BG_2, borderRadius: 8, padding: 20 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 600 }}>集印频率分布</h3>
        {[
          { label: '每周1次以上', pct: 35, color: GREEN },
          { label: '每两周1次', pct: 28, color: BLUE },
          { label: '每月1次', pct: 22, color: YELLOW },
          { label: '不定期', pct: 15, color: TEXT_4 },
        ].map(d => (
          <div key={d.label} style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
              <span style={{ color: TEXT_2 }}>{d.label}</span>
              <span style={{ color: d.color, fontWeight: 600 }}>{d.pct}%</span>
            </div>
            <div style={{ height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ width: `${d.pct}%`, height: '100%', background: d.color, borderRadius: 3 }} />
            </div>
          </div>
        ))}
      </div>
      <div style={{ background: BG_2, borderRadius: 8, padding: 20 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 600 }}>核心指标对比</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {[
            { label: '持卡会员客单价', value: '¥86.5', compare: '普通会员 ¥62.3', better: true },
            { label: '持卡复购率', value: '68%', compare: '普通会员 49%', better: true },
            { label: '持卡月均消费', value: '3.2次', compare: '普通会员 1.8次', better: true },
            { label: '奖励核销率', value: '82.6%', compare: '行业平均 65%', better: true },
          ].map(m => (
            <div key={m.label} style={{ padding: 12, background: 'rgba(255,255,255,0.03)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, color: TEXT_3 }}>{m.label}</div>
              <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{m.value}</div>
              <div style={{ fontSize: 11, color: m.better ? GREEN : RED, marginTop: 4 }}>{m.compare}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
