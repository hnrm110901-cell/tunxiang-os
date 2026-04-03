/**
 * æºè½æ¡å°åè¡¨è§å¾
 * ä½¿ç¨Ant Design Tableç»ä»¶å±ç¤ºè¯¦ç»ä¿¡æ¯
 * @module pages/TableManagement/TableListView
 */

import React, { useMemo, useCallback } from 'react';
import { Table, Tag, Collapse, Row, Col, Spin } from 'antd';
import type { ColumnsType, TableProps } from 'antd/es/table';
import {
  CardField,
  TableCardData,
  TableStatus,
} from '../../types/table-card';
import { useTableStore } from '../../stores/tableStore';
import styles from './TableManagement.module.css';

/**
 * åè¡¨è§å¾Props
 */
export interface TableListViewProps {
  /** æ¡å°åè¡¨ */
  tables: TableCardData[];
  /** é¨åºID */
  storeId: string;
  /** å è½½ä¸­ç¶æ */
  loading?: boolean;
}

/**
 * è·åç¶æå¯¹åºçTagé¢è²
 */
const getStatusTagColor = (status: TableStatus): string => {
  const colorMap: Record<TableStatus, string> = {
    [TableStatus.Empty]: '#52c41a',
    [TableStatus.Dining]: '#1890ff',
    [TableStatus.Reserved]: '#faad14',
    [TableStatus.PendingCheckout]: '#ff4d4f',
    [TableStatus.PendingCleanup]: '#d9d9d9',
  };
  return colorMap[status];
};

/**
 * è·åç¶ææ¾ç¤ºææ¬
 */
const getStatusText = (status: TableStatus): string => {
  const statusMap: Record<TableStatus, string> = {
    [TableStatus.Empty]: 'ç©ºå°',
    [TableStatus.Dining]: 'ç¨é¤ä¸­',
    [TableStatus.Reserved]: 'å·²é¢è®¢',
    [TableStatus.PendingCheckout]: 'å¾ç»è´¦',
    [TableStatus.PendingCleanup]: 'å¾æ¸å°',
  };
  return statusMap[status];
};

/**
 * è·ååè­¦çº§å«å¯¹åºçèæ¯è²
 */
const getAlertColor = (alert: string): string => {
  switch (alert) {
    case 'critical':
      return '#fff2f0';
    case 'warning':
      return '#fffbe6';
    case 'info':
      return '#e6f7ff';
    default:
      return 'transparent';
  }
};

/**
 * ç¡®å®è¡çåè­¦çº§å«ï¼critical > warning > info > normalï¼
 */
const getRowAlertLevel = (fields: CardField[]): string => {
  const alerts = fields.map((f) => f.alert);
  if (alerts.includes('critical')) return 'critical';
  if (alerts.includes('warning')) return 'warning';
  if (alerts.includes('info')) return 'info';
  return 'normal';
};

/**
 * å­æ®µå±ç¤ºå¡çç»ä»¶
 */
const FieldCard: React.FC<{
  field: CardField;
  onFieldClick: (field: CardField) => void;
}> = ({ field, onFieldClick }) => (
  <div
    style={{
      padding: '12px',
      borderRadius: '4px',
      background: getAlertColor(field.alert),
      border: '1px solid #d9d9d9',
      cursor: 'pointer',
      transition: 'all 0.2s ease',
    }}
    onClick={() => onFieldClick(field)}
    role="button"
    tabIndex={0}
    onKeyDown={(e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        onFieldClick(field);
      }
    }}
    onMouseEnter={(e) => {
      e.currentTarget.style.boxShadow = '0 3px 6px rgba(0, 0, 0, 0.1)';
    }}
    onMouseLeave={(e) => {
      e.currentTarget.style.boxShadow = 'none';
    }}
  >
    <div style={{ fontSize: '12px', color: '#595959', marginBottom: '4px' }}>
      {field.label}
    </div>
    <div style={{ fontSize: '16px', fontWeight: '600', color: '#262626' }}>
      {field.value}
    </div>
  </div>
);

/**
 * åè¡¨è§å¾ç»ä»¶
 * ä½¿ç¨Ant Design Tableå±ç¤ºæ¡å°åè¡¨ï¼æ¯æå±å¼æ¥çè¯¦æ
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

  // æåºååç»
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

  // å®ä¹è¡¨æ ¼å
  const columns: ColumnsType<TableCardData> = useMemo(
    () => [
      {
        title: 'æ¡å·',
        dataIndex: 'table_no',
        key: 'table_no',
        width: 80,
        render: (text) => <span style={{ fontWeight: '600', fontSize: '16px' }}>{text}</span>,
      },
      {
        title: 'åºå',
        dataIndex: 'area',
        key: 'area',
        width: 100,
      },
      {
        title: 'åº§ä½',
        dataIndex: 'seats',
        key: 'seats',
        width: 60,
        render: (seats) => `${seats} åº§`,
      },
      {
        title: 'ç¶æ',
        dataIndex: 'status',
        key: 'status',
        width: 100,
        render: (status: TableStatus) => (
          <Tag
            color={getStatusTagColor(status)}
            style={{ margin: 0, borderRadius: '4px', padding: '4px 8px' }}
          >
            {getStatusText(status)}
          </Tag>
        ),
      },
      {
        title: 'å³é®å­æ®µ',
        dataIndex: 'card_fields',
        key: 'card_fields',
        render: (fields: CardField[]) => {
          // æ¾ç¤ºå3ä¸ªä¼åçº§æé«çå­æ®µ
          const topFields = fields
            .sort((a, b) => b.priority - a.priority)
            .slice(0, 3);
          return (
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {topFields.map((field) => (
                <Tag
                  key={field.key}
                  style={{
                    background: getAlertColor(field.alert),
                    border: `1px solid #d9d9d9`,
                    cursor: 'pointer',
                    borderRadius: '4px',
                    padding: '4px 8px',
                    margin: 0,
                  }}
                  onClick={() => handleFieldClick(fields[0].key, field)}
                >
                  <span style={{ fontSize: '12px', color: '#262626' }}>
                    {field.label}: {field.value}
                  </span>
                </Tag>
              ))}
            </div>
          );
        },
      },
    ],
    [handleFieldClick]
  );

  // è¡å±å¼åå®¹
  const expandedRowRender = (record: TableCardData) => {
    const sortedFields = record.card_fields.sort((a, b) => b.priority - a.priority);
    return (
      <div className={styles.expandedRow}>
        {sortedFields.map((field) => (
          <FieldCard
            key={field.key}
            field={field}
            onFieldClick={() => handleFieldClick(record.table_no, field)}
          />
        ))}
      </div>
    );
  };

  // è¡classNameå¤ç
  const rowClassName = (record: TableCardData) => {
    const alertLevel = getRowAlertLevel(record.card_fields);
    const alertClassName = {
      critical: styles.criticalAlert,
      warning: styles.warningAlert,
      info: styles.infoAlert,
      normal: styles.normalAlert,
    };
    return `${styles.tableRow} ${alertClassName[alertLevel as keyof typeof alertClassName]}`;
  };

  if (loading) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100%',
          gap: '16px',
        }}
      >
        <Spin />
        <span>å è½½ä¸­...</span>
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
          color: '#595959',
        }}
      >
        <div style={{ fontSize: '48px', opacity: 0.4 }}>ð</div>
        <div>ææ æ¡å°æ°æ®</div>
      </div>
    );
  }

  return (
    <div className={styles.listViewContainer}>
      {groupedTables.size > 0 ? (
        <Collapse
          items={Array.from(groupedTables.entries()).map(([area, areaTables]) => ({
            key: area,
            label: (
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <span style={{ fontWeight: '600', fontSize: '14px' }}>{area}</span>
                <Tag>{areaTables.length} å¼ </Tag>
              </div>
            ),
            children: (
              <Table
                columns={columns}
                dataSource={areaTables}
                rowKey="table_no"
                pagination={false}
                expandable={{
                  expandedRowRender,
                  defaultExpandedRowKeys: [],
                }}
                rowClassName={rowClassName}
                style={{ marginBottom: 0 }}
                size="small"
              />
            ),
          }))}
          accordion
        />
      ) : null}
    </div>
  );
};

export default TableListView;
