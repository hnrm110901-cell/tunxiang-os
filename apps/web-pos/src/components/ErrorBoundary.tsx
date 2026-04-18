import { Component, ErrorInfo, ReactNode } from 'react';

export interface ErrorReport {
  error: {
    name: string;
    message: string;
    stack?: string;
  };
  componentStack: string;
  occurredAt: string;
}

export interface ErrorBoundaryProps {
  children: ReactNode;
  resetKey?: string | number;
  debug?: boolean;
  onReset?: () => void;
  onReport?: (report: ErrorReport) => void;
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
  componentStack: string;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null, componentStack: '' };

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
    };
    try {
      this.props.onReport?.(report);
    } catch {
      // 上报失败不可再抛出
    }
  }

  componentDidUpdate(prev: ErrorBoundaryProps): void {
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.reset();
    }
  }

  reset = (): void => {
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
  try {
    void fetch(`${base}/api/v1/telemetry/pos-crash`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(report),
      keepalive: true,
    }).catch(() => {});
  } catch {
    // 遥测绝不阻塞 UI
  }
}
