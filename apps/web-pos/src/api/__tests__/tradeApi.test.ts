/**
 * Tier 1 测试：tradeApi — txFetch 硬化
 * - 3s 超时
 * - 错误码语义化映射
 * - X-Request-Id
 * - navigator.onLine=false 时转离线
 * - { ok, data, error } 标准响应
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { txFetchTrade } from '../tradeApi';

type FetchSpy = ReturnType<typeof vi.fn>;

function installFetch(impl: FetchSpy): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).fetch = impl;
}

function setOnline(value: boolean): void {
  Object.defineProperty(navigator, 'onLine', { configurable: true, value });
}

describe('tradeApi.txFetchTrade — Tier1 收银硬化', () => {
  beforeEach(() => {
    setOnline(true);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('txFetch 在 3 秒内无响应返回 NET_TIMEOUT', async () => {
    vi.useFakeTimers();
    const fetchSpy: FetchSpy = vi.fn((_url: string, init?: RequestInit) => {
      return new Promise((_resolve, reject) => {
        const signal = init?.signal;
        if (signal) {
          signal.addEventListener('abort', () => {
            const err = new DOMException('The operation was aborted', 'AbortError');
            reject(err);
          });
        }
      });
    });
    installFetch(fetchSpy);

    const pending = txFetchTrade('/api/v1/trade/orders/x/settle', { method: 'POST' });
    await vi.advanceTimersByTimeAsync(3100);
    const res = await pending;
    expect(res.ok).toBe(false);
    expect(res.error?.code).toBe('NET_TIMEOUT');
    expect(res.error?.timeout_ms).toBe(3000);
  });

  it('后端返回 500 返回 SERVER_5XX', async () => {
    const fetchSpy: FetchSpy = vi.fn(async () => new Response('{"ok":false}', { status: 500 }));
    installFetch(fetchSpy);
    const res = await txFetchTrade('/api/v1/trade/orders');
    expect(res.ok).toBe(false);
    expect(res.error?.code).toBe('SERVER_5XX');
  });

  it('后端返回业务错误 400 返回 BUSINESS_REJECT', async () => {
    const body = JSON.stringify({ ok: false, error: { code: 'TABLE_LOCKED', message: '桌台已锁定' } });
    const fetchSpy: FetchSpy = vi.fn(async () => new Response(body, { status: 400 }));
    installFetch(fetchSpy);
    const res = await txFetchTrade('/api/v1/trade/orders');
    expect(res.ok).toBe(false);
    expect(res.error?.code).toBe('BUSINESS_REJECT');
    expect(res.error?.message).toContain('桌台已锁定');
  });

  it('离线模式（navigator.onLine=false）返回 OFFLINE_QUEUED', async () => {
    setOnline(false);
    const fetchSpy: FetchSpy = vi.fn(async () => {
      throw new Error('不应被调用');
    });
    installFetch(fetchSpy);
    const res = await txFetchTrade('/api/v1/trade/orders', { method: 'POST' });
    expect(res.ok).toBe(false);
    expect(res.error?.code).toBe('OFFLINE_QUEUED');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('每个请求自动加 X-Request-Id UUID header', async () => {
    const fetchSpy: FetchSpy = vi.fn(async () => new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 }));
    installFetch(fetchSpy);
    await txFetchTrade('/api/v1/trade/orders');
    const headers = fetchSpy.mock.calls[0][1].headers as Record<string, string>;
    expect(headers['X-Request-Id']).toBeTruthy();
    expect(headers['X-Request-Id']).toMatch(/^[0-9a-f-]{8,}/i);
  });

  it('成功响应返回 { ok:true, data: <payload> }', async () => {
    const body = JSON.stringify({ ok: true, data: { order_id: 'o-1', order_no: 'T0001' } });
    const fetchSpy: FetchSpy = vi.fn(async () => new Response(body, { status: 200 }));
    installFetch(fetchSpy);
    const res = await txFetchTrade<{ order_id: string; order_no: string }>('/api/v1/trade/orders');
    expect(res.ok).toBe(true);
    expect(res.data?.order_id).toBe('o-1');
    expect(res.data?.order_no).toBe('T0001');
  });
});
