/**
 * Sprint C3 前端契约测试 — KDS delta polling + heartbeat + retry。
 * 只测 API 契约层（不测 IndexedDB / connectionHealth UI / Playwright E2E）。
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

import {
  ALLOWED_DEVICE_KINDS,
  pollOrdersDelta,
  pollOrdersDeltaWithRetry,
  sendHeartbeat,
  type KDSDeltaResponse,
  type HeartbeatResponse,
} from '../kdsDeltaApi';

// 测试用 tenant / store / device
const XUJI_17_TENANT = '00000000-0000-0000-0000-0000000000a1';
const STORE_17 = '00000000-0000-0000-0000-000000000017';
const KDS_DEVICE = 'kds-xuji-17-fryer-01';

// ─── fetch mock helper ──────────────────────────────────────────────────────

function mockFetchOnce(body: unknown, init: { status?: number } = {}) {
  const resp = {
    ok: (init.status ?? 200) < 400,
    status: init.status ?? 200,
    json: async () => body,
  };
  (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    resp as unknown as Response,
  );
}

function mockFetchSequence(entries: Array<{ body: unknown; status?: number }>) {
  for (const e of entries) {
    mockFetchOnce(e.body, { status: e.status });
  }
}

beforeEach(() => {
  globalThis.fetch = vi.fn() as unknown as typeof fetch;
  // 默认 tenant header 不注入（TENANT_ID 为空）；通过 Authorization 亦可
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ─── 场景 1：首次拉取无 cursor ───────────────────────────────────────────────

describe('pollOrdersDelta — 徐记 17 号店首次拉取', () => {
  it('不带 cursor 时 URL 无 cursor 参数，后端返回 next_cursor 供下一轮使用', async () => {
    const payload: KDSDeltaResponse = {
      orders: [
        {
          tenant_id: XUJI_17_TENANT,
          id: 'o-1',
          order_no: 'TX20260424001',
          store_id: STORE_17,
          status: 'preparing',
          table_number: '17',
          updated_at: '2026-04-24T18:00:05Z',
          items_count: 3,
        },
      ],
      next_cursor: '2026-04-24T18:00:05Z',
      server_time: '2026-04-24T18:00:10Z',
      poll_interval_ms: 5000,
      device_id: KDS_DEVICE,
      device_kind: 'kds',
    };
    mockFetchOnce({ ok: true, data: payload });

    const result = await pollOrdersDelta({
      store_id: STORE_17,
      cursor: null,
      device_id: KDS_DEVICE,
      device_kind: 'kds',
    });

    expect(result.orders).toHaveLength(1);
    expect(result.next_cursor).toBe('2026-04-24T18:00:05Z');

    // 请求 URL 不含 cursor 参数（首次）
    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const url = call[0] as string;
    expect(url).toContain('/api/v1/kds/orders/delta');
    expect(url).toContain(`store_id=${encodeURIComponent(STORE_17)}`);
    expect(url).toContain('device_kind=kds');
    expect(url).not.toContain('cursor=');
  });
});

// ─── 场景 2：带 cursor 的后续轮询 ────────────────────────────────────────────

describe('pollOrdersDelta — 带 cursor 的后续轮询', () => {
  it('URL 正确携带 cursor 参数', async () => {
    mockFetchOnce({
      ok: true,
      data: {
        orders: [],
        next_cursor: '2026-04-24T18:00:05Z',
        server_time: '2026-04-24T18:00:10Z',
        poll_interval_ms: 5000,
      },
    });

    await pollOrdersDelta({
      store_id: STORE_17,
      cursor: '2026-04-24T18:00:00Z',
      device_id: KDS_DEVICE,
    });

    const url = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain('cursor=2026-04-24T18%3A00%3A00Z');
  });
});

// ─── 场景 3：5xx 指数退避 + 最终成功 ────────────────────────────────────────

describe('pollOrdersDeltaWithRetry — 5xx 指数退避', () => {
  it('前两次 500 失败后第三次成功；4xx 直接抛', async () => {
    // 使用 fake timers 避免真正 sleep
    vi.useFakeTimers();
    mockFetchSequence([
      { body: { ok: false, error: { message: 'Internal Error 500' } }, status: 500 },
      { body: { ok: false, error: { message: 'Bad Gateway 502' } }, status: 502 },
      {
        body: {
          ok: true,
          data: {
            orders: [],
            next_cursor: null,
            server_time: '2026-04-24T18:00:00Z',
            poll_interval_ms: 5000,
          },
        },
      },
    ]);

    const p = pollOrdersDeltaWithRetry(
      {
        store_id: STORE_17,
        cursor: null,
        device_id: KDS_DEVICE,
      },
      { maxAttempts: 3, baseDelayMs: 10 },
    );

    await vi.runAllTimersAsync();
    const result = await p;

    expect(result.server_time).toBe('2026-04-24T18:00:00Z');
    expect((globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(3);
  });

  it('4xx 语义错误直接抛，不退避', async () => {
    mockFetchOnce(
      { ok: false, error: { message: 'USER_TENANT_MISMATCH' } },
      { status: 403 },
    );
    await expect(
      pollOrdersDeltaWithRetry(
        {
          store_id: STORE_17,
          cursor: null,
          device_id: KDS_DEVICE,
        },
        { maxAttempts: 3, baseDelayMs: 10 },
      ),
    ).rejects.toThrow(/TENANT_MISMATCH/i);
    expect((globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(1);
  });
});

// ─── 场景 4：heartbeat 合法 device_kind ──────────────────────────────────────

describe('sendHeartbeat — device_kind 六枚举合法 / 非法', () => {
  it('合法 device_kind 成功 upsert', async () => {
    const resp: HeartbeatResponse = {
      device_id: KDS_DEVICE,
      device_kind: 'kds',
      server_time: '2026-04-24T18:00:00Z',
      poll_interval_ms: 30000,
    };
    mockFetchOnce({ ok: true, data: resp });

    const result = await sendHeartbeat({
      device_id: KDS_DEVICE,
      device_kind: 'kds',
      store_id: STORE_17,
      os_version: 'Android 13',
      app_version: '3.0.0',
      buffer_backlog: 0,
    });

    expect(result.device_kind).toBe('kds');
    expect(result.poll_interval_ms).toBe(30000);

    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toContain('/api/v1/kds/device/heartbeat');
    const body = JSON.parse((call[1] as RequestInit).body as string);
    expect(body.device_kind).toBe('kds');
    expect(body.buffer_backlog).toBe(0);
  });

  it('非法 device_kind 前端拦截，不发请求', async () => {
    await expect(
      sendHeartbeat({
        // @ts-expect-error 非法 kind 用于测试
        device_kind: 'laptop',
        device_id: KDS_DEVICE,
        store_id: STORE_17,
      }),
    ).rejects.toThrow(/device_kind 非法/);
    expect((globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(0);
  });
});

// ─── 场景 5：ALLOWED_DEVICE_KINDS 六枚举与 v271 CHECK 对齐 ──────────────────

describe('ALLOWED_DEVICE_KINDS — 与 v271 migration CHECK 对齐', () => {
  it('六枚举，严格顺序（测试锁契约防被删/改）', () => {
    expect([...ALLOWED_DEVICE_KINDS]).toEqual([
      'pos',
      'kds',
      'crew_phone',
      'tv_menu',
      'reception',
      'mac_mini',
    ]);
  });
});
