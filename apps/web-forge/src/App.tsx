import React, { useState } from 'react';
import HomePage from './pages/HomePage';
import DocsPage from './pages/DocsPage';
import SDKPage from './pages/SDKPage';
import WebhooksPage from './pages/WebhooksPage';
import MarketplacePage from './pages/MarketplacePage';
import ConsolePage from './pages/ConsolePage';
import SandboxPage from './pages/SandboxPage';

type Page = 'home' | 'docs' | 'sdk' | 'webhooks' | 'marketplace' | 'console' | 'sandbox';

const NAV_ITEMS: { key: Page; label: string }[] = [
  { key: 'home', label: '首页' },
  { key: 'docs', label: '文档' },
  { key: 'sdk', label: 'SDK' },
  { key: 'webhooks', label: 'Webhook' },
  { key: 'marketplace', label: '市场' },
  { key: 'console', label: '控制台' },
  { key: 'sandbox', label: '沙箱' },
];

const BRAND = '#FF6B2C';

const styles: Record<string, React.CSSProperties> = {
  nav: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    height: 56,
    padding: '0 32px',
    background: '#fff',
    borderBottom: '1px solid #e5e7eb',
    position: 'sticky' as const,
    top: 0,
    zIndex: 100,
  },
  logoArea: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    fontWeight: 700,
    fontSize: 18,
    color: '#1a1a1a',
    cursor: 'pointer',
  },
  logoIcon: {
    width: 32,
    height: 32,
    borderRadius: 8,
    background: BRAND,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: '#fff',
    fontWeight: 800,
    fontSize: 16,
  },
  navLinks: {
    display: 'flex',
    gap: 4,
  },
  navLink: {
    padding: '6px 14px',
    borderRadius: 6,
    fontSize: 14,
    cursor: 'pointer',
    color: '#4b5563',
    background: 'transparent',
    border: 'none',
    fontWeight: 500,
    transition: 'all .15s',
  },
  navLinkActive: {
    color: BRAND,
    background: '#FFF5F0',
    fontWeight: 600,
  },
  content: {
    minHeight: 'calc(100vh - 56px)',
    background: '#f9fafb',
  },
};

export default function App() {
  const [page, setPage] = useState<Page>('home');

  const renderPage = () => {
    switch (page) {
      case 'home': return <HomePage onNavigate={setPage} />;
      case 'docs': return <DocsPage />;
      case 'sdk': return <SDKPage />;
      case 'webhooks': return <WebhooksPage />;
      case 'marketplace': return <MarketplacePage />;
      case 'console': return <ConsolePage />;
      case 'sandbox': return <SandboxPage />;
    }
  };

  return (
    <div>
      <nav style={styles.nav}>
        <div style={styles.logoArea} onClick={() => setPage('home')}>
          <div style={styles.logoIcon}>TX</div>
          <span>屯象OS Forge</span>
        </div>
        <div style={styles.navLinks}>
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              onClick={() => setPage(item.key)}
              style={{
                ...styles.navLink,
                ...(page === item.key ? styles.navLinkActive : {}),
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      </nav>
      <main style={styles.content}>{renderPage()}</main>
    </div>
  );
}
