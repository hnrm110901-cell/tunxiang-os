/**
 * web-reception 统一 API 客户端
 * 迎宾/前台所有页面通过此文件调用后端。
 */

// ─── 基础配置 ───

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

export const STORE_TOKEN_KEY = 'tx_store_token';
export const getStoreToken = () => localStorage.getItem(STORE_TOKEN_KEY);
export const setStoreToken = (token: string) => localStorage.setItem(STORE_TOKEN_KEY, token);
export const clearStoreToken = () => localStorage.removeItem(STORE_TOKEN_KEY);

export async function txFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getStoreToken();
  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
      ...(options?.headers as Record<string, string> || {}),
    },
  });
  if (resp.status === 401) {
    clearStoreToken();
    window.location.reload();
    throw new Error('认证已过期');
  }
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data;
}

// ─── 各域 API 统一导出 ───

export * from './reservationApi';
export * from './queueApi';
export * from './tablesApi';
export * from './memberDepthApi';
