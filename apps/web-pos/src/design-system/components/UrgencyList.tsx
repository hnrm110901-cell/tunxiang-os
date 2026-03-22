import React from 'react';
import ZBadge from './ZBadge';

interface UrgencyItem {
  id:              string;
  title:           string;
  description?:    string;
  urgency:         'critical' | 'warning' | 'info';
  amount_yuan?:    number;
  action_label?:   string;
  onAction?:       () => void;
}

interface UrgencyListProps {
  items:     UrgencyItem[];
  maxItems?: number;
}

const urgencyLabel: Record<UrgencyItem['urgency'], string> = {
  critical: '紧急',
  warning:  '告警',
  info:     '提示',
};

export default function UrgencyList({ items, maxItems = 5 }: UrgencyListProps) {
  const visible = items.slice(0, maxItems);

  if (!visible.length) {
    return (
      <div style={{ padding: '16px 0', textAlign: 'center', color: 'var(--text-tertiary)', fontSize: 13 }}>
        暂无待处理事项
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      {visible.map((item) => (
        <div
          key={item.id}
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 12,
            padding: '12px 0',
            borderBottom: '1px solid var(--border)',
          }}
        >
          <div style={{ paddingTop: 2 }}>
            <ZBadge type={item.urgency} text={urgencyLabel[item.urgency]} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', lineHeight: '1.4' }}>
              {item.title}
            </div>
            {item.description && (
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                {item.description}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, flexShrink: 0 }}>
            {item.amount_yuan !== undefined && (
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)' }}>
                ¥{item.amount_yuan.toFixed(0)}
              </span>
            )}
            {item.onAction && item.action_label && (
              <button
                onClick={item.onAction}
                style={{
                  fontSize: 12,
                  color: 'var(--accent)',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  padding: 0,
                  fontFamily: 'inherit',
                  fontWeight: 600,
                }}
              >
                {item.action_label} →
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
