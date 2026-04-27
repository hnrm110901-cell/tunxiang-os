/**
 * Workspace: Edges — 边缘节点管理（替代 v1 DeploymentPage）
 *
 * 左侧列表 + 右侧 Object Page (8 Tab) + 拓扑视图切换
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { hubGet, hubPost } from '../api/hubApi';

// ── 颜色常量 ──
const C = {
  bg: '#0A1418', surface: '#0E1E24', surface2: '#132932', surface3: '#1A3540',
  border: '#1A3540', border2: '#23485a',
  text: '#E6EDF1', text2: '#94A8B3', text3: '#647985',
  orange: '#FF6B2C', green: '#22C55E', yellow: '#F59E0B', red: '#EF4444', blue: '#3B82F6',
};

// ── 类型定义 ──

type EdgeStatus = 'online' | 'offline' | 'updating' | 'quarantine';

interface EdgeNode {
  sn: string;
  model: string;
  macos_version: string;
  tailscale_ip: string;
  merchant_name: string;
  store_name: string;
  status: EdgeStatus;
  latency_ms: number;
  version: string;
  heartbeat_interval: number;
  cpu_pct: number;
  mem_pct: number;
  disk_pct: number;
  services: EdgeService[];
  coreml_queue: CoreMLQueueItem[];
  recent_events: EdgeEvent[];
}

interface EdgeService {
  name: string;
  status: 'running' | 'stopped' | 'error';
  uptime: string;
  port: number;
}

interface CoreMLQueueItem {
  agent: string;
  pending: number;
  avg_latency_ms: number;
  status: 'idle' | 'busy' | 'backlog';
}

interface EdgeEvent {
  id: string;
  time: string;
  type: 'online' | 'offline' | 'update' | 'alert' | 'rollback' | 'maintenance';
  description: string;
}

interface TimelineEvent extends EdgeEvent {
  icon: string;
}

// ── Mock 数据 ──

const MOCK_COREML_QUEUE: CoreMLQueueItem[] = [
  { agent: '折扣守护', pending: 0, avg_latency_ms: 12, status: 'idle' },
  { agent: '智能排菜', pending: 2, avg_latency_ms: 45, status: 'busy' },
  { agent: '出餐调度', pending: 0, avg_latency_ms: 23, status: 'idle' },
  { agent: '会员洞察', pending: 1, avg_latency_ms: 120, status: 'busy' },
  { agent: '库存预警', pending: 0, avg_latency_ms: 35, status: 'idle' },
  { agent: '财务稽核', pending: 3, avg_latency_ms: 89, status: 'backlog' },
  { agent: '巡店质检', pending: 0, avg_latency_ms: 67, status: 'idle' },
  { agent: '私域运营', pending: 1, avg_latency_ms: 210, status: 'busy' },
  { agent: '智能客服', pending: 0, avg_latency_ms: 150, status: 'idle' },
];

const MOCK_SERVICES: EdgeService[] = [
  { name: 'mac-station', status: 'running', uptime: '7d 12h', port: 8000 },
  { name: 'coreml-bridge', status: 'running', uptime: '7d 12h', port: 8100 },
  { name: 'sync-engine', status: 'running', uptime: '7d 11h', port: 8200 },
];

const MOCK_EVENTS: EdgeEvent[] = [
  { id: 'ev1', time: '2026-04-26 08:00', type: 'online', description: '节点上线，版本 3.3.0' },
  { id: 'ev2', time: '2026-04-25 22:15', type: 'update', description: '推送更新 3.2.9 → 3.3.0 成功' },
  { id: 'ev3', time: '2026-04-25 18:00', type: 'alert', description: 'CPU 使用率超过 85%' },
  { id: 'ev4', time: '2026-04-24 09:30', type: 'maintenance', description: '计划维护，重启 sync-engine' },
  { id: 'ev5', time: '2026-04-23 14:00', type: 'online', description: '断网恢复后重新上线' },
];

const MOCK_EDGES: EdgeNode[] = [
  { sn: 'TX-MAC-001', model: 'Mac mini M4', macos_version: 'macOS 15.3', tailscale_ip: '100.64.1.10', merchant_name: '湘粤楼', store_name: '芙蓉路店', status: 'online', latency_ms: 12, version: '3.3.0', heartbeat_interval: 30, cpu_pct: 23, mem_pct: 45, disk_pct: 32, services: MOCK_SERVICES, coreml_queue: MOCK_COREML_QUEUE, recent_events: MOCK_EVENTS },
  { sn: 'TX-MAC-002', model: 'Mac mini M4', macos_version: 'macOS 15.3', tailscale_ip: '100.64.1.11', merchant_name: '湘粤楼', store_name: '万家丽店', status: 'online', latency_ms: 18, version: '3.3.0', heartbeat_interval: 30, cpu_pct: 31, mem_pct: 52, disk_pct: 28, services: MOCK_SERVICES, coreml_queue: MOCK_COREML_QUEUE, recent_events: MOCK_EVENTS },
  { sn: 'TX-MAC-003', model: 'Mac mini M4', macos_version: 'macOS 15.2', tailscale_ip: '100.64.1.12', merchant_name: '徐记海鲜', store_name: '五一广场店', status: 'online', latency_ms: 8, version: '3.3.0', heartbeat_interval: 30, cpu_pct: 45, mem_pct: 67, disk_pct: 41, services: MOCK_SERVICES, coreml_queue: MOCK_COREML_QUEUE, recent_events: MOCK_EVENTS },
  { sn: 'TX-MAC-004', model: 'Mac mini M4', macos_version: 'macOS 15.3', tailscale_ip: '100.64.1.13', merchant_name: '徐记海鲜', store_name: '梅溪湖店', status: 'online', latency_ms: 15, version: '3.2.9', heartbeat_interval: 30, cpu_pct: 18, mem_pct: 38, disk_pct: 25, services: MOCK_SERVICES, coreml_queue: MOCK_COREML_QUEUE, recent_events: MOCK_EVENTS },
  { sn: 'TX-MAC-005', model: 'Mac mini M4', macos_version: 'macOS 15.3', tailscale_ip: '100.64.1.14', merchant_name: '尝在一起', store_name: '天心区店', status: 'online', latency_ms: 22, version: '3.3.0', heartbeat_interval: 30, cpu_pct: 55, mem_pct: 71, disk_pct: 38, services: MOCK_SERVICES, coreml_queue: MOCK_COREML_QUEUE, recent_events: MOCK_EVENTS },
  { sn: 'TX-MAC-006', model: 'Mac mini M4', macos_version: 'macOS 15.2', tailscale_ip: '100.64.1.15', merchant_name: '最黔线', store_name: '开福区店', status: 'offline', latency_ms: -1, version: '3.2.9', heartbeat_interval: 30, cpu_pct: 0, mem_pct: 0, disk_pct: 35, services: [{ name: 'mac-station', status: 'stopped', uptime: '-', port: 8000 }, { name: 'coreml-bridge', status: 'stopped', uptime: '-', port: 8100 }, { name: 'sync-engine', status: 'stopped', uptime: '-', port: 8200 }], coreml_queue: [], recent_events: [{ id: 'ev-off1', time: '2026-04-26 03:15', type: 'offline', description: '心跳超时，节点离线' }] },
  { sn: 'TX-MAC-007', model: 'Mac mini M4', macos_version: 'macOS 15.3', tailscale_ip: '100.64.1.16', merchant_name: '尚宫厨', store_name: '岳麓区店', status: 'offline', latency_ms: -1, version: '3.2.8', heartbeat_interval: 30, cpu_pct: 0, mem_pct: 0, disk_pct: 42, services: [{ name: 'mac-station', status: 'stopped', uptime: '-', port: 8000 }, { name: 'coreml-bridge', status: 'stopped', uptime: '-', port: 8100 }, { name: 'sync-engine', status: 'stopped', uptime: '-', port: 8200 }], coreml_queue: [], recent_events: [{ id: 'ev-off2', time: '2026-04-25 18:00', type: 'offline', description: '计划停机维护' }] },
  { sn: 'TX-MAC-008', model: 'Mac mini M4', macos_version: 'macOS 15.3', tailscale_ip: '100.64.1.17', merchant_name: '湘粤楼', store_name: '星沙店', status: 'offline', latency_ms: -1, version: '3.2.9', heartbeat_interval: 30, cpu_pct: 0, mem_pct: 0, disk_pct: 55, services: [{ name: 'mac-station', status: 'stopped', uptime: '-', port: 8000 }, { name: 'coreml-bridge', status: 'stopped', uptime: '-', port: 8100 }, { name: 'sync-engine', status: 'stopped', uptime: '-', port: 8200 }], coreml_queue: [], recent_events: [{ id: 'ev-off3', time: '2026-04-26 01:30', type: 'offline', description: '网络故障，Tailscale 断连' }] },
  { sn: 'TX-MAC-009', model: 'Mac mini M4', macos_version: 'macOS 15.3', tailscale_ip: '100.64.1.18', merchant_name: '尝在一起', store_name: '雨花区店', status: 'updating', latency_ms: 35, version: '3.2.9→3.3.0', heartbeat_interval: 30, cpu_pct: 72, mem_pct: 80, disk_pct: 45, services: MOCK_SERVICES, coreml_queue: MOCK_COREML_QUEUE, recent_events: [{ id: 'ev-up1', time: '2026-04-26 08:30', type: 'update', description: '正在推送更新 3.2.9 → 3.3.0' }] },
  { sn: 'TX-MAC-010', model: 'Mac mini M4', macos_version: 'macOS 15.2', tailscale_ip: '100.64.1.19', merchant_name: '徐记海鲜', store_name: '河西店', status: 'quarantine', latency_ms: 250, version: '3.2.8', heartbeat_interval: 30, cpu_pct: 92, mem_pct: 95, disk_pct: 88, services: [{ name: 'mac-station', status: 'running', uptime: '1h', port: 8000 }, { name: 'coreml-bridge', status: 'error', uptime: '-', port: 8100 }, { name: 'sync-engine', status: 'running', uptime: '1h', port: 8200 }], coreml_queue: [], recent_events: [{ id: 'ev-q1', time: '2026-04-26 07:00', type: 'alert', description: '磁盘使用率 88%，已隔离' }] },
];

// ── 样式 ──

const STATUS_COLOR: Record<EdgeStatus, string> = {
  online: C.green, offline: C.red, updating: C.yellow, quarantine: C.red,
};
const STATUS_LABEL: Record<EdgeStatus, string> = {
  online: '在线', offline: '离线', updating: '更新中', quarantine: '隔离',
};

type FilterKey = 'all' | EdgeStatus;
type TabKey = 'overview' | 'timeline' | 'actions' | 'traces' | 'cost' | 'logs' | 'related' | 'playbooks';
type ViewMode = 'list' | 'topology';

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
  { key: 'online', label: '在线' },
  { key: 'offline', label: '离线' },
  { key: 'updating', label: '更新中' },
  { key: 'quarantine', label: '隔离' },
];

const EVENT_ICON: Record<string, string> = {
  online: '🟢', offline: '🔴', update: '📦', alert: '⚠️', rollback: '↩️', maintenance: '🔧',
};

// ── Helpers ──

function Placeholder({ label }: { label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200, color: C.text3, fontSize: 14 }}>
      {label}
    </div>
  );
}

function ConfirmDialog({ title, description, onConfirm, onCancel }: {
  title: string; description: string; onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={onCancel}>
      <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: 24, minWidth: 360, maxWidth: 480 }} onClick={e => e.stopPropagation()}>
        <div style={{ fontSize: 16, fontWeight: 700, color: C.text, marginBottom: 8 }}>{title}</div>
        <div style={{ fontSize: 13, color: C.text2, marginBottom: 20 }}>{description}</div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={{ background: 'transparent', color: C.text2, border: `1px solid ${C.border}`, borderRadius: 6, padding: '8px 16px', fontSize: 13, cursor: 'pointer' }}>取消</button>
          <button onClick={onConfirm} style={{ background: C.orange, color: '#fff', border: 'none', borderRadius: 6, padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>确认</button>
        </div>
      </div>
    </div>
  );
}

function MetricBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, borderRadius: 3, background: C.surface3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', borderRadius: 3, background: color, transition: 'width 0.3s' }} />
      </div>
      <span style={{ fontSize: 12, color, fontWeight: 600, minWidth: 36, textAlign: 'right' }}>{value}%</span>
    </div>
  );
}

// ── Overview Tab ──

function OverviewTab({ node }: { node: EdgeNode }) {
  const cpuColor = node.cpu_pct > 80 ? C.red : node.cpu_pct > 60 ? C.yellow : C.green;
  const memColor = node.mem_pct > 80 ? C.red : node.mem_pct > 60 ? C.yellow : C.green;
  const diskColor = node.disk_pct > 80 ? C.red : node.disk_pct > 60 ? C.yellow : C.green;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 节点信息 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>节点信息</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px 24px', fontSize: 13 }}>
          {([
            ['序列号', node.sn], ['型号', node.model], ['macOS版本', node.macos_version],
            ['Tailscale IP', node.tailscale_ip], ['商户', node.merchant_name], ['门店', node.store_name],
          ] as const).map(([label, val]) => (
            <div key={label}>
              <div style={{ color: C.text3, fontSize: 11, marginBottom: 2 }}>{label}</div>
              <div style={{ color: C.text, fontFamily: label === 'Tailscale IP' || label === '序列号' ? 'monospace' : 'inherit' }}>{val}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 状态指标 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>状态指标</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <div style={{ color: C.text3, fontSize: 11, marginBottom: 4 }}>在线状态</div>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 8, height: 8, borderRadius: 4, background: STATUS_COLOR[node.status] }} />
              <span style={{ color: STATUS_COLOR[node.status], fontWeight: 600, fontSize: 13 }}>{STATUS_LABEL[node.status]}</span>
            </span>
          </div>
          <div>
            <div style={{ color: C.text3, fontSize: 11, marginBottom: 4 }}>心跳间隔</div>
            <div style={{ color: C.text, fontSize: 13 }}>{node.heartbeat_interval}s</div>
          </div>
          <div>
            <div style={{ color: C.text3, fontSize: 11, marginBottom: 4 }}>网络延迟</div>
            <div style={{ color: node.latency_ms > 100 ? C.red : node.latency_ms > 50 ? C.yellow : C.green, fontSize: 13, fontWeight: 600 }}>
              {node.latency_ms >= 0 ? `${node.latency_ms}ms` : '-'}
            </div>
          </div>
          <div>
            <div style={{ color: C.text3, fontSize: 11, marginBottom: 4 }}>版本</div>
            <div style={{ color: C.text, fontSize: 13 }}>{node.version}</div>
          </div>
          <div><div style={{ color: C.text3, fontSize: 11, marginBottom: 4 }}>CPU</div><MetricBar value={node.cpu_pct} max={100} color={cpuColor} /></div>
          <div><div style={{ color: C.text3, fontSize: 11, marginBottom: 4 }}>内存</div><MetricBar value={node.mem_pct} max={100} color={memColor} /></div>
          <div style={{ gridColumn: '1 / -1' }}><div style={{ color: C.text3, fontSize: 11, marginBottom: 4 }}>磁盘</div><MetricBar value={node.disk_pct} max={100} color={diskColor} /></div>
        </div>
      </div>

      {/* 运行服务 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>运行服务</div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {node.services.map(svc => {
            const svcColor = svc.status === 'running' ? C.green : svc.status === 'error' ? C.red : C.text3;
            return (
              <div key={svc.name} style={{ flex: '1 1 180px', background: C.surface2, borderRadius: 8, padding: 12, border: `1px solid ${C.border}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 4, background: svcColor }} />
                  <span style={{ fontWeight: 600, fontSize: 13, color: C.text }}>{svc.name}</span>
                </div>
                <div style={{ fontSize: 11, color: C.text3 }}>端口 :{svc.port} / 运行 {svc.uptime}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Core ML 队列 */}
      {node.coreml_queue.length > 0 && (
        <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>Core ML 推理队列</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
            {node.coreml_queue.map(q => {
              const qColor = q.status === 'idle' ? C.green : q.status === 'busy' ? C.yellow : C.red;
              return (
                <div key={q.agent} style={{ background: C.surface2, borderRadius: 6, padding: '8px 10px', border: `1px solid ${C.border}` }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: C.text, marginBottom: 4 }}>{q.agent}</div>
                  <div style={{ display: 'flex', gap: 8, fontSize: 11, color: C.text3 }}>
                    <span>待处理 <span style={{ color: qColor, fontWeight: 600 }}>{q.pending}</span></span>
                    <span>{q.avg_latency_ms}ms</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 最近事件 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>最近事件</div>
        {node.recent_events.map(evt => (
          <div key={evt.id} style={{ display: 'flex', gap: 10, padding: '8px 0', borderBottom: `1px solid ${C.border}`, alignItems: 'center' }}>
            <span style={{ fontSize: 14 }}>{EVENT_ICON[evt.type] || '📌'}</span>
            <span style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace', minWidth: 120 }}>{evt.time}</span>
            <span style={{ fontSize: 13, color: C.text }}>{evt.description}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Timeline Tab ──

function TimelineTab({ node }: { node: EdgeNode }) {
  const [range, setRange] = useState<'24h' | '7d' | '30d'>('7d');

  const MOCK_TIMELINE: TimelineEvent[] = [
    { id: 't1', time: '2026-04-26 08:00', type: 'online', description: '节点上线，版本 3.3.0', icon: '🟢' },
    { id: 't2', time: '2026-04-25 22:15', type: 'update', description: '推送更新 3.2.9 → 3.3.0 完成', icon: '📦' },
    { id: 't3', time: '2026-04-25 22:00', type: 'update', description: '开始推送更新 3.2.9 → 3.3.0', icon: '📦' },
    { id: 't4', time: '2026-04-25 18:00', type: 'alert', description: 'CPU 使用率峰值 87%', icon: '⚠️' },
    { id: 't5', time: '2026-04-25 09:00', type: 'online', description: '节点上线', icon: '🟢' },
    { id: 't6', time: '2026-04-24 23:00', type: 'offline', description: '计划停机，系统更新', icon: '🔴' },
    { id: 't7', time: '2026-04-24 09:30', type: 'maintenance', description: '重启 sync-engine，清理同步队列', icon: '🔧' },
    { id: 't8', time: '2026-04-23 14:00', type: 'online', description: '断网恢复后重新上线', icon: '🟢' },
    { id: 't9', time: '2026-04-23 10:30', type: 'offline', description: '网络故障，Tailscale 断连', icon: '🔴' },
    { id: 't10', time: '2026-04-22 08:00', type: 'online', description: '节点上线', icon: '🟢' },
  ];

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {(['24h', '7d', '30d'] as const).map(r => (
          <button key={r} onClick={() => setRange(r)} style={{
            background: range === r ? C.orange + '22' : 'transparent',
            color: range === r ? C.orange : C.text3,
            border: `1px solid ${range === r ? C.orange : C.border}`,
            borderRadius: 6, padding: '4px 12px', fontSize: 12, cursor: 'pointer',
          }}>{r}</button>
        ))}
      </div>
      <div style={{ position: 'relative', paddingLeft: 24 }}>
        {/* 竖线 */}
        <div style={{ position: 'absolute', left: 7, top: 4, bottom: 4, width: 2, background: C.border }} />
        {MOCK_TIMELINE.map((evt, i) => (
          <div key={evt.id} style={{ display: 'flex', gap: 12, marginBottom: i < MOCK_TIMELINE.length - 1 ? 20 : 0, position: 'relative' }}>
            {/* 节点圆点 */}
            <div style={{ position: 'absolute', left: -20, top: 2, width: 16, height: 16, borderRadius: 8, background: C.surface, border: `2px solid ${C.border2}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9 }}>
              {evt.icon}
            </div>
            <div>
              <div style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace', marginBottom: 2 }}>{evt.time}</div>
              <div style={{ fontSize: 13, color: C.text }}>{evt.description}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Actions Tab ──

function ActionsTab({ node }: { node: EdgeNode }) {
  const [confirm, setConfirm] = useState<{ title: string; desc: string; action: () => void } | null>(null);
  const [versionInput, setVersionInput] = useState('3.3.0');

  const doAction = useCallback(async (path: string, body?: unknown) => {
    try {
      await hubPost(path, body);
    } catch {
      // API 未就绪，静默降级
    }
    setConfirm(null);
  }, []);

  const actions = [
    { icon: '🟢', title: '唤醒 (Wake-on-LAN)', desc: '发送 WOL 包唤醒离线节点', color: C.green, onClick: () => setConfirm({ title: '唤醒节点', desc: `确认向 ${node.sn} 发送 Wake-on-LAN 信号？`, action: () => doAction(`/edges/${node.sn}/wake`) }) },
    { icon: '🔄', title: '重启', desc: '远程重启 Mac mini（约2分钟恢复）', color: C.blue, onClick: () => setConfirm({ title: '重启节点', desc: `确认重启 ${node.sn}？所有本地服务将重启。`, action: () => doAction(`/edges/${node.sn}/reboot`) }) },
    { icon: '📦', title: '推送更新', desc: '推送指定版本到此节点', color: C.orange, onClick: () => setConfirm({ title: '推送更新', desc: `确认推送版本 ${versionInput} 到 ${node.sn}？`, action: () => doAction(`/edges/${node.sn}/push`, { version: versionInput }) }) },
    { icon: '🔍', title: '远程诊断', desc: '运行完整诊断脚本，收集日志', color: C.yellow, onClick: () => setConfirm({ title: '远程诊断', desc: `确认对 ${node.sn} 运行远程诊断？`, action: () => doAction(`/edges/${node.sn}/diagnose`) }) },
  ];

  return (
    <div>
      {confirm && <ConfirmDialog title={confirm.title} description={confirm.desc} onConfirm={confirm.action} onCancel={() => setConfirm(null)} />}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
        {actions.map(a => (
          <button key={a.title} onClick={a.onClick} style={{
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
      {/* 版本输入 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 13, color: C.text2, marginBottom: 8 }}>目标版本号（推送更新时使用）</div>
        <input value={versionInput} onChange={e => setVersionInput(e.target.value)} style={{
          background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 6,
          padding: '6px 12px', fontSize: 13, outline: 'none', width: 200,
        }} />
      </div>
    </div>
  );
}

// ── Related Tab ──

function RelatedTab({ node }: { node: EdgeNode }) {
  const relations = [
    { type: '门店', name: `${node.merchant_name} - ${node.store_name}`, id: 'store-001' },
    { type: '商户', name: node.merchant_name, id: 'merchant-001' },
    { type: 'POS 主机', name: `商米 T2 (${node.store_name})`, id: 'pos-001' },
    { type: 'KDS 平板', name: `商米 D2 (${node.store_name})`, id: 'kds-001' },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {relations.map(r => (
        <div key={r.id} style={{ background: C.surface, borderRadius: 8, padding: 12, border: `1px solid ${C.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <span style={{ fontSize: 11, color: C.text3, marginRight: 8 }}>{r.type}</span>
            <span style={{ fontSize: 13, color: C.text, fontWeight: 600 }}>{r.name}</span>
          </div>
          <span style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace' }}>{r.id}</span>
        </div>
      ))}
    </div>
  );
}

// ── Topology View (SVG) ──

function TopologyView({ edges }: { edges: EdgeNode[] }) {
  const cx = 400;
  const cy = 250;
  const radius = 180;

  return (
    <div style={{ background: C.surface, borderRadius: 12, padding: 20, border: `1px solid ${C.border}`, overflow: 'auto' }}>
      <svg width={800} height={500} viewBox="0 0 800 500" style={{ display: 'block', margin: '0 auto' }}>
        {/* 中心云端节点 */}
        <circle cx={cx} cy={cy} r={36} fill={C.surface2} stroke={C.orange} strokeWidth={2} />
        <text x={cx} y={cy - 6} textAnchor="middle" fill={C.orange} fontSize={11} fontWeight={700}>腾讯云</text>
        <text x={cx} y={cy + 10} textAnchor="middle" fill={C.text3} fontSize={9}>Hub 控制面</text>

        {/* 边缘节点 */}
        {edges.map((edge, i) => {
          const angle = (2 * Math.PI * i) / edges.length - Math.PI / 2;
          const x = cx + radius * Math.cos(angle);
          const y = cy + radius * Math.sin(angle);
          const isOnline = edge.status === 'online' || edge.status === 'updating';
          const nodeColor = STATUS_COLOR[edge.status];

          return (
            <g key={edge.sn}>
              {/* 连线 */}
              <line
                x1={cx} y1={cy} x2={x} y2={y}
                stroke={isOnline ? C.green + '66' : C.red + '44'}
                strokeWidth={isOnline ? 1.5 : 1}
                strokeDasharray={isOnline ? 'none' : '4,4'}
              />
              {/* 节点圆 */}
              <circle cx={x} cy={y} r={24} fill={C.surface2} stroke={nodeColor} strokeWidth={2} />
              <circle cx={x + 16} cy={y - 16} r={4} fill={nodeColor} />
              {/* 标签 */}
              <text x={x} y={y + 2} textAnchor="middle" fill={C.text} fontSize={8} fontWeight={600}>
                {edge.store_name.slice(0, 4)}
              </text>
              <text x={x} y={y + 38} textAnchor="middle" fill={C.text3} fontSize={7}>
                {edge.sn}
              </text>
              <text x={x} y={y + 48} textAnchor="middle" fill={nodeColor} fontSize={7}>
                {STATUS_LABEL[edge.status]}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ── Main Export ──

export function EdgesWorkspace() {
  const [edges, setEdges] = useState<EdgeNode[]>(MOCK_EDGES);
  const [selected, setSelected] = useState<EdgeNode | null>(null);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [tab, setTab] = useState<TabKey>('overview');
  const [view, setView] = useState<ViewMode>('list');

  // 尝试从 API 加载，失败则使用 Mock
  useEffect(() => {
    hubGet<EdgeNode[]>('/edges')
      .then(data => { if (Array.isArray(data) && data.length > 0) setEdges(data); })
      .catch(() => { /* 使用 Mock */ });
  }, []);

  const filtered = useMemo(() => {
    if (filter === 'all') return edges;
    return edges.filter(e => e.status === filter);
  }, [edges, filter]);

  const counts = useMemo(() => {
    const m: Record<string, number> = { all: edges.length };
    for (const e of edges) m[e.status] = (m[e.status] || 0) + 1;
    return m;
  }, [edges]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', color: C.text }}>
      {/* 顶部栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 20, fontWeight: 700, color: C.text }}>边缘节点</div>
        <div style={{ display: 'flex', gap: 6 }}>
          {(['list', 'topology'] as const).map(v => (
            <button key={v} onClick={() => setView(v)} style={{
              background: view === v ? C.orange + '22' : 'transparent',
              color: view === v ? C.orange : C.text3,
              border: `1px solid ${view === v ? C.orange : C.border}`,
              borderRadius: 6, padding: '5px 14px', fontSize: 12, cursor: 'pointer', fontWeight: 600,
            }}>{v === 'list' ? '列表' : '拓扑'}</button>
          ))}
        </div>
      </div>

      {view === 'topology' ? (
        <TopologyView edges={edges} />
      ) : (
        <div style={{ display: 'flex', gap: 16, flex: 1, minHeight: 0 }}>
          {/* 左侧列表 */}
          <div style={{ width: 360, flexShrink: 0, display: 'flex', flexDirection: 'column', background: C.surface, borderRadius: 10, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
            {/* 筛选 chips */}
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
            {/* 列表项 */}
            <div style={{ flex: 1, overflowY: 'auto' }}>
              {filtered.map(edge => {
                const isActive = selected?.sn === edge.sn;
                return (
                  <div key={edge.sn} onClick={() => { setSelected(edge); setTab('overview'); }} style={{
                    padding: '10px 14px', cursor: 'pointer',
                    borderLeft: isActive ? `3px solid ${C.orange}` : '3px solid transparent',
                    background: isActive ? C.orange + '0D' : 'transparent',
                    borderBottom: `1px solid ${C.border}`,
                    transition: 'background 0.15s',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <span style={{ width: 8, height: 8, borderRadius: 4, background: STATUS_COLOR[edge.status], flexShrink: 0 }} />
                      <span style={{ fontSize: 12, color: C.text3, fontFamily: 'monospace' }}>{edge.sn}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{edge.merchant_name} - {edge.store_name}</span>
                      <div style={{ display: 'flex', gap: 8, fontSize: 11, color: C.text3 }}>
                        {edge.latency_ms >= 0 && <span>{edge.latency_ms}ms</span>}
                        <span>{edge.version}</span>
                      </div>
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
                选择一个边缘节点查看详情
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                {/* Header */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 5, background: STATUS_COLOR[selected.status] }} />
                  <span style={{ fontSize: 16, fontWeight: 700, color: C.text }}>{selected.merchant_name} - {selected.store_name}</span>
                  <span style={{ fontSize: 12, color: C.text3, fontFamily: 'monospace' }}>{selected.sn}</span>
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
                  {tab === 'overview' && <OverviewTab node={selected} />}
                  {tab === 'timeline' && <TimelineTab node={selected} />}
                  {tab === 'actions' && <ActionsTab node={selected} />}
                  {tab === 'traces' && <Placeholder label="Trace 数据接入中" />}
                  {tab === 'cost' && <Placeholder label="成本数据接入中" />}
                  {tab === 'logs' && <Placeholder label="日志接入中" />}
                  {tab === 'related' && <RelatedTab node={selected} />}
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
