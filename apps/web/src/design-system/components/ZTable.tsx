import React from 'react';
import styles from './ZTable.module.css';

export interface ZTableColumn<T = any> {
  key:       string;
  title:     string;
  align?:    'left' | 'right' | 'center';
  render?:   (value: any, row: T, index: number) => React.ReactNode;
  width?:    number | string;
}

interface ZTableProps<T = any> {
  columns:    ZTableColumn<T>[];
  data:       T[];
  rowKey?:    keyof T | ((row: T, i: number) => string);
  emptyText?: string;
  style?:     React.CSSProperties;
}

export default function ZTable<T = any>({
  columns,
  data,
  rowKey,
  emptyText = '暂无数据',
  style,
}: ZTableProps<T>) {
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
          {data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className={styles.empty}>{emptyText}</td>
            </tr>
          ) : (
            data.map((row, i) => (
              <tr key={getKey(row, i)} className={styles.row}>
                {columns.map(col => {
                  const value = (row as any)[col.key];
                  return (
                    <td
                      key={col.key}
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
