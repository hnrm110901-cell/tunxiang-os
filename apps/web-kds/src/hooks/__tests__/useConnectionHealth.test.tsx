/**
 * Sprint C2: useConnectionHealth hook
 *
 * 餐厅场景：后厨 KDS WebSocket 心跳 + navigator.onLine 双信号驱动只读降级。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import React from 'react';
import { useConnectionHealth } from '../useConnectionHealth';

// ─── 最小 WebSocket 替身 ─────────────────────────────────────

interface FakeWS {
  readyState: number;
  onopen: ((ev?: Event) => void) | null;
  onmessage: ((ev: MessageEvent) => void) | null;
  onclose: ((ev: CloseEvent) => void) | null;
  onerror: ((ev: Event) => void) | null;
  emitOpen(): void;
  emitMessage(data: unknown): void;
  emitClose(code?: number): void;
}

function makeFakeWs(): FakeWS {
  const ws: FakeWS = {
    readyState: 0, // CONNECTING
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    emitOpen() {
      ws.readyState = 1; // OPEN
      ws.onopen?.();
    },
    emitMessage(data) {
      ws.onmessage?.({ data } as MessageEvent);
    },
    emitClose(code = 1006) {
      ws.readyState = 3; // CLOSED
      ws.onclose?.({ code } as CloseEvent);
    },
  };
  return ws;
}

function setOnline(value: boolean) {
  Object.defineProperty(window.navigator, 'onLine', {
    value,
    configurable: true,
  });
  window.dispatchEvent(new Event(value ? 'online' : 'offline'));
}

describe('useConnectionHealth — KDS 连接健康检测 Hook', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setOnline(true);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('WebSocket 正常连接 health=online', () => {
    const wsRef = { current: null as FakeWS | null };
    const { result, rerender } = renderHook(() =>
      useConnectionHealth({ wsRef: wsRef as unknown as React.RefObject<WebSocket> }),
    );

    // 初始尚未打开：仍然视为 online（乐观），navigator.onLine=true
    expect(result.current.health).toBe('online');

    const fake = makeFakeWs();
    wsRef.current = fake;
    rerender();

    act(() => {
      fake.emitOpen();
      fake.emitMessage('pong');
    });
    expect(result.current.health).toBe('online');
  });

  it('15 秒未收到心跳 health=degraded', () => {
    const fake = makeFakeWs();
    const wsRef = { current: fake as unknown as WebSocket };
    const { result } = renderHook(() =>
      useConnectionHealth({ wsRef, heartbeatTimeoutMs: 15_000 }),
    );

    act(() => {
      fake.emitOpen();
      fake.emitMessage('pong');
    });
    expect(result.current.health).toBe('online');

    // 推进 16s 无任何消息 → degraded
    act(() => {
      vi.advanceTimersByTime(16_000);
    });
    expect(result.current.health).toBe('degraded');
  });

  it('WebSocket close 立即 health=offline', () => {
    const fake = makeFakeWs();
    const wsRef = { current: fake as unknown as WebSocket };
    const { result } = renderHook(() => useConnectionHealth({ wsRef }));

    act(() => {
      fake.emitOpen();
      fake.emitMessage('pong');
    });
    expect(result.current.health).toBe('online');

    act(() => {
      fake.emitClose(1006);
    });
    expect(result.current.health).toBe('offline');
  });

  it('navigator.onLine=false 与 WS 独立都触发 offline', () => {
    const fake = makeFakeWs();
    const wsRef = { current: fake as unknown as WebSocket };
    const { result } = renderHook(() => useConnectionHealth({ wsRef }));

    act(() => {
      fake.emitOpen();
      fake.emitMessage('pong');
    });
    expect(result.current.health).toBe('online');

    // WS 仍 OPEN 但网络断了
    act(() => {
      setOnline(false);
    });
    expect(result.current.health).toBe('offline');

    // 恢复网络 → 应回到 online（WS 仍然开启）
    act(() => {
      setOnline(true);
      fake.emitMessage('heartbeat');
    });
    expect(result.current.health).toBe('online');
  });

  it('health 从 offline→online 时触发 onReconnected 回调', () => {
    const fake = makeFakeWs();
    const wsRef = { current: fake as unknown as WebSocket };
    const onStatusChange = vi.fn();
    const { result } = renderHook(() =>
      useConnectionHealth({ wsRef, onStatusChange }),
    );

    act(() => {
      fake.emitOpen();
      fake.emitMessage('pong');
    });
    expect(result.current.health).toBe('online');

    act(() => {
      fake.emitClose();
    });
    expect(result.current.health).toBe('offline');
    expect(onStatusChange).toHaveBeenCalledWith('offline');

    // 模拟 reconnect
    act(() => {
      result.current.reconnect();
      // 业务代码应当重新建立 WS；这里假设新 WS 通过同一 ref 上线
      fake.readyState = 1;
      fake.onmessage = fake.onmessage; // noop
      // 发射一个消息模拟心跳
      fake.emitMessage('pong');
    });
    expect(result.current.health).toBe('online');
    expect(onStatusChange).toHaveBeenLastCalledWith('online');
  });
});
