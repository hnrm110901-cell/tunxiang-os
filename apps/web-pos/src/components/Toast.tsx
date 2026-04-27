import { useEffect, useRef } from 'react';
import { ToastItem, dismissToast } from '../hooks/useToast';

interface ToastProps {
  item: ToastItem;
}

const PALETTE: Record<ToastItem['type'], { bg: string; fg: string; icon: string }> = {
  success: { bg: '#16a34a', fg: '#ffffff', icon: '✓' },
  error: { bg: '#dc2626', fg: '#ffffff', icon: '✕' },
  info: { bg: '#2563eb', fg: '#ffffff', icon: 'i' },
  // Sprint A1 新增：warning（琥珀色，打印机纸张不足/厨房出餐超时等非阻断提醒）
  warning: { bg: '#d97706', fg: '#ffffff', icon: '!' },
  offline: { bg: '#6b7280', fg: '#ffffff', icon: '⟳' },
};

export function Toast({ item }: ToastProps): JSX.Element {
  const style = PALETTE[item.type];
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (item.autoDismissMs == null) return;
    timer.current = setTimeout(() => dismissToast(item.id), item.autoDismissMs);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [item.id, item.autoDismissMs]);

  const label = item.type === 'offline' ? '离线队列中' : item.type;

  return (
    <div
      data-toast-id={item.id}
      data-toast-type={item.type}
      role="status"
      aria-label={`${label}提示`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        minWidth: 280,
        maxWidth: 420,
        padding: '10px 14px',
        borderRadius: 8,
        background: style.bg,
        color: style.fg,
        boxShadow: '0 6px 16px rgba(0,0,0,0.25)',
        fontSize: 14,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 22,
          height: 22,
          borderRadius: '50%',
          background: 'rgba(255,255,255,0.2)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontWeight: 700,
        }}
      >
        {style.icon}
      </span>
      <span style={{ flex: 1 }}>{item.message}</span>
      {item.type === 'offline' && (
        <span style={{ fontSize: 12, opacity: 0.85 }}>离线队列中</span>
      )}
      <button
        type="button"
        aria-label="关闭"
        onClick={() => dismissToast(item.id)}
        style={{
          background: 'transparent',
          border: 'none',
          color: style.fg,
          fontSize: 18,
          cursor: 'pointer',
          lineHeight: 1,
        }}
      >
        ×
      </button>
    </div>
  );
}
