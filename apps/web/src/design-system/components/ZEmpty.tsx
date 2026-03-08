import React from 'react';
import styles from './ZEmpty.module.css';

interface ZEmptyProps {
  icon?: React.ReactNode;
  title?: string;
  text?: string;
  description?: string;
  action?: React.ReactNode;
}

export default function ZEmpty({
  icon = '📭',
  title = '暂无数据',
  text,
  description,
  action,
}: ZEmptyProps) {
  const shownTitle = text ?? title;
  return (
    <div className={styles.wrap}>
      <div className={styles.icon}>{icon}</div>
      {shownTitle && <p className={styles.title}>{shownTitle}</p>}
      {description && <p className={styles.desc}>{description}</p>}
      {action && <div className={styles.action}>{action}</div>}
    </div>
  );
}
