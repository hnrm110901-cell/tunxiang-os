/**
 * MemberProfilePage -- 会员画像与CDP分析页
 *
 * 三Tab布局：会员列表 / RFM分析 / 会员增长
 * API: tx-member :8003，降级Mock
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Card,
  Col,
  Drawer,
  Row,
  Select,
  Space,
  Statistic,
  Tabs,
  Tag,
  Timeline,
  Typography,
  Descriptions,
  Input,
  Button,
  Spin,
  message,
} from 'antd';
import {
  CrownOutlined,
  FireOutlined,
  TeamOutlined,
  UserAddOutlined,
  UserOutlined,
  SearchOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns, ActionType } from '@ant-design/pro-components';

const { Title, Text } = Typography;

const BASE = 'http://localhost:8003';

// ─── 类型定义 ────────────────────────────────────────────────

interface MemberStat {
  total: number;
  active: number;
  sleeping: number;
  newThisMonth: number;
}

interface MemberRow {
  id: string;
  name: string;
  phone: string;
  level: string;
  totalSpendYuan: number;
  lastVisit: string;
  frequency: number;
  rfmTag: 'high_value' | 'important_develop' | 'general_maintain' | 'churn_risk';
}

interface MemberPreference {
  topDishes: { name: string; count: number }[];
  flavorTags: string[];
  avgSpendYuan: number;
}

interface MemberTimeline {
  time: string;
  event: string;
}

interface MemberDetail {
  id: string;
  name: string;
  phone: string;
  gender: string;
  level: string;
  joinDate: string;
  birthday: string;
  preference: MemberPreference;
  spendTrend: { month: string; amount: number }[];
  timeline: MemberTimeline[];
}

interface RFMPoint {
  id: string;
  name: string;
  frequency: number;
  monetary: number;
  recency: number;
  quadrant: string;
}

interface RFMQuadrant {
  label: string;
  count: number;
  percent: number;
}

interface GrowthMonth {
  month: string;
  newCount: number;
  churnCount: number;
  netGrowth: number;
}

interface ChannelSource {
  channel: string;
  count: number;
  percent: number;
}

interface RetentionStep {
  label: string;
  rate: number;
}

// ─── RFM标签配置 ─────────────────────────────────────────────

const RFM_TAG_CONFIG: Record<MemberRow['rfmTag'], { label: string; color: string }> = {
  high_value: { label: '高价值', color: 'gold' },
  important_develop: { label: '重要发展', color: 'blue' },
  general_maintain: { label: '一般维护', color: 'default' },
  churn_risk: { label: '流失预警', color: 'red' },
};

const LEVEL_OPTIONS = [
  { label: '全部等级', value: '' },
  { label: '普通会员', value: 'normal' },
  { label: '银卡会员', value: 'silver' },
  { label: '金卡会员', value: 'gold' },
  { label: '钻石会员', value: 'diamond' },
];

const RFM_OPTIONS = [
  { label: '全部标签', value: '' },
  { label: '高价值', value: 'high_value' },
  { label: '重要发展', value: 'important_develop' },
  { label: '一般维护', value: 'general_maintain' },
  { label: '流失预警', value: 'churn_risk' },
];

// ─── Mock数据 ────────────────────────────────────────────────

function mockStats(): MemberStat {
  return { total: 12680, active: 4230, sleeping: 3150, newThisMonth: 386 };
}

function mockMembers(page: number, size: number, filters: { keyword: string; level: string; rfmTag: string }): { items: MemberRow[]; total: number } {
  const rfmTags: MemberRow['rfmTag'][] = ['high_value', 'important_develop', 'general_maintain', 'churn_risk'];
  const levels = ['normal', 'silver', 'gold', 'diamond'];
  const names = ['张三', '李四', '王五', '赵六', '孙七', '周八', '吴九', '郑十', '陈十一', '钱十二'];
  const items: MemberRow[] = [];
  for (let i = 0; i < size; i++) {
    const idx = (page - 1) * size + i;
    const rfm = rfmTags[idx % 4];
    const lv = levels[idx % 4];
    if (filters.level && lv !== filters.level) continue;
    if (filters.rfmTag && rfm !== filters.rfmTag) continue;
    if (filters.keyword && !names[idx % 10].includes(filters.keyword)) continue;
    items.push({
      id: `M${String(10000 + idx)}`,
      name: names[idx % 10],
      phone: `138****${String(1000 + idx).slice(-4)}`,
      level: lv,
      totalSpendYuan: Math.round(500 + Math.random() * 9500),
      lastVisit: `2026-0${1 + (idx % 3)}-${10 + (idx % 20)}`,
      frequency: 2 + (idx % 30),
      rfmTag: rfm,
    });
  }
  return { items, total: 200 };
}

function mockMemberDetail(id: string): MemberDetail {
  const months = Array.from({ length: 12 }, (_, i) => {
    const m = i + 1;
    return { month: `2025-${String(m).padStart(2, '0')}`, amount: Math.round(200 + Math.random() * 1800) };
  });
  return {
    id,
    name: '张三',
    phone: '138****5678',
    gender: '男',
    level: 'gold',
    joinDate: '2024-03-15',
    birthday: '1990-08-20',
    preference: {
      topDishes: [
        { name: '剁椒鱼头', count: 18 },
        { name: '小炒黄牛肉', count: 14 },
        { name: '臭豆腐', count: 11 },
        { name: '口味虾', count: 9 },
        { name: '糖油粑粑', count: 7 },
      ],
      flavorTags: ['微辣', '鲜香', '酸甜'],
      avgSpendYuan: 186,
    },
    spendTrend: months,
    timeline: [
      { time: '2024-03-15', event: '注册成为会员' },
      { time: '2024-03-20', event: '首次消费 ¥158' },
      { time: '2024-06-01', event: '升级为银卡会员' },
      { time: '2025-01-10', event: '升级为金卡会员' },
      { time: '2026-03-25', event: '最近消费 ¥236' },
    ],
  };
}

function mockRFMPoints(): RFMPoint[] {
  const quadrants = ['高频高额', '高频低额', '低频高额', '低频低额'];
  const points: RFMPoint[] = [];
  for (let i = 0; i < 80; i++) {
    const freq = Math.random() * 30;
    const mon = Math.random() * 10000;
    const q = freq > 15 ? (mon > 5000 ? '高频高额' : '高频低额') : (mon > 5000 ? '低频高额' : '低频低额');
    points.push({
      id: `M${10000 + i}`,
      name: `会员${i + 1}`,
      frequency: Math.round(freq * 10) / 10,
      monetary: Math.round(mon),
      recency: Math.round(Math.random() * 90),
      quadrant: q,
    });
  }
  return points;
}

function mockRFMQuadrants(points: RFMPoint[]): RFMQuadrant[] {
  const map: Record<string, number> = {};
  points.forEach(p => { map[p.quadrant] = (map[p.quadrant] || 0) + 1; });
  const total = points.length;
  return ['高频高额', '高频低额', '低频高额', '低频低额'].map(label => ({
    label,
    count: map[label] || 0,
    percent: total > 0 ? Math.round(((map[label] || 0) / total) * 100) : 0,
  }));
}

function mockGrowthData(): GrowthMonth[] {
  return Array.from({ length: 12 }, (_, i) => {
    const m = i + 1;
    const nc = 300 + Math.round(Math.random() * 200);
    const cc = 80 + Math.round(Math.random() * 120);
    return { month: `2025-${String(m).padStart(2, '0')}`, newCount: nc, churnCount: cc, netGrowth: nc - cc };
  });
}

function mockChannels(): ChannelSource[] {
  return [
    { channel: '扫码注册', count: 4200, percent: 33 },
    { channel: '小程序', count: 3800, percent: 30 },
    { channel: '好友推荐', count: 2500, percent: 20 },
    { channel: '线下办理', count: 2180, percent: 17 },
  ];
}

function mockRetention(): RetentionStep[] {
  return [
    { label: '首月', rate: 78 },
    { label: '3个月', rate: 55 },
    { label: '6个月', rate: 38 },
    { label: '12个月', rate: 24 },
  ];
}

// ─── API调用(降级Mock) ──────────────────────────────────────

async function fetchStats(): Promise<MemberStat> {
  try {
    const resp = await fetch(`${BASE}/api/v1/member/analytics/stats`);
    const json = await resp.json();
    if (json.ok) return json.data;
  } catch (err: unknown) {
    console.warn('fetchStats fallback to mock', err instanceof Error ? err.message : err);
  }
  return mockStats();
}

async function fetchMembers(
  page: number,
  size: number,
  filters: { keyword: string; level: string; rfmTag: string },
): Promise<{ items: MemberRow[]; total: number }> {
  try {
    const params = new URLSearchParams({
      page: String(page),
      size: String(size),
      ...(filters.keyword ? { keyword: filters.keyword } : {}),
      ...(filters.level ? { level: filters.level } : {}),
      ...(filters.rfmTag ? { rfm_tag: filters.rfmTag } : {}),
    });
    const resp = await fetch(`${BASE}/api/v1/member/list?${params}`);
    const json = await resp.json();
    if (json.ok) return json.data;
  } catch (err: unknown) {
    console.warn('fetchMembers fallback to mock', err instanceof Error ? err.message : err);
  }
  return mockMembers(page, size, filters);
}

async function fetchMemberDetail(id: string): Promise<MemberDetail> {
  try {
    const resp = await fetch(`${BASE}/api/v1/member/${id}/profile`);
    const json = await resp.json();
    if (json.ok) return json.data;
  } catch (err: unknown) {
    console.warn('fetchMemberDetail fallback to mock', err instanceof Error ? err.message : err);
  }
  return mockMemberDetail(id);
}

async function fetchRFMData(): Promise<{ points: RFMPoint[]; quadrants: RFMQuadrant[] }> {
  try {
    const resp = await fetch(`${BASE}/api/v1/member/rfm/batch`);
    const json = await resp.json();
    if (json.ok) {
      const points: RFMPoint[] = json.data.points || [];
      return { points, quadrants: mockRFMQuadrants(points) };
    }
  } catch (err: unknown) {
    console.warn('fetchRFMData fallback to mock', err instanceof Error ? err.message : err);
  }
  const pts = mockRFMPoints();
  return { points: pts, quadrants: mockRFMQuadrants(pts) };
}

async function fetchGrowthData(): Promise<{
  growth: GrowthMonth[];
  channels: ChannelSource[];
  retention: RetentionStep[];
}> {
  try {
    const resp = await fetch(`${BASE}/api/v1/member/analytics/growth?period=month&days=365`);
    const json = await resp.json();
    if (json.ok) {
      return {
        growth: json.data.growth || mockGrowthData(),
        channels: json.data.channels || mockChannels(),
        retention: json.data.retention || mockRetention(),
      };
    }
  } catch (err: unknown) {
    console.warn('fetchGrowthData fallback to mock', err instanceof Error ? err.message : err);
  }
  return { growth: mockGrowthData(), channels: mockChannels(), retention: mockRetention() };
}

// ─── SVG组件 ─────────────────────────────────────────────────

/** 折线图：近12月消费趋势 */
function SpendTrendChart({ data }: { data: { month: string; amount: number }[] }) {
  if (!data.length) return null;
  const W = 560;
  const H = 200;
  const PAD = { top: 20, right: 20, bottom: 40, left: 50 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const maxVal = Math.max(...data.map(d => d.amount), 1);

  const points = data.map((d, i) => {
    const x = PAD.left + (i / Math.max(data.length - 1, 1)) * plotW;
    const y = PAD.top + plotH - (d.amount / maxVal) * plotH;
    return { x, y, ...d };
  });

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');
  const areaPath = `${linePath} L${points[points.length - 1].x},${PAD.top + plotH} L${points[0].x},${PAD.top + plotH} Z`;

  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      <defs>
        <linearGradient id="trendGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#FF6B35" stopOpacity={0.3} />
          <stop offset="100%" stopColor="#FF6B35" stopOpacity={0.02} />
        </linearGradient>
      </defs>
      {/* Y-axis gridlines */}
      {[0, 0.25, 0.5, 0.75, 1].map(r => {
        const y = PAD.top + plotH - r * plotH;
        return (
          <g key={r}>
            <line x1={PAD.left} y1={y} x2={PAD.left + plotW} y2={y} stroke="#f0f0f0" />
            <text x={PAD.left - 8} y={y + 4} textAnchor="end" fontSize={10} fill="#999">
              {Math.round(maxVal * r)}
            </text>
          </g>
        );
      })}
      {/* Area */}
      <path d={areaPath} fill="url(#trendGrad)" />
      {/* Line */}
      <path d={linePath} fill="none" stroke="#FF6B35" strokeWidth={2} />
      {/* Points */}
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={3} fill="#FF6B35" />
      ))}
      {/* X-axis labels */}
      {points.map((p, i) => (
        <text key={i} x={p.x} y={H - 8} textAnchor="middle" fontSize={9} fill="#999">
          {p.month.slice(5)}
        </text>
      ))}
    </svg>
  );
}

/** 四象限散点图 */
function RFMScatterChart({
  points,
  onQuadrantClick,
}: {
  points: RFMPoint[];
  onQuadrantClick: (quadrant: string) => void;
}) {
  const W = 600;
  const H = 440;
  const PAD = { top: 30, right: 30, bottom: 50, left: 60 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const maxFreq = Math.max(...points.map(p => p.frequency), 1);
  const maxMon = Math.max(...points.map(p => p.monetary), 1);
  const midX = PAD.left + plotW / 2;
  const midY = PAD.top + plotH / 2;

  const quadrantColors: Record<string, string> = {
    '高频高额': '#FF6B35',
    '高频低额': '#1890ff',
    '低频高额': '#52c41a',
    '低频低额': '#999',
  };

  const quadrantLabels = [
    { label: '低频高额', x: PAD.left + plotW * 0.25, y: PAD.top + plotH * 0.25 },
    { label: '高频高额', x: PAD.left + plotW * 0.75, y: PAD.top + plotH * 0.25 },
    { label: '低频低额', x: PAD.left + plotW * 0.25, y: PAD.top + plotH * 0.75 },
    { label: '高频低额', x: PAD.left + plotW * 0.75, y: PAD.top + plotH * 0.75 },
  ];

  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      {/* Quadrant backgrounds (clickable) */}
      {quadrantLabels.map(q => {
        const isLeft = q.x < midX;
        const isTop = q.y < midY;
        return (
          <rect
            key={q.label}
            x={isLeft ? PAD.left : midX}
            y={isTop ? PAD.top : midY}
            width={plotW / 2}
            height={plotH / 2}
            fill={quadrantColors[q.label]}
            fillOpacity={0.04}
            stroke="none"
            style={{ cursor: 'pointer' }}
            onClick={() => onQuadrantClick(q.label)}
          />
        );
      })}
      {/* Center lines */}
      <line x1={midX} y1={PAD.top} x2={midX} y2={PAD.top + plotH} stroke="#d9d9d9" strokeDasharray="4,4" />
      <line x1={PAD.left} y1={midY} x2={PAD.left + plotW} y2={midY} stroke="#d9d9d9" strokeDasharray="4,4" />
      {/* Quadrant labels */}
      {quadrantLabels.map(q => (
        <text
          key={q.label}
          x={q.x}
          y={q.y}
          textAnchor="middle"
          fontSize={12}
          fontWeight={600}
          fill={quadrantColors[q.label]}
          style={{ cursor: 'pointer' }}
          onClick={() => onQuadrantClick(q.label)}
        >
          {q.label}
        </text>
      ))}
      {/* Scatter points */}
      {points.map((p, i) => {
        const cx = PAD.left + (p.frequency / maxFreq) * plotW;
        const cy = PAD.top + plotH - (p.monetary / maxMon) * plotH;
        const r = 3 + Math.max(0, (90 - p.recency) / 90) * 6;
        return (
          <circle
            key={i}
            cx={cx}
            cy={cy}
            r={r}
            fill={quadrantColors[p.quadrant] || '#999'}
            fillOpacity={0.6}
            stroke={quadrantColors[p.quadrant] || '#999'}
            strokeWidth={1}
          >
            <title>{`${p.name}: 频率${p.frequency} 金额${p.monetary} 最近${p.recency}天`}</title>
          </circle>
        );
      })}
      {/* Axes */}
      <line x1={PAD.left} y1={PAD.top + plotH} x2={PAD.left + plotW} y2={PAD.top + plotH} stroke="#333" />
      <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={PAD.top + plotH} stroke="#333" />
      <text x={PAD.left + plotW / 2} y={H - 8} textAnchor="middle" fontSize={12} fill="#666">
        消费频率(次)
      </text>
      <text x={14} y={PAD.top + plotH / 2} textAnchor="middle" fontSize={12} fill="#666" transform={`rotate(-90,14,${PAD.top + plotH / 2})`}>
        消费金额(元)
      </text>
    </svg>
  );
}

/** 面积图：近12月增长 */
function GrowthAreaChart({ data }: { data: GrowthMonth[] }) {
  if (!data.length) return null;
  const W = 600;
  const H = 240;
  const PAD = { top: 20, right: 20, bottom: 40, left: 50 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const allVals = data.flatMap(d => [d.newCount, d.churnCount, d.netGrowth]);
  const maxV = Math.max(...allVals, 1);
  const minV = Math.min(...allVals, 0);
  const range = maxV - minV || 1;

  const toY = (v: number) => PAD.top + plotH - ((v - minV) / range) * plotH;
  const toX = (i: number) => PAD.left + (i / Math.max(data.length - 1, 1)) * plotW;

  const buildPath = (key: 'newCount' | 'churnCount' | 'netGrowth') =>
    data.map((d, i) => `${i === 0 ? 'M' : 'L'}${toX(i)},${toY(d[key])}`).join(' ');

  const buildArea = (key: 'newCount' | 'churnCount' | 'netGrowth') => {
    const line = buildPath(key);
    const baseY = toY(0);
    return `${line} L${toX(data.length - 1)},${baseY} L${toX(0)},${baseY} Z`;
  };

  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      <defs>
        <linearGradient id="newGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#52c41a" stopOpacity={0.3} />
          <stop offset="100%" stopColor="#52c41a" stopOpacity={0.02} />
        </linearGradient>
        <linearGradient id="churnGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ff4d4f" stopOpacity={0.3} />
          <stop offset="100%" stopColor="#ff4d4f" stopOpacity={0.02} />
        </linearGradient>
      </defs>
      {/* Grid */}
      {[0, 0.25, 0.5, 0.75, 1].map(r => {
        const v = minV + r * range;
        const y = toY(v);
        return (
          <g key={r}>
            <line x1={PAD.left} y1={y} x2={PAD.left + plotW} y2={y} stroke="#f0f0f0" />
            <text x={PAD.left - 8} y={y + 4} textAnchor="end" fontSize={10} fill="#999">
              {Math.round(v)}
            </text>
          </g>
        );
      })}
      {/* Areas */}
      <path d={buildArea('newCount')} fill="url(#newGrad)" />
      <path d={buildArea('churnCount')} fill="url(#churnGrad)" />
      {/* Lines */}
      <path d={buildPath('newCount')} fill="none" stroke="#52c41a" strokeWidth={2} />
      <path d={buildPath('churnCount')} fill="none" stroke="#ff4d4f" strokeWidth={2} />
      <path d={buildPath('netGrowth')} fill="none" stroke="#FF6B35" strokeWidth={2} strokeDasharray="6,3" />
      {/* X labels */}
      {data.map((d, i) => (
        <text key={i} x={toX(i)} y={H - 8} textAnchor="middle" fontSize={9} fill="#999">
          {d.month.slice(5)}
        </text>
      ))}
      {/* Legend */}
      <circle cx={PAD.left + plotW - 200} cy={10} r={4} fill="#52c41a" />
      <text x={PAD.left + plotW - 192} y={14} fontSize={10} fill="#666">新增</text>
      <circle cx={PAD.left + plotW - 150} cy={10} r={4} fill="#ff4d4f" />
      <text x={PAD.left + plotW - 142} y={14} fontSize={10} fill="#666">流失</text>
      <circle cx={PAD.left + plotW - 100} cy={10} r={4} fill="#FF6B35" />
      <text x={PAD.left + plotW - 92} y={14} fontSize={10} fill="#666">净增长</text>
    </svg>
  );
}

/** 饼图(SVG arc): 渠道来源 */
function ChannelPieChart({ data }: { data: ChannelSource[] }) {
  const W = 280;
  const H = 280;
  const cx = W / 2;
  const cy = H / 2 - 10;
  const R = 100;
  const colors = ['#FF6B35', '#1890ff', '#52c41a', '#faad14'];

  let startAngle = -Math.PI / 2;
  const slices = data.map((d, i) => {
    const angle = (d.percent / 100) * 2 * Math.PI;
    const endAngle = startAngle + angle;
    const largeArc = angle > Math.PI ? 1 : 0;
    const x1 = cx + R * Math.cos(startAngle);
    const y1 = cy + R * Math.sin(startAngle);
    const x2 = cx + R * Math.cos(endAngle);
    const y2 = cy + R * Math.sin(endAngle);
    const midAngle = startAngle + angle / 2;
    const labelR = R + 20;
    const lx = cx + labelR * Math.cos(midAngle);
    const ly = cy + labelR * Math.sin(midAngle);
    const path = `M${cx},${cy} L${x1},${y1} A${R},${R} 0 ${largeArc},1 ${x2},${y2} Z`;
    startAngle = endAngle;
    return { path, color: colors[i % colors.length], lx, ly, d };
  });

  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      {slices.map((s, i) => (
        <g key={i}>
          <path d={s.path} fill={s.color} fillOpacity={0.85} stroke="#fff" strokeWidth={2} />
          <text x={s.lx} y={s.ly} textAnchor="middle" fontSize={10} fill="#333">
            {s.d.channel}
          </text>
          <text x={s.lx} y={s.ly + 13} textAnchor="middle" fontSize={9} fill="#999">
            {s.d.percent}%
          </text>
        </g>
      ))}
    </svg>
  );
}

/** 留存率漏斗 */
function RetentionFunnel({ data }: { data: RetentionStep[] }) {
  const W = 400;
  const H = 200;
  const barH = 36;
  const gap = 8;
  const maxW = W - 100;

  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      {data.map((d, i) => {
        const bw = (d.rate / 100) * maxW;
        const x = (maxW - bw) / 2 + 80;
        const y = i * (barH + gap) + 10;
        const opacity = 1 - i * 0.15;
        return (
          <g key={i}>
            <rect x={x} y={y} width={bw} height={barH} rx={4} fill="#FF6B35" fillOpacity={opacity} />
            <text x={70} y={y + barH / 2 + 4} textAnchor="end" fontSize={12} fill="#333">
              {d.label}
            </text>
            <text x={x + bw / 2} y={y + barH / 2 + 5} textAnchor="middle" fontSize={13} fontWeight={600} fill="#fff">
              {d.rate}%
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────

export function MemberProfilePage() {
  const [stats, setStats] = useState<MemberStat | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('list');

  // Tab1 state
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [memberDetail, setMemberDetail] = useState<MemberDetail | null>(null);
  const tableRef = useRef<ActionType>(null);

  // Tab2 state
  const [rfmPoints, setRfmPoints] = useState<RFMPoint[]>([]);
  const [rfmQuadrants, setRfmQuadrants] = useState<RFMQuadrant[]>([]);
  const [rfmLoading, setRfmLoading] = useState(false);
  const [selectedQuadrant, setSelectedQuadrant] = useState<string | null>(null);

  // Tab3 state
  const [growthData, setGrowthData] = useState<GrowthMonth[]>([]);
  const [channels, setChannels] = useState<ChannelSource[]>([]);
  const [retention, setRetention] = useState<RetentionStep[]>([]);
  const [growthLoading, setGrowthLoading] = useState(false);

  // Fetch stats on mount
  useEffect(() => {
    setLoading(true);
    fetchStats().then(s => {
      setStats(s);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  // Fetch RFM when tab switches
  useEffect(() => {
    if (activeTab === 'rfm' && rfmPoints.length === 0) {
      setRfmLoading(true);
      fetchRFMData().then(d => {
        setRfmPoints(d.points);
        setRfmQuadrants(d.quadrants);
        setRfmLoading(false);
      }).catch(() => setRfmLoading(false));
    }
  }, [activeTab, rfmPoints.length]);

  // Fetch growth when tab switches
  useEffect(() => {
    if (activeTab === 'growth' && growthData.length === 0) {
      setGrowthLoading(true);
      fetchGrowthData().then(d => {
        setGrowthData(d.growth);
        setChannels(d.channels);
        setRetention(d.retention);
        setGrowthLoading(false);
      }).catch(() => setGrowthLoading(false));
    }
  }, [activeTab, growthData.length]);

  const openDetail = useCallback(async (id: string) => {
    setDrawerOpen(true);
    setDetailLoading(true);
    try {
      const detail = await fetchMemberDetail(id);
      setMemberDetail(detail);
    } catch (err: unknown) {
      message.error('加载会员详情失败');
      console.error(err);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const handleQuadrantClick = useCallback((quadrant: string) => {
    setSelectedQuadrant(prev => prev === quadrant ? null : quadrant);
  }, []);

  const filteredQuadrantMembers = useMemo(() => {
    if (!selectedQuadrant) return [];
    return rfmPoints.filter(p => p.quadrant === selectedQuadrant);
  }, [selectedQuadrant, rfmPoints]);

  // ── ProTable columns
  const columns: ProColumns<MemberRow>[] = [
    {
      title: '会员名',
      dataIndex: 'name',
      width: 100,
    },
    {
      title: '手机',
      dataIndex: 'phone',
      width: 120,
      search: false,
    },
    {
      title: '等级',
      dataIndex: 'level',
      width: 100,
      valueEnum: {
        normal: { text: '普通' },
        silver: { text: '银卡' },
        gold: { text: '金卡' },
        diamond: { text: '钻石' },
      },
    },
    {
      title: '总消费(元)',
      dataIndex: 'totalSpendYuan',
      width: 110,
      sorter: true,
      search: false,
      render: (_: unknown, row: MemberRow) => `¥${row.totalSpendYuan.toLocaleString()}`,
    },
    {
      title: '最近消费日',
      dataIndex: 'lastVisit',
      width: 120,
      search: false,
    },
    {
      title: '消费频次',
      dataIndex: 'frequency',
      width: 90,
      sorter: true,
      search: false,
      render: (_: unknown, row: MemberRow) => `${row.frequency}次`,
    },
    {
      title: 'RFM标签',
      dataIndex: 'rfmTag',
      width: 110,
      valueEnum: {
        high_value: { text: '高价值' },
        important_develop: { text: '重要发展' },
        general_maintain: { text: '一般维护' },
        churn_risk: { text: '流失预警' },
      },
      render: (_: unknown, row: MemberRow) => {
        const cfg = RFM_TAG_CONFIG[row.rfmTag];
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '操作',
      width: 80,
      search: false,
      render: (_: unknown, row: MemberRow) => (
        <Button
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => openDetail(row.id)}
        >
          画像
        </Button>
      ),
    },
  ];

  // ── Render
  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>会员画像与CDP分析</Title>

      {/* 顶部统计卡片 */}
      <Spin spinning={loading}>
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="总会员数"
                value={stats?.total ?? 0}
                prefix={<TeamOutlined style={{ color: '#FF6B35' }} />}
                valueStyle={{ color: '#FF6B35' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="活跃会员(30天)"
                value={stats?.active ?? 0}
                prefix={<FireOutlined style={{ color: '#52c41a' }} />}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="沉睡会员(>90天)"
                value={stats?.sleeping ?? 0}
                prefix={<UserOutlined style={{ color: '#999' }} />}
                valueStyle={{ color: '#999' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="本月新增"
                value={stats?.newThisMonth ?? 0}
                prefix={<UserAddOutlined style={{ color: '#1890ff' }} />}
                valueStyle={{ color: '#1890ff' }}
              />
            </Card>
          </Col>
        </Row>
      </Spin>

      {/* Tab区域 */}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'list',
            label: '会员列表',
            children: (
              <>
                <ProTable<MemberRow>
                  actionRef={tableRef}
                  columns={columns}
                  rowKey="id"
                  search={{
                    labelWidth: 'auto',
                  }}
                  request={async (params) => {
                    const { current = 1, pageSize = 20, name, level, rfmTag } = params;
                    const result = await fetchMembers(current, pageSize, {
                      keyword: (name as string) || '',
                      level: (level as string) || '',
                      rfmTag: (rfmTag as string) || '',
                    });
                    return {
                      data: result.items,
                      total: result.total,
                      success: true,
                    };
                  }}
                  pagination={{ pageSize: 20, showSizeChanger: true }}
                  dateFormatter="string"
                  headerTitle="会员列表"
                  options={{ density: true, reload: true }}
                />
              </>
            ),
          },
          {
            key: 'rfm',
            label: 'RFM分析',
            children: (
              <Spin spinning={rfmLoading}>
                <Row gutter={24}>
                  <Col span={16}>
                    <Card title="RFM四象限散点图" style={{ marginBottom: 16 }}>
                      <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                        点击象限查看该类会员 | 点大小=最近消费时间(越大越近)
                      </Text>
                      <RFMScatterChart points={rfmPoints} onQuadrantClick={handleQuadrantClick} />
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card title="象限分布" style={{ marginBottom: 16 }}>
                      {rfmQuadrants.map(q => (
                        <div
                          key={q.label}
                          style={{
                            padding: '12px 16px',
                            marginBottom: 8,
                            borderRadius: 8,
                            background: selectedQuadrant === q.label ? '#fff7e6' : '#fafafa',
                            border: selectedQuadrant === q.label ? '1px solid #FF6B35' : '1px solid #f0f0f0',
                            cursor: 'pointer',
                          }}
                          onClick={() => handleQuadrantClick(q.label)}
                        >
                          <Text strong>{q.label}</Text>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                            <Text>{q.count} 人</Text>
                            <Text type="secondary">{q.percent}%</Text>
                          </div>
                        </div>
                      ))}
                    </Card>
                  </Col>
                </Row>
                {/* 象限会员列表 */}
                {selectedQuadrant && (
                  <Card title={`${selectedQuadrant}会员列表 (${filteredQuadrantMembers.length}人)`} style={{ marginTop: 16 }}>
                    <ProTable<RFMPoint>
                      columns={[
                        { title: 'ID', dataIndex: 'id', width: 100 },
                        { title: '会员名', dataIndex: 'name', width: 100 },
                        { title: '消费频率', dataIndex: 'frequency', width: 100, render: (_: unknown, r: RFMPoint) => `${r.frequency}次` },
                        { title: '消费金额', dataIndex: 'monetary', width: 120, render: (_: unknown, r: RFMPoint) => `¥${r.monetary.toLocaleString()}` },
                        { title: '最近消费(天)', dataIndex: 'recency', width: 120, render: (_: unknown, r: RFMPoint) => `${r.recency}天前` },
                      ]}
                      dataSource={filteredQuadrantMembers}
                      rowKey="id"
                      search={false}
                      pagination={{ pageSize: 10 }}
                      options={false}
                      toolBarRender={false}
                    />
                  </Card>
                )}
              </Spin>
            ),
          },
          {
            key: 'growth',
            label: '会员增长',
            children: (
              <Spin spinning={growthLoading}>
                <Card title="近12月新增/流失/净增长" style={{ marginBottom: 24 }}>
                  <GrowthAreaChart data={growthData} />
                </Card>
                <Row gutter={24}>
                  <Col span={12}>
                    <Card title="渠道来源分布">
                      <ChannelPieChart data={channels} />
                    </Card>
                  </Col>
                  <Col span={12}>
                    <Card title="留存率漏斗">
                      <RetentionFunnel data={retention} />
                    </Card>
                  </Col>
                </Row>
              </Spin>
            ),
          },
        ]}
      />

      {/* 会员画像Drawer */}
      <Drawer
        title="会员画像"
        width={640}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
      >
        <Spin spinning={detailLoading}>
          {memberDetail && (
            <div>
              {/* 基本信息 */}
              <Card title="基本信息" size="small" style={{ marginBottom: 16 }}>
                <Descriptions column={2} size="small">
                  <Descriptions.Item label="姓名">{memberDetail.name}</Descriptions.Item>
                  <Descriptions.Item label="手机">{memberDetail.phone}</Descriptions.Item>
                  <Descriptions.Item label="性别">{memberDetail.gender}</Descriptions.Item>
                  <Descriptions.Item label="等级">
                    <Tag color="gold">{memberDetail.level}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="注册日期">{memberDetail.joinDate}</Descriptions.Item>
                  <Descriptions.Item label="生日">{memberDetail.birthday}</Descriptions.Item>
                </Descriptions>
              </Card>

              {/* 消费偏好 */}
              <Card title="消费偏好" size="small" style={{ marginBottom: 16 }}>
                <div style={{ marginBottom: 12 }}>
                  <Text strong style={{ display: 'block', marginBottom: 4 }}>最常点菜品 TOP5</Text>
                  <Space wrap>
                    {memberDetail.preference.topDishes.map((d, i) => (
                      <Tag key={i} color={i < 3 ? '#FF6B35' : 'default'}>
                        {d.name} ({d.count}次)
                      </Tag>
                    ))}
                  </Space>
                </div>
                <div style={{ marginBottom: 12 }}>
                  <Text strong style={{ display: 'block', marginBottom: 4 }}>偏好口味</Text>
                  <Space>
                    {memberDetail.preference.flavorTags.map((f, i) => (
                      <Tag key={i} color="orange">{f}</Tag>
                    ))}
                  </Space>
                </div>
                <div>
                  <Text strong>平均客单价: </Text>
                  <Text style={{ color: '#FF6B35', fontSize: 16, fontWeight: 600 }}>
                    ¥{memberDetail.preference.avgSpendYuan}
                  </Text>
                </div>
              </Card>

              {/* 消费趋势 */}
              <Card title="近12月消费趋势" size="small" style={{ marginBottom: 16 }}>
                <SpendTrendChart data={memberDetail.spendTrend} />
              </Card>

              {/* 会员历程 */}
              <Card title="会员历程" size="small">
                <Timeline
                  items={memberDetail.timeline.map(t => ({
                    color: '#FF6B35',
                    children: (
                      <div>
                        <Text type="secondary" style={{ fontSize: 12 }}>{t.time}</Text>
                        <br />
                        <Text>{t.event}</Text>
                      </div>
                    ),
                  }))}
                />
              </Card>
            </div>
          )}
        </Spin>
      </Drawer>
    </div>
  );
}
