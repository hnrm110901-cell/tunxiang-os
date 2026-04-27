import { Component, ErrorInfo, ReactNode } from 'react';

/**
 * Sprint A1 扩展：boundary_level / saga_id / order_no / severity / timeout_reason /
 * recovery_action 全部可选上报，后端 telemetry v268 已落列（向前兼容）。
 */
export type BoundaryLevel = 'root' | 'cashier' | 'unknown';
export type CrashSeverity = 'fatal' | 'warn' | 'info';
export type TimeoutReason =
  | 'fetch_timeout'
  | 'saga_timeout'
  | 'gateway_timeout'
  | 'rls_deny'
  | 'disk_io_error'
  | 'unknown';
export type RecoveryAction = 'reset' | 'redirect_tables' | 'retry' | 'abort';

export interface ErrorReport {
  error: {
    name: string;
    message: string;
    stack?: string;
  };
  componentStack: string;
  occurredAt: string;
  // Sprint A1 扩字段
  boundary_level?: BoundaryLevel;
  severity?: CrashSeverity;
  saga_id?: string;
  order_no?: string;
  timeout_reason?: TimeoutReason;
  recovery_action?: RecoveryAction;
}

export interface ErrorBoundaryProps {
  children: ReactNode;
  resetKey?: string | number;
  debug?: boolean;
  onReset?: () => void;
  onReport?: (report: ErrorReport) => void;
  fallback?: (error: Error, reset: () => void) => ReactNode;
  // ── Sprint A1 新增 props ────────────────────────────────────
  /** ErrorBoundary 层级：root（顶层） / cashier（结算路由） / unknown。上报遥测。 */
  boundary_level?: BoundaryLevel;
  /** 默认 'fatal'。warn/info 用于非阻断性降级 UI。 */
  severity?: CrashSeverity;
  /** 关联支付 saga ID（从当前结算上下文传入）。 */
  saga_id?: string;
  /** 当前订单号（如 XJ20260424-00047）。 */
  order_no?: string;
  /** 已知的超时原因（当捕获的是 TxTimeoutError 时可预填）。 */
  timeout_reason?: TimeoutReason;
  /** 预期恢复动作（reset / redirect_tables / retry / abort）。 */
  recovery_action?: RecoveryAction;
  /**
   * 自动重置毫秒数（Sprint A1）。>0 时，捕获错误后 N ms 自动调用 reset() + onReset()，
   * 用于网络抖动类短暂崩溃的自愈场景（收银员无需重启 POS）。
   * 0 / undefined = 不自动重置。
   */
  resetAfterMs?: number;
}

interface ErrorBoundaryState {
  error: Error | null;
  componentStack: string;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null, componentStack: '' };
  private _autoResetTimer: ReturnType<typeof setTimeout> | null = null;

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    const componentStack = info.componentStack ?? '';
    this.setState({ componentStack });
    const report: ErrorReport = {
      error: { name: error.name, message: error.message, stack: error.stack },
      componentStack,
      occurredAt: new Date().toISOString(),
      boundary_level: this.props.boundary_level,
      severity: this.props.severity ?? 'fatal',
      saga_id: this.props.saga_id,
      order_no: this.props.order_no,
      timeout_reason: this.props.timeout_reason,
      recovery_action: this.props.recovery_action,
    };
    try {
      this.props.onReport?.(report);
    } catch {
      // 上报失败不可再抛出
    }

    // Sprint A1：N ms 后自动重置（用于网络抖动自愈）
    const resetAfter = this.props.resetAfterMs;
    if (typeof resetAfter === 'number' && resetAfter > 0) {
      if (this._autoResetTimer) clearTimeout(this._autoResetTimer);
      this._autoResetTimer = setTimeout(() => {
        this.reset();
        try {
          this.props.onReset?.();
        } catch {
          // onReset 失败不再抛
        }
      }, resetAfter);
    }
  }

  componentDidUpdate(prev: ErrorBoundaryProps): void {
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.reset();
    }
  }

  componentWillUnmount(): void {
    if (this._autoResetTimer) {
      clearTimeout(this._autoResetTimer);
      this._autoResetTimer = null;
    }
  }

  reset = (): void => {
    if (this._autoResetTimer) {
      clearTimeout(this._autoResetTimer);
      this._autoResetTimer = null;
    }
    this.setState({ error: null, componentStack: '' });
  };

  handleReturn = (): void => {
    this.reset();
    this.props.onReset?.();
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    if (this.props.fallback) return this.props.fallback(error, this.reset);

    const debug = this.props.debug ?? (import.meta.env?.DEV ?? false);

    return (
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
        <div style={{ fontSize: 28, fontWeight: 700, marginBottom: 12 }}>结账失败</div>
        <div style={{ fontSize: 16, opacity: 0.8, marginBottom: 24 }}>
          请扫桌重试，或按下方按钮返回桌台
        </div>
        {debug && (
          <pre
            style={{
              maxWidth: 720,
              maxHeight: 240,
              overflow: 'auto',
              background: '#111827',
              color: '#fca5a5',
              padding: 12,
              borderRadius: 8,
              fontSize: 12,
              textAlign: 'left',
            }}
          >
            {error.message}
            {error.stack ? `\n${error.stack}` : ''}
            {this.state.componentStack}
          </pre>
        )}
        <button
          type="button"
          onClick={this.handleReturn}
          style={{
            marginTop: 16,
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
  }
}

export function reportCrashToTelemetry(report: ErrorReport): void {
  const base = import.meta.env.VITE_API_BASE_URL || '';
  const deviceId =
    (window as unknown as { TXBridge?: { getDeviceInfo?: () => string } }).TXBridge?.getDeviceInfo?.() ||
    navigator.userAgent;
  const tenantId = localStorage.getItem('tenant_id') || '';
  try {
    void fetch(`${base}/api/v1/telemetry/pos-crash`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Tenant-ID': tenantId,
      },
      body: JSON.stringify({
        device_id: deviceId,
        route: window.location.pathname,
        error_stack: report.error.stack ?? `${report.error.name}: ${report.error.message}`,
        store_id: localStorage.getItem('store_id') || undefined,
        // Sprint A1 扩字段
        boundary_level: report.boundary_level,
        severity: report.severity,
        saga_id: report.saga_id,
        order_no: report.order_no,
        timeout_reason: report.timeout_reason,
        recovery_action: report.recovery_action,
      }),
      keepalive: true,
    }).catch(() => {});
  } catch {
    // 遥测绝不阻塞 UI
  }
}
