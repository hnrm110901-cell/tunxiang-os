/**
 * TableCard — 桌台状态卡片
 *
 * 跨端共享组件，用于：
 *   - web-pos TableMapPage 桌台网格
 *   - web-reception 前台桌台概览
 *   - web-crew 服务员巡台视图
 *
 * 展示：桌号、状态、座位数/客人数、用餐时长、订单金额
 */
import styles from './TableCard.module.css';
import { cn } from '../../utils/cn';

export type TableCardStatus = 'free' | 'occupied' | 'overtime' | 'reserved' | 'vip' | 'cleaning';

export interface TableCardData {
  tableNo: string;
  area?: string;
  seats: number;
  status: TableCardStatus;
  guestCount?: number;
  /** 用餐分钟数 */
  diningMinutes?: number;
  /** 订单金额（分） */
  orderAmountFen?: number;
  /** 服务员 */
  waiterName?: string;
  /** 预订人 */
  reservedName?: string;
  /** 预订时间 */
  reservedTime?: string;
}

export interface TableCardProps {
  table: TableCardData;
  selected?: boolean;
  onClick?: (table: TableCardData) => void;
}

const STATUS_META: Record<TableCardStatus, { label: string; className: string }> = {
  free:     { label: '空闲',   className: 'statusFree' },
  occupied: { label: '就餐中', className: 'statusOccupied' },
  overtime: { label: '超时',   className: 'statusOvertime' },
  reserved: { label: '预订',   className: 'statusReserved' },
  vip:      { label: 'VIP',    className: 'statusVip' },
  cleaning: { label: '清台中', className: 'statusCleaning' },
};

function formatMinutes(min: number): string {
  if (min < 60) return `${min}分钟`;
  return `${Math.floor(min / 60)}时${min % 60}分`;
}

function shortPrice(fen: number): string {
  return `¥${Math.round(fen / 100)}`;
}

export default function TableCard({ table, selected, onClick }: TableCardProps) {
  const meta = STATUS_META[table.status] ?? STATUS_META.free;
  const isActive = table.status === 'occupied' || table.status === 'overtime' || table.status === 'vip';

  return (
    <button
      type="button"
      className={cn(
        styles.card,
        styles[meta.className],
        selected && styles.selected,
        table.status === 'overtime' && styles.overtime,
      )}
      onClick={() => onClick?.(table)}
    >
      {/* 桌号 */}
      <div className={styles.tableNo}>{table.tableNo}</div>

      {/* 状态标签 */}
      <div className={cn(styles.statusBadge, styles[meta.className])}>
        {meta.label}
      </div>

      {/* 详情 */}
      <div className={styles.details}>
        {table.status === 'free' ? (
          <span className={styles.seats}>{table.seats}座</span>
        ) : table.status === 'reserved' ? (
          <span className={styles.seats}>
            {table.seats}座
            {table.reservedName && <span className={styles.name}> · {table.reservedName}</span>}
          </span>
        ) : isActive ? (
          <>
            <span className={styles.guests}>
              {table.guestCount ?? 0}人 · {table.seats}座
            </span>
            {table.diningMinutes != null && (
              <span className={cn(styles.time, table.status === 'overtime' && styles.timeOvertime)}>
                {formatMinutes(table.diningMinutes)}
              </span>
            )}
            {table.orderAmountFen != null && (
              <span className={styles.amount}>
                {shortPrice(table.orderAmountFen)}
              </span>
            )}
          </>
        ) : (
          <span className={styles.seats}>{table.seats}座</span>
        )}
      </div>
    </button>
  );
}
