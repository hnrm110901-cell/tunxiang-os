/**
 * Sprint C2: OfflineBanner 组件测试
 *
 * 餐厅场景：KDS 顶栏常驻的离线/降级提示，online 隐藏、degraded 黄色、offline 橙色
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { OfflineBanner } from '../OfflineBanner';

describe('OfflineBanner — KDS 离线降级横条', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-18T12:00:00Z'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('health=online 时不显示 banner', () => {
    const { container } = render(
      <OfflineBanner health="online" offlineDurationMs={0} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('health=offline 时显示橙色横条 + 断线时长计时', () => {
    const { container, rerender } = render(
      <OfflineBanner health="offline" offlineDurationMs={0} />,
    );
    // 初始文案
    expect(screen.getByText(/离线只读/)).toBeInTheDocument();
    expect(screen.getByText(/00:00/)).toBeInTheDocument();

    const banner = container.firstChild as HTMLElement;
    // 橙色背景（#F97316 是 tailwind orange-500 级；我们只校验 role/class 包含 orange）
    expect(banner.className.toLowerCase()).toContain('orange');

    // 推进 65 秒 → 01:05
    rerender(<OfflineBanner health="offline" offlineDurationMs={65_000} />);
    expect(screen.getByText(/01:05/)).toBeInTheDocument();
  });

  it('health=degraded 时显示黄色横条 "连接不稳定"', () => {
    const { container } = render(
      <OfflineBanner health="degraded" offlineDurationMs={0} />,
    );
    expect(screen.getByText(/连接不稳定/)).toBeInTheDocument();
    const banner = container.firstChild as HTMLElement;
    expect(banner.className.toLowerCase()).toContain('yellow');
  });

  it('点击 banner 不可关闭（强制提示）', () => {
    const { container } = render(
      <OfflineBanner health="offline" offlineDurationMs={5_000} />,
    );
    const banner = container.firstChild as HTMLElement;
    fireEvent.click(banner);
    // 点击后依旧显示
    expect(screen.getByText(/离线只读/)).toBeInTheDocument();
  });
});
