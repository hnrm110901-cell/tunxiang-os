/** 演示环境监控面板 API — Gap C-04 */

import { txFetchData } from './client';

export interface HealthCheck {
  name: string;
  count: number;
  ok: boolean;
}

export interface MerchantHealth {
  merchant_code: string;
  merchant_name: string;
  service: string;
  status: 'healthy' | 'degraded' | 'error';
  db_connected: boolean;
  data_quality_score: number;
  grade: string;
  last_seed_at: string | null;
  checks: HealthCheck[];
}

export interface DemoHealthResponse {
  ok: boolean;
  data: MerchantHealth[];
}

export interface ServiceInfo {
  name: string;
  port: number;
  status: string;
  note: string;
}

export interface DemoServicesResponse {
  ok: boolean;
  data: {
    services: ServiceInfo[];
    analytics_quality_url: string;
    demo_monitor_health_url: string;
  };
}

export async function fetchDemoHealth(): Promise<DemoHealthResponse> {
  return txFetchData<DemoHealthResponse>('/api/v1/analytics/demo-monitor/health');
}

export async function fetchDemoServices(): Promise<DemoServicesResponse> {
  return txFetchData<DemoServicesResponse>('/api/v1/analytics/demo-monitor/services');
}
