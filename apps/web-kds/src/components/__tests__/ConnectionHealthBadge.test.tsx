/**
 * Tier 2 — ConnectionHealthBadge.tsx vitest 覆盖
 *
 * 4 个状态视觉断言 + 时间显示 + 手动刷新点击。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { ConnectionHealthBadge } from '../ConnectionHealthBadge';
import {
  createKdsHealthStore,
  useKdsHealthStore,
} from '../../store/useKdsHealthStore';

const NOW = 1_700_000_000_000;

beforeEach(() => {
  // 每个用例隔离全局 store，避免污染
  useKdsHealthStore.getState().reset();
});

describe('ConnectionHealthBadge — 4 个连接状态视觉', () => {
  it('synced: 上次成功 < 10s → 绿色 已同步', () => {
    const store = createKdsHealthStore();
    store.setState({ lastSuccessAt: NOW - 3_000, inFlight: false, failureStreak: 0 });
    render(<ConnectionHealthBadge useStore={store} nowProvider={() => NOW} />);
    const badge = screen.getByTestId('connection-health-badge');
    expect(badge.dataset.status).toBe('synced');
    expect(screen.getByTestId('connection-health-badge-label').textContent).toBe('已同步');
    expect(screen.getByTestId('connection-health-badge-ago').textContent).toBe('3秒前');
  });

  it('syncing: inFlight=true → 蓝色 同步中（刷新按钮禁用）', () => {
    const store = createKdsHealthStore();
    store.setState({ lastSuccessAt: NOW - 1_000, inFlight: true, failureStreak: 0 });
    render(<ConnectionHealthBadge useStore={store} nowProvider={() => NOW} />);
    expect(screen.getByTestId('connection-health-badge').dataset.status).toBe('syncing');
    expect(screen.getByTestId('connection-health-badge-label').textContent).toBe('同步中');
    expect(
      (screen.getByTestId('connection-health-badge-refresh') as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('stale: 上次成功 30s 前 → 黄色 同步滞后', () => {
    const store = createKdsHealthStore();
    store.setState({ lastSuccessAt: NOW - 30_000, inFlight: false, failureStreak: 0 });
    render(<ConnectionHealthBadge useStore={store} nowProvider={() => NOW} />);
    expect(screen.getByTestId('connection-health-badge').dataset.status).toBe('stale');
    expect(screen.getByTestId('connection-health-badge-label').textContent).toBe('同步滞后');
    expect(screen.getByTestId('connection-health-badge-ago').textContent).toBe('30秒前');
  });

  it('disconnected: 上次成功 > 60s 前 → 红色 已断线', () => {
    const store = createKdsHealthStore();
    store.setState({ lastSuccessAt: NOW - 90_000, inFlight: false, failureStreak: 0 });
    render(<ConnectionHealthBadge useStore={store} nowProvider={() => NOW} />);
    expect(screen.getByTestId('connection-health-badge').dataset.status).toBe('disconnected');
    expect(screen.getByTestId('connection-health-badge-label').textContent).toBe('已断线');
    expect(screen.getByTestId('connection-health-badge-ago').textContent).toBe('1分钟前');
  });

  it('disconnected: 连续 3 次失败 → 红色（哪怕最近成功 < 60s）', () => {
    const store = createKdsHealthStore();
    store.setState({ lastSuccessAt: NOW - 5_000, inFlight: false, failureStreak: 3 });
    render(<ConnectionHealthBadge useStore={store} nowProvider={() => NOW} />);
    expect(screen.getByTestId('connection-health-badge').dataset.status).toBe('disconnected');
  });

  it('从未成功: lastSuccessAt=-1 → 已断线（infinity since）+ 显示 "—"', () => {
    const store = createKdsHealthStore();
    // 默认 lastSuccessAt=-1
    render(<ConnectionHealthBadge useStore={store} nowProvider={() => NOW} />);
    expect(screen.getByTestId('connection-health-badge').dataset.status).toBe('disconnected');
    expect(screen.getByTestId('connection-health-badge-ago').textContent).toBe('—');
  });

  it('上次成功 90 分钟前 → "1小时前"', () => {
    const store = createKdsHealthStore();
    store.setState({
      lastSuccessAt: NOW - 90 * 60 * 1000,
      inFlight: false,
      failureStreak: 0,
    });
    render(<ConnectionHealthBadge useStore={store} nowProvider={() => NOW} />);
    expect(screen.getByTestId('connection-health-badge-ago').textContent).toBe('1小时前');
  });

  it('点击刷新按钮触发 onRefresh 回调', () => {
    const store = createKdsHealthStore();
    store.setState({ lastSuccessAt: NOW - 3_000, inFlight: false, failureStreak: 0 });
    const onRefresh = vi.fn();
    render(
      <ConnectionHealthBadge useStore={store} nowProvider={() => NOW} onRefresh={onRefresh} />,
    );
    fireEvent.click(screen.getByTestId('connection-health-badge-refresh'));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});

describe('useKdsHealthStore — 写操作语义', () => {
  it('beforePoll → markPollSuccess: failureStreak 归零，inFlight 关闭', () => {
    const store = createKdsHealthStore();
    store.setState({ failureStreak: 5, inFlight: false, lastSuccessAt: -1 });
    act(() => store.getState().beforePoll());
    expect(store.getState().inFlight).toBe(true);
    act(() => store.getState().markPollSuccess());
    expect(store.getState().inFlight).toBe(false);
    expect(store.getState().failureStreak).toBe(0);
    expect(store.getState().lastSuccessAt).toBeGreaterThan(0);
  });

  it('markPollFailure: failureStreak 累加，inFlight 关闭，lastSuccessAt 不变', () => {
    const store = createKdsHealthStore();
    store.setState({ lastSuccessAt: 12345, inFlight: true, failureStreak: 1 });
    act(() => store.getState().markPollFailure());
    expect(store.getState().failureStreak).toBe(2);
    expect(store.getState().inFlight).toBe(false);
    expect(store.getState().lastSuccessAt).toBe(12345);
  });
});
