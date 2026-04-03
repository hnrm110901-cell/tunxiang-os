import { useLang } from '@/i18n/LangContext';
import type { OrderStatus } from '@/api/orderApi';
import styles from './ProgressTracker.module.css';

interface Step {
  key: OrderStatus;
  label: string;
  estimatedMinutes: number;
  completedAt?: string;
}

interface ProgressTrackerProps {
  steps: Step[];
  currentStatus: OrderStatus;
}

const STATUS_ORDER: OrderStatus[] = ['received', 'cooking', 'ready', 'pickup'];

export default function ProgressTracker({ steps, currentStatus }: ProgressTrackerProps) {
  const { t } = useLang();
  const currentIdx = STATUS_ORDER.indexOf(currentStatus);

  const stepLabels: Record<OrderStatus, string> = {
    received: t('stepReceived'),
    cooking: t('stepCooking'),
    ready: t('stepReady'),
    pickup: t('stepPickup'),
    completed: t('stepPickup'),
  };

  return (
    <div className={styles.tracker}>
      {STATUS_ORDER.map((key, idx) => {
        const step = steps.find((s) => s.key === key);
        const isCompleted = idx <= currentIdx;
        const isActive = idx === currentIdx;

        return (
          <div key={key} className={styles.stepWrap}>
            {/* 连接线 */}
            {idx > 0 && (
              <div className={`${styles.line} ${idx <= currentIdx ? styles.lineActive : ''}`} />
            )}

            {/* 圆点 */}
            <div
              className={`
                ${styles.dot}
                ${isCompleted ? styles.dotCompleted : ''}
                ${isActive ? styles.dotActive : ''}
              `}
            >
              {isCompleted && (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <path d="M5 13l4 4L19 7" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              )}
            </div>

            {/* 标签 */}
            <span className={`${styles.label} ${isActive ? styles.labelActive : ''}`}>
              {stepLabels[key]}
            </span>

            {/* 预估时间 */}
            {step && !step.completedAt && isActive && (
              <span className={styles.estimate}>
                {t('estimatedTime').replace('{min}', String(step.estimatedMinutes))}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
