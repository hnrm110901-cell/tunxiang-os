import React from 'react';
import { Outlet, NavLink } from 'react-router-dom';
import styles from './FloorLayout.module.css';

const NAV_ITEMS = [
  { to: '/floor',              label: '看板',   icon: '🏪' },
  { to: '/floor/tables',       label: '桌台',   icon: '🪑' },
  { to: '/floor/queue',        label: '排队',   icon: '🔢' },
  { to: '/floor/reservations', label: '预订',   icon: '📅' },
  { to: '/floor/checkout',     label: '收银',   icon: '💳' },
  { to: '/floor/kitchen',      label: '出品',   icon: '🍽️' },
];

export default function FloorLayout() {
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>楼面</div>
        {NAV_ITEMS.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/floor'}
            className={({ isActive }) =>
              `${styles.navItem} ${isActive ? styles.active : ''}`
            }
          >
            <span className={styles.navIcon}>{icon}</span>
            <span className={styles.navLabel}>{label}</span>
          </NavLink>
        ))}
      </aside>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
