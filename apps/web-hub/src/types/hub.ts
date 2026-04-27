/**
 * Hub v2.0 — 核心类型定义
 * 工作模式导航 + 8 Workspace + Object Page
 */

/* ─── 工作模式枚举 ─── */
export type WorkMode = 'today' | 'stream' | 'workspaces' | 'playbooks';

/* ─── Workspace 类型 ─── */
export type WorkspaceType =
  | 'customers'
  | 'stores'
  | 'edges'
  | 'services'
  | 'adapters'
  | 'agents'
  | 'migrations'
  | 'incidents';

export const WORKSPACE_META: Record<WorkspaceType, { label: string; icon: string }> = {
  customers:  { label: '客户',     icon: '🏢' },
  stores:     { label: '门店',     icon: '🏪' },
  edges:      { label: '边缘',     icon: '🖥' },
  services:   { label: '服务',     icon: '⚙️' },
  adapters:   { label: '适配器',   icon: '🔌' },
  agents:     { label: 'Agent',   icon: '🤖' },
  migrations: { label: '迁移',     icon: '📋' },
  incidents:  { label: '事件',     icon: '🚨' },
};

/* ─── Object Page Tab ─── */
export type ObjectPageTab =
  | 'overview'
  | 'config'
  | 'health'
  | 'events'
  | 'metrics'
  | 'logs'
  | 'related'
  | 'actions';

export const OBJECT_PAGE_TABS: { key: ObjectPageTab; label: string }[] = [
  { key: 'overview', label: '概览' },
  { key: 'config',   label: '配置' },
  { key: 'health',   label: '健康' },
  { key: 'events',   label: '事件' },
  { key: 'metrics',  label: '指标' },
  { key: 'logs',     label: '日志' },
  { key: 'related',  label: '关联' },
  { key: 'actions',  label: '操作' },
];

/* ─── 健康度评分 ─── */
export interface HealthScore {
  score: number;       // 0-100
  level: 'healthy' | 'warning' | 'critical' | 'unknown';
  factors: { name: string; score: number; weight: number }[];
  updated_at: string;  // ISO 8601
}

/* ─── 实时事件流 ─── */
export type StreamEventSeverity = 'info' | 'warn' | 'error' | 'critical';

export interface StreamEvent {
  id: string;
  timestamp: string;
  source_service: string;
  event_type: string;
  severity: StreamEventSeverity;
  workspace: WorkspaceType;
  object_id?: string;
  object_name?: string;
  title: string;
  detail?: string;
  tenant_id: string;
}

/* ─── 通用列表项（ListPanel 使用） ─── */
export interface ListItem {
  id: string;
  name: string;
  status: 'online' | 'offline' | 'warning' | 'error' | 'pending' | 'unknown';
  subtitle?: string;
  meta?: string;
  health_score?: number;
}

/* ─── Workspace 对象接口 ─── */

export interface Customer {
  id: string;
  name: string;
  brand_name: string;
  status: 'active' | 'trial' | 'suspended' | 'churned';
  store_count: number;
  contract_end: string;
  health: HealthScore;
  created_at: string;
}

export interface Store {
  id: string;
  name: string;
  customer_id: string;
  customer_name: string;
  city: string;
  status: 'online' | 'offline' | 'maintenance';
  edge_id?: string;
  daily_revenue_fen: number;
  health: HealthScore;
}

export interface Edge {
  id: string;
  hostname: string;
  store_id: string;
  store_name: string;
  model: string;            // e.g. "Mac mini M4 16GB"
  os_version: string;
  tailscale_ip: string;
  status: 'online' | 'offline' | 'degraded';
  cpu_pct: number;
  mem_pct: number;
  disk_pct: number;
  last_seen: string;
  sync_lag_sec: number;
  health: HealthScore;
}

export interface Service {
  id: string;
  name: string;             // e.g. "tx-trade"
  port: number;
  version: string;
  status: 'running' | 'stopped' | 'error';
  instance_count: number;
  p99_ms: number;
  error_rate_pct: number;
  health: HealthScore;
}

export interface Adapter {
  id: string;
  name: string;             // e.g. "品智POS"
  adapter_type: string;
  customer_id: string;
  customer_name: string;
  status: 'active' | 'error' | 'disabled';
  last_sync: string;
  sync_success_rate: number;
  health: HealthScore;
}

export interface Agent {
  id: string;
  name: string;             // e.g. "折扣守护"
  agent_type: string;
  run_location: 'edge' | 'cloud' | 'both';
  status: 'running' | 'idle' | 'error' | 'disabled';
  last_decision_at: string;
  decision_count_24h: number;
  confidence_avg: number;
  health: HealthScore;
}

export interface Migration {
  id: string;
  name: string;
  customer_id: string;
  customer_name: string;
  source_system: string;
  status: 'planned' | 'in_progress' | 'validating' | 'completed' | 'failed';
  progress_pct: number;
  started_at?: string;
  completed_at?: string;
}

export interface Incident {
  id: string;
  title: string;
  severity: 'P0' | 'P1' | 'P2' | 'P3';
  status: 'open' | 'investigating' | 'mitigated' | 'resolved';
  workspace: WorkspaceType;
  object_id?: string;
  object_name?: string;
  assignee?: string;
  created_at: string;
  resolved_at?: string;
}

/* ─── Today 模式 ─── */
export interface TodayItem {
  id: string;
  type: 'todo' | 'alert' | 'incident' | 'renewal';
  title: string;
  detail?: string;
  severity?: StreamEventSeverity;
  workspace?: WorkspaceType;
  object_id?: string;
  due_at?: string;
  created_at: string;
}

/* ─── Playbook ─── */
export interface Playbook {
  id: string;
  name: string;
  description: string;
  category: string;
  step_count: number;
  last_run?: string;
  status: 'draft' | 'active' | 'archived';
}

/* ─── Hub API 响应类型 ─── */
export interface HubEnvelope<T = unknown> {
  ok: boolean;
  data?: T;
  error?: { code?: string; message?: string };
}

export interface HubPaginatedResponse<T> {
  items: T[];
  total: number;
}

/* ─── Stream 连接状态 ─── */
export type StreamConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';
