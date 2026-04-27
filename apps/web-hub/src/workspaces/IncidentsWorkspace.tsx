/**
 * Workspace: Incidents — 事件响应系统（替代 v1 TicketsPage P0/P1 部分）
 *
 * 左侧列表 + 右侧 Object Page (8 Tab)
 * 核心：状态流转条 + Incident指挥链 + 精确时间线 + Postmortem
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

type Severity = 'P0' | 'P1' | 'P2';
type IncidentStatus = '检测' | '声明' | '响应' | '恢复' | '关闭' | '复盘';
type FilterKey = 'all' | 'active' | 'resolved' | 'postmortem';

interface Commander {
  role: '指挥官(IC)' | '记录员(Scribe)' | '技术负责人(Tech Lead)';
  name: string;
  contact: string;
}

interface ActionItem {
  id: string;
  title: string;
  assignee: string;
  status: '待处理' | '进行中' | '已完成';
  dueDate: string;
}

interface TimelineEntry {
  id: string;
  time: string; // HH:MM:SS
  source: 'system' | 'human' | 'ai';
  actor: string;
  description: string;
}

interface AffectedCustomer {
  id: string;
  name: string;
  stores: number;
  impact: string;
}

interface AffectedService {
  id: string;
  name: string;
  status: '降级' | '不可用' | '已恢复';
}

interface RelatedPlaybook {
  id: string;
  name: string;
  status: '已触发' | '运行中' | '已完成';
}

interface RelatedTicket {
  id: string;
  title: string;
  status: string;
}

interface PostmortemData {
  summary: string;
  rootCause: string;
  fiveWhys: string[];
  actionItems: ActionItem[];
  improvements: string[];
}

interface IncidentRecord {
  id: string;
  code: string; // INC-2026-XXX
  title: string;
  severity: Severity;
  status: IncidentStatus;
  currentStage: number; // 0-5 对应流转条
  mttrMinutes: number;
  affectedCustomers: number;
  affectedStores: number;
  affectedOrders: number;
  commanders: Commander[];
  actionItems: ActionItem[];
  timeline: TimelineEntry[];
  affectedCustomerList: AffectedCustomer[];
  affectedServices: AffectedService[];
  relatedPlaybooks: RelatedPlaybook[];
  relatedTickets: RelatedTicket[];
  postmortem: PostmortemData | null;
  createdAt: string;
  resolvedAt: string | null;
}

// ── Mock 数据 ──

const MOCK_TIMELINE_042: TimelineEntry[] = [
  { id: 'tl1', time: '03:14:22', source: 'system', actor: '系统', description: 'SLO告警：湘粤楼广州区 Mac mini 集群 3/5 节点心跳超时' },
  { id: 'tl2', time: '03:14:25', source: 'system', actor: '系统', description: '自动声明 Incident INC-2026-042, P0' },
  { id: 'tl3', time: '03:15:01', source: 'system', actor: '系统', description: 'On-call路由：通知 SRE-张三、SRE-李四' },
  { id: 'tl4', time: '03:16:30', source: 'human', actor: '张三', description: '确认响应，开始排查' },
  { id: 'tl5', time: '03:18:45', source: 'ai', actor: 'AI', description: '建议：检查广州机房UPS供电状态，近期有市政电力维护通知' },
  { id: 'tl6', time: '03:20:12', source: 'human', actor: '张三', description: '确认UPS电池耗尽导致断电，联系物业恢复供电' },
  { id: 'tl7', time: '03:35:00', source: 'human', actor: '李四', description: '物业已恢复供电，等待节点自动重启' },
  { id: 'tl8', time: '03:42:00', source: 'system', actor: '系统', description: '3/5 节点已恢复心跳' },
  { id: 'tl9', time: '03:45:00', source: 'system', actor: '系统', description: '5/5 节点全部恢复，SLO恢复正常' },
];

const MOCK_TIMELINE_041: TimelineEntry[] = [
  { id: 'tl1', time: '14:22:10', source: 'system', actor: '系统', description: 'SLO告警：tx-trade P95延迟 > 500ms' },
  { id: 'tl2', time: '14:22:15', source: 'system', actor: '系统', description: '自动声明 Incident INC-2026-041, P1' },
  { id: 'tl3', time: '14:23:00', source: 'system', actor: '系统', description: 'On-call路由：通知 SRE-张三' },
  { id: 'tl4', time: '14:24:30', source: 'human', actor: '张三', description: '确认响应' },
  { id: 'tl5', time: '14:26:45', source: 'ai', actor: 'AI', description: '建议：最近变更 edge 2.4.1 灰度推送可能相关' },
  { id: 'tl6', time: '14:28:12', source: 'human', actor: '张三', description: '执行回滚 edge 2.4.1 \u2192 2.3.9' },
  { id: 'tl7', time: '14:30:00', source: 'system', actor: '系统', description: 'SLO恢复正常' },
  { id: 'tl8', time: '14:30:30', source: 'system', actor: '系统', description: 'Incident自动关闭' },
];

const MOCK_COMMANDERS: Commander[] = [
  { role: '指挥官(IC)', name: '张三', contact: 'zhangsan@tunxiang.io' },
  { role: '记录员(Scribe)', name: '王芳', contact: 'wangfang@tunxiang.io' },
  { role: '技术负责人(Tech Lead)', name: '李四', contact: 'lisi@tunxiang.io' },
];

const MOCK_ACTION_ITEMS: ActionItem[] = [
  { id: 'ai1', title: '排查UPS电池更换周期', assignee: '李四', status: '进行中', dueDate: '2026-04-28' },
  { id: 'ai2', title: '增加机房供电监控告警', assignee: '张三', status: '待处理', dueDate: '2026-04-30' },
  { id: 'ai3', title: '评估备用电源方案', assignee: '李四', status: '待处理', dueDate: '2026-05-05' },
];

const MOCK_POSTMORTEM_041: PostmortemData = {
  summary: 'edge 2.4.1 灰度推送引入内存泄漏，导致 tx-trade 服务 P95 延迟飙升至 800ms。',
  rootCause: 'edge 2.4.1 中 coreml-bridge 新增的批量推理接口存在内存泄漏，在高并发场景下触发 GC 暂停。',
  fiveWhys: [
    '为什么延迟飙升？因为 GC 暂停导致请求排队',
    '为什么会 GC 暂停？因为 coreml-bridge 内存泄漏',
    '为什么有内存泄漏？因为批量推理结果未正确释放',
    '为什么未发现？因为压测用例未覆盖批量推理路径',
    '为什么未覆盖？因为压测脚本未同步更新新接口',
  ],
  actionItems: [
    { id: 'pm-ai1', title: '修复 coreml-bridge 内存泄漏', assignee: '李四', status: '已完成', dueDate: '2026-04-22' },
    { id: 'pm-ai2', title: '补充批量推理压测用例', assignee: '张三', status: '已完成', dueDate: '2026-04-23' },
    { id: 'pm-ai3', title: '灰度推送增加内存监控门槛', assignee: '王芳', status: '进行中', dueDate: '2026-04-28' },
  ],
  improvements: [
    '灰度推送前必须通过完整压测套件',
    '增加 edge 节点内存使用率自动告警（>80%）',
    '建立 coreml-bridge 变更必经的性能回归测试流程',
  ],
};

const MOCK_INCIDENTS: IncidentRecord[] = [
  {
    id: 'inc-042', code: 'INC-2026-042', title: 'Mac mini集群离线 - 湘粤楼广州区', severity: 'P0', status: '响应',
    currentStage: 2, mttrMinutes: 31, affectedCustomers: 1, affectedStores: 5, affectedOrders: 120,
    commanders: MOCK_COMMANDERS, actionItems: MOCK_ACTION_ITEMS, timeline: MOCK_TIMELINE_042,
    affectedCustomerList: [{ id: 'tx-9005', name: '湘粤楼', stores: 5, impact: '广州区全部门店离线' }],
    affectedServices: [{ id: 'svc-1', name: 'mac-station', status: '不可用' }, { id: 'svc-2', name: 'sync-engine', status: '不可用' }],
    relatedPlaybooks: [{ id: 'rpb-1', name: 'P0自动响应', status: '运行中' }],
    relatedTickets: [{ id: 'TK-0210', title: '湘粤楼广州区Mac mini掉线', status: '处理中' }],
    postmortem: null, createdAt: '2026-04-26 03:14', resolvedAt: null,
  },
  {
    id: 'inc-041', code: 'INC-2026-041', title: 'tx-trade P95延迟飙升', severity: 'P1', status: '复盘',
    currentStage: 5, mttrMinutes: 8, affectedCustomers: 10, affectedStores: 156, affectedOrders: 3200,
    commanders: MOCK_COMMANDERS, actionItems: [], timeline: MOCK_TIMELINE_041,
    affectedCustomerList: [{ id: 'tx-9001', name: '徐记海鲜', stores: 56, impact: 'P95延迟 > 500ms' }, { id: 'tx-9005', name: '湘粤楼', stores: 12, impact: 'P95延迟 > 500ms' }],
    affectedServices: [{ id: 'svc-3', name: 'tx-trade', status: '已恢复' }],
    relatedPlaybooks: [{ id: 'rpb-2', name: 'SLO违约恢复', status: '已完成' }, { id: 'rpb-3', name: '灰度回滚', status: '已完成' }],
    relatedTickets: [], postmortem: MOCK_POSTMORTEM_041,
    createdAt: '2026-04-25 14:22', resolvedAt: '2026-04-25 14:30',
  },
  {
    id: 'inc-040', code: 'INC-2026-040', title: '客如云Adapter增量延迟', severity: 'P1', status: '复盘',
    currentStage: 5, mttrMinutes: 45, affectedCustomers: 3, affectedStores: 28, affectedOrders: 580,
    commanders: MOCK_COMMANDERS, actionItems: [], timeline: [
      { id: 'tl1', time: '10:00:15', source: 'system', actor: '系统', description: '客如云Adapter增量同步延迟 > 30min' },
      { id: 'tl2', time: '10:05:00', source: 'human', actor: '王芳', description: '确认响应，排查Adapter日志' },
      { id: 'tl3', time: '10:15:00', source: 'ai', actor: 'AI', description: '建议：客如云API限流导致，建议降低并发数' },
      { id: 'tl4', time: '10:20:00', source: 'human', actor: '王芳', description: '调整并发数从10降至3' },
      { id: 'tl5', time: '10:45:00', source: 'system', actor: '系统', description: '同步恢复正常，延迟 < 5min' },
    ],
    affectedCustomerList: [{ id: 'tx-9003', name: '最黔线', stores: 15, impact: '数据同步延迟' }],
    affectedServices: [{ id: 'svc-4', name: 'adapter-keruyun', status: '已恢复' }],
    relatedPlaybooks: [{ id: 'rpb-4', name: 'Adapter故障恢复', status: '已完成' }],
    relatedTickets: [], postmortem: null,
    createdAt: '2026-04-24 10:00', resolvedAt: '2026-04-24 10:45',
  },
  {
    id: 'inc-039', code: 'INC-2026-039', title: '茶颜悦色会员积分同步异常', severity: 'P2', status: '关闭',
    currentStage: 4, mttrMinutes: 22, affectedCustomers: 1, affectedStores: 120, affectedOrders: 0,
    commanders: MOCK_COMMANDERS, actionItems: [], timeline: [
      { id: 'tl1', time: '16:30:00', source: 'system', actor: '系统', description: '会员积分同步队列堆积 > 10000' },
      { id: 'tl2', time: '16:35:00', source: 'human', actor: '张三', description: '确认响应，检查 tx-member 服务' },
      { id: 'tl3', time: '16:40:00', source: 'human', actor: '张三', description: '重启消费者队列，积分开始恢复同步' },
      { id: 'tl4', time: '16:52:00', source: 'system', actor: '系统', description: '队列恢复正常' },
    ],
    affectedCustomerList: [{ id: 'tx-9009', name: '茶颜悦色', stores: 120, impact: '会员积分延迟' }],
    affectedServices: [{ id: 'svc-5', name: 'tx-member', status: '已恢复' }],
    relatedPlaybooks: [], relatedTickets: [],
    postmortem: null, createdAt: '2026-04-23 16:30', resolvedAt: '2026-04-23 16:52',
  },
  {
    id: 'inc-038', code: 'INC-2026-038', title: '费大厨KDS推送延迟', severity: 'P2', status: '关闭',
    currentStage: 4, mttrMinutes: 15, affectedCustomers: 1, affectedStores: 42, affectedOrders: 85,
    commanders: MOCK_COMMANDERS, actionItems: [], timeline: [
      { id: 'tl1', time: '12:05:00', source: 'system', actor: '系统', description: 'KDS WebSocket推送延迟 > 10s' },
      { id: 'tl2', time: '12:08:00', source: 'human', actor: '李四', description: '确认响应' },
      { id: 'tl3', time: '12:15:00', source: 'human', actor: '李四', description: '重启 WebSocket 网关' },
      { id: 'tl4', time: '12:20:00', source: 'system', actor: '系统', description: '推送恢复正常' },
    ],
    affectedCustomerList: [{ id: 'tx-9006', name: '费大厨', stores: 42, impact: 'KDS推送延迟' }],
    affectedServices: [{ id: 'svc-6', name: 'gateway', status: '已恢复' }],
    relatedPlaybooks: [], relatedTickets: [],
    postmortem: null, createdAt: '2026-04-22 12:05', resolvedAt: '2026-04-22 12:20',
  },
  {
    id: 'inc-037', code: 'INC-2026-037', title: '文和友POS打印机批量超时', severity: 'P2', status: '关闭',
    currentStage: 4, mttrMinutes: 30, affectedCustomers: 1, affectedStores: 5, affectedOrders: 45,
    commanders: MOCK_COMMANDERS, actionItems: [], timeline: [
      { id: 'tl1', time: '18:00:00', source: 'system', actor: '系统', description: 'POS打印超时告警，5家门店同时触发' },
      { id: 'tl2', time: '18:05:00', source: 'human', actor: '王芳', description: '确认响应' },
      { id: 'tl3', time: '18:15:00', source: 'ai', actor: 'AI', description: '建议：检查安卓POS壳层打印队列' },
      { id: 'tl4', time: '18:25:00', source: 'human', actor: '王芳', description: '远程重启POS打印服务' },
      { id: 'tl5', time: '18:30:00', source: 'system', actor: '系统', description: '打印恢复正常' },
    ],
    affectedCustomerList: [{ id: 'tx-9008', name: '文和友', stores: 5, impact: '打印超时' }],
    affectedServices: [{ id: 'svc-7', name: 'android-pos', status: '已恢复' }],
    relatedPlaybooks: [], relatedTickets: [],
    postmortem: null, createdAt: '2026-04-21 18:00', resolvedAt: '2026-04-21 18:30',
  },
  {
    id: 'inc-036', code: 'INC-2026-036', title: '黑色经典门店网络波动', severity: 'P1', status: '关闭',
    currentStage: 4, mttrMinutes: 60, affectedCustomers: 1, affectedStores: 12, affectedOrders: 200,
    commanders: MOCK_COMMANDERS, actionItems: [], timeline: [
      { id: 'tl1', time: '09:00:00', source: 'system', actor: '系统', description: '12家门店 Tailscale 连接断续' },
      { id: 'tl2', time: '09:05:00', source: 'human', actor: '张三', description: '确认响应' },
      { id: 'tl3', time: '09:30:00', source: 'human', actor: '张三', description: '确认是ISP路由故障' },
      { id: 'tl4', time: '10:00:00', source: 'system', actor: '系统', description: 'ISP故障恢复，网络稳定' },
    ],
    affectedCustomerList: [{ id: 'tx-9010', name: '黑色经典', stores: 12, impact: '网络波动' }],
    affectedServices: [{ id: 'svc-8', name: 'tailscale', status: '已恢复' }],
    relatedPlaybooks: [], relatedTickets: [],
    postmortem: null, createdAt: '2026-04-20 09:00', resolvedAt: '2026-04-20 10:00',
  },
  {
    id: 'inc-035', code: 'INC-2026-035', title: '炊烟CoreML推理队列堆积', severity: 'P1', status: '关闭',
    currentStage: 4, mttrMinutes: 25, affectedCustomers: 1, affectedStores: 35, affectedOrders: 150,
    commanders: MOCK_COMMANDERS, actionItems: [], timeline: [
      { id: 'tl1', time: '20:10:00', source: 'system', actor: '系统', description: 'CoreML推理队列 pending > 50' },
      { id: 'tl2', time: '20:12:00', source: 'human', actor: '李四', description: '确认响应' },
      { id: 'tl3', time: '20:20:00', source: 'ai', actor: 'AI', description: '建议：清理模型缓存并重启 coreml-bridge' },
      { id: 'tl4', time: '20:25:00', source: 'human', actor: '李四', description: '执行清理和重启' },
      { id: 'tl5', time: '20:35:00', source: 'system', actor: '系统', description: '推理队列恢复正常' },
    ],
    affectedCustomerList: [{ id: 'tx-9007', name: '炊烟', stores: 35, impact: 'AI推理延迟' }],
    affectedServices: [{ id: 'svc-9', name: 'coreml-bridge', status: '已恢复' }],
    relatedPlaybooks: [], relatedTickets: [],
    postmortem: null, createdAt: '2026-04-19 20:10', resolvedAt: '2026-04-19 20:35',
  },
];

// ── 辅助 ──

type TabKey = 'overview' | 'timeline' | 'actions' | 'playbooks' | 'related' | 'traces' | 'cost' | 'logs';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'actions', label: 'Actions' },
  { key: 'playbooks', label: 'Playbooks' },
  { key: 'related', label: 'Related' },
  { key: 'traces', label: 'Traces' },
  { key: 'cost', label: 'Cost' },
  { key: 'logs', label: 'Logs' },
];

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '活跃' },
  { key: 'resolved', label: '已解决' },
  { key: 'postmortem', label: '复盘中' },
];

const SEV_COLOR: Record<Severity, string> = { P0: C.red, P1: C.orange, P2: C.yellow };

const STAGES: IncidentStatus[] = ['检测', '声明', '响应', '恢复', '关闭', '复盘'];

function isActive(inc: IncidentRecord): boolean {
  return inc.status === '检测' || inc.status === '声明' || inc.status === '响应' || inc.status === '恢复';
}

function isResolved(inc: IncidentRecord): boolean {
  return inc.status === '关闭';
}

function Placeholder({ label }: { label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200, color: C.text3, fontSize: 14 }}>
      {label}
    </div>
  );
}

// ── 注入P0脉冲动画 ──
let styleInjected = false;
function injectPulseStyle() {
  if (styleInjected) return;
  styleInjected = true;
  const style = document.createElement('style');
  style.textContent = `
    @keyframes incidentP0Pulse {
      0%, 100% { box-shadow: 0 0 0 2px ${C.red}33; }
      50% { box-shadow: 0 0 0 5px ${C.red}66; }
    }
  `;
  document.head.appendChild(style);
}

// ── 状态流转条 ──

function StatusFlowBar({ currentStage }: { currentStage: number }) {
  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
      {STAGES.map((stage, i) => {
        const isCurrent = i === currentStage;
        const isDone = i < currentStage;
        const bg = isCurrent ? C.orange : isDone ? C.green : C.surface3;
        const textColor = isCurrent || isDone ? '#fff' : C.text3;
        return (
          <div key={stage} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{
              padding: '4px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600,
              background: bg, color: textColor, whiteSpace: 'nowrap' as const,
            }}>{stage}</div>
            {i < STAGES.length - 1 && (
              <span style={{ color: isDone ? C.green : C.text3, fontSize: 10 }}>\u2192</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Overview Tab ──

function OverviewTab({ incident }: { incident: IncidentRecord }) {
  const sevColor = SEV_COLOR[incident.severity];
  const aiStatusColor: Record<string, string> = { '待处理': C.yellow, '进行中': C.blue, '已完成': C.green };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 信息头 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: sevColor, background: sevColor + '22', padding: '3px 10px', borderRadius: 4 }}>{incident.severity}</span>
          <span style={{ fontSize: 16, fontWeight: 700, color: C.text }}>{incident.title}</span>
        </div>
        <div style={{ marginBottom: 12 }}>
          <StatusFlowBar currentStage={incident.currentStage} />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '10px 24px', fontSize: 13 }}>
          <div>
            <div style={{ color: C.text3, fontSize: 11, marginBottom: 2 }}>MTTR</div>
            <div style={{ color: incident.mttrMinutes > 30 ? C.red : C.green, fontWeight: 700, fontSize: 18 }}>{incident.mttrMinutes}min</div>
          </div>
          <div>
            <div style={{ color: C.text3, fontSize: 11, marginBottom: 2 }}>受影响客户</div>
            <div style={{ color: C.text, fontWeight: 700, fontSize: 18 }}>{incident.affectedCustomers}</div>
          </div>
          <div>
            <div style={{ color: C.text3, fontSize: 11, marginBottom: 2 }}>受影响门店</div>
            <div style={{ color: C.text, fontWeight: 700, fontSize: 18 }}>{incident.affectedStores}</div>
          </div>
          <div>
            <div style={{ color: C.text3, fontSize: 11, marginBottom: 2 }}>受影响订单</div>
            <div style={{ color: C.text, fontWeight: 700, fontSize: 18 }}>{incident.affectedOrders}</div>
          </div>
        </div>
      </div>

      {/* 指挥链 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>指挥链</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
          {incident.commanders.map(cmd => {
            const roleColor = cmd.role.includes('指挥官') ? C.red : cmd.role.includes('记录') ? C.blue : C.green;
            return (
              <div key={cmd.role} style={{ background: C.surface2, borderRadius: 8, padding: 12, border: `1px solid ${C.border}` }}>
                <div style={{ fontSize: 11, color: roleColor, fontWeight: 600, marginBottom: 4 }}>{cmd.role}</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginBottom: 2 }}>{cmd.name}</div>
                <div style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace' }}>{cmd.contact}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Action Items */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>当前 Action Items</div>
        {incident.actionItems.length === 0 ? (
          <div style={{ fontSize: 12, color: C.text3 }}>暂无Action Items</div>
        ) : incident.actionItems.map(ai => (
          <div key={ai.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ width: 8, height: 8, borderRadius: 4, background: aiStatusColor[ai.status] || C.text3 }} />
              <span style={{ fontSize: 13, color: C.text }}>{ai.title}</span>
            </div>
            <div style={{ display: 'flex', gap: 12, fontSize: 11, color: C.text3 }}>
              <span>{ai.assignee}</span>
              <span>{ai.dueDate}</span>
              <span style={{ color: aiStatusColor[ai.status] || C.text3, fontWeight: 600 }}>{ai.status}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Timeline Tab ──

function TimelineTab({ incident }: { incident: IncidentRecord }) {
  const sourceColor: Record<string, string> = { system: C.blue, human: C.orange, ai: C.purple };
  const sourceLabel: Record<string, string> = { system: '系统', human: '人工', ai: 'AI' };

  return (
    <div style={{ position: 'relative', paddingLeft: 24 }}>
      <div style={{ position: 'absolute', left: 7, top: 4, bottom: 4, width: 2, background: C.border }} />
      {incident.timeline.map((entry, i) => {
        const sc = sourceColor[entry.source] || C.text3;
        return (
          <div key={entry.id} style={{ display: 'flex', gap: 12, marginBottom: i < incident.timeline.length - 1 ? 20 : 0, position: 'relative' }}>
            <div style={{
              position: 'absolute', left: -20, top: 2, width: 16, height: 16, borderRadius: 8,
              background: sc + '33', border: `2px solid ${sc}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <span style={{ width: 6, height: 6, borderRadius: 3, background: sc }} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                <span style={{ fontSize: 12, fontFamily: 'monospace', color: C.text2, fontWeight: 600 }}>{entry.time}</span>
                <span style={{ fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 3, background: sc + '22', color: sc }}>{sourceLabel[entry.source]}</span>
                <span style={{ fontSize: 11, color: C.text3 }}>[{entry.actor}]</span>
              </div>
              <div style={{ fontSize: 13, color: C.text }}>{entry.description}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Actions Tab ──

function ActionsTab({ incident }: { incident: IncidentRecord }) {
  const actions = [
    { icon: '\uD83D\uDCE2', title: '升级严重度', desc: `当前 ${incident.severity}`, color: C.red },
    { icon: '\uD83D\uDC64', title: '变更指挥官', desc: `当前IC: ${incident.commanders[0]?.name || '-'}`, color: C.blue },
    { icon: '\uD83D\uDD04', title: '执行回滚', desc: '回滚最近变更', color: C.orange },
    { icon: '\uD83D\uDCDD', title: '添加更新', desc: '向时间线添加手动更新', color: C.yellow },
    { icon: '\u2705', title: '关闭Incident', desc: '确认恢复并关闭', color: C.green },
    { icon: '\uD83D\uDCCB', title: '生成Postmortem', desc: '基于时间线自动生成复盘报告', color: C.purple },
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

// ── Playbooks Tab (Postmortem) ──

function PlaybooksTab({ incident }: { incident: IncidentRecord }) {
  const aiStatusColor: Record<string, string> = { '待处理': C.yellow, '进行中': C.blue, '已完成': C.green };
  const pbStatusColor: Record<string, string> = { '已触发': C.yellow, '运行中': C.blue, '已完成': C.green };
  const pm = incident.postmortem;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Postmortem 草稿 */}
      {pm ? (
        <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>Postmortem 报告</div>

          {/* 摘要 */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, color: C.text3, marginBottom: 4 }}>摘要</div>
            <div style={{ fontSize: 13, color: C.text, background: C.surface2, padding: 12, borderRadius: 6 }}>{pm.summary}</div>
          </div>

          {/* 根因 */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, color: C.text3, marginBottom: 4 }}>根因分析</div>
            <div style={{ fontSize: 13, color: C.text, background: C.surface2, padding: 12, borderRadius: 6 }}>{pm.rootCause}</div>
          </div>

          {/* 5 Why */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, color: C.text3, marginBottom: 4 }}>5 Whys</div>
            <div style={{ background: C.surface2, borderRadius: 6, padding: 12 }}>
              {pm.fiveWhys.map((w, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, marginBottom: i < pm.fiveWhys.length - 1 ? 8 : 0 }}>
                  <span style={{ fontSize: 12, color: C.orange, fontWeight: 700, minWidth: 50 }}>Why {i + 1}</span>
                  <span style={{ fontSize: 12, color: C.text }}>{w}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Action Items */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, color: C.text3, marginBottom: 4 }}>Action Items</div>
            {pm.actionItems.map(ai => (
              <div key={ai.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: `1px solid ${C.border}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 4, background: aiStatusColor[ai.status] || C.text3 }} />
                  <span style={{ fontSize: 12, color: C.text }}>{ai.title}</span>
                </div>
                <div style={{ display: 'flex', gap: 10, fontSize: 11, color: C.text3 }}>
                  <span>{ai.assignee}</span>
                  <span>{ai.dueDate}</span>
                  <span style={{ color: aiStatusColor[ai.status] || C.text3, fontWeight: 600 }}>{ai.status}</span>
                </div>
              </div>
            ))}
          </div>

          {/* 改进措施 */}
          <div>
            <div style={{ fontSize: 12, color: C.text3, marginBottom: 4 }}>改进措施</div>
            <div style={{ background: C.surface2, borderRadius: 6, padding: 12 }}>
              {pm.improvements.map((imp, i) => (
                <div key={i} style={{ fontSize: 12, color: C.text, marginBottom: i < pm.improvements.length - 1 ? 6 : 0, display: 'flex', gap: 6 }}>
                  <span style={{ color: C.green }}>*</span> {imp}
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div style={{ background: C.surface, borderRadius: 10, padding: 24, border: `1px solid ${C.border}`, textAlign: 'center' }}>
          <div style={{ fontSize: 14, color: C.text3, marginBottom: 12 }}>Postmortem 尚未生成</div>
          <button style={{
            background: C.purple, color: '#fff', border: 'none', borderRadius: 6,
            padding: '8px 20px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
          }}>生成 Postmortem</button>
        </div>
      )}

      {/* 关联Playbook */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>关联 Playbook</div>
        {incident.relatedPlaybooks.length === 0 ? (
          <div style={{ fontSize: 12, color: C.text3 }}>暂无关联Playbook</div>
        ) : incident.relatedPlaybooks.map(pb => (
          <div key={pb.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
            <span style={{ fontSize: 13, color: C.text }}>{pb.name}</span>
            <span style={{ fontSize: 11, color: pbStatusColor[pb.status] || C.text3, fontWeight: 600 }}>{pb.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Related Tab ──

function RelatedTab({ incident }: { incident: IncidentRecord }) {
  const svcStatusColor: Record<string, string> = { '降级': C.yellow, '不可用': C.red, '已恢复': C.green };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 受影响客户 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>受影响客户 ({incident.affectedCustomerList.length})</div>
        {incident.affectedCustomerList.map(c => (
          <div key={c.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{c.name}</span>
              <span style={{ fontSize: 11, color: C.text3 }}>{c.stores}家门店</span>
            </div>
            <span style={{ fontSize: 11, color: C.red }}>{c.impact}</span>
          </div>
        ))}
      </div>

      {/* 受影响服务 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>受影响服务 ({incident.affectedServices.length})</div>
        {incident.affectedServices.map(s => (
          <div key={s.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: C.text, fontFamily: 'monospace' }}>{s.name}</span>
            <span style={{ fontSize: 11, color: svcStatusColor[s.status] || C.text3, fontWeight: 600 }}>{s.status}</span>
          </div>
        ))}
      </div>

      {/* 触发的Playbook */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>触发的 Playbook ({incident.relatedPlaybooks.length})</div>
        {incident.relatedPlaybooks.length === 0 ? (
          <div style={{ fontSize: 12, color: C.text3 }}>暂无</div>
        ) : incident.relatedPlaybooks.map(pb => (
          <div key={pb.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
            <span style={{ fontSize: 13, color: C.text }}>{pb.name}</span>
            <span style={{ fontSize: 11, color: C.green, fontWeight: 600 }}>{pb.status}</span>
          </div>
        ))}
      </div>

      {/* 相关工单 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>相关工单 ({incident.relatedTickets.length})</div>
        {incident.relatedTickets.length === 0 ? (
          <div style={{ fontSize: 12, color: C.text3 }}>暂无</div>
        ) : incident.relatedTickets.map(t => (
          <div key={t.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 12, fontFamily: 'monospace', color: C.text3 }}>{t.id}</span>
              <span style={{ fontSize: 13, color: C.text }}>{t.title}</span>
            </div>
            <span style={{ fontSize: 11, color: C.blue, fontWeight: 600 }}>{t.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Export ──

export function IncidentsWorkspace() {
  const [incidents, setIncidents] = useState<IncidentRecord[]>(MOCK_INCIDENTS);
  const [selected, setSelected] = useState<IncidentRecord | null>(null);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [tab, setTab] = useState<TabKey>('overview');

  useEffect(() => { injectPulseStyle(); }, []);

  useEffect(() => {
    hubGet<IncidentRecord[]>('/incidents')
      .then(data => { if (Array.isArray(data) && data.length > 0) setIncidents(data); })
      .catch(() => { /* 使用 Mock */ });
  }, []);

  const filtered = useMemo(() => {
    switch (filter) {
      case 'active':
        return incidents.filter(isActive);
      case 'resolved':
        return incidents.filter(isResolved);
      case 'postmortem':
        return incidents.filter(inc => inc.status === '复盘');
      default:
        return incidents;
    }
  }, [incidents, filter]);

  const counts = useMemo(() => {
    const m: Record<string, number> = { all: incidents.length };
    for (const inc of incidents) {
      if (isActive(inc)) m['active'] = (m['active'] || 0) + 1;
      if (isResolved(inc)) m['resolved'] = (m['resolved'] || 0) + 1;
      if (inc.status === '复盘') m['postmortem'] = (m['postmortem'] || 0) + 1;
    }
    return m;
  }, [incidents]);

  // 排序：P0 > P1 > P2, 活跃优先, 然后按时间降序
  const sorted = useMemo(() => {
    const sevOrder: Record<string, number> = { P0: 0, P1: 1, P2: 2 };
    return [...filtered].sort((a, b) => {
      const aActive = isActive(a) ? 0 : 1;
      const bActive = isActive(b) ? 0 : 1;
      if (aActive !== bActive) return aActive - bActive;
      const sevDiff = (sevOrder[a.severity] ?? 3) - (sevOrder[b.severity] ?? 3);
      if (sevDiff !== 0) return sevDiff;
      return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
    });
  }, [filtered]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', color: C.text }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: C.text, marginBottom: 16 }}>事件</div>

      <div style={{ display: 'flex', gap: 16, flex: 1, minHeight: 0 }}>
        {/* 左侧列表 */}
        <div style={{ width: 400, flexShrink: 0, display: 'flex', flexDirection: 'column', background: C.surface, borderRadius: 10, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
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
            {sorted.map(inc => {
              const isActiveItem = selected?.id === inc.id;
              const sevColor = SEV_COLOR[inc.severity];
              const statusLabel = isActive(inc) ? '活跃' : inc.status === '复盘' ? '复盘中' : '已解决';
              const statusColor = isActive(inc) ? C.red : inc.status === '复盘' ? C.yellow : C.green;
              return (
                <div key={inc.id} onClick={() => { setSelected(inc); setTab('overview'); }} style={{
                  padding: '10px 14px', cursor: 'pointer',
                  borderLeft: isActiveItem ? `3px solid ${C.orange}` : '3px solid transparent',
                  background: isActiveItem ? C.orange + '0D' : 'transparent',
                  borderBottom: `1px solid ${C.border}`, transition: 'background 0.15s',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{
                      width: 10, height: 10, borderRadius: 5, background: sevColor, flexShrink: 0,
                      ...(inc.severity === 'P0' && isActive(inc) ? { animation: 'incidentP0Pulse 1.5s ease-in-out infinite' } : {}),
                    }} />
                    <span style={{ fontSize: 12, fontFamily: 'monospace', color: C.text3 }}>{inc.code}</span>
                    <span style={{ fontSize: 11, color: statusColor, fontWeight: 600, background: statusColor + '18', padding: '1px 6px', borderRadius: 4 }}>{statusLabel}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingLeft: 18 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: C.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const, maxWidth: 240 }}>{inc.title}</span>
                    <span style={{ fontSize: 11, color: C.text3, flexShrink: 0 }}>MTTR {inc.mttrMinutes}min</span>
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
              选择一个事件查看详情
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                <span style={{
                  width: 10, height: 10, borderRadius: 5, background: SEV_COLOR[selected.severity],
                  ...(selected.severity === 'P0' && isActive(selected) ? { animation: 'incidentP0Pulse 1.5s ease-in-out infinite' } : {}),
                }} />
                <span style={{ fontSize: 16, fontWeight: 700, color: C.text }}>{selected.code}</span>
                <span style={{ fontSize: 12, color: C.text3 }}>{selected.title}</span>
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
                {tab === 'overview' && <OverviewTab incident={selected} />}
                {tab === 'timeline' && <TimelineTab incident={selected} />}
                {tab === 'actions' && <ActionsTab incident={selected} />}
                {tab === 'playbooks' && <PlaybooksTab incident={selected} />}
                {tab === 'related' && <RelatedTab incident={selected} />}
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
