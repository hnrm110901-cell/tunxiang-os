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

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  Sprint A1 徐记 Tier1 场景
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  it('test_xujihaixian_peak_hour_5_toast_types_queue_management', () => {
    // 晚高峰 6-9pm 收银员连续触发 5 类 Toast（success/error/info/warning/offline）；
    // 队列最多 3 条同屏（MAX_VISIBLE=3），超出淘汰最老；warning 是 Sprint A1 新增类别。
    render(<ToastContainer />);
    act(() => {
      showToast('桌台开台成功', 'success');
      showToast('打印机纸张不足', 'warning');
      showToast('网络超时，请重试', 'error');
      showToast('请扫会员码', 'info');
      showToast('已加入离线队列', 'offline');
    });

    const queued = useToastStore.getState().toasts;
    expect(queued.length).toBeLessThanOrEqual(3);
    // warning 类型必须已注册（5 类齐全）— 只校验类型可被 push 而不降级成 info
    // 最后 3 条保留（error/info/offline），前 2 条被淘汰
    expect(screen.queryByText('桌台开台成功')).not.toBeInTheDocument();
    expect(screen.queryByText('打印机纸张不足')).not.toBeInTheDocument();
    expect(screen.getByText('网络超时，请重试')).toBeInTheDocument();
    expect(screen.getByText('请扫会员码')).toBeInTheDocument();
    expect(screen.getByText('已加入离线队列')).toBeInTheDocument();

    // 单独验证 warning 可用（不淘汰的场景）
    act(() => {
      useToastStore.setState({ toasts: [] });
      showToast('厨房出餐超过 25 分钟', 'warning');
    });
    const warnNode = screen
      .getByText('厨房出餐超过 25 分钟')
      .closest('[data-toast-type]');
    expect(warnNode?.getAttribute('data-toast-type')).toBe('warning');
  });
});
