import { useToasts } from '../hooks/useToast';
import { Toast } from './Toast';
import { isEnabled } from '../config/featureFlags';

export function ToastContainer(): JSX.Element | null {
  const toasts = useToasts();
  if (!isEnabled('trade.pos.toast.enable')) return null;

  return (
    <div
      aria-live="polite"
      style={{
        position: 'fixed',
        top: 16,
        right: 16,
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        pointerEvents: 'none',
      }}
    >
      {toasts.map((t) => (
        <div key={t.id} style={{ pointerEvents: 'auto' }}>
          <Toast item={t} />
        </div>
      ))}
    </div>
  );
}
