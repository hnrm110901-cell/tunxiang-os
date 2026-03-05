import React from 'react';
import { Outlet, NavLink } from 'react-router-dom';
import styles from './ChefLayout.module.css';

const NAV_ITEMS = [
  { to: '/chef',         label: '首页',   icon: '🍳' },
  { to: '/chef/waste',   label: '损耗',   icon: '📉' },
  { to: '/chef/inventory', label: '库存', icon: '📦' },
];

export default function ChefLayout() {
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
            end={to === '/chef'}
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
