/**
 * Workspace: Customers — 客户管理（替代 v1 MerchantsPage + BrandOverviewPage）
 *
 * 核心升级：健康分多维模型 + Playbook引擎
 * 左侧列表 + 右侧 Object Page (8 Tab)
 */
import { useState, useEffect, useMemo } from 'react';
import { hubGet } from '../api/hubApi';

// ── 颜色常量 ──
const C = {
  bg: '#0A1418', surface: '#0E1E24', surface2: '#132932', surface3: '#1A3540',
  border: '#1A3540', border2: '#23485a',
  text: '#E6EDF1', text2: '#94A8B3', text3: '#647985',
  orange: '#FF6B2C', green: '#22C55E', yellow: '#F59E0B', red: '#EF4444', blue: '#3B82F6', purple: '#A855F7',
};

// ── 类型定义 ──

type CustomerTier = 'A' | 'B' | 'C';
type CustomerType = '直营' | '加盟';

interface CustomerHealth {
  slaHitRate: number;     // SLA命中率 %
  nps: number;            // NPS评分 0-100
  adapterLatency: number; // Adapter延迟 P95 ms
  activity: number;       // 活跃度 0-100
  ticketResponseRate: number; // 工单响应率 %
}

interface PlaybookItem {
  id: string;
  name: string;
  status: '运行中' | '已完成' | '待触发';
  lastRun: string;
  sliRate: number; // %
}

interface CustomerEvent {
  id: string;
  time: string;
  type: '签约' | '续约' | '投诉' | 'Incident' | '实施' | '上线' | '季度检查' | '首月护航';
  description: string;
  operator: string;
}

interface RelatedStore {
  id: string;
  name: string;
  status: '在线' | '离线' | '维护中';
  lastOrderTime: string;
}

interface RelatedTicket {
  id: string;
  title: string;
  status: '待处理' | '处理中' | '已关闭';
  createdAt: string;
}

interface RelatedIncident {
  id: string;
  title: string;
  severity: 'P0' | 'P1' | 'P2';
  status: '活跃' | '已解决';
}

interface CustomerRecord {
  id: string;
  name: string;
  type: CustomerType;
  cuisine: string;
  stores: number;
  arr: number;
  healthScore: number;
  health: CustomerHealth;
  nps: number;
  renewalDate: string;
  signDate: string;
  csm: string;
  tier: CustomerTier;
  haas: number;
  saas: number;
  aiAddon: number;
  playbooks: PlaybookItem[];
  events: CustomerEvent[];
  relatedStores: RelatedStore[];
  relatedTickets: RelatedTicket[];
  relatedIncidents: RelatedIncident[];
}

// ── Mock 数据 ──

const MOCK_PLAYBOOKS_A: PlaybookItem[] = [
  { id: 'pb-1', name: 'Onboarding（新客户上线）', status: '已完成', lastRun: '2026-01-10', sliRate: 98 },
  { id: 'pb-2', name: '首营月护航（30天密集跟进）', status: '已完成', lastRun: '2026-02-10', sliRate: 95 },
  { id: 'pb-3', name: '季度健康检查', status: '运行中', lastRun: '2026-04-01', sliRate: 92 },
  { id: 'pb-4', name: '续约前90/60/30天', status: '待触发', lastRun: '-', sliRate: 0 },
];

const MOCK_PLAYBOOKS_B: PlaybookItem[] = [
  { id: 'pb-1', name: 'Onboarding（新客户上线）', status: '已完成', lastRun: '2026-02-15', sliRate: 90 },
  { id: 'pb-2', name: '首营月护航（30天密集跟进）', status: '运行中', lastRun: '2026-03-15', sliRate: 82 },
  { id: 'pb-3', name: '季度健康检查', status: '待触发', lastRun: '-', sliRate: 0 },
  { id: 'pb-4', name: '续约前90/60/30天', status: '待触发', lastRun: '-', sliRate: 0 },
];

const MOCK_EVENTS_COMMON: CustomerEvent[] = [
  { id: 'ev1', time: '2026-04-01', type: '季度检查', description: 'Q2季度健康检查启动', operator: '李明' },
  { id: 'ev2', time: '2026-03-15', type: '投诉', description: '反馈出餐调度Agent延迟偏高', operator: '客户' },
  { id: 'ev3', time: '2026-02-01', type: '上线', description: '全部门店上线完成', operator: '张伟' },
  { id: 'ev4', time: '2026-01-15', type: '实施', description: '实施团队进场部署', operator: '王芳' },
  { id: 'ev5', time: '2026-01-01', type: '签约', description: '签约屯象OS标准版', operator: '李明' },
];

const MOCK_STORES_XJ: RelatedStore[] = [
  { id: 'st-001', name: '五一广场店', status: '在线', lastOrderTime: '2026-04-26 12:30' },
  { id: 'st-002', name: '梅溪湖店', status: '在线', lastOrderTime: '2026-04-26 12:15' },
  { id: 'st-003', name: '河西店', status: '离线', lastOrderTime: '2026-04-25 21:00' },
  { id: 'st-004', name: '星沙店', status: '在线', lastOrderTime: '2026-04-26 11:45' },
];

const MOCK_TICKETS: RelatedTicket[] = [
  { id: 'TK-0201', title: '打印机偶发卡纸', status: '处理中', createdAt: '2026-04-20' },
  { id: 'TK-0198', title: 'KDS显示延迟', status: '已关闭', createdAt: '2026-04-15' },
];

const MOCK_REL_INCIDENTS: RelatedIncident[] = [
  { id: 'INC-2026-042', title: 'Mac mini集群离线', severity: 'P0', status: '活跃' },
];

const MOCK_CUSTOMERS: CustomerRecord[] = [
  { id: 'tx-9001', name: '徐记海鲜', type: '直营', cuisine: '海鲜酒楼', stores: 56, arr: 168000, healthScore: 92, health: { slaHitRate: 98, nps: 78, adapterLatency: 45, activity: 95, ticketResponseRate: 96 }, nps: 78, renewalDate: '2026-09-15', signDate: '2025-09-15', csm: '李明', tier: 'A', haas: 67200, saas: 84000, aiAddon: 16800, playbooks: MOCK_PLAYBOOKS_A, events: MOCK_EVENTS_COMMON, relatedStores: MOCK_STORES_XJ, relatedTickets: MOCK_TICKETS, relatedIncidents: MOCK_REL_INCIDENTS },
  { id: 'tx-9002', name: '尝在一起', type: '直营', cuisine: '快餐', stores: 23, arr: 69000, healthScore: 85, health: { slaHitRate: 92, nps: 72, adapterLatency: 60, activity: 88, ticketResponseRate: 90 }, nps: 72, renewalDate: '2026-07-01', signDate: '2025-10-01', csm: '王芳', tier: 'A', haas: 27600, saas: 34500, aiAddon: 6900, playbooks: MOCK_PLAYBOOKS_A, events: MOCK_EVENTS_COMMON, relatedStores: [{ id: 'st-010', name: '天心区店', status: '在线', lastOrderTime: '2026-04-26 12:00' }, { id: 'st-011', name: '雨花区店', status: '在线', lastOrderTime: '2026-04-26 11:30' }], relatedTickets: MOCK_TICKETS, relatedIncidents: [] },
  { id: 'tx-9003', name: '最黔线', type: '加盟', cuisine: '贵州菜', stores: 15, arr: 45000, healthScore: 76, health: { slaHitRate: 85, nps: 65, adapterLatency: 120, activity: 72, ticketResponseRate: 80 }, nps: 65, renewalDate: '2026-08-20', signDate: '2025-11-01', csm: '张伟', tier: 'B', haas: 18000, saas: 22500, aiAddon: 4500, playbooks: MOCK_PLAYBOOKS_B, events: MOCK_EVENTS_COMMON, relatedStores: [{ id: 'st-020', name: '开福区店', status: '离线', lastOrderTime: '2026-04-25 20:00' }], relatedTickets: MOCK_TICKETS, relatedIncidents: [] },
  { id: 'tx-9004', name: '尚宫厨', type: '直营', cuisine: '韩式料理', stores: 8, arr: 24000, healthScore: 68, health: { slaHitRate: 78, nps: 58, adapterLatency: 180, activity: 60, ticketResponseRate: 72 }, nps: 58, renewalDate: '2026-06-10', signDate: '2025-12-01', csm: '李明', tier: 'B', haas: 9600, saas: 12000, aiAddon: 2400, playbooks: MOCK_PLAYBOOKS_B, events: MOCK_EVENTS_COMMON, relatedStores: [{ id: 'st-030', name: '岳麓区店', status: '离线', lastOrderTime: '2026-04-25 18:00' }], relatedTickets: MOCK_TICKETS, relatedIncidents: [] },
  { id: 'tx-9005', name: '湘粤楼', type: '直营', cuisine: '湘菜粤菜', stores: 12, arr: 36000, healthScore: 88, health: { slaHitRate: 95, nps: 75, adapterLatency: 55, activity: 90, ticketResponseRate: 93 }, nps: 75, renewalDate: '2026-10-01', signDate: '2025-08-01', csm: '王芳', tier: 'A', haas: 14400, saas: 18000, aiAddon: 3600, playbooks: MOCK_PLAYBOOKS_A, events: MOCK_EVENTS_COMMON, relatedStores: [{ id: 'st-040', name: '芙蓉路店', status: '在线', lastOrderTime: '2026-04-26 12:20' }, { id: 'st-041', name: '万家丽店', status: '在线', lastOrderTime: '2026-04-26 12:10' }], relatedTickets: [], relatedIncidents: [{ id: 'INC-2026-042', title: 'Mac mini集群离线 - 广州区', severity: 'P0', status: '活跃' }] },
  { id: 'tx-9006', name: '费大厨', type: '直营', cuisine: '湘菜', stores: 42, arr: 126000, healthScore: 91, health: { slaHitRate: 97, nps: 80, adapterLatency: 35, activity: 93, ticketResponseRate: 95 }, nps: 80, renewalDate: '2026-11-20', signDate: '2025-07-01', csm: '张伟', tier: 'A', haas: 50400, saas: 63000, aiAddon: 12600, playbooks: MOCK_PLAYBOOKS_A, events: MOCK_EVENTS_COMMON, relatedStores: [{ id: 'st-050', name: '国金中心店', status: '在线', lastOrderTime: '2026-04-26 12:25' }], relatedTickets: [], relatedIncidents: [] },
  { id: 'tx-9007', name: '炊烟', type: '直营', cuisine: '湘菜', stores: 35, arr: 105000, healthScore: 55, health: { slaHitRate: 70, nps: 50, adapterLatency: 250, activity: 45, ticketResponseRate: 60 }, nps: 50, renewalDate: '2026-05-15', signDate: '2025-05-15', csm: '李明', tier: 'C', haas: 42000, saas: 52500, aiAddon: 10500, playbooks: MOCK_PLAYBOOKS_B, events: [...MOCK_EVENTS_COMMON, { id: 'ev-alert1', time: '2026-04-20', type: '投诉', description: '多次反馈Adapter同步延迟，P95>200ms', operator: '客户' }], relatedStores: [{ id: 'st-060', name: '坡子街店', status: '在线', lastOrderTime: '2026-04-26 11:00' }], relatedTickets: MOCK_TICKETS, relatedIncidents: [] },
  { id: 'tx-9008', name: '文和友', type: '直营', cuisine: '长沙小吃', stores: 5, arr: 15000, healthScore: 78, health: { slaHitRate: 88, nps: 68, adapterLatency: 90, activity: 75, ticketResponseRate: 85 }, nps: 68, renewalDate: '2026-12-01', signDate: '2026-01-01', csm: '王芳', tier: 'B', haas: 6000, saas: 7500, aiAddon: 1500, playbooks: MOCK_PLAYBOOKS_B, events: MOCK_EVENTS_COMMON, relatedStores: [{ id: 'st-070', name: '海信广场店', status: '在线', lastOrderTime: '2026-04-26 12:00' }], relatedTickets: [], relatedIncidents: [] },
  { id: 'tx-9009', name: '茶颜悦色', type: '直营', cuisine: '茶饮', stores: 120, arr: 360000, healthScore: 95, health: { slaHitRate: 99, nps: 88, adapterLatency: 25, activity: 98, ticketResponseRate: 99 }, nps: 88, renewalDate: '2026-08-01', signDate: '2025-08-01', csm: '张伟', tier: 'A', haas: 144000, saas: 180000, aiAddon: 36000, playbooks: MOCK_PLAYBOOKS_A, events: MOCK_EVENTS_COMMON, relatedStores: [{ id: 'st-080', name: '黄兴路步行街店', status: '在线', lastOrderTime: '2026-04-26 12:35' }, { id: 'st-081', name: 'IFS店', status: '在线', lastOrderTime: '2026-04-26 12:32' }], relatedTickets: [], relatedIncidents: [] },
  { id: 'tx-9010', name: '黑色经典', type: '加盟', cuisine: '长沙小吃', stores: 80, arr: 240000, healthScore: 82, health: { slaHitRate: 90, nps: 70, adapterLatency: 70, activity: 85, ticketResponseRate: 88 }, nps: 70, renewalDate: '2026-09-01', signDate: '2025-09-01', csm: '李明', tier: 'A', haas: 96000, saas: 120000, aiAddon: 24000, playbooks: MOCK_PLAYBOOKS_A, events: MOCK_EVENTS_COMMON, relatedStores: [{ id: 'st-090', name: '太平街店', status: '在线', lastOrderTime: '2026-04-26 12:30' }], relatedTickets: MOCK_TICKETS, relatedIncidents: [] },
];

// ── 辅助 ──

type FilterKey = 'all' | 'A' | 'B' | 'C' | 'alert' | 'renewing';
type TabKey = 'overview' | 'timeline' | 'playbooks' | 'actions' | 'related' | 'traces' | 'cost' | 'logs';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'playbooks', label: 'Playbooks' },
  { key: 'actions', label: 'Actions' },
  { key: 'related', label: 'Related' },
  { key: 'traces', label: 'Traces' },
  { key: 'cost', label: 'Cost' },
  { key: 'logs', label: 'Logs' },
];

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'A', label: 'A类' },
  { key: 'B', label: 'B类' },
  { key: 'C', label: 'C类' },
  { key: 'alert', label: '告警' },
  { key: 'renewing', label: '即将续约' },
];

function healthColor(score: number): string {
  if (score >= 80) return C.green;
  if (score >= 60) return C.yellow;
  return C.red;
}

function formatARR(v: number): string {
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万`;
  return `${(v / 1000).toFixed(1)}k`;
}

function Placeholder({ label }: { label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200, color: C.text3, fontSize: 14 }}>
      {label}
    </div>
  );
}

// ── SVG 雷达图 ──

function RadarChart({ health, totalScore }: { health: CustomerHealth; totalScore: number }) {
  const cx = 150, cy = 150, r = 100;
  const dims = [
    { label: 'SLA命中率', value: health.slaHitRate, max: 100 },
    { label: 'NPS评分', value: health.nps, max: 100 },
    { label: 'Adapter延迟', value: Math.max(0, 100 - (health.adapterLatency / 3)), max: 100 }, // 反转：延迟越低越好
    { label: '活跃度', value: health.activity, max: 100 },
    { label: '工单响应率', value: health.ticketResponseRate, max: 100 },
  ];
  const n = dims.length;
  const angleStep = (2 * Math.PI) / n;

  const getPoint = (index: number, ratio: number) => {
    const angle = angleStep * index - Math.PI / 2;
    return {
      x: cx + r * ratio * Math.cos(angle),
      y: cy + r * ratio * Math.sin(angle),
    };
  };

  // 背景网格
  const gridLevels = [0.2, 0.4, 0.6, 0.8, 1.0];
  const gridPaths = gridLevels.map(level => {
    const points = Array.from({ length: n }, (_, i) => {
      const p = getPoint(i, level);
      return `${p.x},${p.y}`;
    });
    return `M${points.join('L')}Z`;
  });

  // 数据多边形
  const dataPoints = dims.map((d, i) => {
    const ratio = d.value / d.max;
    return getPoint(i, ratio);
  });
  const dataPath = `M${dataPoints.map(p => `${p.x},${p.y}`).join('L')}Z`;

  // 轴线
  const axisLines = Array.from({ length: n }, (_, i) => getPoint(i, 1));

  const scoreColor = healthColor(totalScore);

  return (
    <svg width={300} height={300} viewBox="0 0 300 300" style={{ display: 'block', margin: '0 auto' }}>
      {/* 背景网格 */}
      {gridPaths.map((d, i) => (
        <path key={i} d={d} fill="none" stroke={C.border2} strokeWidth={0.5} opacity={0.6} />
      ))}
      {/* 轴线 */}
      {axisLines.map((p, i) => (
        <line key={i} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke={C.border2} strokeWidth={0.5} opacity={0.4} />
      ))}
      {/* 数据区域 */}
      <path d={dataPath} fill={scoreColor + '33'} stroke={scoreColor} strokeWidth={2} />
      {/* 数据点 */}
      {dataPoints.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={4} fill={scoreColor} stroke={C.surface} strokeWidth={1.5} />
      ))}
      {/* 维度标签 */}
      {dims.map((d, i) => {
        const labelPoint = getPoint(i, 1.25);
        return (
          <text key={i} x={labelPoint.x} y={labelPoint.y} textAnchor="middle" dominantBaseline="middle"
            fill={C.text2} fontSize={10} fontFamily="inherit">
            {d.label}
          </text>
        );
      })}
      {/* 中心总分 */}
      <text x={cx} y={cy - 8} textAnchor="middle" dominantBaseline="middle"
        fill={scoreColor} fontSize={28} fontWeight={700} fontFamily="inherit">
        {totalScore}
      </text>
      <text x={cx} y={cy + 14} textAnchor="middle" dominantBaseline="middle"
        fill={C.text3} fontSize={10} fontFamily="inherit">
        健康总分
      </text>
    </svg>
  );
}

// ── Overview Tab ──

function OverviewTab({ customer }: { customer: CustomerRecord }) {
  const sc = healthColor(customer.healthScore);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 客户信息卡 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>客户信息</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px 24px', fontSize: 13 }}>
          {([
            ['名称', customer.name], ['类型', customer.type], ['主营业态', customer.cuisine],
            ['门店数', `${customer.stores} 家`], ['CSM负责人', customer.csm], ['签约日', customer.signDate],
            ['续约日', customer.renewalDate], ['客户等级', `${customer.tier}类`],
          ] as const).map(([label, val]) => (
            <div key={label}>
              <div style={{ color: C.text3, fontSize: 11, marginBottom: 2 }}>{label}</div>
              <div style={{ color: C.text }}>{val}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 健康分雷达图 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>健康分析</div>
        <RadarChart health={customer.health} totalScore={customer.healthScore} />
        {/* 维度明细 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 12 }}>
          {[
            { label: 'SLA命中率', value: `${customer.health.slaHitRate}%`, color: customer.health.slaHitRate >= 90 ? C.green : C.yellow },
            { label: 'NPS评分', value: `${customer.health.nps}`, color: customer.health.nps >= 70 ? C.green : C.yellow },
            { label: 'Adapter延迟', value: `${customer.health.adapterLatency}ms`, color: customer.health.adapterLatency <= 100 ? C.green : customer.health.adapterLatency <= 200 ? C.yellow : C.red },
            { label: '活跃度', value: `${customer.health.activity}%`, color: customer.health.activity >= 80 ? C.green : C.yellow },
            { label: '工单响应率', value: `${customer.health.ticketResponseRate}%`, color: customer.health.ticketResponseRate >= 90 ? C.green : C.yellow },
          ].map(d => (
            <div key={d.label} style={{ background: C.surface2, borderRadius: 6, padding: '8px 10px', border: `1px solid ${C.border}`, cursor: 'pointer' }}>
              <div style={{ fontSize: 11, color: C.text3, marginBottom: 2 }}>{d.label}</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: d.color }}>{d.value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ARR拆解 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>ARR拆解</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
          {[
            { label: 'HaaS', value: customer.haas, color: C.blue },
            { label: 'SaaS', value: customer.saas, color: C.green },
            { label: 'AI增值', value: customer.aiAddon, color: C.purple },
          ].map(item => (
            <div key={item.label} style={{ background: C.surface2, borderRadius: 8, padding: 12, border: `1px solid ${C.border}`, textAlign: 'center' }}>
              <div style={{ fontSize: 11, color: C.text3, marginBottom: 4 }}>{item.label}</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: item.color }}>{formatARR(item.value)}</div>
              <div style={{ fontSize: 11, color: C.text3 }}>{((item.value / customer.arr) * 100).toFixed(0)}%</div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 8, textAlign: 'center', fontSize: 12, color: C.text2 }}>
          总 ARR: <span style={{ fontWeight: 700, color: C.orange }}>{formatARR(customer.arr)}</span>
        </div>
      </div>

      {/* 当前活跃Playbook */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>当前活跃 Playbook</div>
        {customer.playbooks.filter(p => p.status === '运行中').map(pb => (
          <div key={pb.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: `1px solid ${C.border}` }}>
            <span style={{ fontSize: 13, color: C.text }}>{pb.name}</span>
            <span style={{ fontSize: 11, color: C.green, fontWeight: 600 }}>SLI {pb.sliRate}%</span>
          </div>
        ))}
        {customer.playbooks.filter(p => p.status === '运行中').length === 0 && (
          <div style={{ fontSize: 12, color: C.text3 }}>暂无运行中的Playbook</div>
        )}
      </div>

      {/* 最近关键事件 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>最近关键事件</div>
        {customer.events.slice(0, 5).map(evt => {
          const typeColor: Record<string, string> = { '签约': C.green, '续约': C.green, '投诉': C.red, 'Incident': C.red, '实施': C.blue, '上线': C.blue, '季度检查': C.yellow, '首月护航': C.purple };
          return (
            <div key={evt.id} style={{ display: 'flex', gap: 10, padding: '8px 0', borderBottom: `1px solid ${C.border}`, alignItems: 'center' }}>
              <span style={{ fontSize: 11, background: (typeColor[evt.type] || C.text3) + '22', color: typeColor[evt.type] || C.text3, padding: '2px 6px', borderRadius: 4, fontWeight: 600, minWidth: 55, textAlign: 'center' }}>{evt.type}</span>
              <span style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace', minWidth: 85 }}>{evt.time}</span>
              <span style={{ fontSize: 13, color: C.text, flex: 1 }}>{evt.description}</span>
              <span style={{ fontSize: 11, color: C.text3 }}>{evt.operator}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Timeline Tab ──

function TimelineTab({ customer }: { customer: CustomerRecord }) {
  const lifecycle: { time: string; stage: string; description: string; operator: string; done: boolean }[] = [
    { time: customer.signDate, stage: '签约', description: `签约屯象OS，${customer.stores}家门店`, operator: customer.csm, done: true },
    { time: customer.events.find(e => e.type === '实施')?.time || '-', stage: '实施', description: '实施团队进场部署Mac mini及POS终端', operator: '实施组', done: true },
    { time: customer.events.find(e => e.type === '上线')?.time || '-', stage: '上线', description: '全部门店上线完成', operator: '实施组', done: true },
    { time: '-', stage: '首月护航', description: '30天密集跟进，确保系统稳定', operator: customer.csm, done: customer.playbooks.some(p => p.name.includes('首营月') && p.status === '已完成') },
    { time: '-', stage: '季度检查', description: '健康检查 + 功能使用分析', operator: customer.csm, done: customer.playbooks.some(p => p.name.includes('季度') && p.status === '已完成') },
    { time: customer.renewalDate, stage: '续约', description: `续约到期日 ${customer.renewalDate}`, operator: customer.csm, done: false },
  ];

  return (
    <div style={{ position: 'relative', paddingLeft: 24 }}>
      <div style={{ position: 'absolute', left: 7, top: 4, bottom: 4, width: 2, background: C.border }} />
      {lifecycle.map((evt, i) => (
        <div key={i} style={{ display: 'flex', gap: 12, marginBottom: i < lifecycle.length - 1 ? 24 : 0, position: 'relative' }}>
          <div style={{
            position: 'absolute', left: -20, top: 2, width: 16, height: 16, borderRadius: 8,
            background: evt.done ? C.green : C.surface, border: `2px solid ${evt.done ? C.green : C.border2}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, color: '#fff',
          }}>
            {evt.done ? '\u2713' : ''}
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{
                fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
                background: evt.done ? C.green + '22' : C.surface3, color: evt.done ? C.green : C.text3,
              }}>{evt.stage}</span>
              <span style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace' }}>{evt.time}</span>
            </div>
            <div style={{ fontSize: 13, color: C.text, marginBottom: 2 }}>{evt.description}</div>
            <div style={{ fontSize: 11, color: C.text3 }}>{evt.operator}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Playbooks Tab ──

function PlaybooksTab({ customer }: { customer: CustomerRecord }) {
  const statusColor: Record<string, string> = { '运行中': C.green, '已完成': C.blue, '待触发': C.text3 };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {customer.playbooks.map(pb => (
        <div key={pb.id} style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginBottom: 4 }}>{pb.name}</div>
            <div style={{ display: 'flex', gap: 12, fontSize: 11, color: C.text3 }}>
              <span>状态: <span style={{ color: statusColor[pb.status] || C.text3, fontWeight: 600 }}>{pb.status}</span></span>
              <span>最近执行: {pb.lastRun}</span>
              {pb.sliRate > 0 && <span>SLI达成率: <span style={{ color: pb.sliRate >= 90 ? C.green : C.yellow, fontWeight: 600 }}>{pb.sliRate}%</span></span>}
            </div>
          </div>
          {pb.status === '待触发' && (
            <button style={{
              background: C.orange, color: '#fff', border: 'none', borderRadius: 6,
              padding: '6px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
            }}>手动触发</button>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Actions Tab ──

function ActionsTab({ customer }: { customer: CustomerRecord }) {
  const actions = [
    { icon: '\u2B06', title: '升级套餐', desc: 'lite \u2192 standard \u2192 pro', color: C.orange },
    { icon: '\uD83D\uDD04', title: '延长续约', desc: `当前续约日 ${customer.renewalDate}`, color: C.green },
    { icon: '\uD83D\uDC64', title: '分配CSM', desc: `当前CSM: ${customer.csm}`, color: C.blue },
    { icon: '\u23F8', title: '暂停服务', desc: '暂停所有Agent及同步服务', color: C.red },
    { icon: '\uD83C\uDFE5', title: '触发健康检查', desc: '立即执行季度健康检查Playbook', color: C.yellow },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
      {actions.map(a => (
        <button key={a.title} onClick={() => {}} style={{
          background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16,
          cursor: 'pointer', textAlign: 'left', display: 'flex', gap: 12, alignItems: 'flex-start',
        }}>
          <span style={{ fontSize: 24 }}>{a.icon}</span>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: a.color, marginBottom: 4 }}>{a.title}</div>
            <div style={{ fontSize: 12, color: C.text3 }}>{a.desc}</div>
          </div>
        </button>
      ))}
    </div>
  );
}

// ── Related Tab ──

function RelatedTab({ customer }: { customer: CustomerRecord }) {
  const storeStatusColor: Record<string, string> = { '在线': C.green, '离线': C.red, '维护中': C.yellow };
  const ticketStatusColor: Record<string, string> = { '待处理': C.yellow, '处理中': C.blue, '已关闭': C.text3 };
  const incSevColor: Record<string, string> = { P0: C.red, P1: C.orange, P2: C.yellow };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 关联门店 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>关联门店 ({customer.relatedStores.length})</div>
        {customer.relatedStores.map(s => (
          <div key={s.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ width: 8, height: 8, borderRadius: 4, background: storeStatusColor[s.status] || C.text3 }} />
              <span style={{ fontSize: 13, color: C.text, fontWeight: 600 }}>{s.name}</span>
              <span style={{ fontSize: 11, color: storeStatusColor[s.status] || C.text3 }}>{s.status}</span>
            </div>
            <span style={{ fontSize: 11, color: C.text3 }}>最近订单 {s.lastOrderTime}</span>
          </div>
        ))}
      </div>

      {/* 关联工单 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>关联工单 ({customer.relatedTickets.length})</div>
        {customer.relatedTickets.length === 0 ? (
          <div style={{ fontSize: 12, color: C.text3 }}>暂无工单</div>
        ) : customer.relatedTickets.map(t => (
          <div key={t.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 12, fontFamily: 'monospace', color: C.text3 }}>{t.id}</span>
              <span style={{ fontSize: 13, color: C.text }}>{t.title}</span>
            </div>
            <span style={{ fontSize: 11, color: ticketStatusColor[t.status] || C.text3, fontWeight: 600 }}>{t.status}</span>
          </div>
        ))}
      </div>

      {/* 关联Incident */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>关联Incident ({customer.relatedIncidents.length})</div>
        {customer.relatedIncidents.length === 0 ? (
          <div style={{ fontSize: 12, color: C.text3 }}>暂无Incident</div>
        ) : customer.relatedIncidents.map(inc => (
          <div key={inc.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, background: (incSevColor[inc.severity] || C.text3) + '22', color: incSevColor[inc.severity] || C.text3, padding: '2px 6px', borderRadius: 4, fontWeight: 700 }}>{inc.severity}</span>
              <span style={{ fontSize: 13, color: C.text }}>{inc.title}</span>
            </div>
            <span style={{ fontSize: 11, color: inc.status === '活跃' ? C.red : C.green, fontWeight: 600 }}>{inc.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Export ──

export function CustomersWorkspace() {
  const [customers, setCustomers] = useState<CustomerRecord[]>(MOCK_CUSTOMERS);
  const [selected, setSelected] = useState<CustomerRecord | null>(null);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [tab, setTab] = useState<TabKey>('overview');

  useEffect(() => {
    hubGet<CustomerRecord[]>('/customers')
      .then(data => { if (Array.isArray(data) && data.length > 0) setCustomers(data); })
      .catch(() => { /* 使用 Mock */ });
  }, []);

  const filtered = useMemo(() => {
    switch (filter) {
      case 'A': case 'B': case 'C':
        return customers.filter(c => c.tier === filter);
      case 'alert':
        return customers.filter(c => c.healthScore < 60);
      case 'renewing': {
        const now = new Date();
        const ninetyDays = 90 * 24 * 60 * 60 * 1000;
        return customers.filter(c => {
          const rd = new Date(c.renewalDate);
          return rd.getTime() - now.getTime() < ninetyDays && rd.getTime() > now.getTime();
        });
      }
      default:
        return customers;
    }
  }, [customers, filter]);

  const counts = useMemo(() => {
    const now = new Date();
    const ninetyDays = 90 * 24 * 60 * 60 * 1000;
    const m: Record<string, number> = { all: customers.length };
    for (const c of customers) {
      m[c.tier] = (m[c.tier] || 0) + 1;
      if (c.healthScore < 60) m['alert'] = (m['alert'] || 0) + 1;
      const rd = new Date(c.renewalDate);
      if (rd.getTime() - now.getTime() < ninetyDays && rd.getTime() > now.getTime()) {
        m['renewing'] = (m['renewing'] || 0) + 1;
      }
    }
    return m;
  }, [customers]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', color: C.text }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: C.text, marginBottom: 16 }}>客户</div>

      <div style={{ display: 'flex', gap: 16, flex: 1, minHeight: 0 }}>
        {/* 左侧列表 */}
        <div style={{ width: 380, flexShrink: 0, display: 'flex', flexDirection: 'column', background: C.surface, borderRadius: 10, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
          {/* 筛选 */}
          <div style={{ padding: '12px 14px', borderBottom: `1px solid ${C.border}`, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {FILTERS.map(f => (
              <button key={f.key} onClick={() => setFilter(f.key)} style={{
                background: filter === f.key ? C.orange + '22' : 'transparent',
                color: filter === f.key ? C.orange : C.text3,
                border: `1px solid ${filter === f.key ? C.orange : C.border}`,
                borderRadius: 20, padding: '3px 10px', fontSize: 11, cursor: 'pointer',
              }}>
                {f.label} {counts[f.key] ?? 0}
              </button>
            ))}
          </div>
          {/* 列表 */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {filtered.map(cust => {
              const isActive = selected?.id === cust.id;
              const sc = healthColor(cust.healthScore);
              return (
                <div key={cust.id} onClick={() => { setSelected(cust); setTab('overview'); }} style={{
                  padding: '10px 14px', cursor: 'pointer',
                  borderLeft: isActive ? `3px solid ${C.orange}` : '3px solid transparent',
                  background: isActive ? C.orange + '0D' : 'transparent',
                  borderBottom: `1px solid ${C.border}`, transition: 'background 0.15s',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 5, background: sc, flexShrink: 0 }} />
                    <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>{cust.name}</span>
                    <span style={{ fontSize: 11, color: C.text3, background: C.surface3, padding: '1px 6px', borderRadius: 4 }}>{cust.tier}类</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: C.text3, paddingLeft: 18 }}>
                    <span>{cust.stores}家门店</span>
                    <span>ARR {formatARR(cust.arr)}</span>
                    <span>续约 {cust.renewalDate.slice(5)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 右侧 Object Page */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {!selected ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: C.text3, fontSize: 14 }}>
              选择一个客户查看详情
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                <span style={{ width: 10, height: 10, borderRadius: 5, background: healthColor(selected.healthScore) }} />
                <span style={{ fontSize: 16, fontWeight: 700, color: C.text }}>{selected.name}</span>
                <span style={{ fontSize: 12, color: C.text3, fontFamily: 'monospace' }}>{selected.id}</span>
                <span style={{ fontSize: 11, fontWeight: 600, color: healthColor(selected.healthScore), background: healthColor(selected.healthScore) + '18', padding: '2px 8px', borderRadius: 4 }}>{selected.healthScore}分</span>
              </div>
              {/* Tab bar */}
              <div style={{ display: 'flex', gap: 0, borderBottom: `1px solid ${C.border}`, marginBottom: 16 }}>
                {TABS.map(t => (
                  <button key={t.key} onClick={() => setTab(t.key)} style={{
                    padding: '8px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
                    color: tab === t.key ? C.orange : C.text3,
                    borderBottom: tab === t.key ? `2px solid ${C.orange}` : '2px solid transparent',
                    background: 'transparent', border: 'none', borderBottomStyle: 'solid' as const,
                  }}>{t.label}</button>
                ))}
              </div>
              {/* Tab content */}
              <div style={{ flex: 1, overflowY: 'auto' }}>
                {tab === 'overview' && <OverviewTab customer={selected} />}
                {tab === 'timeline' && <TimelineTab customer={selected} />}
                {tab === 'playbooks' && <PlaybooksTab customer={selected} />}
                {tab === 'actions' && <ActionsTab customer={selected} />}
                {tab === 'related' && <RelatedTab customer={selected} />}
                {tab === 'traces' && <Placeholder label="Trace 数据接入中" />}
                {tab === 'cost' && <Placeholder label="成本数据接入中" />}
                {tab === 'logs' && <Placeholder label="日志接入中" />}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
