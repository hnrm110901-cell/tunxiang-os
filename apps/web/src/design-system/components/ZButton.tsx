import React from 'react';
import styles from './ZButton.module.css';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'lg';

interface ZButtonProps {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  children?: React.ReactNode;
  style?: React.CSSProperties;
  type?: 'button' | 'submit' | 'reset';
}

export default function ZButton({
  variant = 'primary', size = 'md', loading, icon, disabled,
  onClick, children, style, type = 'button',
}: ZButtonProps) {
  return (
    <button
      type={type}
      className={`${styles.btn} ${styles[variant]} ${styles[size]}`}
      disabled={disabled || loading}
      onClick={onClick}
      style={style}
    >
      {loading ? <span>⟳</span> : icon}
      {children}
    </button>
  );
}
