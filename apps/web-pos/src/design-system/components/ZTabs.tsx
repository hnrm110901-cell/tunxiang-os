import React, { useState } from 'react';
import styles from './ZTabs.module.css';

interface TabItem {
  key:    string;
  label:  string;
  badge?: number;
  children: React.ReactNode;
}

interface ZTabsProps {
  items:        TabItem[];
  defaultKey?:  string;
  onChange?:    (key: string) => void;
}

export default function ZTabs({ items, defaultKey, onChange }: ZTabsProps) {
  const [active, setActive] = useState(defaultKey ?? items[0]?.key ?? '');

  const handleSelect = (key: string) => {
    setActive(key);
    onChange?.(key);
  };

  const current = items.find(i => i.key === active);

  return (
    <div>
      <div className={styles.tabs} role="tablist">
        {items.map(item => (
          <button
            key={item.key}
            role="tab"
            aria-selected={item.key === active}
            className={`${styles.tab} ${item.key === active ? styles.active : ''}`}
            onClick={() => handleSelect(item.key)}
          >
            {item.label}
            {item.badge != null && item.badge > 0 && (
              <span className={styles.badge}>{item.badge > 99 ? '99+' : item.badge}</span>
            )}
          </button>
        ))}
      </div>
      <div className={styles.panel} role="tabpanel">
        {current?.children}
      </div>
    </div>
  );
}
