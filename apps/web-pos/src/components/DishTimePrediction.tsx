/**
 * DishTimePrediction — AI 出品时间预测组件
 *
 * 根据预测分钟数显示对应颜色和文案，支持超时警示和紧凑模式。
 * Sprint 2：菜品智能体 + 客户大脑 POS 层
 */

interface DishTimePredictionProps {
  dishName: string;
  predictedMinutes: number;  // AI预测分钟数
  elapsedMinutes?: number;   // 已等待分钟数（如有）
  compact?: boolean;         // 紧凑模式（用于卡片内嵌）
}

function getTimingConfig(minutes: number): { color: string; text: string; icon: string } {
  if (minutes <= 10) {
    return { color: '#0F6E56', text: `约${minutes}分钟`, icon: '🟢' };
  }
  if (minutes <= 20) {
    return { color: '#BA7517', text: `约${minutes}分钟，稍候`, icon: '🟡' };
  }
  return { color: '#A32D2D', text: `预计${minutes}分钟，较慢`, icon: '🔴' };
}

export default function DishTimePrediction({
  dishName,
  predictedMinutes,
  elapsedMinutes,
  compact = false,
}: DishTimePredictionProps) {
  const { color, text, icon } = getTimingConfig(predictedMinutes);
  const isOverdue =
    elapsedMinutes !== undefined && elapsedMinutes > predictedMinutes;
  const overdueMinutes = isOverdue
    ? elapsedMinutes! - predictedMinutes
    : 0;

  if (compact) {
    return (
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          fontSize: 12,
          color,
          fontWeight: 600,
        }}
      >
        {icon}
        <span>{text}</span>
        {isOverdue && (
          <span
            style={{
              color: '#A32D2D',
              animation: 'tx-pulse 1s infinite',
              marginLeft: 4,
            }}
          >
            ⚠ 超{overdueMinutes}分钟
          </span>
        )}
      </span>
    );
  }

  return (
    <div
      style={{
        background: `rgba(${color === '#0F6E56' ? '15,110,86' : color === '#BA7517' ? '186,117,23' : '163,45,45'}, .06)`,
        border: `1px solid ${color}33`,
        borderRadius: 8,
        padding: '8px 12px',
      }}
    >
      {/* 标题 */}
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: '#8A94A4',
          textTransform: 'uppercase',
          letterSpacing: '0.5px',
          marginBottom: 4,
        }}
      >
        AI 出品预测 · {dishName}
      </div>

      {/* 时间信息 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <span style={{ fontSize: 20 }}>{icon}</span>
        <span
          style={{
            fontSize: 15,
            fontWeight: 700,
            color,
          }}
        >
          {text}
        </span>

        {/* 进度展示（如有已等待时间） */}
        {elapsedMinutes !== undefined && !isOverdue && (
          <span style={{ fontSize: 12, color: '#8A94A4', marginLeft: 4 }}>
            已等 {elapsedMinutes} 分钟
          </span>
        )}
      </div>

      {/* 超时警示 */}
      {isOverdue && (
        <>
          <style>{`
            @keyframes tx-pulse {
              0%, 100% { opacity: 1; }
              50%       { opacity: 0.5; }
            }
          `}</style>
          <div
            style={{
              marginTop: 6,
              fontSize: 13,
              fontWeight: 700,
              color: '#A32D2D',
              animation: 'tx-pulse 1s infinite',
              display: 'flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            ⚠ 已超时 {overdueMinutes} 分钟
          </div>
        </>
      )}
    </div>
  );
}
