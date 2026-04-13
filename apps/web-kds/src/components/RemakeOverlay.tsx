/**
 * RemakeOverlay — KDS 重做通知弹窗
 *
 * 全屏遮罩 + 居中卡片，显示重做原因和次数。
 * 由 KitchenBoard 和 ZoneKitchenBoard 共享使用。
 */
import type { RemakeAlert } from '../hooks/useKdsWebSocket';

interface RemakeOverlayProps {
  alerts: RemakeAlert[];
  onDismiss: (taskId: string) => void;
  /** CSS animation name for slide-in effect (default: 'kds-slide-in') */
  slideAnimation?: string;
}

export function RemakeOverlay({ alerts, onDismiss, slideAnimation = 'kds-slide-in' }: RemakeOverlayProps) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000,
    }}>
      <div style={{
        background: '#1a1a1a', borderRadius: 16, padding: 28,
        border: '3px solid #A32D2D', maxWidth: 480, width: '90%',
        animation: `${slideAnimation} 0.3s ease-out`,
      }}>
        <div style={{
          fontSize: 28, fontWeight: 'bold', color: '#ff4d4f',
          marginBottom: 20, textAlign: 'center',
        }}>
          重做通知
        </div>
        {alerts.map(a => (
          <div key={a.taskId} style={{
            background: '#222', borderRadius: 12, padding: 16,
            marginBottom: 12, borderLeft: '6px solid #A32D2D',
          }}>
            <div style={{ fontSize: 22, fontWeight: 'bold', color: '#fff', marginBottom: 8 }}>
              {a.tableNumber && `${a.tableNumber} - `}{a.dishName}
              {a.remakeCount > 1 && (
                <span style={{ fontSize: 18, color: '#ff4d4f', marginLeft: 8 }}>
                  (第{a.remakeCount}次)
                </span>
              )}
            </div>
            <div style={{ fontSize: 18, color: '#BA7517', marginBottom: 12 }}>
              原因: {a.reason}
            </div>
            <button
              onClick={() => onDismiss(a.taskId)}
              style={{
                width: '100%', padding: '14px 0', background: '#A32D2D',
                color: '#fff', border: 'none', borderRadius: 8,
                fontSize: 20, fontWeight: 'bold', cursor: 'pointer',
                minHeight: 56,
              }}
              onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
              onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
            >
              收到，立即重做
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
