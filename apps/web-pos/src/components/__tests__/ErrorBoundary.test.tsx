/**
 * Tier 1 测试：ErrorBoundary（结算页崩溃降级）
 * 场景驱动，非技术边界值。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ErrorBoundary } from '../ErrorBoundary';
import { rootFallback, navigateToTables } from '../RootFallback';

function Boom({ msg = '订单金额计算异常' }: { msg?: string }): JSX.Element {
  throw new Error(msg);
}

function Safe(): JSX.Element {
  return <div>结算界面正常</div>;
}

describe('ErrorBoundary — 结算页崩溃降级', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('结算页 React 组件渲染崩溃时降级到"结账失败，请扫桌重试"面板而非白屏', () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText('结账失败')).toBeInTheDocument();
    expect(screen.getByText(/请扫桌重试/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /返回桌台/ })).toBeInTheDocument();
  });

  it('错误边界内点击"返回桌台"按钮可恢复到 TablesPage', () => {
    const onReset = vi.fn();
    render(
      <ErrorBoundary onReset={onReset}>
        <Boom />
      </ErrorBoundary>,
    );
    fireEvent.click(screen.getByRole('button', { name: /返回桌台/ }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it('ErrorBoundary 捕获错误后调用 onReport 上报 stack 到遥测端点', () => {
    const onReport = vi.fn();
    render(
      <ErrorBoundary onReport={onReport}>
        <Boom msg="会员扣费接口超时" />
      </ErrorBoundary>,
    );
    expect(onReport).toHaveBeenCalledTimes(1);
    const payload = onReport.mock.calls[0][0];
    expect(payload.error.message).toContain('会员扣费接口超时');
    expect(payload.error.stack).toBeTruthy();
    expect(payload.componentStack).toBeTruthy();
  });

  it('resetKey 变化时 ErrorBoundary 自动恢复（用于路由切换）', () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="order-A">
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/结账失败/)).toBeInTheDocument();

    rerender(
      <ErrorBoundary resetKey="order-B">
        <Safe />
      </ErrorBoundary>,
    );
    expect(screen.getByText('结算界面正常')).toBeInTheDocument();
    expect(screen.queryByText(/结账失败/)).not.toBeInTheDocument();
  });

  it('捕获错误后不冒泡到父级 ErrorBoundary', () => {
    const outerReport = vi.fn();
    const innerReport = vi.fn();
    render(
      <ErrorBoundary onReport={outerReport}>
        <div>
          <ErrorBoundary onReport={innerReport}>
            <Boom msg="内层收银组件崩溃" />
          </ErrorBoundary>
        </div>
      </ErrorBoundary>,
    );
    expect(innerReport).toHaveBeenCalledTimes(1);
    expect(outerReport).not.toHaveBeenCalled();
  });

  it('开发环境显示完整 stack，生产环境只显示友好文案', () => {
    const dev = render(
      <ErrorBoundary debug>
        <Boom msg="桌台号 A08 无法识别" />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/桌台号 A08 无法识别/)).toBeInTheDocument();
    dev.unmount();

    render(
      <ErrorBoundary debug={false}>
        <Boom msg="桌台号 A08 无法识别" />
      </ErrorBoundary>,
    );
    expect(screen.queryByText(/桌台号 A08 无法识别/)).not.toBeInTheDocument();
    expect(screen.getByText('结账失败')).toBeInTheDocument();
  });

  it('ErrorBoundary 捕获错误后点"返回桌台"调用 onReset（Sprint A1 P1-5）', () => {
    const onReset = vi.fn();
    render(
      <ErrorBoundary onReset={onReset}>
        <Boom msg="支付回调解析失败" />
      </ErrorBoundary>,
    );
    fireEvent.click(screen.getByRole('button', { name: /返回桌台/ }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});

describe('rootFallback — 顶层 ErrorBoundary 降级 UI（Sprint A1 审查收窄）', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('顶层 ErrorBoundary 文案不出现"结账"字样（非结算页崩溃时不误导收银员）', () => {
    render(
      <ErrorBoundary fallback={rootFallback}>
        <Boom msg="菜单渲染异常" />
      </ErrorBoundary>,
    );
    expect(screen.getByText('遇到意外错误')).toBeInTheDocument();
    expect(screen.getByText(/点击返回可恢复/)).toBeInTheDocument();
    expect(screen.queryByText(/结账/)).not.toBeInTheDocument();
    expect(screen.queryByText(/结账失败/)).not.toBeInTheDocument();
  });

  it('rootFallback 的"返回桌台"按钮点击后真正跳转到 /tables（P1-5）', () => {
    const assignSpy = vi.fn();
    const originalLocation = window.location;
    // jsdom 的 window.location 的 assign 不可 redefine，整体替换
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, assign: assignSpy },
    });
    try {
      render(
        <ErrorBoundary fallback={rootFallback}>
          <Boom msg="意外崩溃" />
        </ErrorBoundary>,
      );
      fireEvent.click(screen.getByRole('button', { name: /返回桌台/ }));
      expect(assignSpy).toHaveBeenCalledWith('/tables');
    } finally {
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: originalLocation,
      });
    }
  });

  it('navigateToTables 导航到 /tables 且不抛错', () => {
    expect(typeof navigateToTables).toBe('function');
    const assignSpy = vi.fn();
    const originalLocation = window.location;
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, assign: assignSpy },
    });
    try {
      expect(() => navigateToTables()).not.toThrow();
      expect(assignSpy).toHaveBeenCalledWith('/tables');
    } finally {
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: originalLocation,
      });
    }
  });
});
