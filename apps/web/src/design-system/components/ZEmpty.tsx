import React from 'react';
import styles from './ZEmpty.module.css';

interface ZEmptyProps {
  icon?: React.ReactNode;
  title?: string;
  description?: string;
  action?: React.ReactNode;
}

export default function ZEmpty({
  icon = '📭',
  title = '暂无数据',
  description,
  action,
}: ZEmptyProps) {
  return (
    <div className={styles.wrap}>
      <div className={styles.icon}>{icon}</div>
      {title && <p className={styles.title}>{title}</p>}
      {description && <p className={styles.desc}>{description}</p>}
      {action && <div className={styles.action}>{action}</div>}
    </div>
  );
}
