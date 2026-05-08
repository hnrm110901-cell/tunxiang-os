import { useEffect, useRef } from 'react';
import styles from './TXAgentAlert.module.css';

export type TXAgentAlertSeverity = 'info' | 'warning' | 'critical';

/** TTS 行为模式 — 默认 auto = 仅 critical 播报（厨房噪音环境下不被淹没） */
export type TXAgentAlertTTSMode = 'auto' | 'never' | 'always';

export interface TXAgentAlertProps {
  agentName: string;
  message: string;
  severity: TXAgentAlertSeverity;
  data?: Record<string, unknown>;
  onAction?: () => void;
  actionLabel?: string;
  /**
   * TTS 播报模式（S3-04）。
   *   - 'auto' (默认): severity=critical 时播报，warning/info 静默
   *   - 'always': 任意 severity 都播报（厨房关键工位）
   *   - 'never': 完全静默（噪音容忍度低的窗口）
   */
  ttsMode?: TXAgentAlertTTSMode;
  /** TTS 内容覆盖；未提供时使用 `${agentName}：${message}` */
  ttsText?: string;
}

/** 内部：决定是否触发 TTS */
function shouldSpeak(severity: TXAgentAlertSeverity, mode: TXAgentAlertTTSMode): boolean {
  if (mode === 'never') return false;
  if (mode === 'always') return true;
  // auto：仅 critical 播报
  return severity === 'critical';
}

/** 内部：调用 Web Speech API 播报。失败/不支持时静默降级。 */
function speakViaWebAPI(text: string): void {
  if (typeof window === 'undefined') return;
  const synth = (window as Window & { speechSynthesis?: SpeechSynthesis }).speechSynthesis;
  if (!synth) return;
  try {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'zh-CN';
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;
    synth.speak(utterance);
  } catch {
    // 静默降级：浏览器可能阻止未交互页面的 TTS
  }
}

export function TXAgentAlert({
  agentName,
  message,
  severity,
  data: _data,
  onAction,
  actionLabel,
  ttsMode = 'auto',
  ttsText,
}: TXAgentAlertProps) {
  const alertRef = useRef<HTMLDivElement>(null);
  const spokenRef = useRef(false);

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

  // S3-04: TTS 触发（mount 时一次，避免重渲染重复播报）
  useEffect(() => {
    if (spokenRef.current) return;
    if (!shouldSpeak(severity, ttsMode)) return;
    spokenRef.current = true;
    speakViaWebAPI(ttsText ?? `${agentName}：${message}`);
  }, [severity, ttsMode, ttsText, agentName, message]);

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
