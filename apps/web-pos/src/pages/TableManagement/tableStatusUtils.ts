import { TableStatus } from '../../types/table-card';

/** 桌台状态 → 显示文字 */
export const getStatusText = (status: TableStatus): string => {
  const map: Record<TableStatus, string> = {
    [TableStatus.Empty]: '空台',
    [TableStatus.Dining]: '用餐中',
    [TableStatus.Reserved]: '已预订',
    [TableStatus.PendingCheckout]: '待结账',
    [TableStatus.PendingCleanup]: '待清台',
  };
  return map[status];
};

/** 桌台状态 → 主题色（CSS 色值） */
export const getStatusColor = (status: TableStatus): string => {
  const map: Record<TableStatus, string> = {
    [TableStatus.Empty]: '#0F6E56',
    [TableStatus.Dining]: '#185FA5',
    [TableStatus.Reserved]: '#BA7517',
    [TableStatus.PendingCheckout]: '#A32D2D',
    [TableStatus.PendingCleanup]: '#555',
  };
  return map[status];
};

/** Agent 预警级别 → 背景色（带透明度） */
export const getAlertBgColor = (alert: string): string => {
  switch (alert) {
    case 'critical': return 'rgba(163,45,45,0.20)';
    case 'warning':  return 'rgba(186,117,23,0.20)';
    case 'info':     return 'rgba(24,95,165,0.20)';
    default:         return 'rgba(255,255,255,0.06)';
  }
};
