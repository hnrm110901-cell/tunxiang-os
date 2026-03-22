import React from 'react';
import styles from './ZButton.module.css';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'default';
type Size = 'sm' | 'md' | 'lg';

interface ZButtonProps {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: React.ReactNode;
  disabled?: boolean;
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  children?: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
  type?: 'button' | 'submit' | 'reset';
  title?: string;
}

export default function ZButton({
  variant = 'primary', size = 'md', loading, icon, disabled,
  onClick, children, style, className, type = 'button', title,
}: ZButtonProps) {
  const normalizedVariant = variant === 'default' ? 'secondary' : variant;
  return (
    <button
      type={type}
      className={`${styles.btn} ${styles[normalizedVariant]} ${styles[size]} ${className ?? ''}`}
      disabled={disabled || loading}
      onClick={onClick}
      style={style}
      title={title}
    >
      {loading ? <span>⟳</span> : icon}
      {children}
    </button>
  );
}
