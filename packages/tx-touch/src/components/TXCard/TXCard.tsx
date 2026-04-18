import React from 'react';
import styles from './TXCard.module.css';

export interface TXCardProps {
  selected?: boolean;
  status?: 'normal' | 'warning' | 'danger';
  onPress?: () => void;
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

export function TXCard({
  selected = false,
  status = 'normal',
  onPress,
  children,
  className,
  style,
}: TXCardProps) {
  const classNames = [
    styles.card,
    selected ? styles.selected : '',
    status === 'warning' ? styles.warning : '',
    status === 'danger' ? styles.danger : '',
    onPress ? styles.pressable : '',
    className ?? '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div
      className={classNames}
      style={style}
      onClick={onPress}
      role={onPress ? 'button' : undefined}
      tabIndex={onPress ? 0 : undefined}
      onKeyDown={
        onPress
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') onPress();
            }
          : undefined
      }
    >
      {children}
    </div>
  );
}

export default TXCard;
