/**
 * web-admin — 总部管理后台
 * 决策1: Shell-HQ 四栏布局
 * 决策2: Agent Console 右侧面板
 * 决策3: Auth Guard — 未登录则显示 LoginPage
 */
import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ShellHQ } from './shell/ShellHQ';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { StoreHealthPage } from './pages/StoreHealthPage';
import { AgentMonitorPage } from './pages/AgentMonitorPage';
import { TradePage } from './pages/TradePage';
import { CatalogPage } from './pages/CatalogPage';
import { SupplyPage } from './pages/SupplyPage';
import { OperationsPage } from './pages/OperationsPage';
import { CrmPage } from './pages/CrmPage';
import { OrgPage } from './pages/OrgPage';
import { SystemPage } from './pages/SystemPage';
import { DailyPlanPage } from './pages/DailyPlanPage';
import { GrowthDashboardPage } from './pages/hq/growth/GrowthDashboardPage';
import { SegmentCenterPage } from './pages/hq/growth/SegmentCenterPage';
import { JourneyListPage } from './pages/hq/growth/JourneyListPage';
import { JourneyCanvasPage } from './pages/hq/growth/JourneyCanvasPage';
import { ROIOverviewPage } from './pages/hq/growth/ROIOverviewPage';
import { IntelDashboardPage } from './pages/hq/market-intel/IntelDashboardPage';
import { NewProductListPage } from './pages/hq/market-intel/NewProductListPage';
import { NewProductOpportunityPage } from './pages/hq/market-intel/NewProductOpportunityPage';
import { ContentCenterPage } from './pages/hq/growth/ContentCenterPage';
import { OfferCenterPage } from './pages/hq/growth/OfferCenterPage';
import { ChannelCenterPage } from './pages/hq/growth/ChannelCenterPage';
import { ReferralCenterPage } from './pages/hq/growth/ReferralCenterPage';
import { StoreExecutionPage } from './pages/hq/growth/StoreExecutionPage';
import { CompetitorCenterPage } from './pages/hq/market-intel/CompetitorCenterPage';
import { ReviewTopicPage } from './pages/hq/market-intel/ReviewTopicPage';
import { TrendReportPage } from './pages/hq/market-intel/TrendReportPage';

function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(!!localStorage.getItem('tx_token'));

  const handleLogout = () => {
    const token = localStorage.getItem('tx_token');
    // Fire-and-forget logout call
    if (token) {
      fetch('/api/v1/auth/logout', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {/* ignore */});
    }
    localStorage.removeItem('tx_token');
    localStorage.removeItem('tx_user');
    setIsLoggedIn(false);
  };

  if (!isLoggedIn) {
    return <LoginPage onLogin={() => setIsLoggedIn(true)} />;
  }

  return (
    <BrowserRouter>
      <ShellHQ onLogout={handleLogout}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/store-health" element={<StoreHealthPage />} />
          <Route path="/agents" element={<AgentMonitorPage />} />
          <Route path="/trade" element={<TradePage />} />
          <Route path="/catalog" element={<CatalogPage />} />
          <Route path="/supply" element={<SupplyPage />} />
          <Route path="/operations" element={<OperationsPage />} />
          <Route path="/crm" element={<CrmPage />} />
          <Route path="/org" element={<OrgPage />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="/daily-plan" element={<DailyPlanPage />} />
          <Route path="/hq/growth/dashboard" element={<GrowthDashboardPage />} />
          <Route path="/hq/growth/segments" element={<SegmentCenterPage />} />
          <Route path="/hq/growth/journeys" element={<JourneyListPage />} />
          <Route path="/hq/growth/journeys/:journeyId/canvas" element={<JourneyCanvasPage />} />
          <Route path="/hq/growth/roi" element={<ROIOverviewPage />} />
          <Route path="/hq/market-intel/dashboard" element={<IntelDashboardPage />} />
          <Route path="/hq/market-intel/new-products" element={<NewProductListPage />} />
          <Route path="/hq/market-intel/new-products/:id" element={<NewProductOpportunityPage />} />
          <Route path="/hq/growth/content" element={<ContentCenterPage />} />
          <Route path="/hq/growth/offers" element={<OfferCenterPage />} />
          <Route path="/hq/growth/channels" element={<ChannelCenterPage />} />
          <Route path="/hq/growth/referral" element={<ReferralCenterPage />} />
          <Route path="/hq/growth/execution" element={<StoreExecutionPage />} />
          <Route path="/hq/market-intel/competitors" element={<CompetitorCenterPage />} />
          <Route path="/hq/market-intel/reviews" element={<ReviewTopicPage />} />
          <Route path="/hq/market-intel/reports" element={<TrendReportPage />} />
        </Routes>
      </ShellHQ>
    </BrowserRouter>
  );
}

export default App;
