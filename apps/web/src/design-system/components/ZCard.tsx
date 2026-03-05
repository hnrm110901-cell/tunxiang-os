import React from 'react';
import styles from './ZCard.module.css';

interface ZCardProps {
  title?: React.ReactNode;
  subtitle?: string;
  extra?: React.ReactNode;
  children?: React.ReactNode;
  onClick?: () => void;
  noPadding?: boolean;
  style?: React.CSSProperties;
  className?: string;
}

export default function ZCard({
  title, subtitle, extra, children, onClick, noPadding, style, className,
}: ZCardProps) {
  const classes = [
    styles.card,
    onClick ? styles.clickable : '',
    noPadding ? styles.noPadding : '',
    className || '',
  ].join(' ');

  return (
    <div className={classes} style={style} onClick={onClick}>
      {(title || extra) && (
        <div className={styles.header}>
          <div>
            {title && <div className={styles.title}>{title}</div>}
            {subtitle && <div className={styles.subtitle}>{subtitle}</div>}
          </div>
          {extra && <div>{extra}</div>}
        </div>
      )}
      <div className={styles.body}>{children}</div>
    </div>
  );
}
