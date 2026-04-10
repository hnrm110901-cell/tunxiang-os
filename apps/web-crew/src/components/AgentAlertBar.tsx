/**
 * AgentAlertBar — Agent 顶部预警条（web-crew）
 * Sprint 1: 运营指挥官基础层
 */

export interface AgentAlert {
  id: string;
  level: 'critical' | 'warning' | 'info';
  message: string;
  actionLabel?: string;
  onAction?: () => void;
}

interface AgentAlertBarProps {
  alerts?: AgentAlert[];
}

const DEFAULT_ALERTS: AgentAlert[] = [
  {
    id: '1',
    level: 'critical',
    message: '🔴 运营指挥官 · B01桌 剁椒鱼头超时8分钟 — 已自动催单，预计5分钟',
    actionLabel: '查看',
  },
];

const LEVEL_STYLE: Record<AgentAlert['level'], { background: string; borderBottom: string; color: string }> = {
  critical: {
    background: 'rgba(163,45,45,.1)',
    borderBottom: '2px solid #A32D2D',
    color: '#A32D2D',
  },
  warning: {
    background: 'rgba(186,117,23,.1)',
    borderBottom: '2px solid #BA7517',
    color: '#BA7517',
  },
  info: {
    background: 'rgba(24,95,165,.08)',
    borderBottom: '2px solid #185FA5',
    color: '#185FA5',
  },
};

export default function AgentAlertBar({ alerts = DEFAULT_ALERTS }: AgentAlertBarProps) {
  if (!alerts || alerts.length === 0) return null;

  // 取第一条（最高优先级）
  const alert = alerts[0];
  const levelStyle = LEVEL_STYLE[alert.level];

  return (
    <>
      {alert.level === 'critical' && (
        <style>{`
          @keyframes txAlertPulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
          }
          .tx-agent-alert-critical {
            animation: txAlertPulse 1.8s ease-in-out infinite;
          }
        `}</style>
      )}
      <div
        className={alert.level === 'critical' ? 'tx-agent-alert-critical' : undefined}
        style={{
          height: 48,
          display: 'flex',
          alignItems: 'center',
          padding: '0 16px',
          gap: 12,
          background: levelStyle.background,
          borderBottom: levelStyle.borderBottom,
        }}
      >
        {/* 消息文本 */}
        <span
          style={{
            flex: 1,
            fontSize: 13,
            fontWeight: 600,
            color: levelStyle.color,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {alert.message}
        </span>

        {/* 行动按钮 */}
        {alert.actionLabel && (
          <button
            onClick={alert.onAction}
            style={{
              flexShrink: 0,
              minHeight: 44,
              padding: '0 16px',
              border: `1px solid ${levelStyle.color}`,
              borderRadius: 6,
              background: 'transparent',
              color: levelStyle.color,
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            {alert.actionLabel}
          </button>
        )}
      </div>
    </>
  );
}

export type { AgentAlertBarProps };
