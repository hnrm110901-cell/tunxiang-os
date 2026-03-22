/**
 * useTxAPI — 统一数据获取 hook
 *
 * 所有 API 调用通过此 hook，自动处理：
 * - X-Tenant-ID header 注入
 * - 统一响应格式解析 { ok, data, error }
 * - 加载状态管理
 * - 错误处理
 */
import { useState, useCallback } from 'react';
import { getMacMiniUrl } from '../bridge/TXBridge';

interface TxResponse<T> {
  ok: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
}

interface UseTxAPIResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  fetch: (path: string, options?: RequestInit) => Promise<T | null>;
  post: (path: string, body: unknown) => Promise<T | null>;
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

async function txFetch<T>(path: string, options: RequestInit = {}): Promise<TxResponse<T>> {
  const url = `${BASE_URL || getMacMiniUrl()}${path}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
    ...(options.headers as Record<string, string> || {}),
  };

  const resp = await window.fetch(url, { ...options, headers });
  return resp.json();
}

export function useTxAPI<T = unknown>(): UseTxAPIResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (path: string, options: RequestInit = {}): Promise<T | null> => {
    setLoading(true);
    setError(null);
    try {
      const result = await txFetch<T>(path, options);
      if (result.ok) {
        setData(result.data);
        return result.data;
      } else {
        setError(result.error?.message || 'Unknown error');
        return null;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Network error');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const post = useCallback(async (path: string, body: unknown): Promise<T | null> => {
    return fetchData(path, { method: 'POST', body: JSON.stringify(body) });
  }, [fetchData]);

  return { data, loading, error, fetch: fetchData, post };
}
