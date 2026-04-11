/**
 * 集成健康中心 API — 旧系统适配器 & Webhook 监控
 */
import { txFetchData } from './client';

// ─── 类型定义 ───

export type AdapterStatus = 'online' | 'degraded' | 'offline';

export interface AdapterHealth {
  adapter_id: string;
  name: string;
  status: AdapterStatus;
  last_sync_at: string;
  sync_delay_seconds: number;
  today_synced: {
    orders: number;
    members: number;
    dishes: number;
  };
  recent_failures: number;
  error_rate_24h: number;
  config: {
    sync_interval_seconds: number;
    api_endpoint: string;
    auth_type: string;
  };
  recent_logs: {
    time: string;
    event: string;
    status: 'success' | 'failure';
    duration_ms: number;
    error?: string;
  }[];
  daily_volumes: { date: string; count: number }[];
}

export interface WebhookEvent {
  id: string;
  source: string;
  event_type: string;
  received_at: string;
  status: 'processed' | 'failed' | 'pending';
  response_ms: number;
  payload_size: number;
}

// ─── API 调用 ───

/** 获取所有适配器健康状态 */
export async function fetchIntegrationHealth(): Promise<AdapterHealth[]> {
  return txFetchData<AdapterHealth[]>('/api/v1/platform/integrations/health');
}

/** 获取单个适配器详情 */
export async function fetchAdapterDetail(adapterId: string): Promise<AdapterHealth> {
  return txFetchData<AdapterHealth>(`/api/v1/platform/integrations/${encodeURIComponent(adapterId)}/detail`);
}

/** 手动重试适配器同步 */
export async function retryAdapterSync(adapterId: string): Promise<{ task_id: string; status: string }> {
  return txFetchData<{ task_id: string; status: string }>(
    `/api/v1/platform/integrations/${encodeURIComponent(adapterId)}/retry`,
    { method: 'POST' },
  );
}

/** 获取最近 Webhook 事件 */
export async function fetchRecentWebhooks(limit = 50): Promise<WebhookEvent[]> {
  return txFetchData<WebhookEvent[]>(`/api/v1/platform/webhooks/recent?limit=${limit}`);
}
