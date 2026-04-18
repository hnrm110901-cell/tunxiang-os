/**
 * 顶层 ErrorBoundary 的降级 UI（Sprint A1 P1-5 + 审查收窄）。
 *
 * 为什么不复用默认文案？
 *   默认 fallback 是"结账失败"（仅适合结算页）。顶层 ErrorBoundary 可能在非结算页
 *   兜底（菜单/报表/桌台图崩溃），文案必须中性避免误导收银员。
 *   结算相关路由（/settle /order）由 App.tsx 中的 CashierBoundary 单独包裹。
 */
import type { ReactNode } from 'react';
import type { ErrorBoundaryProps } from './ErrorBoundary';

export function navigateToTables(): void {
  if (typeof window !== 'undefined' && window.location) {
    window.location.assign('/tables');
  }
}

export type RootFallback = NonNullable<ErrorBoundaryProps['fallback']>;

export const rootFallback: RootFallback = (_error: Error, reset: () => void): ReactNode => (
  <div
    role="alert"
    style={{
      minHeight: '60vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 24,
      background: '#1f2937',
      color: '#f9fafb',
      textAlign: 'center',
    }}
  >
    <div style={{ fontSize: 28, fontWeight: 700, marginBottom: 12 }}>遇到意外错误</div>
    <div style={{ fontSize: 16, opacity: 0.8, marginBottom: 24 }}>点击返回可恢复</div>
    <button
      type="button"
      onClick={() => { reset(); navigateToTables(); }}
      style={{
        padding: '12px 32px',
        fontSize: 16,
        background: '#2563eb',
        color: '#fff',
        border: 'none',
        borderRadius: 8,
        cursor: 'pointer',
      }}
    >
      返回桌台
    </button>
  </div>
);
