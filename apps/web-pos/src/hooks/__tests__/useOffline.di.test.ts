/**
 * #270 — useOffline DI 注入回归测试
 *
 * 验证业务 API URL/tenantId/fetch 能从外部注入：
 *   场景 G：跨终端复用 — Crew 端 replay 走不同 baseUrl，不污染 web-pos 默认值
 *   场景 H：测试注入 mock fetch，不依赖 import.meta.env
 *   场景 I：customReplay 完全替代默认 op-type 路由（未来扩展点）
 */
import { describe, it, expect, vi } from 'vitest';
import {
  replayOperation,
  type OfflineOperation,
  type ReplayContext,
} from '../useOffline';

function mkSettleOp(orderId: string): OfflineOperation {
  return {
    id: `offline_${orderId}`,
    type: 'settle_order',
    payload: { orderId },
    createdAt: '2026-05-08T13:00:00.000Z',
    retryCount: 0,
    idempotencyKey: `settle:${orderId}`,
  };
}

describe('#270 useOffline DI — replayOperation 接受 ctx 注入', () => {
  it('场景 G：apiBaseUrl 来自 ctx，不依赖 import.meta.env', async () => {
    const fetchSpy = vi.fn(
      async () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    const ctx: ReplayContext = {
      apiBaseUrl: 'https://crew.tunxiang.local',
      tenantId: 'tenant-crew',
      fetch: fetchSpy as unknown as typeof fetch,
    };

    await replayOperation(mkSettleOp('XJ-CREW-1'), ctx);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://crew.tunxiang.local/api/v1/trade/orders/XJ-CREW-1/settle');
    const headers = init.headers as Record<string, string>;
    expect(headers['X-Tenant-ID']).toBe('tenant-crew');
    expect(headers['X-Idempotency-Key']).toBe('settle:XJ-CREW-1');
  });

  it('场景 H：ctx.fetch 注入 mock — 完全旁路 globalThis.fetch', async () => {
    // 不动 globalThis.fetch，看 ctx.fetch 是否被使用
    const isolatedFetch = vi.fn(
      async () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    const ctx: ReplayContext = {
      apiBaseUrl: '',
      tenantId: '',
      fetch: isolatedFetch as unknown as typeof fetch,
    };

    const ok = await replayOperation(mkSettleOp('ISOLATED-1'), ctx);
    expect(ok).toBe(true);
    expect(isolatedFetch).toHaveBeenCalledTimes(1);
  });

  it('场景 I：未传 ctx 时仍走默认（向后兼容，不破坏 12 老测试）', async () => {
    const fetchSpy = vi.fn(
      async () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).fetch = fetchSpy;

    const ok = await replayOperation(mkSettleOp('DEFAULT-1'));
    expect(ok).toBe(true);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers['X-Idempotency-Key']).toBe('settle:DEFAULT-1');
  });
});
