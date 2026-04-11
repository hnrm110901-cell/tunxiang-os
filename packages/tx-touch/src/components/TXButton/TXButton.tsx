import React from 'react';
import styles from './TXButton.module.css';

export type TXButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
export type TXButtonSize = 'normal' | 'large' | 'fullwidth';

export interface TXButtonProps {
  variant?: TXButtonVariant;
  size?: TXButtonSize;
  icon?: React.ReactNode;
  badge?: number;
  disabled?: boolean;
  loading?: boolean;
  children: React.ReactNode;
  onPress: () => void;
  className?: string;
  style?: React.CSSProperties;
}

export function TXButton({
  variant = 'primary',
  size = 'normal',
  icon,
  badge,
  disabled = false,
  loading = false,
  children,
  onPress,
  className,
  style,
}: TXButtonProps) {
  const classNames = [
    styles.btn,
    styles[variant],
    styles[size],
    className ?? '',
  ]
    .filter(Boolean)
    .join(' ');

  const handleClick = () => {
    if (!disabled && !loading) {
      onPress();
    }
  };

  return (
    <button
      type="button"
      className={classNames}
      disabled={disabled || loading}
      onClick={handleClick}
      style={style}
    >
      {loading ? (
        <span className={styles.loadingIcon} aria-hidden="true" />
      ) : (
        icon && <span className={styles.icon}>{icon}</span>
      )}
      {children}
      {badge !== undefined && badge > 0 && (
        <span className={styles.badge} aria-label={`${badge}个`}>
          {badge >= 10 ? '9+' : badge}
        </span>
      )}
    </button>
  );
}

export default TXButton;
