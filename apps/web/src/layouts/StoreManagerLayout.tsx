import React from 'react';
import { Outlet, NavLink, useLocation } from 'react-router-dom';
import styles from './StoreManagerLayout.module.css';

const NAV_ITEMS = [
  { to: '/sm',          label: '首页',   icon: '🏠' },
  { to: '/sm/business', label: '经营',   icon: '📊' },
  { to: '/sm/decisions',label: '决策',   icon: '🎯' },
  { to: '/sm/alerts',   label: '告警',   icon: '🔔' },
];

export default function StoreManagerLayout() {
  return (
    <div className={styles.shell}>
      <main className={styles.main}>
        <Outlet />
      </main>
      <nav className={styles.tabBar}>
        {NAV_ITEMS.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/sm'}
            className={({ isActive }) =>
              `${styles.tabItem} ${isActive ? styles.active : ''}`
            }
          >
            <span className={styles.tabIcon}>{icon}</span>
            <span className={styles.tabLabel}>{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
