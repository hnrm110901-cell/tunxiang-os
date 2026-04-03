/**
 * 迎宾端 — iPad/平板横屏应用
 * 预订台账 / 到店签到 / 排队叫号 / 桌台分配 / 宴请接待
 */
import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from 'react-router-dom';
import { ReservationBoard } from './pages/ReservationBoard';
import { CheckInPage } from './pages/CheckInPage';
import { QueuePage } from './pages/QueuePage';
import { SeatAssignPage } from './pages/SeatAssignPage';
import { VIPAlertPage } from './pages/VIPAlertPage';

const NAV_ITEMS = [
  { path: '/reservations', label: '预订台账', icon: '📋' },
  { path: '/checkin', label: '到店签到', icon: '✅' },
  { path: '/queue', label: '排队叫号', icon: '📢' },
  { path: '/seats', label: '桌台分配', icon: '🪑' },
  { path: '/vip', label: '宴请接待', icon: '⭐' },
];

/** CSS 变量 — 遵循屯象Design Token */
const CSS_VARS = `
:root {
  --tx-primary: #FF6B35;
  --tx-primary-active: #E55A28;
  --tx-primary-light: #FFF3ED;
  --tx-success: #0F6E56;
  --tx-warning: #BA7517;
  --tx-danger: #A32D2D;
  --tx-info: #185FA5;
  --tx-text-1: #2C2C2A;
  --tx-text-2: #5F5E5A;
  --tx-text-3: #B4B2A9;
  --tx-border: #E8E6E1;
  --tx-bg-1: #FFFFFF;
  --tx-bg-2: #F8F7F5;
  --tx-bg-3: #F0EDE6;
  --tx-radius-sm: 8px;
  --tx-radius-md: 12px;
  --tx-radius-lg: 16px;
  --tx-shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
  --tx-shadow-md: 0 4px 12px rgba(0,0,0,0.08);
  --tx-tap-min: 48px;
  --tx-tap-rec: 56px;
  --tx-tap-lg: 72px;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #root { height: 100%; overflow: hidden; }
button { font-family: inherit; }
`;

function SideNav() {
  const loc = useLocation();

  return (
    <nav style={{
      width: 100,
      minHeight: '100vh',
      background: '#1E2A3A',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      paddingTop: 20,
      gap: 8,
      flexShrink: 0,
    }}>
      {/* 品牌标识 */}
      <div style={{
        color: 'var(--tx-primary)',
        fontSize: 20,
        fontWeight: 800,
        marginBottom: 16,
        letterSpacing: 2,
      }}>
        迎宾
      </div>

      {NAV_ITEMS.map(item => {
        const isActive = loc.pathname === item.path;
        return (
          <Link
            key={item.path}
            to={item.path}
            style={{
              width: 80,
              minHeight: 72,
              borderRadius: 'var(--tx-radius-md)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 4,
              textDecoration: 'none',
              color: isActive ? '#fff' : '#8899AA',
              background: isActive ? 'rgba(255,107,53,0.18)' : 'transparent',
              borderLeft: isActive ? '3px solid var(--tx-primary)' : '3px solid transparent',
              transition: 'all 200ms ease',
              fontSize: 18,
            }}
          >
            <span style={{ fontSize: 24 }}>{item.icon}</span>
            <span style={{ fontSize: 16, fontWeight: isActive ? 700 : 400 }}>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export default function App() {
  return (
    <>
      <style>{CSS_VARS}</style>
      <BrowserRouter>
        <div style={{
          display: 'flex',
          height: '100vh',
          width: '100vw',
          background: 'var(--tx-bg-2)',
          color: 'var(--tx-text-1)',
        }}>
          <SideNav />
          <main style={{
            flex: 1,
            overflow: 'auto',
            WebkitOverflowScrolling: 'touch',
          }}>
            <Routes>
              <Route path="/" element={<Navigate to="/reservations" replace />} />
              <Route path="/reservations" element={<ReservationBoard />} />
              <Route path="/checkin" element={<CheckInPage />} />
              <Route path="/queue" element={<QueuePage />} />
              <Route path="/seats" element={<SeatAssignPage />} />
              <Route path="/vip" element={<VIPAlertPage />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </>
  );
}
