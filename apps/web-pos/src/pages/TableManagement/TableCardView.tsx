/**
 * 智能桌台卡片视图
 * 使用CSS Grid网格布局展示卡片
 * @module pages/TableManagement/TableCardView
 */

import React, { useCallback, useMemo } from 'react';
import { CardField, TableCardData, TableStatus } from '../../types/table-card';
import { useTableStore } from '../../stores/tableStore';
import styles from './TableManagement.module.css';

/**
 * 卡片视图Props
 */
export interface TableCardViewProps {
  /** 桌台列表 */
  tables: TableCardData[];
  /** 门店ID */
  storeId: string;
  /** 加载中状态 */
  loading?: boolean;
}

/**
 * 获取状态对应的CSS类名
 */
const getStatusClassName = (status: TableStatus): string => {
  const statusMap: Record<TableStatus, string> = {
    [TableStatus.Empty]: styles.empty,
    [TableStatus.Dining]: styles.dining,
    [TableStatus.Reserved]: styles.reserved,
    [TableStatus.PendingCheckout]: styles.pendingCheckout,
    [TableStatus.PendingCleanup]: styles.pendingCleanup,
  };
  return statusMap[status];
};

/**
 * 获取状态徽章的样式类名
 */
const getStatusBadgeClassName = (status: TableStatus): string => {
  const statusMap: Record<TableStatus, string> = {
    [TableStatus.Empty]: styles.empty,
    [TableStatus.Dining]: styles.dining,
    [TableStatus.Reserved]: styles.reserved,
    [TableStatus.PendingCheckout]: styles.pendingCheckout,
    [TableStatus.PendingCleanup]: styles.pendingCleanup,
  };
  return statusMap[status];
};

/**
 * 获取告警级别的CSS类名
 */
const getAlertClassName = (alert: string): string => {
  switch (alert) {
    case 'critical':
      return styles.criticalAlert;
    case 'warning':
      return styles.warningAlert;
    case 'info':
      return styles.infoAlert;
    default:
      return styles.normalAlert;
  }
};

/**
 * 获取字段告警级别的样式
 */
const getFieldAlertClassName = (alert: string): string => {
  switch (alert) {
    case 'critical':
      return styles.criticalAlert;
    case 'warning':
      return styles.warningAlert;
    case 'info':
      return styles.infoAlert;
    default:
      return styles.normalAlert;
  }
};

/**
 * 获取状态对应的显示文本
 */
const getStatusText = (status: TableStatus): string => {
  const statusMap: Record<TableStatus, string> = {
    [TableStatus.Empty]: '空台',
    [TableStatus.Dining]: '用餐中',
    [TableStatus.Reserved]: '已预订',
    [TableStatus.PendingCheckout]: '待结账',
    [TableStatus.PendingCleanup]: '待清台',
  };
  return statusMap[status];
};

/**
 * 表格卡片组件
 * 显示单个桌台的卡片信息
 */
const TableCard: React.FC<{
  table: TableCardData;
  storeId: string;
}> = ({ table, storeId }) => {
  const { trackFieldClick } = useTableStore();

  // 按优先级排序字段，只显示前4-6个
  const displayFields = useMemo(() => {
    return table.card_fields
      .sort((a, b) => b.priority - a.priority)
      .slice(0, 6);
  }, [table.card_fields]);

  // 确定卡片的主要告警级别（critical > warning > info > normal）
  const cardAlertLevel = useMemo(() => {
    const alerts = displayFields.map((f) => f.alert);
    if (alerts.includes('critical')) return 'critical';
    if (alerts.includes('warning')) return 'warning';
    if (alerts.includes('info')) return 'info';
    return 'normal';
  }, [displayFields]);

  const handleFieldClick = useCallback(
    (field: CardField) => {
      trackFieldClick(storeId, table.table_no, field.key, field.label);
    },
    [storeId, table.table_no, trackFieldClick]
  );

  return (
    <div
      className={`
        ${styles.tableCard}
        ${getStatusClassName(table.status)}
        ${getAlertClassName(cardAlertLevel)}
      `}
    >
      {/* 卡片头部 */}
      <div className={styles.cardHeader}>
        <div className={styles.tableNoAndArea}>
          <div className={styles.tableNo}>{table.table_no}</div>
          <div className={styles.area}>{table.area}</div>
        </div>
        <div className={styles.cardMeta}>
          <span className={`${styles.statusBadge} ${getStatusBadgeClassName(table.status)}`}>
            {getStatusText(table.status)}
          </span>
          <div className={styles.seats}>{table.seats} 座</div>
        </div>
      </div>

      {/* 字段列表 */}
      <div className={styles.fieldsContainer}>
        {displayFields.map((field) => (
          <div
            key={field.key}
            className={`${styles.field} ${getFieldAlertClassName(field.alert)}`}
            onClick={() => handleFieldClick(field)}
            title={`${field.label}: ${field.value}`}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                handleFieldClick(field);
              }
            }}
          >
            <span className={styles.fieldLabel}>{field.label}</span>
            <span className={styles.fieldValue}>{field.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

/**
 * 卡片视图组件
 * 使用CSS Grid网格展示所有桌台卡片
 */
export const TableCardView: React.FC<TableCardViewProps> = ({
  tables,
  storeId,
  loading = false,
}) => {
  if (loading) {
    return (
      <div className={styles.cardViewContainer}>
        <div className={styles.loadingContainer}>
          <div className={styles.spinner} />
          <span>加载中...</span>
        </div>
      </div>
    );
  }

  if (tables.length === 0) {
    return (
      <div className={styles.cardViewContainer}>
        <div className={styles.emptyState}>
          <div className={styles.emptyIcon}>📋</div>
          <div className={styles.emptyText}>暂无桌台数据</div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.cardViewContainer}>
      <div className={styles.cardGrid}>
        {tables.map((table) => (
          <TableCard key={table.table_no} table={table} storeId={storeId} />
        ))}
      </div>
    </div>
  );
};

export default TableCardView;
