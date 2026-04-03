/**
 * 桌台状态汇总栏
 * 显示各状态的桌台数量统计
 * @module pages/TableManagement/components/StatusSummaryBar
 */

import React, { useMemo } from 'react';
import { TableStatus, TableSummary } from '../../../types/table-card';
import styles from '../TableManagement.module.css';

/**
 * 状态配置
 */
const STATUS_CONFIG: Record<
  string,
  {
    label: string;
    color: string;
    statusValue: TableStatus;
  }
> = {
  empty: {
    label: '空台',
    color: '#52c41a',
    statusValue: TableStatus.Empty,
  },
  dining: {
    label: '用餐中',
    color: '#1890ff',
    statusValue: TableStatus.Dining,
  },
  reserved: {
    label: '已预订',
    color: '#faad14',
    statusValue: TableStatus.Reserved,
  },
  pending_checkout: {
    label: '待结账',
    color: '#ff4d4f',
    statusValue: TableStatus.PendingCheckout,
  },
  pending_cleanup: {
    label: '待清台',
    color: '#d9d9d9',
    statusValue: TableStatus.PendingCleanup,
  },
};

/**
 * 汇总栏项目顺序
 */
const STATUS_ORDER = ['empty', 'dining', 'reserved', 'pending_checkout', 'pending_cleanup'];

/**
 * 汇总统计栏Props
 */
export interface StatusSummaryBarProps {
  /** 汇总数据 */
  summary: TableSummary | null;
  /** 当前选中的筛选状态 */
  activeStatus: string | null;
  /** 状态筛选变化回调 */
  onStatusChange: (status: string | null) => void;
  /** 加载中状态 */
  loading?: boolean;
}

/**
 * 汇总统计栏组件
 * 水平排列显示各状态的桌台数量，支持点击筛选
 */
export const StatusSummaryBar: React.FC<StatusSummaryBarProps> = ({
  summary,
  activeStatus,
  onStatusChange,
  loading = false,
}) => {
  const summaryItems = useMemo(() => {
    if (!summary) {
      return [];
    }

    return STATUS_ORDER.map((statusKey) => {
      const config = STATUS_CONFIG[statusKey];
      const count = summary[statusKey as keyof TableSummary];

      return {
        key: statusKey,
        label: config.label,
        color: config.color,
        count,
        statusValue: config.statusValue,
      };
    });
  }, [summary]);

  const handleItemClick = (statusKey: string) => {
    if (loading) return;

    // 如果点击的是已选中的项，则取消筛选
    if (activeStatus === statusKey) {
      onStatusChange(null);
    } else {
      onStatusChange(statusKey);
    }
  };

  if (!summary) {
    return null;
  }

  return (
    <div className={styles.summaryBar}>
      {summaryItems.map((item) => (
        <div
          key={item.key}
          className={`${styles.summaryItem} ${activeStatus === item.key ? styles.active : ''}`}
          onClick={() => handleItemClick(item.key)}
          style={{
            opacity: loading ? 0.6 : 1,
            pointerEvents: loading ? 'none' : 'auto',
          }}
          title={`点击筛选 "${item.label}" 的桌台`}
        >
          <span
            className={styles.statusDot}
            style={{ backgroundColor: item.color }}
            aria-hidden="true"
          />
          <span className={styles.summaryLabel}>{item.label}</span>
          <span className={styles.summaryCount}>{item.count}</span>
        </div>
      ))}
    </div>
  );
};

export default StatusSummaryBar;
