/**
 * Sprint A1 P1-4 Tier 1：Feature Flag 远程下发契约测试
 *
 * 核心断言：
 *   1. yaml DEFAULTS 命中（首屏保底）
 *   2. 远程成功覆盖
 *   3. 404 降级 + 警告
 *   4. 5s 超时不阻塞
 *   5. setFlagOverride 最高优先级
 *   6. Unknown flag 返回 false + debug log
 */
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import {
  isEnabled,
  setFlagOverride,
  resetFlagOverrides,
  fetchFlagsFromRemote,
  _resetRemoteFlagsForTest,
} from '../featureFlags';

describe('featureFlags — Sprint A1 P1-4 远程下发', () => {
  beforeEach(() => {
    resetFlagOverrides();
    _resetRemoteFlagsForTest();
  });

  afterEach(() => {
    resetFlagOverrides();
    _resetRemoteFlagsForTest();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('yaml DEFAULTS 在未拉取远程时生效（首屏保底）', () => {
    expect(isEnabled('trade.pos.settle.hardening.enable')).toBe(true);
    expect(isEnabled('trade.pos.toast.enable')).toBe(true);
    expect(isEnabled('trade.pos.errorBoundary.enable')).toBe(true);
    // 兼容旧 key
    expect(isEnabled('trade.pos.settle.hardening')).toBe(true);
  });

  it('fetchFlagsFromRemote 成功后覆盖本地 default', async () => {
    const mockFetch = vi.fn(async () =>
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            flags: {
              'trade.pos.settle.hardening.enable': false,
              'trade.pos.toast.enable': true,
              'trade.pos.errorBoundary.enable': false,
            },
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const applied = await fetchFlagsFromRemote({
      fetchFn: mockFetch as unknown as typeof fetch,
      baseUrl: 'http://test',
    });
    expect(applied['trade.pos.settle.hardening.enable']).toBe(false);
    expect(isEnabled('trade.pos.settle.hardening.enable')).toBe(false);
    expect(isEnabled('trade.pos.toast.enable')).toBe(true);
    expect(isEnabled('trade.pos.errorBoundary.enable')).toBe(false);
    expect(mockFetch).toHaveBeenCalledWith(
      'http://test/api/v1/flags?domain=trade',
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('远程端点 404 时降级到 default 并 log 警告', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const mockFetch = vi.fn(
      async () => new Response('not found', { status: 404 }),
    );
    const applied = await fetchFlagsFromRemote({
      fetchFn: mockFetch as unknown as typeof fetch,
      baseUrl: 'http://test',
    });
    expect(applied).toEqual({});
    // 仍然命中 yaml defaultValue
    expect(isEnabled('trade.pos.settle.hardening.enable')).toBe(true);
    expect(warnSpy).toHaveBeenCalledWith(
      '[featureFlags] remote fetch non-ok',
      expect.objectContaining({ status: 404 }),
    );
  });

  it('远程超时不阻塞后续逻辑（5s）', async () => {
    vi.useFakeTimers();
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    // 永不 resolve 的 fetch，用于触发 AbortController
    const mockFetch = vi.fn((_url: string, init?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          reject(new DOMException('aborted', 'AbortError'));
        });
      });
    });
    const promise = fetchFlagsFromRemote({
      fetchFn: mockFetch as unknown as typeof fetch,
      timeoutMs: 5000,
      baseUrl: 'http://test',
    });
    // 推进 5s，触发 AbortController
    await vi.advanceTimersByTimeAsync(5001);
    const applied = await promise;
    expect(applied).toEqual({});
    // default 仍可用
    expect(isEnabled('trade.pos.toast.enable')).toBe(true);
    // log 标注 timeout
    expect(warnSpy).toHaveBeenCalledWith(
      '[featureFlags] remote fetch failed, fall back to defaults',
      expect.objectContaining({ reason: 'timeout' }),
    );
  });

  it('setFlagOverride 优先级高于 default 和远程', async () => {
    // 先用远程下发 true
    const mockFetch = vi.fn(async () =>
      new Response(
        JSON.stringify({
          ok: true,
          data: { flags: { 'trade.pos.toast.enable': true } },
        }),
        { status: 200 },
      ),
    );
    await fetchFlagsFromRemote({
      fetchFn: mockFetch as unknown as typeof fetch,
      baseUrl: 'http://test',
    });
    expect(isEnabled('trade.pos.toast.enable')).toBe(true);

    // override 必须胜出
    setFlagOverride('trade.pos.toast.enable', false);
    expect(isEnabled('trade.pos.toast.enable')).toBe(false);

    // 清除 override 后回到远程值
    resetFlagOverrides();
    expect(isEnabled('trade.pos.toast.enable')).toBe(true);
  });

  it('Unknown flag name 返回 false 并 log debug', () => {
    const debugSpy = vi.spyOn(console, 'debug').mockImplementation(() => {});
    expect(isEnabled('trade.pos.not.registered')).toBe(false);
    expect(isEnabled('totally.made.up.flag')).toBe(false);
    expect(debugSpy).toHaveBeenCalledWith(
      '[featureFlags] unknown flag',
      'trade.pos.not.registered',
    );
  });
});
