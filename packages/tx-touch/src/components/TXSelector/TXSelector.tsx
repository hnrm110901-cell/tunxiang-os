import React, { useState, useEffect } from 'react';
import styles from './TXSelector.module.css';

export interface TXSelectorOption {
  label: string;
  value: string;
  icon?: React.ReactNode;
  description?: string;
}

export interface TXSelectorProps {
  title: string;
  options: TXSelectorOption[];
  value: string | string[];
  multiple?: boolean;
  onSelect: (value: string | string[]) => void;
  onClose: () => void;
  visible: boolean;
  searchable?: boolean;
}

export function TXSelector({
  title,
  options,
  value,
  multiple = false,
  onSelect,
  onClose,
  visible,
  searchable = false,
}: TXSelectorProps) {
  const [query, setQuery] = useState('');
  const [selectedValues, setSelectedValues] = useState<string[]>(() =>
    Array.isArray(value) ? value : value ? [value] : [],
  );

  // Sync external value changes
  useEffect(() => {
    setSelectedValues(Array.isArray(value) ? value : value ? [value] : []);
  }, [value]);

  // Reset search on close
  useEffect(() => {
    if (!visible) setQuery('');
  }, [visible]);

  const filtered = query
    ? options.filter((o) =>
        o.label.toLowerCase().includes(query.toLowerCase()) ||
        (o.description ?? '').toLowerCase().includes(query.toLowerCase()),
      )
    : options;

  const isSelected = (val: string) => selectedValues.includes(val);

  const handleOption = (val: string) => {
    if (multiple) {
      const next = isSelected(val)
        ? selectedValues.filter((v) => v !== val)
        : [...selectedValues, val];
      setSelectedValues(next);
      onSelect(next);
    } else {
      setSelectedValues([val]);
      onSelect(val);
      onClose();
    }
  };

  if (!visible) return null;

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div
        className={styles.sheet}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 拖动条 */}
        <div className={styles.handle} aria-hidden="true" />

        {/* 标题 */}
        <div className={styles.header}>
          <h3 className={styles.title}>{title}</h3>
          {multiple && (
            <button
              type="button"
              className={styles.doneBtn}
              onClick={onClose}
            >
              完成
            </button>
          )}
        </div>

        {/* 搜索栏 */}
        {searchable && (
          <div className={styles.searchWrapper}>
            <input
              type="text"
              className={styles.searchInput}
              placeholder="搜索..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoFocus={false}
            />
          </div>
        )}

        {/* 选项列表 */}
        <ul className={styles.list}>
          {filtered.length === 0 ? (
            <li className={styles.empty}>无匹配项</li>
          ) : (
            filtered.map((option) => (
              <li key={option.value}>
                <button
                  type="button"
                  className={`${styles.option} ${isSelected(option.value) ? styles.optionSelected : ''}`}
                  onClick={() => handleOption(option.value)}
                  aria-pressed={isSelected(option.value)}
                >
                  {option.icon && (
                    <span className={styles.optionIcon}>{option.icon}</span>
                  )}
                  <span className={styles.optionContent}>
                    <span className={styles.optionLabel}>{option.label}</span>
                    {option.description && (
                      <span className={styles.optionDesc}>{option.description}</span>
                    )}
                  </span>
                  {multiple && (
                    <span
                      className={`${styles.checkbox} ${isSelected(option.value) ? styles.checkboxChecked : ''}`}
                      aria-hidden="true"
                    >
                      {isSelected(option.value) && '✓'}
                    </span>
                  )}
                  {!multiple && isSelected(option.value) && (
                    <span className={styles.checkmark} aria-hidden="true">✓</span>
                  )}
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}

export default TXSelector;
