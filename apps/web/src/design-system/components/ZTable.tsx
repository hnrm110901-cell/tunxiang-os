import React from 'react';
import styles from './ZTable.module.css';

export interface ZTableColumn<T = any> {
  key?:      string;
  dataIndex?: keyof T | string;
  title:     string;
  align?:    'left' | 'right' | 'center';
  render?:   (value: any, row: T, index: number) => React.ReactNode;
  width?:    number | string;
}

export interface ZTableProps<T = any> {
  columns:    ZTableColumn<T>[];
  data?:      T[];
  dataSource?: T[];
  rowKey?:    keyof T | ((row: T, i: number) => string);
  emptyText?: string;
  style?:     React.CSSProperties;
  size?: 'small' | 'middle' | 'large' | 'sm' | 'md' | 'lg';
  pagination?: any;
}

export default function ZTable<T = any>({
  columns,
  data,
  dataSource,
  rowKey,
  emptyText = '暂无数据',
  style,
}: ZTableProps<T>) {
  const rows = dataSource ?? data ?? [];
  const getKey = (row: T, i: number): string => {
    if (!rowKey) return String(i);
    if (typeof rowKey === 'function') return rowKey(row, i);
    return String(row[rowKey]);
  };

  return (
    <div className={styles.wrap} style={style}>
      <table>
        <thead>
          <tr className={styles.thead}>
            {columns.map(col => (
              <th
                key={col.key}
                className={col.align === 'right' ? styles.right : col.align === 'center' ? styles.center : ''}
                style={col.width ? { width: col.width } : undefined}
              >
                {col.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className={styles.empty}>{emptyText}</td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr key={getKey(row, i)} className={styles.row}>
                {columns.map((col, colIdx) => {
                  const lookupKey = (col.dataIndex ?? col.key) as string | undefined;
                  const value = lookupKey ? (row as any)[lookupKey] : undefined;
                  const cellKey = col.key ?? lookupKey ?? String(colIdx);
                  return (
                    <td
                      key={cellKey}
                      className={col.align === 'right' ? styles.right : col.align === 'center' ? styles.center : ''}
                    >
                      {col.render ? col.render(value, row, i) : value ?? '—'}
                    </td>
                  );
                })}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
