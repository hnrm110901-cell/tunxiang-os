import React from 'react';
import styles from './TXNumpad.module.css';

export interface TXNumpadProps {
  value: string;
  onChange: (value: string) => void;
  onConfirm: (value: number) => void;
  allowDecimal?: boolean;
  maxValue?: number;
  label?: string;
}

const KEYS = [
  ['1', '2', '3'],
  ['4', '5', '6'],
  ['7', '8', '9'],
  ['.', '0', 'del'],
];

export function TXNumpad({
  value,
  onChange,
  onConfirm,
  allowDecimal = true,
  maxValue,
  label,
}: TXNumpadProps) {
  const handleKey = (key: string) => {
    if (key === 'del') {
      onChange(value.slice(0, -1));
      return;
    }
    if (key === '.') {
      if (!allowDecimal) return;
      if (value.includes('.')) return;
      onChange(value === '' ? '0.' : value + '.');
      return;
    }
    const next = value + key;
    // 最多保留两位小数
    if (value.includes('.') && value.split('.')[1]?.length === 2) return;
    const numVal = parseFloat(next);
    if (maxValue !== undefined && !isNaN(numVal) && numVal > maxValue) return;
    onChange(next);
  };

  const handleConfirm = () => {
    const num = parseFloat(value);
    if (!isNaN(num)) {
      onConfirm(num);
    }
  };

  return (
    <div className={styles.numpad}>
      {/* 显示区域 */}
      <div className={styles.display}>
        {label && <span className={styles.label}>{label}</span>}
        <span className={styles.displayValue}>{value || '0'}</span>
      </div>

      {/* 键盘区域 */}
      <div className={styles.grid}>
        <div className={styles.keys}>
          {KEYS.map((row, rowIdx) => (
            <div key={rowIdx} className={styles.row}>
              {row.map((key) => (
                <button
                  key={key}
                  type="button"
                  className={`${styles.key} ${key === '.' && !allowDecimal ? styles.keyDisabled : ''}`}
                  onClick={() => handleKey(key)}
                  disabled={key === '.' && !allowDecimal}
                  aria-label={key === 'del' ? '删除' : key}
                >
                  {key === 'del' ? (
                    <span className={styles.delIcon} aria-hidden="true">⌫</span>
                  ) : (
                    key
                  )}
                </button>
              ))}
            </div>
          ))}
        </div>

        {/* 确认键（竖排，占两行高度） */}
        <button
          type="button"
          className={styles.confirmKey}
          onClick={handleConfirm}
          aria-label="确认"
        >
          确认
        </button>
      </div>
    </div>
  );
}

export default TXNumpad;
