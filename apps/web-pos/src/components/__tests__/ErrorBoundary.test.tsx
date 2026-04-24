/**
 * Tier 1 测试：ErrorBoundary（结算页崩溃降级）
 * 场景驱动，非技术边界值。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
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

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Sprint A1 — 徐记海鲜 Tier1 场景用例（先测后写）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

describe('ErrorBoundary — 徐记海鲜 Sprint A1 Tier1 场景', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('test_xujihaixian_cashier_page_crash_47th_order_shows_fallback_within_3s', () => {
    // 徐记 17 号桌收银员结完第 47 单后，CashierPage 抛出"会员抵扣计算异常"；
    // 降级 UI 在 3s 内可见（实际只要单次渲染即达成），非白屏。
    const t0 = performance.now();
    render(
      <ErrorBoundary boundary_level="cashier">
        <Boom msg="第47单会员抵扣计算异常" />
      </ErrorBoundary>,
    );
    const elapsed = performance.now() - t0;
    expect(screen.getByText('结账失败')).toBeInTheDocument();
    expect(elapsed).toBeLessThan(3000);
  });

  it('test_xujihaixian_17_table_network_jitter_auto_recover_no_pos_restart', () => {
    // 17 桌结账时 4G 抖动触发 ErrorBoundary；resetAfterMs=3000 触发自动恢复；
    // 恢复后 resetKey 变化允许子组件重渲染，收银员无需重启 POS。
    vi.useFakeTimers();
    const onReset = vi.fn();
    const { rerender } = render(
      <ErrorBoundary boundary_level="cashier" resetAfterMs={3000} onReset={onReset}>
        <Boom msg="17 号桌网络抖动" />
      </ErrorBoundary>,
    );
    expect(screen.getByText('结账失败')).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(3100);
    });
    // 3s 自动重置后，重新渲染（模拟网络恢复传入安全组件）
    rerender(
      <ErrorBoundary boundary_level="cashier" resetAfterMs={3000}>
        <Safe />
      </ErrorBoundary>,
    );
    expect(screen.getByText('结算界面正常')).toBeInTheDocument();
    // 自动重置触发 onReset（收银员视角："POS 没重启，自动活过来了"）
    expect(onReset).toHaveBeenCalled();
  });

  it('test_xujihaixian_cash_drawer_state_consistent_after_boundary', () => {
    // ErrorBoundary 捕获错误后，onReport 上报 payload 含 boundary_level/saga_id/order_no；
    // 钱箱状态不因边界崩溃而留半状态（收银员关注点）。
    const onReport = vi.fn();
    localStorage.setItem('cash_drawer_state', 'closed');
    render(
      <ErrorBoundary
        boundary_level="cashier"
        saga_id="saga-47-table-17"
        order_no="XJ20260424-00047"
        severity="fatal"
        onReport={onReport}
      >
        <Boom msg="支付回调解析失败" />
      </ErrorBoundary>,
    );
    expect(onReport).toHaveBeenCalledTimes(1);
    const payload = onReport.mock.calls[0][0];
    expect(payload.boundary_level).toBe('cashier');
    expect(payload.saga_id).toBe('saga-47-table-17');
    expect(payload.order_no).toBe('XJ20260424-00047');
    expect(payload.severity).toBe('fatal');
    // 钱箱状态未被覆盖（不应留半状态）
    expect(localStorage.getItem('cash_drawer_state')).toBe('closed');
    localStorage.removeItem('cash_drawer_state');
  });
});
