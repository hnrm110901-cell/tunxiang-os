import React from 'react';
import styles from './ZInput.module.css';

interface ZInputProps {
  placeholder?: string;
  value?: string;
  onChange?: (v: string) => void;
  onClear?: () => void;
  icon?: React.ReactNode;
  style?: React.CSSProperties;
}

export default function ZInput({ placeholder, value, onChange, onClear, icon, style }: ZInputProps) {
  return (
    <div className={styles.wrap} style={style}>
      {icon && <span className={styles.iconLeft}>{icon}</span>}
      <input
        className={`${styles.input} ${icon ? styles.hasIcon : ''}`}
        placeholder={placeholder}
        value={value}
        onChange={e => onChange?.(e.target.value)}
      />
      {value && onClear && (
        <button className={styles.clearBtn} onClick={onClear} type="button">✕</button>
      )}
    </div>
  );
}
