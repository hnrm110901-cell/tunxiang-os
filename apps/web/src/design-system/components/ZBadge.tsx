import React from 'react';
import styles from './ZBadge.module.css';

type BadgeType = 'critical' | 'warning' | 'success' | 'info' | 'default' | 'accent';

interface ZBadgeProps {
  type?: BadgeType;
  text: string;
  icon?: React.ReactNode;
}

export default function ZBadge({ type = 'default', text, icon }: ZBadgeProps) {
  return (
    <span className={`${styles.badge} ${styles[type]}`}>
      {icon && icon}
      {text}
    </span>
  );
}
