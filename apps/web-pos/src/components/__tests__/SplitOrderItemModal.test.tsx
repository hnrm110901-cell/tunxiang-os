/**
 * SplitOrderItemModal 测试 — PRD-11 sub-C 拆单弹层
 *
 * 场景:
 *   render / 取消 / 提交成功 / 422 错误显示 / 上下界校验
 *
 * 注: 用原生 vitest expect (不依赖 jest-dom 扩展, 与 baseline test infra
 * vitest 4.x + jest-dom 6.x 不全兼容现状脱钩).
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SplitOrderItemModal } from '../modals/SplitOrderItemModal';

const baseProps = {
  dishName: '酸菜鱼',
  currentShareCount: 1,
};

describe('SplitOrderItemModal', () => {
  it('visible=false 不渲染', () => {
    const onSubmit = vi.fn(async () => {});
    const onClose = vi.fn();
    const { container } = render(
      <SplitOrderItemModal
        visible={false}
        {...baseProps}
        onSubmit={onSubmit}
        onClose={onClose}
      />,
    );
    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });

  it('visible=true 渲染菜名 + 当前拆分人数', () => {
    const onSubmit = vi.fn(async () => {});
    const onClose = vi.fn();
    render(
      <SplitOrderItemModal
        visible
        {...baseProps}
        currentShareCount={2}
        onSubmit={onSubmit}
        onClose={onClose}
      />,
    );
    expect(screen.queryByRole('dialog')).not.toBeNull();
    expect(screen.queryByText(/酸菜鱼/)).not.toBeNull();
    // input 默认值 = currentShareCount
    const input = screen.getByLabelText('拆分人数') as HTMLInputElement;
    expect(input.value).toBe('2');
  });

  it('点击取消调 onClose', () => {
    const onSubmit = vi.fn(async () => {});
    const onClose = vi.fn();
    render(
      <SplitOrderItemModal
        visible
        {...baseProps}
        onSubmit={onSubmit}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByText('取消'));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('改 input 值 + 点击确认调 onSubmit 带新 shareCount', async () => {
    const onSubmit = vi.fn(async () => {});
    const onClose = vi.fn();
    render(
      <SplitOrderItemModal
        visible
        {...baseProps}
        onSubmit={onSubmit}
        onClose={onClose}
      />,
    );
    const input = screen.getByLabelText('拆分人数') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '3' } });
    fireEvent.click(screen.getByText('确认拆单'));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(3);
    });
  });

  it('onSubmit 抛 Error (后端 422) 时显示错误信息', async () => {
    const onSubmit = vi.fn(async () => {
      throw new Error('share_count=99 超 max_share_count=8');
    });
    const onClose = vi.fn();
    render(
      <SplitOrderItemModal
        visible
        {...baseProps}
        onSubmit={onSubmit}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByText('确认拆单'));

    await waitFor(() => {
      const alert = screen.queryByRole('alert');
      expect(alert).not.toBeNull();
      expect(alert!.textContent).toContain('share_count=99');
    });
    // 失败不自动关闭
    expect(onClose).not.toHaveBeenCalled();
  });

  it('shareCount=0 或负数, 提交前本地校验失败', async () => {
    const onSubmit = vi.fn(async () => {});
    const onClose = vi.fn();
    render(
      <SplitOrderItemModal
        visible
        {...baseProps}
        onSubmit={onSubmit}
        onClose={onClose}
      />,
    );
    const input = screen.getByLabelText('拆分人数') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '0' } });
    fireEvent.click(screen.getByText('确认拆单'));

    await waitFor(() => {
      const alert = screen.queryByRole('alert');
      expect(alert).not.toBeNull();
      expect(alert!.textContent).toContain('1 到 20');
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('shareCount 超 maxShareCount 时本地校验失败', async () => {
    const onSubmit = vi.fn(async () => {});
    const onClose = vi.fn();
    render(
      <SplitOrderItemModal
        visible
        {...baseProps}
        onSubmit={onSubmit}
        onClose={onClose}
        maxShareCount={8}
      />,
    );
    const input = screen.getByLabelText('拆分人数') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '99' } });
    fireEvent.click(screen.getByText('确认拆单'));

    await waitFor(() => {
      const alert = screen.queryByRole('alert');
      expect(alert).not.toBeNull();
      expect(alert!.textContent).toContain('1 到 8');
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('提交中点击取消按钮 - disabled (避免双提交 / 状态错乱)', async () => {
    let resolveSubmit: () => void = () => {};
    const onSubmit = vi.fn(
      async () =>
        new Promise<void>((resolve) => {
          resolveSubmit = resolve;
        }),
    );
    const onClose = vi.fn();
    render(
      <SplitOrderItemModal
        visible
        {...baseProps}
        onSubmit={onSubmit}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByText('确认拆单'));
    await waitFor(() => {
      expect(screen.queryByText('提交中...')).not.toBeNull();
    });
    // 提交中点击取消按钮 - 不应触发 onClose
    fireEvent.click(screen.getByText('取消'));
    expect(onClose).not.toHaveBeenCalled();

    // resolve 让 promise 完成
    resolveSubmit();
    await waitFor(() => {
      expect(screen.queryByText('提交中...')).toBeNull();
    });
  });
});
