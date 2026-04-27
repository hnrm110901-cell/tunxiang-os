/**
 * Workspace: Services — 微服务管理工作区
 *
 * 左侧列表 + 右侧 Object Page (8 Tab) + Service Map 视图切换
 */
import { useState, useEffect, useMemo } from 'react';
import { hubGet } from '../api/hubApi';

// ── 颜色常量 ──
const C = {
  bg: '#0A1418', surface: '#0E1E24', surface2: '#132932', surface3: '#1A3540',
  border: '#1A3540', border2: '#23485a',
  text: '#E6EDF1', text2: '#94A8B3', text3: '#647985',
  orange: '#FF6B2C', green: '#22C55E', yellow: '#F59E0B', red: '#EF4444', blue: '#3B82F6',
  purple: '#A855F7',
};

// ── 类型 ──

type SvcHealth = 'healthy' | 'degraded' | 'error';

interface SLOItem {
  name: string;
  target: number;
  current: number;
}

interface ServiceDep {
  name: string;
  port: number;
  direction: 'upstream' | 'downstream';
}

interface ServiceItem {
  name: string;
  port: number;
  health: SvcHealth;
  git_path: string;
  version: string;
  deploy_time: string;
  availability: number;
  p95_latency_ms: number;
  error_rate: number;
  qps: number;
  slo: SLOItem[];
  deps: ServiceDep[];
}

interface TimelineEvent {
  id: string;
  time: string;
  type: 'deploy' | 'alert' | 'slo_breach';
  description: string;
}

// ── Mock 数据 ──

const slo = (a: number, p: number, e: number): SLOItem[] => [
  { name: '可用性', target: 99.9, current: a },
  { name: 'P95延迟', target: 200, current: p },
  { name: '错误率', target: 0.1, current: e },
];

const deps = (up: string[], down: string[]): ServiceDep[] => [
  ...up.map(n => ({ name: n.split(':')[0], port: Number(n.split(':')[1] || 0), direction: 'upstream' as const })),
  ...down.map(n => ({ name: n.split(':')[0], port: Number(n.split(':')[1] || 0), direction: 'downstream' as const })),
];

const MOCK_SERVICES: ServiceItem[] = [
  { name: 'gateway', port: 8000, health: 'healthy', git_path: 'services/gateway', version: '3.3.0', deploy_time: '2026-04-25 10:00', availability: 99.99, p95_latency_ms: 8, error_rate: 0.01, qps: 1200, slo: slo(99.99, 8, 0.01), deps: deps([], ['tx-trade:8001', 'tx-menu:8002', 'tx-member:8003', 'tx-growth:8004', 'tx-ops:8005', 'tx-supply:8006', 'tx-finance:8007', 'tx-agent:8008', 'tx-analytics:8009', 'tx-brain:8010', 'tx-intel:8011', 'tx-org:8012', 'tx-civic:8014']) },
  { name: 'tx-trade', port: 8001, health: 'healthy', git_path: 'services/tx-trade', version: '3.3.0', deploy_time: '2026-04-25 10:05', availability: 99.97, p95_latency_ms: 45, error_rate: 0.02, qps: 850, slo: slo(99.97, 45, 0.02), deps: deps(['gateway:8000'], ['tx-menu:8002', 'tx-member:8003', 'tx-finance:8007']) },
  { name: 'tx-menu', port: 8002, health: 'healthy', git_path: 'services/tx-menu', version: '3.3.0', deploy_time: '2026-04-25 10:05', availability: 99.98, p95_latency_ms: 32, error_rate: 0.01, qps: 420, slo: slo(99.98, 32, 0.01), deps: deps(['gateway:8000', 'tx-trade:8001'], ['tx-supply:8006']) },
  { name: 'tx-member', port: 8003, health: 'healthy', git_path: 'services/tx-member', version: '3.3.0', deploy_time: '2026-04-25 10:06', availability: 99.95, p95_latency_ms: 55, error_rate: 0.03, qps: 310, slo: slo(99.95, 55, 0.03), deps: deps(['gateway:8000', 'tx-trade:8001'], ['tx-growth:8004']) },
  { name: 'tx-growth', port: 8004, health: 'healthy', git_path: 'services/tx-growth', version: '3.3.0', deploy_time: '2026-04-25 10:07', availability: 99.96, p95_latency_ms: 68, error_rate: 0.02, qps: 180, slo: slo(99.96, 68, 0.02), deps: deps(['gateway:8000', 'tx-member:8003'], []) },
  { name: 'tx-ops', port: 8005, health: 'healthy', git_path: 'services/tx-ops', version: '3.3.0', deploy_time: '2026-04-25 10:08', availability: 99.98, p95_latency_ms: 28, error_rate: 0.01, qps: 95, slo: slo(99.98, 28, 0.01), deps: deps(['gateway:8000'], ['tx-supply:8006']) },
  { name: 'tx-supply', port: 8006, health: 'degraded', git_path: 'services/tx-supply', version: '3.2.9', deploy_time: '2026-04-24 16:00', availability: 99.50, p95_latency_ms: 180, error_rate: 0.08, qps: 145, slo: slo(99.50, 180, 0.08), deps: deps(['gateway:8000', 'tx-menu:8002', 'tx-ops:8005'], []) },
  { name: 'tx-finance', port: 8007, health: 'healthy', git_path: 'services/tx-finance', version: '3.3.0', deploy_time: '2026-04-25 10:09', availability: 99.99, p95_latency_ms: 42, error_rate: 0.01, qps: 78, slo: slo(99.99, 42, 0.01), deps: deps(['gateway:8000', 'tx-trade:8001'], []) },
  { name: 'tx-agent', port: 8008, health: 'healthy', git_path: 'services/tx-agent', version: '3.3.0', deploy_time: '2026-04-25 10:10', availability: 99.92, p95_latency_ms: 120, error_rate: 0.04, qps: 230, slo: slo(99.92, 120, 0.04), deps: deps(['gateway:8000'], ['tx-brain:8010']) },
  { name: 'tx-analytics', port: 8009, health: 'healthy', git_path: 'services/tx-analytics', version: '3.3.0', deploy_time: '2026-04-25 10:11', availability: 99.97, p95_latency_ms: 95, error_rate: 0.02, qps: 65, slo: slo(99.97, 95, 0.02), deps: deps(['gateway:8000'], ['tx-intel:8011']) },
  { name: 'tx-brain', port: 8010, health: 'healthy', git_path: 'services/tx-brain', version: '3.3.0', deploy_time: '2026-04-25 10:12', availability: 99.90, p95_latency_ms: 350, error_rate: 0.05, qps: 45, slo: slo(99.90, 350, 0.05), deps: deps(['tx-agent:8008'], []) },
  { name: 'tx-intel', port: 8011, health: 'healthy', git_path: 'services/tx-intel', version: '3.3.0', deploy_time: '2026-04-25 10:13', availability: 99.95, p95_latency_ms: 78, error_rate: 0.02, qps: 35, slo: slo(99.95, 78, 0.02), deps: deps(['tx-analytics:8009'], []) },
  { name: 'tx-org', port: 8012, health: 'healthy', git_path: 'services/tx-org', version: '3.3.0', deploy_time: '2026-04-25 10:14', availability: 99.98, p95_latency_ms: 35, error_rate: 0.01, qps: 55, slo: slo(99.98, 35, 0.01), deps: deps(['gateway:8000'], []) },
  { name: 'tx-civic', port: 8014, health: 'degraded', git_path: 'services/tx-civic', version: '3.2.9', deploy_time: '2026-04-24 14:00', availability: 99.60, p95_latency_ms: 210, error_rate: 0.07, qps: 12, slo: slo(99.60, 210, 0.07), deps: deps(['gateway:8000'], []) },
  { name: 'mcp-server', port: 0, health: 'error', git_path: 'services/mcp-server', version: '3.2.8', deploy_time: '2026-04-23 09:00', availability: 95.00, p95_latency_ms: 500, error_rate: 2.50, qps: 3, slo: slo(95.00, 500, 2.50), deps: deps([], []) },
];

const MOCK_TIMELINE: TimelineEvent[] = [
  { id: 'te1', time: '2026-04-25 10:15', type: 'deploy', description: '部署 v3.3.0 完成（12 个服务）' },
  { id: 'te2', time: '2026-04-25 10:30', type: 'alert', description: 'tx-supply P95延迟升高至 180ms' },
  { id: 'te3', time: '2026-04-24 16:00', type: 'deploy', description: 'tx-supply 紧急回滚至 v3.2.9' },
  { id: 'te4', time: '2026-04-24 14:00', type: 'slo_breach', description: 'tx-civic 可用性低于 99.9% SLO' },
  { id: 'te5', time: '2026-04-23 09:00', type: 'alert', description: 'mcp-server 启动失败，错误率 2.5%' },
];

// ── 常量 ──

const HEALTH_COLOR: Record<SvcHealth, string> = { healthy: C.green, degraded: C.yellow, error: C.red };
const HEALTH_LABEL: Record<SvcHealth, string> = { healthy: '健康', degraded: '降级', error: '异常' };

type FilterKey = 'all' | SvcHealth;
type TabKey = 'overview' | 'timeline' | 'actions' | 'traces' | 'cost' | 'logs' | 'related' | 'playbooks';
type ViewMode = 'list' | 'map';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'actions', label: 'Actions' },
  { key: 'traces', label: 'Traces' },
  { key: 'cost', label: 'Cost' },
  { key: 'logs', label: 'Logs' },
  { key: 'related', label: 'Related' },
  { key: 'playbooks', label: 'Playbooks' },
];

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'healthy', label: '健康' },
  { key: 'degraded', label: '降级' },
  { key: 'error', label: '异常' },
];

// ── Helpers ──

function Placeholder({ label }: { label: string }) {
  return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200, color: C.text3, fontSize: 14 }}>{label}</div>;
}

function MetricCard({ label, value, unit, color }: { label: string; value: string | number; unit?: string; color: string }) {
  return (
    <div style={{ flex: '1 1 140px', background: C.surface2, borderRadius: 8, padding: 12, border: `1px solid ${C.border}` }}>
      <div style={{ fontSize: 11, color: C.text3, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>
        {value}<span style={{ fontSize: 12, fontWeight: 400, marginLeft: 2 }}>{unit}</span>
      </div>
    </div>
  );
}

// ── Overview Tab ──

function SvcOverviewTab({ svc }: { svc: ServiceItem }) {
  const availColor = svc.availability >= 99.9 ? C.green : svc.availability >= 99 ? C.yellow : C.red;
  const latColor = svc.p95_latency_ms <= 100 ? C.green : svc.p95_latency_ms <= 200 ? C.yellow : C.red;
  const errColor = svc.error_rate <= 0.05 ? C.green : svc.error_rate <= 0.5 ? C.yellow : C.red;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 服务信息 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>服务信息</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px 24px', fontSize: 13 }}>
          {([
            ['名称', svc.name], ['端口', `:${svc.port}`], ['Git路径', svc.git_path],
            ['当前版本', svc.version], ['部署时间', svc.deploy_time], ['健康状态', HEALTH_LABEL[svc.health]],
          ] as const).map(([label, val]) => (
            <div key={label}>
              <div style={{ color: C.text3, fontSize: 11, marginBottom: 2 }}>{label}</div>
              <div style={{ color: label === '健康状态' ? HEALTH_COLOR[svc.health] : C.text, fontWeight: label === '健康状态' ? 600 : 400 }}>{val}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 健康指标 */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <MetricCard label="可用性" value={svc.availability.toFixed(2)} unit="%" color={availColor} />
        <MetricCard label="P95 延迟" value={svc.p95_latency_ms} unit="ms" color={latColor} />
        <MetricCard label="错误率" value={svc.error_rate.toFixed(2)} unit="%" color={errColor} />
        <MetricCard label="QPS" value={svc.qps} unit="/s" color={C.blue} />
      </div>

      {/* SLO 状态 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>SLO 状态</div>
        {svc.slo.map(s => {
          const isGood = s.name === '错误率' ? s.current <= s.target : s.name === 'P95延迟' ? s.current <= s.target : s.current >= s.target;
          const color = isGood ? C.green : C.red;
          const budgetPct = s.name === '可用性'
            ? Math.max(0, Math.min(100, ((s.current - s.target) / (100 - s.target)) * 100))
            : s.name === '错误率'
              ? Math.max(0, Math.min(100, ((s.target - s.current) / s.target) * 100))
              : Math.max(0, Math.min(100, ((s.target - s.current) / s.target) * 100));
          return (
            <div key={s.name} style={{ marginBottom: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                <span style={{ color: C.text2 }}>{s.name}</span>
                <span>
                  <span style={{ color }}>当前 {s.current}{s.name === '可用性' || s.name === '错误率' ? '%' : 'ms'}</span>
                  <span style={{ color: C.text3, marginLeft: 8 }}>目标 {s.target}{s.name === '可用性' || s.name === '错误率' ? '%' : 'ms'}</span>
                </span>
              </div>
              <div style={{ height: 6, borderRadius: 3, background: C.surface3, overflow: 'hidden' }}>
                <div style={{ width: `${Math.abs(budgetPct)}%`, height: '100%', borderRadius: 3, background: color, transition: 'width 0.3s' }} />
              </div>
            </div>
          );
        })}
      </div>

      {/* 上下游依赖 */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 240px', background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>上游（调用方）</div>
          {svc.deps.filter(d => d.direction === 'upstream').length === 0 ? (
            <div style={{ color: C.text3, fontSize: 12 }}>无上游依赖</div>
          ) : svc.deps.filter(d => d.direction === 'upstream').map(d => (
            <div key={d.name} style={{ padding: '6px 0', borderBottom: `1px solid ${C.border}`, fontSize: 13 }}>
              <span style={{ color: C.text, fontWeight: 600 }}>{d.name}</span>
              <span style={{ color: C.text3, marginLeft: 6 }}>:{d.port}</span>
            </div>
          ))}
        </div>
        <div style={{ flex: '1 1 240px', background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>下游（被调用）</div>
          {svc.deps.filter(d => d.direction === 'downstream').length === 0 ? (
            <div style={{ color: C.text3, fontSize: 12 }}>无下游依赖</div>
          ) : svc.deps.filter(d => d.direction === 'downstream').map(d => (
            <div key={d.name} style={{ padding: '6px 0', borderBottom: `1px solid ${C.border}`, fontSize: 13 }}>
              <span style={{ color: C.text, fontWeight: 600 }}>{d.name}</span>
              <span style={{ color: C.text3, marginLeft: 6 }}>:{d.port}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Timeline Tab ──

function SvcTimelineTab() {
  const EVENT_COLOR: Record<string, string> = { deploy: C.blue, alert: C.yellow, slo_breach: C.red };
  const EVENT_LABEL: Record<string, string> = { deploy: '部署', alert: '告警', slo_breach: 'SLO违约' };
  const EVENT_ICON: Record<string, string> = { deploy: '🚀', alert: '⚠️', slo_breach: '🔴' };

  return (
    <div style={{ position: 'relative', paddingLeft: 24 }}>
      <div style={{ position: 'absolute', left: 7, top: 4, bottom: 4, width: 2, background: C.border }} />
      {MOCK_TIMELINE.map((evt, i) => (
        <div key={evt.id} style={{ display: 'flex', gap: 12, marginBottom: i < MOCK_TIMELINE.length - 1 ? 20 : 0, position: 'relative' }}>
          <div style={{ position: 'absolute', left: -20, top: 2, width: 16, height: 16, borderRadius: 8, background: C.surface, border: `2px solid ${EVENT_COLOR[evt.type]}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9 }}>
            {EVENT_ICON[evt.type]}
          </div>
          <div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 2 }}>
              <span style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace' }}>{evt.time}</span>
              <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: EVENT_COLOR[evt.type] + '22', color: EVENT_COLOR[evt.type], fontWeight: 600 }}>{EVENT_LABEL[evt.type]}</span>
            </div>
            <div style={{ fontSize: 13, color: C.text }}>{evt.description}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Service Map (SVG) ──

interface MapNode { name: string; port: number; x: number; y: number; health: SvcHealth }

function ServiceMap({ services }: { services: ServiceItem[] }) {
  const W = 900;
  const H = 600;

  // 布局：分层
  const positions: Record<string, [number, number]> = {
    'gateway':       [450, 60],
    'tx-brain':      [280, 150], 'tx-agent': [620, 150],
    'tx-trade':      [100, 260], 'tx-menu': [240, 260], 'tx-member': [380, 260], 'tx-growth': [520, 260],
    'tx-ops':        [660, 260], 'tx-supply': [170, 360], 'tx-finance': [450, 360],
    'tx-analytics':  [100, 450], 'tx-intel': [280, 450], 'tx-org': [460, 450], 'tx-civic': [640, 450],
    'mcp-server':    [800, 150],
  };

  // 底层基础设施
  const infra: { name: string; x: number; y: number }[] = [
    { name: 'PostgreSQL', x: 250, y: 550 },
    { name: 'Redis', x: 450, y: 550 },
    { name: 'Claude API', x: 650, y: 550 },
  ];

  const nodes: MapNode[] = services.map(s => {
    const [x, y] = positions[s.name] || [450, 300];
    return { name: s.name, port: s.port, x, y, health: s.health };
  });

  // 连线：service deps
  const edges: { from: string; to: string }[] = [];
  for (const svc of services) {
    for (const dep of svc.deps.filter(d => d.direction === 'downstream')) {
      edges.push({ from: svc.name, to: dep.name });
    }
  }

  const getPos = (name: string): [number, number] => {
    const node = nodes.find(n => n.name === name);
    return node ? [node.x, node.y] : [450, 300];
  };

  return (
    <div style={{ background: C.surface, borderRadius: 12, padding: 20, border: `1px solid ${C.border}`, overflow: 'auto' }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', margin: '0 auto' }}>
        {/* 连线 */}
        {edges.map((e, i) => {
          const [x1, y1] = getPos(e.from);
          const [x2, y2] = getPos(e.to);
          return (
            <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={C.border2} strokeWidth={1.2} opacity={0.6}
            />
          );
        })}
        {/* 到基础设施的连线 */}
        {infra.map((inf, i) => (
          <line key={`inf-${i}`} x1={450} y1={450} x2={inf.x} y2={inf.y}
            stroke={C.border} strokeWidth={1} strokeDasharray="3,3" opacity={0.4}
          />
        ))}
        {/* 基础设施节点 */}
        {infra.map(inf => (
          <g key={inf.name}>
            <rect x={inf.x - 45} y={inf.y - 14} width={90} height={28} rx={6}
              fill={C.surface2} stroke={C.border2} strokeWidth={1}
            />
            <text x={inf.x} y={inf.y + 4} textAnchor="middle" fill={C.text3} fontSize={10}>{inf.name}</text>
          </g>
        ))}
        {/* 服务节点 */}
        {nodes.map(node => {
          const hColor = HEALTH_COLOR[node.health];
          return (
            <g key={node.name}>
              <rect x={node.x - 50} y={node.y - 16} width={100} height={32} rx={8}
                fill={C.surface2} stroke={hColor} strokeWidth={1.5}
              />
              <text x={node.x} y={node.y - 2} textAnchor="middle" fill={C.text} fontSize={10} fontWeight={600}>
                {node.name}
              </text>
              <text x={node.x} y={node.y + 10} textAnchor="middle" fill={C.text3} fontSize={8}>
                :{node.port}
              </text>
              {/* 状态点 */}
              <circle cx={node.x + 44} cy={node.y - 10} r={3} fill={hColor} />
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ── Main Export ──

export function ServicesWorkspace() {
  const [services, setServices] = useState<ServiceItem[]>(MOCK_SERVICES);
  const [selected, setSelected] = useState<ServiceItem | null>(null);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [tab, setTab] = useState<TabKey>('overview');
  const [view, setView] = useState<ViewMode>('list');

  useEffect(() => {
    hubGet<ServiceItem[]>('/services')
      .then(data => { if (Array.isArray(data) && data.length > 0) setServices(data); })
      .catch(() => { /* 使用 Mock */ });
  }, []);

  const filtered = useMemo(() => {
    if (filter === 'all') return services;
    return services.filter(s => s.health === filter);
  }, [services, filter]);

  const counts = useMemo(() => {
    const m: Record<string, number> = { all: services.length };
    for (const s of services) m[s.health] = (m[s.health] || 0) + 1;
    return m;
  }, [services]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', color: C.text }}>
      {/* 顶部栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 20, fontWeight: 700 }}>微服务</div>
        <div style={{ display: 'flex', gap: 6 }}>
          {(['list', 'map'] as const).map(v => (
            <button key={v} onClick={() => setView(v)} style={{
              background: view === v ? C.orange + '22' : 'transparent',
              color: view === v ? C.orange : C.text3,
              border: `1px solid ${view === v ? C.orange : C.border}`,
              borderRadius: 6, padding: '5px 14px', fontSize: 12, cursor: 'pointer', fontWeight: 600,
            }}>{v === 'list' ? '列表' : '地图'}</button>
          ))}
        </div>
      </div>

      {view === 'map' ? (
        <ServiceMap services={services} />
      ) : (
        <div style={{ display: 'flex', gap: 16, flex: 1, minHeight: 0 }}>
          {/* 左侧列表 */}
          <div style={{ width: 340, flexShrink: 0, display: 'flex', flexDirection: 'column', background: C.surface, borderRadius: 10, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
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
            <div style={{ flex: 1, overflowY: 'auto' }}>
              {filtered.map(svc => {
                const isActive = selected?.name === svc.name;
                return (
                  <div key={svc.name} onClick={() => { setSelected(svc); setTab('overview'); }} style={{
                    padding: '10px 14px', cursor: 'pointer',
                    borderLeft: isActive ? `3px solid ${C.orange}` : '3px solid transparent',
                    background: isActive ? C.orange + '0D' : 'transparent',
                    borderBottom: `1px solid ${C.border}`,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <span style={{ width: 8, height: 8, borderRadius: 4, background: HEALTH_COLOR[svc.health], flexShrink: 0 }} />
                      <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{svc.name}</span>
                      <span style={{ fontSize: 11, color: C.text3 }}>:{svc.port}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: C.text3 }}>
                      <span>SLO {svc.availability.toFixed(1)}%</span>
                      <span>{svc.deploy_time.split(' ')[0]}</span>
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
                选择一个微服务查看详情
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 5, background: HEALTH_COLOR[selected.health] }} />
                  <span style={{ fontSize: 16, fontWeight: 700, color: C.text }}>{selected.name}</span>
                  <span style={{ fontSize: 12, color: C.text3 }}>:{selected.port}</span>
                  <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: HEALTH_COLOR[selected.health] + '22', color: HEALTH_COLOR[selected.health], fontWeight: 600 }}>
                    {HEALTH_LABEL[selected.health]}
                  </span>
                </div>
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
                <div style={{ flex: 1, overflowY: 'auto' }}>
                  {tab === 'overview' && <SvcOverviewTab svc={selected} />}
                  {tab === 'timeline' && <SvcTimelineTab />}
                  {tab === 'actions' && <Placeholder label="操作面板接入中" />}
                  {tab === 'traces' && <Placeholder label="Trace 数据接入中" />}
                  {tab === 'cost' && <Placeholder label="成本数据接入中" />}
                  {tab === 'logs' && <Placeholder label="日志接入中" />}
                  {tab === 'related' && <Placeholder label="关联对象列表" />}
                  {tab === 'playbooks' && <Placeholder label="关联剧本列表" />}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
