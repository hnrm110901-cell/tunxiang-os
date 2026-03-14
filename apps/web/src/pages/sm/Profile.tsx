/**
 * 个人中心 — 店长移动端
 * 个人信息、设置、退出登录
 */
import React from 'react';
import { Card, Button, List } from 'antd';
import { useAuth } from '../../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import styles from './Profile.module.css';

const MENU_ITEMS = [
  { label: '门店切换',    icon: '🏪', action: 'switch-store' },
  { label: '通知设置',    icon: '🔔', action: 'notification-settings' },
  { label: '操作日志',    icon: '📝', action: 'activity-log' },
  { label: '帮助与反馈',  icon: '💬', action: 'help' },
  { label: '关于屯象OS', icon: 'ℹ️', action: 'about' },
];

export default function Profile() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className={styles.container}>
      <Card className={styles.userCard} size="small">
        <div className={styles.userRow}>
          <div className={styles.avatar}>
            {user?.full_name?.[0] || user?.username?.[0] || 'U'}
          </div>
          <div className={styles.userInfo}>
            <div className={styles.userName}>{user?.full_name || user?.username || '店长'}</div>
            <div className={styles.userRole}>门店管理员</div>
          </div>
        </div>
      </Card>

      <Card className={styles.menuCard} size="small">
        <List
          dataSource={MENU_ITEMS}
          split
          renderItem={(item) => (
            <List.Item className={styles.menuItem}>
              <span>{item.icon} {item.label}</span>
              <span className={styles.arrow}>›</span>
            </List.Item>
          )}
        />
      </Card>

      <Button
        block
        danger
        className={styles.logoutBtn}
        onClick={handleLogout}
      >
        退出登录
      </Button>
    </div>
  );
}
