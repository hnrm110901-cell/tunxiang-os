/**
 * web-reception 统一 API 客户端
 * 迎宾/前台所有页面通过此文件调用后端。
 */

// ─── 基础配置 ───

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

export async function txFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
      ...(options?.headers as Record<string, string> || {}),
    },
  });
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data;
}

// ─── 各域 API 统一导出 ───

export * from './reservationApi';
export * from './queueApi';
export * from './tablesApi';
export * from './memberDepthApi';
