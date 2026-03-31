/**
 * 翻台预测提示卡 — Phase 3-A AI-Native 护城河功能
 *
 * 当翻台预测显示"预计20分钟内结束"且等位队列有人时，
 * 在底部浮动显示候位提醒卡（非模态，不阻断主流程）。
 *
 * inline style, 命名导出, 触控热区 >= 48px, 字体 >= 16px
 */

interface TurnPredictionAlertProps {
  tableNo: string;
  estimatedMinutes: number;
  queueCount: number;      // 候位人数（组数）
  onNotifyQueue: () => void;
  onDismiss: () => void;
}

export function TurnPredictionAlert({
  tableNo,
  estimatedMinutes,
  queueCount,
  onNotifyQueue,
  onDismiss,
}: TurnPredictionAlertProps) {
  // 只在满足条件时渲染：预计20分钟内结束且有候位顾客
  if (estimatedMinutes > 20 || queueCount <= 0) return null;

  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        position: 'fixed',
        bottom: 80,
        left: 16,
        right: 16,
        zIndex: 200,
        background: '#0d2233',
        border: '1.5px solid #1A9BE8',
        borderRadius: 14,
        padding: '14px 16px',
        boxShadow: '0 4px 24px rgba(0,0,0,0.5)',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      {/* 标题行 */}
      <div style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 8,
      }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0', lineHeight: 1.4 }}>
            {tableNo}桌预计{estimatedMinutes}分钟后结束
          </div>
          <div style={{ fontSize: 16, color: '#94a3b8', marginTop: 4, lineHeight: 1.4 }}>
            等位队列还有{queueCount}组，是否提前通知？
          </div>
        </div>
        {/* 关闭按钮 */}
        <button
          onClick={onDismiss}
          aria-label="忽略此提示"
          style={{
            minWidth: 32,
            minHeight: 32,
            padding: 0,
            background: 'transparent',
            border: 'none',
            color: '#64748b',
            fontSize: 18,
            cursor: 'pointer',
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: 6,
          }}
        >
          ×
        </button>
      </div>

      {/* 操作按钮行 */}
      <div style={{ display: 'flex', gap: 10 }}>
        <button
          onClick={onNotifyQueue}
          style={{
            flex: 1,
            minHeight: 48,
            background: '#1A9BE8',
            border: 'none',
            borderRadius: 10,
            color: '#ffffff',
            fontSize: 16,
            fontWeight: 700,
            cursor: 'pointer',
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          通知
        </button>
        <button
          onClick={onDismiss}
          style={{
            flex: 1,
            minHeight: 48,
            background: 'transparent',
            border: '1.5px solid #2a3a44',
            borderRadius: 10,
            color: '#64748b',
            fontSize: 16,
            fontWeight: 400,
            cursor: 'pointer',
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          忽略
        </button>
      </div>
    </div>
  );
}

export default TurnPredictionAlert;
