/**
 * Tier 1 测试：Toast / useToast（收银员运行时反馈）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { ToastContainer } from '../ToastContainer';
import { useToastStore, showToast } from '../../hooks/useToast';

function resetToasts(): void {
  useToastStore.setState({ toasts: [] });
}

describe('Toast — 收银员场景', () => {
  beforeEach(() => {
    resetToasts();
    vi.useFakeTimers();
  });

  it('断网时调用 showToast("网络不通，请检查网线", "error") 显示红色 Toast 3 秒后消失', () => {
    render(<ToastContainer />);
    act(() => {
      showToast('网络不通，请检查网线', 'error');
    });
    const toast = screen.getByText('网络不通，请检查网线');
    expect(toast).toBeInTheDocument();
    expect(toast.closest('[data-toast-type]')?.getAttribute('data-toast-type')).toBe('error');

    act(() => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.queryByText('网络不通，请检查网线')).not.toBeInTheDocument();
  });

  it('支付成功调用 showToast("支付成功", "success") 显示绿色 Toast', () => {
    render(<ToastContainer />);
    act(() => {
      showToast('支付成功', 'success');
    });
    const node = screen.getByText('支付成功').closest('[data-toast-type]');
    expect(node?.getAttribute('data-toast-type')).toBe('success');
  });

  it('同时弹出 3 个 Toast 依次排队显示（最多 3 条同屏）', () => {
    render(<ToastContainer />);
    act(() => {
      showToast('一号桌下单成功', 'success');
      showToast('二号桌下单成功', 'success');
      showToast('三号桌下单成功', 'success');
      showToast('四号桌下单成功', 'success');
    });
    const visible = useToastStore.getState().toasts;
    expect(visible.length).toBeLessThanOrEqual(3);
    expect(screen.getByText('二号桌下单成功')).toBeInTheDocument();
    expect(screen.getByText('三号桌下单成功')).toBeInTheDocument();
    expect(screen.getByText('四号桌下单成功')).toBeInTheDocument();
  });

  it('offline 类型 Toast 带"离线队列中"图标且不自动消失', () => {
    render(<ToastContainer />);
    act(() => {
      showToast('已进入离线队列', 'offline');
    });
    expect(screen.getByText('已进入离线队列')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.getByText('已进入离线队列')).toBeInTheDocument();
  });

  it('Toast 点击×关闭按钮立即消失', () => {
    render(<ToastContainer />);
    act(() => {
      showToast('请扫会员码', 'info');
    });
    const closeBtn = screen.getByRole('button', { name: /关闭/ });
    fireEvent.click(closeBtn);
    expect(screen.queryByText('请扫会员码')).not.toBeInTheDocument();
  });

  it('会员余额不足弹 info Toast：会员余额 ¥12 不足，需 ¥45', () => {
    render(<ToastContainer />);
    act(() => {
      showToast('会员余额 ¥12 不足，需 ¥45', 'info');
    });
    const node = screen.getByText('会员余额 ¥12 不足，需 ¥45').closest('[data-toast-type]');
    expect(node?.getAttribute('data-toast-type')).toBe('info');
  });
});
