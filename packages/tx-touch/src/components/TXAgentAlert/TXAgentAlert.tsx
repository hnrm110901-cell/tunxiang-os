import React, { useEffect, useRef } from 'react';
import styles from './TXAgentAlert.module.css';

export interface TXAgentAlertProps {
  agentName: string;
  message: string;
  severity: 'info' | 'warning' | 'critical';
  data?: Record<string, unknown>;
  onAction?: () => void;
  actionLabel?: string;
}

export function TXAgentAlert({
  agentName,
  message,
  severity,
  data: _data,
  onAction,
  actionLabel,
}: TXAgentAlertProps) {
  const alertRef = useRef<HTMLDivElement>(null);

  // 动态更新 CSS 变量 --agent-alert-height，供下方内容使用
  useEffect(() => {
    const updateHeight = () => {
      if (alertRef.current) {
        const h = alertRef.current.offsetHeight;
        document.documentElement.style.setProperty('--agent-alert-height', `${h}px`);
      }
    };
    updateHeight();
    const observer = new ResizeObserver(updateHeight);
    if (alertRef.current) observer.observe(alertRef.current);
    return () => {
      observer.disconnect();
      document.documentElement.style.setProperty('--agent-alert-height', '0px');
    };
  }, []);

  const severityClass = {
    info: styles.info,
    warning: styles.warning,
    critical: styles.critical,
  }[severity];

  return (
    <div
      ref={alertRef}
      className={`${styles.alert} ${severityClass}`}
      role="alert"
      aria-live={severity === 'critical' ? 'assertive' : 'polite'}
    >
      <div className={styles.content}>
        <span className={styles.agentTag}>{agentName}</span>
        <span className={styles.message}>{message}</span>
      </div>
      {onAction && actionLabel && (
        <button
          type="button"
          className={styles.actionBtn}
          onClick={onAction}
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}

export default TXAgentAlert;
