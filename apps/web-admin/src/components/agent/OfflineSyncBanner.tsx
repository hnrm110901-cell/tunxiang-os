/**
 * OfflineSyncBanner — 离线/同步状态横幅
 *
 * 门店页面必须显示：本地缓存模式提示、同步中提示、同步失败重试
 */
import { Alert, Button, Space } from 'antd';
import { WifiOutlined, SyncOutlined, DisconnectOutlined } from '@ant-design/icons';

export type SyncStatus = 'online' | 'syncing' | 'offline' | 'error';

interface OfflineSyncBannerProps {
  status: SyncStatus;
  lastSyncTime?: string;
  onRetry?: () => void;
}

const CONFIG: Record<SyncStatus, { type: 'success' | 'info' | 'warning' | 'error'; icon: React.ReactNode; message: string }> = {
  online: { type: 'success', icon: <WifiOutlined />, message: '已连接' },
  syncing: { type: 'info', icon: <SyncOutlined spin />, message: '数据同步中...' },
  offline: { type: 'warning', icon: <DisconnectOutlined />, message: '当前为本地缓存模式，部分数据可能未更新' },
  error: { type: 'error', icon: <DisconnectOutlined />, message: '数据同步失败' },
};

export function OfflineSyncBanner({ status, lastSyncTime, onRetry }: OfflineSyncBannerProps) {
  if (status === 'online') return null;

  const cfg = CONFIG[status];
  return (
    <Alert
      type={cfg.type}
      icon={cfg.icon}
      showIcon
      banner
      message={
        <Space>
          <span>{cfg.message}</span>
          {lastSyncTime && <span style={{ fontSize: 11, color: '#B4B2A9' }}>上次同步: {lastSyncTime}</span>}
          {(status === 'offline' || status === 'error') && onRetry && (
            <Button size="small" type="link" onClick={onRetry}>重试</Button>
          )}
        </Space>
      }
    />
  );
}
