/**
 * Hub 运维 API — 网关前缀 /api/v1/hub/*
 * 开发时由 Vite 代理至 localhost:8000
 */

export const HUB_API_PREFIX = '/api/v1/hub';

export class HubApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly body?: unknown,
  ) {
    super(message);
    this.name = 'HubApiError';
  }
}

type HubEnvelope = { ok: boolean; data?: unknown; error?: { message?: string } };

export async function hubGet<T>(path: string, init?: RequestInit): Promise<T> {
  const p = path.startsWith('/') ? path : `/${path}`;
  const res = await fetch(`${HUB_API_PREFIX}${p}`, {
    ...init,
    method: 'GET',
    headers: { Accept: 'application/json', ...init?.headers },
  });
  const body = (await res.json()) as HubEnvelope;
  if (!res.ok) {
    throw new HubApiError(body.error?.message || `HTTP ${res.status}`, res.status, body);
  }
  if (!body.ok) {
    throw new HubApiError(body.error?.message || 'Hub 返回失败', res.status, body);
  }
  return body.data as T;
}

export async function hubPost<T>(path: string, jsonBody?: unknown, init?: RequestInit): Promise<T> {
  const p = path.startsWith('/') ? path : `/${path}`;
  const res = await fetch(`${HUB_API_PREFIX}${p}`, {
    ...init,
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...init?.headers,
    },
    body: jsonBody !== undefined ? JSON.stringify(jsonBody) : undefined,
  });
  const body = (await res.json()) as HubEnvelope;
  if (!res.ok) {
    throw new HubApiError(body.error?.message || `HTTP ${res.status}`, res.status, body);
  }
  if (!body.ok) {
    throw new HubApiError(body.error?.message || 'Hub 返回失败', res.status, body);
  }
  return body.data as T;
}

/** 列表分页通用结构 */
export type HubListResult<T> = { items: T[]; total: number };
