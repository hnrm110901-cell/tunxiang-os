/**
 * 屯象OS 统一 API 客户端 — JWT 认证版
 */
import { useState, useEffect, useCallback } from 'react';

interface JWTPayload {
  user_id: string;
  tenant_id: string;
  role: string;
  merchant_name: string;
  exp: number;
  iat: number;
}

function decodeJWT(token: string): JWTPayload | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1];
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    const jsonStr = decodeURIComponent(
      atob(base64).split('').map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join('')
    );
    return JSON.parse(jsonStr);
  } catch {
    return null;
  }
}

const TOKEN_KEY = 'tx_token';
const USER_KEY = 'tx_user';

export function getToken(): string | null { return localStorage.getItem(TOKEN_KEY); }
export function setToken(token: string): void { localStorage.setItem(TOKEN_KEY, token); }
export function clearAuth(): void { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); }
export function getTokenPayload(): JWTPayload | null { const token = getToken(); if (!token) return null; return decodeJWT(token); }
export function getTenantId(): string | null { return getTokenPayload()?.tenant_id ?? null; }
export function isTokenExpired(): boolean { const payload = getTokenPayload(); if (!payload) return true; return Date.now() / 1000 > payload.exp; }

export interface TxResponse<T> { ok: boolean; data: T | null; error: { code: string; message: string } | null; }

export class TxApiError extends Error {
  code: string;
  statusCode: number;
  constructor(message: string, code: string, statusCode: number) {
    super(message); this.name = 'TxApiError'; this.code = code; this.statusCode = statusCode;
  }
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export async function txFetch<T>(path: string, options?: RequestInit): Promise<TxResponse<T>> {
  const token = getToken();
  const tenantId = getTenantId();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
    ...((options?.headers as Record<string, string>) || {}),
  };
  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (resp.status === 401) {
    clearAuth(); window.location.reload();
    throw new TxApiError('认证已过期', 'UNAUTHORIZED', 401);
  }
  const json: TxResponse<T> = await resp.json();
  if (!json.ok) {
    throw new TxApiError(json.error?.message || 'API Error', json.error?.code || 'UNKNOWN', resp.status);
  }
  return json;
}

export async function txFetchData<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await txFetch<T>(path, options);
  return resp.data as T;
}

/** 便捷方法：GET，返回 data 字段 */
export async function apiGet<T>(path: string): Promise<T> {
  return txFetchData<T>(path);
}

/** 便捷方法：POST，返回 data 字段 */
export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return txFetchData<T>(path, {
    method: 'POST',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

/** 便捷方法：PATCH，返回 data 字段 */
export async function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  return txFetchData<T>(path, {
    method: 'PATCH',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

/** 兼容别名 */
export { TxApiError as ApiError };
export type ApiRequestOptions = RequestInit;

/** 通用请求（兼容旧调用），返回完整 TxResponse */
export async function apiRequest<T>(path: string, options?: RequestInit): Promise<TxResponse<T>> {
  return txFetch<T>(path, options);
}

interface UseTxAPIResult<T> { data: T | null; loading: boolean; error: string | null; refetch: () => void; }

export function useTxAPI<T>(path: string, deps: unknown[] = []): UseTxAPIResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [trigger, setTrigger] = useState(0);
  const refetch = useCallback(() => setTrigger((t) => t + 1), []);
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    txFetch<T>(path).then((resp) => { if (!cancelled) { setData(resp.data); setLoading(false); } })
      .catch((err: unknown) => { if (!cancelled) { setError(err instanceof Error ? err.message : 'Unknown error'); setLoading(false); } });
    return () => { cancelled = true; };
  }, [path, trigger, ...deps]);
  return { data, loading, error, refetch };
}
