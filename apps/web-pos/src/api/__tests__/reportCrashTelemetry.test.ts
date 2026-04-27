/**
 * Tier 1 测试：reportCrashToTelemetry — A1 跨租户写入漏洞修复（前端侧）
 *
 * 关键契约：JWT 不存在 / 不可解析时 *绝不* 调用 fetch（不再回退 localStorage tenant_id）。
 * 这一行为是收敛 XSS 攻击面的核心：宁可丢一条遥测，也不允许跨租户写入。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { decodeTenantIdFromJwt, reportCrashToTelemetry } from '../tradeApi';

type FetchSpy = ReturnType<typeof vi.fn>;

function installFetch(impl: FetchSpy): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).fetch = impl;
}

function buildJwt(payload: Record<string, unknown>): string {
  // 仅供测试：构造一个合法 base64url 编码的 JWT（不验签）
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
  const body = btoa(JSON.stringify(payload))
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
  return `${header}.${body}.signature-not-verified-on-client`;
}

describe('reportCrashToTelemetry — Tier1 A1 跨租户拦截', () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('test_report_crash_no_jwt_aborts_no_cross_tenant_write — 无 JWT 时静默 abort，不调用 fetch', () => {
    // 攻击场景：徐记 17 号桌收银员 localStorage 被 XSS 注入
    //   localStorage.setItem('tenant_id', '<对手租户 UUID>')
    // 但 'tx_store_token'（合法 JWT）不存在 / 已过期被清除。
    // 旧版会用 localStorage tenant_id 作为 X-Tenant-ID 上报跨租户 crash。
    // 修复后必须：fetch 调用 0 次。

    // 攻击者塞的 localStorage tenant_id（旧版会读它）
    localStorage.setItem('tenant_id', '22222222-2222-2222-2222-222222222222');
    localStorage.setItem('store_id', '33333333-3333-3333-3333-333333333333');
    // 但没有 JWT — 用户未登录或已退出
    expect(localStorage.getItem('tx_store_token')).toBeNull();

    const fetchSpy: FetchSpy = vi.fn(async () => new Response('{}', { status: 200 }));
    installFetch(fetchSpy);

    reportCrashToTelemetry({
      error: { name: 'TypeError', message: 'fake crash for tenant probing', stack: 'at attacker' },
      saga_id: '99999999-9999-9999-9999-999999999999',
      order_no: 'XJ20260424-PROBE',
      severity: 'fatal',
      boundary_level: 'cashier',
    });

    // 关键断言：fetch 必须 0 次调用（不再回退 localStorage tenant_id）
    expect(fetchSpy).toHaveBeenCalledTimes(0);
  });

  it('JWT 损坏（非三段式）时静默 abort，不调用 fetch', () => {
    localStorage.setItem('tx_store_token', 'this-is-not-a-valid-jwt');
    localStorage.setItem('tenant_id', '22222222-2222-2222-2222-222222222222');

    const fetchSpy: FetchSpy = vi.fn(async () => new Response('{}', { status: 200 }));
    installFetch(fetchSpy);

    reportCrashToTelemetry({
      error: { name: 'Error', message: 'crash' },
    });

    expect(fetchSpy).toHaveBeenCalledTimes(0);
  });

  it('JWT 有效且含 tenant_id → fetch 用 JWT tenant_id 而非 localStorage', () => {
    const jwtTenant = '11111111-1111-1111-1111-111111111111';
    const tamperedTenant = '22222222-2222-2222-2222-222222222222';

    const jwt = buildJwt({ tenant_id: jwtTenant, user_id: 'xuji-007', sub: 'xuji-007' });
    localStorage.setItem('tx_store_token', jwt);
    // XSS 攻击：localStorage 的 tenant_id 被改为对手租户。修复后不再读它。
    localStorage.setItem('tenant_id', tamperedTenant);

    const fetchSpy: FetchSpy = vi.fn(async () => new Response('{}', { status: 200 }));
    installFetch(fetchSpy);

    reportCrashToTelemetry({
      error: { name: 'TypeError', message: 'real crash' },
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0];
    const headers = init?.headers as Record<string, string>;
    // X-Tenant-ID 必须来自 JWT，不是被篡改的 localStorage 'tenant_id'
    expect(headers['X-Tenant-ID']).toBe(jwtTenant);
    expect(headers['X-Tenant-ID']).not.toBe(tamperedTenant);
    // 同时附 Authorization Bearer，让 gateway 二次校验
    expect(headers['Authorization']).toBe(`Bearer ${jwt}`);
  });

  it('decodeTenantIdFromJwt — 各种异常输入返回 null', () => {
    expect(decodeTenantIdFromJwt(null)).toBeNull();
    expect(decodeTenantIdFromJwt(undefined)).toBeNull();
    expect(decodeTenantIdFromJwt('')).toBeNull();
    expect(decodeTenantIdFromJwt('only.two')).toBeNull();
    expect(decodeTenantIdFromJwt('a.b.c')).toBeNull(); // payload 解码后非 JSON
    // 合法 JWT 但 payload 无 tenant_id 字段
    const noTenant = buildJwt({ user_id: 'x' });
    expect(decodeTenantIdFromJwt(noTenant)).toBeNull();
    // 合法 JWT 含 tenant_id
    const ok = buildJwt({ tenant_id: 'aaaa-bbbb-cccc-dddd' });
    expect(decodeTenantIdFromJwt(ok)).toBe('aaaa-bbbb-cccc-dddd');
  });
});
