/**
 * 桌台列表视图
 * 使用 TXScrollList + TXCard 替代 antd Table/Tag/Collapse/Spin
 * @module pages/TableManagement/TableListView
 */

import React, { useMemo, useCallback, useState } from 'react';
import { TXCard, TXScrollList } from '@tx/touch';
import {
  CardField,
  TableCardData,
  TableStatus,
} from '../../types/table-card';
import { useTableStore } from '../../stores/tableStore';
import styles from './TableManagement.module.css';

/**
 * 列表视图Props
 */
export interface TableListViewProps {
  /** 桌台列表 */
  tables: TableCardData[];
  /** 门店ID */
  storeId: string;
  /** 加载中状态 */
  loading?: boolean;
}

/**
 * 获取状态对应的Tag颜色
 */
const getStatusTagColor = (status: TableStatus): string => {
  const colorMap: Record<TableStatus, string> = {
    [TableStatus.Empty]: '#0F6E56',
    [TableStatus.Dining]: '#185FA5',
    [TableStatus.Reserved]: '#BA7517',
    [TableStatus.PendingCheckout]: '#A32D2D',
    [TableStatus.PendingCleanup]: '#555',
  };
  return colorMap[status];
};

/**
 * 获取状态显示文本
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
 * 获取预警级别对应的背景色
 */
const getAlertColor = (alert: string): string => {
  switch (alert) {
    case 'critical':
      return 'rgba(163,45,45,0.20)';
    case 'warning':
      return 'rgba(186,117,23,0.20)';
    case 'info':
      return 'rgba(24,95,165,0.20)';
    default:
      return 'rgba(255,255,255,0.06)';
  }
};

/**
 * 确定行的预警级别（critical > warning > info > normal）
 */
const getRowAlertLevel = (fields: CardField[]): string => {
  const alerts = fields.map((f) => f.alert);
  if (alerts.includes('critical')) return 'critical';
  if (alerts.includes('warning')) return 'warning';
  if (alerts.includes('info')) return 'info';
  return 'normal';
};

/**
 * 区域折叠面板（替代 antd Collapse）
 */
const AreaPanel: React.FC<{
  area: string;
  tables: TableCardData[];
  onFieldClick: (tableNo: string, field: CardField) => void;
}> = ({ area, tables, onFieldClick }) => {
  const [expanded, setExpanded] = useState(true);

  return (
    <div style={{ marginBottom: 12, borderRadius: 8, overflow: 'hidden', border: '1px solid rgba(255,255,255,0.10)' }}>
      {/* 折叠标题 */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '12px 16px',
          background: 'rgba(255,255,255,0.04)',
          border: 'none',
          cursor: 'pointer',
          textAlign: 'left',
          minHeight: 56,
          fontFamily: 'inherit',
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 16, color: '#fff' }}>{area}</span>
        <span style={{
          padding: '2px 10px',
          borderRadius: 12,
          background: 'rgba(255,107,53,0.18)',
          color: '#FF6B35',
          fontSize: 14,
          fontWeight: 600,
        }}>
          {tables.length} 桌
        </span>
        <span style={{ marginLeft: 'auto', color: 'rgba(255,255,255,0.45)', fontSize: 18 }}>
          {expanded ? '▲' : '▼'}
        </span>
      </button>

      {/* 展开内容 — 桌台行列表 */}
      {expanded && (
        <div>
          {/* 表头 */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '80px 100px 60px 120px 1fr',
            gap: 8,
            padding: '8px 16px',
            background: 'rgba(255,255,255,0.02)',
            borderBottom: '1px solid rgba(255,255,255,0.06)',
            fontSize: 14,
            color: 'rgba(255,255,255,0.45)',
            fontWeight: 600,
          }}>
            <span>桌号</span>
            <span>区域</span>
            <span>座位</span>
            <span>状态</span>
            <span>关键字段</span>
          </div>
          <TXScrollList
            data={tables}
            keyExtractor={(t) => t.table_no}
            renderItem={(table) => {
              const alertLevel = getRowAlertLevel(table.card_fields);
              const rowBg = alertLevel === 'critical'
                ? 'rgba(163,45,45,0.10)'
                : alertLevel === 'warning'
                  ? 'rgba(186,117,23,0.10)'
                  : alertLevel === 'info'
                    ? 'rgba(24,95,165,0.10)'
                    : 'transparent';

              const topFields = [...table.card_fields]
                .sort((a, b) => b.priority - a.priority)
                .slice(0, 3);

              return (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: '80px 100px 60px 120px 1fr',
                  gap: 8,
                  padding: '12px 16px',
                  borderBottom: '1px solid rgba(255,255,255,0.05)',
                  background: rowBg,
                  alignItems: 'center',
                  minHeight: 56,
                }}>
                  <span style={{ fontWeight: 600, fontSize: 16, color: '#fff' }}>
                    {table.table_no}
                  </span>
                  <span style={{ fontSize: 16, color: 'rgba(255,255,255,0.65)' }}>
                    {table.area}
                  </span>
                  <span style={{ fontSize: 16, color: 'rgba(255,255,255,0.65)' }}>
                    {table.seats} 座
                  </span>
                  {/* 状态标签（替代 antd Tag） */}
                  <span style={{
                    display: 'inline-block',
                    padding: '4px 10px',
                    borderRadius: 6,
                    background: getStatusTagColor(table.status),
                    color: '#fff',
                    fontSize: 14,
                    fontWeight: 600,
                    textAlign: 'center',
                  }}>
                    {getStatusText(table.status)}
                  </span>
                  {/* 关键字段标签组（替代 antd Tag） */}
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {topFields.map((field) => (
                      <button
                        key={field.key}
                        type="button"
                        onClick={() => onFieldClick(table.table_no, field)}
                        style={{
                          padding: '4px 10px',
                          borderRadius: 6,
                          background: getAlertColor(field.alert),
                          border: '1px solid rgba(255,255,255,0.12)',
                          cursor: 'pointer',
                          fontSize: 13,
                          color: '#fff',
                          fontFamily: 'inherit',
                          minHeight: 32,
                        }}
                      >
                        {field.label}: {field.value}
                      </button>
                    ))}
                  </div>
                </div>
              );
            }}
          />
        </div>
      )}
    </div>
  );
};

/**
 * 列表视图组件
 * 使用 TXScrollList + 原生折叠面板替代 antd Table/Collapse
 */
export const TableListView: React.FC<TableListViewProps> = ({
  tables,
  storeId,
  loading = false,
}) => {
  const { trackFieldClick } = useTableStore();

  const handleFieldClick = useCallback(
    (tableNo: string, field: CardField) => {
      trackFieldClick(storeId, tableNo, field.key, field.label);
    },
    [storeId, trackFieldClick]
  );

  // 按区域分组
  const groupedTables = useMemo(() => {
    const groups = new Map<string, TableCardData[]>();
    tables.forEach((table) => {
      if (!groups.has(table.area)) {
        groups.set(table.area, []);
      }
      groups.get(table.area)!.push(table);
    });
    return groups;
  }, [tables]);

  if (loading) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100%',
          gap: '16px',
          color: 'rgba(255,255,255,0.65)',
          fontSize: 16,
        }}
      >
        <span style={{ fontSize: 24 }}>⟳</span>
        <span>加载中...</span>
      </div>
    );
  }

  if (tables.length === 0) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          gap: '16px',
          color: 'rgba(255,255,255,0.45)',
          fontSize: 16,
        }}
      >
        <div style={{ fontSize: '48px', opacity: 0.4 }}>🪑</div>
        <div>暂无桌台数据</div>
      </div>
    );
  }

  return (
    <div className={styles.listViewContainer}>
      {groupedTables.size > 0
        ? Array.from(groupedTables.entries()).map(([area, areaTables]) => (
            <AreaPanel
              key={area}
              area={area}
              tables={areaTables}
              onFieldClick={handleFieldClick}
            />
          ))
        : null}
    </div>
  );
};

export default TableListView;
