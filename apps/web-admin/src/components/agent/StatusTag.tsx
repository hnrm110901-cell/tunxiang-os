/**
 * StatusTag — 统一状态标签
 *
 * 根据状态值自动选择颜色，支持所有 P0 页面的状态枚举。
 */
import { Tag } from 'antd';

const STATUS_COLORS: Record<string, string> = {
  // 通用
  pending: 'orange', processing: 'blue', completed: 'green', returned: 'red',
  // 预警
  new: 'red', closed: 'default', ignored: 'default',
  // 预订
  pending_confirm: 'orange', confirmed: 'green', arrived: 'blue',
  seated: 'cyan', canceled: 'default', no_show: 'red',
  // 等位
  waiting: 'orange', called: 'blue', missed: 'red',
  // 桌台
  idle: 'green', reserved: 'blue', occupied: 'orange', ordering: 'blue',
  dining: 'orange', waiting_payment: 'purple', cleaning: 'default',
  disabled: 'default', overtime: 'red',
  // 日结
  draft: 'default', verifying: 'blue', waiting_signoff: 'orange',
  signed_off: 'green',
  // 任务
  running: 'blue', success: 'green', failed: 'red', skipped: 'default',
  // 严重级
  p1: 'red', p2: 'orange', p3: 'blue',
};

const STATUS_LABELS: Record<string, string> = {
  pending: '待处理', processing: '处理中', completed: '已完成', returned: '已退回',
  new: '新告警', closed: '已闭环', ignored: '已忽略',
  pending_confirm: '待确认', confirmed: '已确认', arrived: '已到店',
  seated: '已入座', canceled: '已取消', no_show: '未到店',
  waiting: '等待中', called: '已叫号', missed: '已过号',
  idle: '空闲', reserved: '已预订', occupied: '占用中', ordering: '点单中',
  dining: '用餐中', waiting_payment: '待结账', cleaning: '清台中',
  disabled: '停用', overtime: '超时',
  draft: '草稿', verifying: '核对中', waiting_signoff: '待签核', signed_off: '已签核',
  running: '执行中', success: '成功', failed: '失败', skipped: '跳过',
  p1: 'P1 严重', p2: 'P2 警告', p3: 'P3 提示',
};

interface StatusTagProps {
  status: string;
  label?: string;
}

export function StatusTag({ status, label }: StatusTagProps) {
  return (
    <Tag color={STATUS_COLORS[status] || 'default'}>
      {label || STATUS_LABELS[status] || status}
    </Tag>
  );
}
