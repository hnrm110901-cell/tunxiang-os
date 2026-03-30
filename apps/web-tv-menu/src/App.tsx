import { Routes, Route, Navigate } from 'react-router-dom';
import MenuWall from './pages/MenuWall';
import SeafoodPriceBoard from './pages/SeafoodPriceBoard';
import RankingBoard from './pages/RankingBoard';
import ComboShowcase from './pages/ComboShowcase';
import WelcomeScreen from './pages/WelcomeScreen';
import AdminConfig from './pages/AdminConfig';

/** 全局CSS变量 — 大屏深色主题 */
const globalStyles = `
  :root {
    --tx-primary: #FF6B2C;
    --tx-primary-hover: #FF8555;
    --tx-primary-active: #E55A28;
    --tx-primary-light: rgba(255, 107, 44, 0.15);
    --tx-bg-dark: #0A0A0A;
    --tx-bg-card: #1A1A1A;
    --tx-bg-card-hover: #222222;
    --tx-border: #2A2A2A;
    --tx-text-primary: #FFFFFF;
    --tx-text-secondary: #B0B0B0;
    --tx-text-tertiary: #666666;
    --tx-success: #0F6E56;
    --tx-warning: #BA7517;
    --tx-danger: #A32D2D;
    --tx-info: #185FA5;
    --tx-gold: #FFD700;
    --tx-silver: #C0C0C0;
    --tx-bronze: #CD7F32;
    --tx-seafood-up: #FF4444;
    --tx-seafood-down: #00CC66;
    --tx-seafood-flat: #FFFFFF;
    --tx-font: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif;
    --tx-radius-sm: 8px;
    --tx-radius-md: 12px;
    --tx-radius-lg: 16px;
  }

  @keyframes tx-fade-in {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes tx-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }
  @keyframes tx-slide-up {
    from { opacity: 0; transform: translateY(20px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes tx-blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  @keyframes tx-scroll-left {
    from { transform: translateX(0); }
    to   { transform: translateX(-50%); }
  }

  .tx-fade-in {
    animation: tx-fade-in 0.4s ease-out both;
  }
  .tx-pulse {
    animation: tx-pulse 1.5s infinite;
  }

  /* 触控模式: 显示鼠标 */
  body.touch-mode { cursor: default !important; }
  body.touch-mode * { cursor: default !important; }
`;

export default function App() {
  return (
    <>
      <style>{globalStyles}</style>
      <Routes>
        <Route path="/" element={<Navigate to="/menu" replace />} />
        <Route path="/menu" element={<MenuWall />} />
        <Route path="/seafood" element={<SeafoodPriceBoard />} />
        <Route path="/ranking" element={<RankingBoard />} />
        <Route path="/combo" element={<ComboShowcase />} />
        <Route path="/welcome" element={<WelcomeScreen />} />
        <Route path="/admin" element={<AdminConfig />} />
      </Routes>
    </>
  );
}
