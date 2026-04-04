/**
 * OfflineBanner — 离线状态提示横条
 *
 * - 离线时：顶部固定红色横条 "离线模式 -- 数据将在恢复连接后同步"
 * - 在线时：绿色 "已连接" 3秒后自动隐藏
 * - 队列中有待同步操作时显示数量
 *
 * 编码规范：TypeScript strict，纯 inline style，禁止 any
 */
import { useState, useEffect, useRef } from 'react';

interface OfflineBannerProps {
  isOnline: boolean;
  queueLength: number;
  syncing: boolean;
}

export function OfflineBanner({ isOnline, queueLength, syncing }: OfflineBannerProps) {
  const [visible, setVisible] = useState(!isOnline);
  const [showConnected, setShowConnected] = useState(false);
  const prevOnlineRef = useRef(isOnline);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isOnline && !prevOnlineRef.current) {
      // 刚恢复连接：显示绿色横条 3 秒
      setShowConnected(true);
      setVisible(true);
      timerRef.current = setTimeout(() => {
        if (queueLength === 0) {
          setVisible(false);
        }
        setShowConnected(false);
      }, 3000);
    } else if (!isOnline) {
      // 断网：立即显示红色横条
      setVisible(true);
      setShowConnected(false);
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    } else if (isOnline && queueLength === 0 && !showConnected) {
      // 在线且无队列：隐藏
      setVisible(false);
    }

    prevOnlineRef.current = isOnline;
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [isOnline, queueLength, showConnected]);

  // 同步中 / 有队列时保持可见
  useEffect(() => {
    if (syncing || queueLength > 0) {
      setVisible(true);
    }
  }, [syncing, queueLength]);

  if (!visible) return null;

  const isOffline = !isOnline;
  const bgColor = isOffline ? '#DC2626' : showConnected ? '#16A34A' : '#D97706';

  const containerStyle: React.CSSProperties = {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 9999,
    backgroundColor: bgColor,
    color: '#FFFFFF',
    padding: '8px 16px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '12px',
    fontSize: '14px',
    fontWeight: 600,
    transition: 'background-color 0.3s ease',
    boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
  };

  const dotStyle: React.CSSProperties = {
    width: 8,
    height: 8,
    borderRadius: '50%',
    backgroundColor: '#FFFFFF',
    flexShrink: 0,
    animation: isOffline ? undefined : 'none',
  };

  const badgeStyle: React.CSSProperties = {
    backgroundColor: 'rgba(255,255,255,0.25)',
    borderRadius: '12px',
    padding: '2px 10px',
    fontSize: '12px',
    fontWeight: 700,
  };

  let text: string;
  if (isOffline) {
    text = '离线模式 -- 数据将在恢复连接后同步';
  } else if (showConnected) {
    text = '已连接';
  } else if (syncing) {
    text = '正在同步离线数据...';
  } else {
    text = '待同步';
  }

  return (
    <div style={containerStyle}>
      <span style={dotStyle} />
      <span>{text}</span>
      {queueLength > 0 && (
        <span style={badgeStyle}>{queueLength} 条待同步</span>
      )}
    </div>
  );
}
