/**
 * 移动端管理直通车布局
 * 底部Tab导航：首页/门店/报表/设置
 * 顶部状态栏：集团名称 + 当前日期
 * 响应式：390px宽度下正常显示，>=768px显示桌面提示
 */
import { ReactNode } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';

interface MobileLayoutProps {
  children: ReactNode;
  title?: string;
}

interface TabItem {
  key: string;
  path: string;
  label: string;
  icon: string;
  activeIcon: string;
}

const TABS: TabItem[] = [
  { key: 'home',     path: '/m/home',     label: '首页', icon: '⊞', activeIcon: '⊞' },
  { key: 'stores',   path: '/m/stores',   label: '门店', icon: '⬡', activeIcon: '⬡' },
  { key: 'reports',  path: '/m/reports',   label: '报表', icon: '⊟', activeIcon: '⊟' },
  { key: 'settings', path: '/m/settings',  label: '设置', icon: '⚙', activeIcon: '⚙' },
];

/** 从 localStorage 读取集团名称 */
function getMerchantName(): string {
  try {
    const raw = localStorage.getItem('tx_user');
    if (raw) {
      const u = JSON.parse(raw);
      return u.merchant || u.merchant_name || '屯象集团';
    }
  } catch {
    // ignore
  }
  return '屯象集团';
}

/** 格式化当前日期 */
function formatToday(): string {
  const d = new Date();
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
  return `${month}月${day}日 周${weekdays[d.getDay()]}`;
}

export function MobileLayout({ children, title }: MobileLayoutProps) {
  const navigate = useNavigate();
  const location = useLocation();

  const activeTab = TABS.find(t => location.pathname.startsWith(t.path))?.key
    // 兼容旧路由
    ?? (location.pathname.startsWith('/m/dashboard') ? 'home' : null)
    ?? (location.pathname.startsWith('/m/anomaly') ? 'home' : null)
    ?? (location.pathname.startsWith('/m/tables') ? 'stores' : null)
    ?? 'home';

  const merchantName = getMerchantName();
  const todayStr = formatToday();

  return (
    <>
      {/* 桌面端隐藏移动布局提示 */}
      <style>{`
        @media (min-width: 768px) {
          .tx-mobile-layout { display: none !important; }
          .tx-mobile-desktop-hint {
            display: flex !important;
            align-items: center;
            justify-content: center;
            height: 100vh;
            flex-direction: column;
            gap: 16px;
            color: #5F5E5A;
            font-size: 16px;
          }
        }
        @media (max-width: 767px) {
          .tx-mobile-desktop-hint { display: none !important; }
        }
      `}</style>

      {/* 桌面端提示 */}
      <div className="tx-mobile-desktop-hint" style={{ display: 'none' }}>
        <div style={{ fontSize: 48 }}>📱</div>
        <div style={{ fontWeight: 600, color: '#2C2C2A' }}>移动端管理直通车</div>
        <div>请在手机上访问以获得最佳体验</div>
        <div>或将浏览器宽度调整至 767px 以下</div>
        <button
          onClick={() => navigate('/dashboard')}
          style={{
            marginTop: 8,
            padding: '10px 24px',
            background: '#FF6B35',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: 'pointer',
            fontSize: 14,
          }}
        >
          返回桌面版
        </button>
      </div>

      {/* 移动端布局 */}
      <div className="tx-mobile-layout" style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100dvh',
        background: '#F8F7F5',
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
        maxWidth: '100vw',
        overflow: 'hidden',
      }}>
        {/* 顶部 Header — 集团名称 + 日期 */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 16px',
          background: '#1E2A3A',
          color: '#fff',
          flexShrink: 0,
          paddingTop: 'calc(12px + env(safe-area-inset-top))',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{
              width: 28,
              height: 28,
              background: '#FF6B35',
              borderRadius: 6,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 14,
              fontWeight: 700,
            }}>屯</div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontWeight: 600, fontSize: 15, lineHeight: 1.2 }}>{merchantName}</span>
              {title && (
                <span style={{ fontSize: 11, color: '#94A3B8', lineHeight: 1.2 }}>{title}</span>
              )}
            </div>
          </div>
          <span style={{ fontSize: 13, color: '#94A3B8', fontWeight: 500 }}>{todayStr}</span>
        </div>

        {/* 内容区域 */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          overflowX: 'hidden',
          WebkitOverflowScrolling: 'touch',
        }}>
          {children}
        </div>

        {/* 底部 Tab 导航 */}
        <div style={{
          display: 'flex',
          background: '#fff',
          borderTop: '1px solid #E8E6E1',
          flexShrink: 0,
          paddingBottom: 'env(safe-area-inset-bottom)',
        }}>
          {TABS.map(tab => {
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                onClick={() => navigate(tab.path)}
                style={{
                  flex: 1,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: '10px 0',
                  border: 'none',
                  background: 'transparent',
                  cursor: 'pointer',
                  minHeight: 56,
                  gap: 4,
                  color: isActive ? '#FF6B35' : '#B4B2A9',
                  transition: 'color 0.15s',
                }}
              >
                <span style={{ fontSize: 20, lineHeight: 1 }}>
                  {isActive ? tab.activeIcon : tab.icon}
                </span>
                <span style={{
                  fontSize: 11,
                  fontWeight: isActive ? 600 : 400,
                  letterSpacing: 0.5,
                }}>
                  {tab.label}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </>
  );
}
