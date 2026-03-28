/**
 * TXAgentAlert — Agent 预警条（固定屏幕顶部，不可关闭）
 *
 * 规范:
 *   - critical: 红色背景 + 白色文字 + 脉冲动画
 *   - warning: 橙色背景
 *   - info: 蓝色背景
 *   - 固定在 SafeArea 顶部，其他内容下推
 *   - 不可被用户关闭（只能处理或等 Agent 撤回）
 */
import styles from './TXAgentAlert.module.css';

export interface TXAgentAlertProps {
  agentName: string;
  message: string;
  severity: 'info' | 'warning' | 'critical';
  onAction?: () => void;
  actionLabel?: string;
}

export function TXAgentAlert({
  agentName,
  message,
  severity,
  onAction,
  actionLabel,
}: TXAgentAlertProps) {
  return (
    <div
      className={`${styles.bar} ${styles[severity]} ${severity === 'critical' ? 'tx-pulse' : ''}`}
      role="alert"
      aria-live={severity === 'critical' ? 'assertive' : 'polite'}
    >
      <div className={styles.content}>
        <span className={styles.agent}>{agentName}</span>
        <span className={styles.message}>{message}</span>
      </div>
      {onAction && actionLabel && (
        <button className={`${styles.action} tx-pressable`} onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  );
}
