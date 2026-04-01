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
import { CompetitorDetailPage } from './pages/hq/market-intel/CompetitorDetailPage';
import { ReviewTopicPage } from './pages/hq/market-intel/ReviewTopicPage';
import { TrendReportPage } from './pages/hq/market-intel/TrendReportPage';
import { TrendRadarPage } from './pages/hq/market-intel/TrendRadarPage';
import { ReviewIntelPage } from './pages/hq/market-intel/ReviewIntelPage';
import { JourneyDetailPage } from './pages/hq/growth/JourneyDetailPage';
import { OpsDashboardPage } from './pages/hq/ops/OpsDashboardPage';
import { StoreAnalysisPage } from './pages/hq/ops/StoreAnalysisPage';
import { DishAnalysisPage } from './pages/hq/ops/DishAnalysisPage';
import { ApprovalCenterPage } from './pages/hq/ops/ApprovalCenterPage';
import { ReviewCenterPage } from './pages/hq/ops/ReviewCenterPage';
import { AlertCenterPage } from './pages/hq/ops/AlertCenterPage';
import { SettingsPage } from './pages/hq/ops/SettingsPage';
import { PeakMonitorPage } from './pages/hq/ops/PeakMonitorPage';
import { RegionalPage } from './pages/hq/ops/RegionalPage';
import { CruiseMonitorPage } from './pages/hq/ops/CruiseMonitorPage';
import { OperationPlanPage } from './pages/hq/ops/OperationPlanPage';
import { EventBusHealthPage } from './pages/hq/ops/EventBusHealthPage';
import { StoreClonePage } from './pages/hq/ops/StoreClonePage';
import { DailyReviewPage } from './pages/hq/ops/DailyReviewPage';
import { SmartSpecialsPage } from './pages/hq/ops/SmartSpecialsPage';
import { FinanceAnalysisPage } from './pages/hq/analytics/FinanceAnalysisPage';
import { PLReportPage } from './pages/hq/analytics/PLReportPage';
import { MemberAnalysisPage } from './pages/hq/analytics/MemberAnalysisPage';
import { MultiStoreComparePage } from './pages/hq/analytics/MultiStoreComparePage';
import { TrendAnalysisPage } from './pages/hq/analytics/TrendAnalysisPage';
import { BanquetBoardPage } from './pages/hq/BanquetBoardPage';
import { ReceiptEditorPage } from './pages/ReceiptEditorPage';
import { GroupBuyPage } from './pages/hq/growth/GroupBuyPage';
import { StampCardPage } from './pages/hq/growth/StampCardPage';
import { XHSIntegrationPage } from './pages/hq/growth/XHSIntegrationPage';
import { RetailMallPage } from './pages/hq/growth/RetailMallPage';
import { JourneyMonitorPage } from './pages/hq/growth/JourneyMonitorPage';
import { DeliveryPage } from './pages/hq/trade/DeliveryPage';
import { InventoryIntelPage } from './pages/hq/supply/InventoryIntelPage';
import { SupplyChainPage } from './pages/hq/supply/SupplyChainPage';
import { HRDashboardPage } from './pages/hq/org/HRDashboardPage';
import { BudgetTrackerPage } from './pages/hq/analytics/BudgetTrackerPage';
import { MemberCardPage } from './pages/hq/growth/MemberCardPage';

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
          <Route path="/hq/growth/journeys/:journeyId" element={<JourneyDetailPage />} />
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
          <Route path="/hq/market-intel/competitors/:competitorId" element={<CompetitorDetailPage />} />
          <Route path="/hq/market-intel/reviews" element={<ReviewTopicPage />} />
          <Route path="/hq/market-intel/reports" element={<TrendReportPage />} />
          <Route path="/hq/market-intel/trend-radar" element={<TrendRadarPage />} />
          <Route path="/hq/market-intel/review-intel" element={<ReviewIntelPage />} />
          <Route path="/hq/ops/dashboard" element={<OpsDashboardPage />} />
          <Route path="/hq/ops/store-analysis" element={<StoreAnalysisPage />} />
          <Route path="/hq/ops/dish-analysis" element={<DishAnalysisPage />} />
          <Route path="/hq/ops/approvals" element={<ApprovalCenterPage />} />
          <Route path="/hq/ops/review" element={<ReviewCenterPage />} />
          <Route path="/hq/ops/alerts" element={<AlertCenterPage />} />
          <Route path="/hq/ops/settings" element={<SettingsPage />} />
          <Route path="/hq/ops/peak-monitor" element={<PeakMonitorPage />} />
          <Route path="/hq/ops/regional" element={<RegionalPage />} />
          <Route path="/hq/ops/cruise" element={<CruiseMonitorPage />} />
          <Route path="/hq/ops/operation-plans" element={<OperationPlanPage />} />
          <Route path="/hq/ops/event-bus-health" element={<EventBusHealthPage />} />
          <Route path="/hq/ops/store-clone" element={<StoreClonePage />} />
          <Route path="/hq/ops/daily-review" element={<DailyReviewPage />} />
          <Route path="/hq/ops/smart-specials" element={<SmartSpecialsPage />} />
          <Route path="/hq/analytics/finance" element={<FinanceAnalysisPage />} />
          <Route path="/hq/analytics/pl-report" element={<PLReportPage />} />
          <Route path="/hq/analytics/member" element={<MemberAnalysisPage />} />
          <Route path="/hq/analytics/multi-store" element={<MultiStoreComparePage />} />
          <Route path="/hq/analytics/trend" element={<TrendAnalysisPage />} />
          <Route path="/hq/analytics/budget" element={<BudgetTrackerPage />} />
          <Route path="/hq/growth/group-buy" element={<GroupBuyPage />} />
          <Route path="/hq/growth/stamp-card" element={<StampCardPage />} />
          <Route path="/hq/growth/xhs" element={<XHSIntegrationPage />} />
          <Route path="/hq/growth/retail-mall" element={<RetailMallPage />} />
          <Route path="/hq/growth/journey-monitor" element={<JourneyMonitorPage />} />
          <Route path="/hq/trade/delivery" element={<DeliveryPage />} />
          <Route path="/hq/supply/inventory-intel" element={<InventoryIntelPage />} />
          <Route path="/hq/supply/chain" element={<SupplyChainPage />} />
          <Route path="/hq/org/hr" element={<HRDashboardPage />} />
          <Route path="/hq/banquet" element={<BanquetBoardPage />} />
          <Route path="/receipt-editor" element={<ReceiptEditorPage />} />
          <Route path="/receipt-editor/:templateId" element={<ReceiptEditorPage />} />
          <Route path="/hq/growth/member-cards" element={<MemberCardPage />} />
        </Routes>
      </ShellHQ>
    </BrowserRouter>
  );
}

export default App;
