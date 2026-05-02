/**
 * PosErrorBoundary — POS 收银专用 ErrorBoundary
 *
 * 展示友好的中文降级 UI，适合收银员在繁忙环境中快速理解问题。
 * 与通用 ErrorBoundary 的关系：
 * - 通用 ErrorBoundary 支持丰富的 props（boundary_level / severity / saga_id 等）
 * - PosErrorBoundary 封装了 POS 场景的合理默认值，简化使用
 *
 * 职责：
 * - 捕获渲染异常，显示"收银遇到问题，请重试"友好提示
 * - 点击重试按钮 → 重置 error state 重新渲染 children
 * - 自动上报错误到 console.error（后续可对接 sentry）
 * - Tailwind 样式，中文文案
 */
import { Component, ErrorInfo, ReactNode } from 'react';

interface PosErrorBoundaryProps {
  children: ReactNode;
  /** 可选：从上层传入的额外上下文（如 saga_id / order_id） */
  context?: Record<string, string | undefined>;
  /** 可选：自定义 fallback 覆盖默认 UI */
  fallback?: (error: Error, reset: () => void) => ReactNode;
  /** 可选：重置后回调 */
  onReset?: () => void;
}

interface PosErrorBoundaryState {
  error: Error | null;
}

export class PosErrorBoundary extends Component<PosErrorBoundaryProps, PosErrorBoundaryState> {
  state: PosErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): Partial<PosErrorBoundaryState> {
    return { error };
  }

  componentDidCatch(error: Error, _info: ErrorInfo): void {
    // 上报到 console.error（后续可对接 sentry / telemetry）
    console.error('[PosErrorBoundary] 捕获收银异常:', {
      name: error.name,
      message: error.message,
      stack: error.stack,
      occurredAt: new Date().toISOString(),
      context: this.props.context,
    });
  }

  reset = (): void => {
    this.setState({ error: null });
    this.props.onReset?.();
  };

  render(): ReactNode {
    if (!this.state.error) {
      return this.props.children;
    }

    if (this.props.fallback) {
      return this.props.fallback(this.state.error, this.reset);
    }

    return (
      <div
        role="alert"
        className="flex min-h-[60vh] flex-col items-center justify-center bg-gray-900 p-6 text-center text-gray-50"
      >
        <div className="mb-3 text-2xl font-bold">收银遇到问题，请重试</div>
        <div className="mb-6 max-w-md text-sm opacity-80">
          系统遇到临时异常，请点击下方按钮重试。如果问题持续出现，请联系店长。
        </div>

        {/* 开发环境：显示错误详情 */}
        {import.meta.env?.DEV && (
          <pre className="mb-4 max-w-[720px] max-h-60 overflow-auto rounded-lg bg-gray-950 p-3 text-left text-xs text-red-300">
            {this.state.error.message}
            {this.state.error.stack ? `\n${this.state.error.stack}` : ''}
          </pre>
        )}

        <button
          type="button"
          onClick={this.reset}
          className="cursor-pointer rounded-lg bg-blue-600 px-8 py-3 text-base font-medium text-white transition-colors hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-900"
        >
          重试
        </button>
      </div>
    );
  }
}
