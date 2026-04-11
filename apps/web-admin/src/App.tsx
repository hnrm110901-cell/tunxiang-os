/**
 * web-admin — 总部管理后台
 */
import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { getToken, clearAuth, isTokenExpired } from './api/client';
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
import { LiveSeafoodPage } from './pages/menu/live-seafood/LiveSeafoodPage';
import { BanquetMenuPage } from './pages/trade/banquet-menu/BanquetMenuPage';
import BanquetManagePage from './pages/trade/BanquetManagePage'; // Y-A8 宴席支付闭环
import { DishDeptMappingPage } from './pages/trade/kds-mapping/DishDeptMappingPage';
import { OperationsDashboardPage } from './pages/OperationsDashboardPage';
import { MenuTemplatePage } from './pages/menu/template/MenuTemplatePage';
import { CentralKitchenPage } from './pages/CentralKitchenPage';
import { CentralKitchenPage as CentralKitchenPageV2 } from './pages/supply/CentralKitchenPage';
import { BomEditorPage } from './pages/supply/bom/BomEditorPage';
import { PayrollPage } from './pages/PayrollPage';
import { ApprovalTemplatePage } from './pages/ops/approval/ApprovalTemplatePage';
import { ApprovalCenterPage as ApprovalCenterPageNew } from './pages/ops/approval/ApprovalCenterPage';
import { PayrollManagePage } from './pages/org/payroll/PayrollManagePage';
import { FranchiseDashboardPage } from './pages/org/franchise/FranchiseDashboardPage';
import { FranchisePage } from './pages/franchise/FranchisePage';
import FranchiseContractPage from './pages/franchise/FranchiseContractPage';
import { PayrollConfigPage } from './pages/org/PayrollConfigPage';
import { PayrollRecordsPage } from './pages/org/PayrollRecordsPage';
import { FinanceAuditPage } from './pages/finance/FinanceAuditPage';
import PnLReportPage from './pages/finance/PnLReportPage';
import PayrollPage from './pages/finance/PayrollPage';
import { PatrolInspectionPage } from './pages/ops/PatrolInspectionPage';
import { HACCPPage } from './pages/ops/HACCPPage';
import { EnergyBudgetPage } from './pages/ops/EnergyBudgetPage';
import { AnalyticsDashboardPage } from './pages/analytics/DashboardPage';
import { HQDashboardPage } from './pages/analytics/HQDashboardPage';
import { DishAnalyticsPage } from './pages/analytics/DishAnalyticsPage';
import { MenuOptimizePage } from './pages/menu/MenuOptimizePage';
import { DishSpecPage } from './pages/menu/DishSpecPage';
import { DishSortPage } from './pages/menu/DishSortPage';
import { DishBatchPage } from './pages/menu/DishBatchPage';
import { CRMCampaignPage } from './pages/growth/CRMCampaignPage';
import { CustomerPoolPage } from './pages/hq/growth/CustomerPoolPage';
import { Customer360Page } from './pages/hq/growth/Customer360Page';
import { GrowthJourneyTemplatePage } from './pages/hq/growth/GrowthJourneyTemplatePage';
import { GrowthJourneyRunsPage } from './pages/hq/growth/GrowthJourneyRunsPage';
import { AgentWorkbenchPage } from './pages/hq/growth/AgentWorkbenchPage';
import { GrowthSettingsPage } from './pages/hq/growth/GrowthSettingsPage';
import { JourneyAttributionPage } from './pages/hq/growth/JourneyAttributionPage';
import { StoreGrowthRankPage } from './pages/hq/growth/StoreGrowthRankPage';
import { BrandComparisonPage } from './pages/hq/growth/BrandComparisonPage';
import { CrossBrandPage } from './pages/hq/growth/CrossBrandPage';
import { ExternalSignalsPage } from './pages/hq/growth/ExternalSignalsPage';
import { GrowthSegmentTagsPage } from './pages/hq/growth/GrowthSegmentTagsPage';
import { GrowthOfferPacksPage } from './pages/hq/growth/GrowthOfferPacksPage';
import { CampaignManagePage } from './pages/growth/CampaignManagePage';
import ReferralManagePage from './pages/growth/ReferralManagePage';  // v191 三级分销
import { AttendancePage } from './pages/org/AttendancePage';
import { PerformancePage } from './pages/org/PerformancePage';
import { PieceworkPage } from './pages/org/PieceworkPage';  // v187 计件提成3.0
import { MemberInsightPage } from './pages/member/MemberInsightPage';
import { CustomerServicePage } from './pages/member/CustomerServicePage';
import { MemberTierPage } from './pages/member/MemberTierPage';
import { PurchaseOrderPage } from './pages/supply/PurchaseOrderPage';
import { ExpiryAlertPage } from './pages/supply/ExpiryAlertPage';
import { SupplyDashboardPage } from './pages/supply/SupplyDashboardPage';
import { BanquetTemplatePage } from './pages/hq/trade/BanquetTemplatePage';
import { SupplierPortalPage } from './pages/hq/supply/SupplierPortalPage';
import { ReviewManagePage } from './pages/ops/ReviewManagePage';
import { SettlementMonitorPage } from './pages/ops/SettlementMonitorPage';
import { StoreManagePage } from './pages/store/StoreManagePage';
import { MarketSessionPage } from './pages/store/MarketSessionPage';  // v186 营业市别
import FoodCourtManagePage from './pages/store/FoodCourtManagePage';  // TC-P2-12 智慧商街档口管理
import { AgentDashboardPage } from './pages/agent/AgentDashboardPage';
// ─── Phase1-4 新增页面 ───────────────────────────────────────────────────────
import MenuSchemePage from './pages/menu/MenuSchemePage';
import { WineStoragePage } from './pages/finance/WineStoragePage';
import { DepositManagePage } from './pages/finance/DepositManagePage';
import { CostManagePage } from './pages/finance/CostManagePage';
import { BudgetManagePage } from './pages/finance/BudgetManagePage';
import { AgreementUnitPage } from './pages/finance/AgreementUnitPage';  // TC-P1-09
import { EnterprisePage } from './pages/trade/EnterprisePage';
import { ServiceChargeConfigPage } from './pages/trade/ServiceChargeConfigPage';
import { DispatchRuleConfigPage } from './pages/kds/DispatchRuleConfigPage';
import { DispatchCodePage } from './pages/kds/DispatchCodePage';
import { KDSCallSettingsPage } from './pages/kds/KDSCallSettingsPage';
import { ManagerDashboardPage } from './pages/analytics/ManagerDashboardPage';
import { WineDepositReportPage } from './pages/analytics/WineDepositReportPage';
import ReportCenterPage from './pages/analytics/ReportCenterPage';  // TC-P2-15 品牌自定义报表框架
// ─── Sprint 0-8: 人力中枢页面 ──────────────────────────────────────────────────
import { HRHubPage } from './pages/hr/HRHubPage';
import { EmployeeListPage } from './pages/hr/EmployeeListPage';
import { EmployeeCreatePage } from './pages/hr/EmployeeCreatePage';
import { EmployeeDetailPage } from './pages/hr/EmployeeDetailPage';
import { OrgStructurePage } from './pages/hr/OrgStructurePage';
import { JobGradesPage } from './pages/hr/JobGradesPage';
import { ScheduleCenterPage } from './pages/hr/ScheduleCenterPage';
import { ScheduleStoreWeekPage } from './pages/hr/ScheduleStoreWeekPage';
import { ScheduleBatchPage } from './pages/hr/ScheduleBatchPage';
import { ScheduleAdjustmentsPage } from './pages/hr/ScheduleAdjustmentsPage';
import { ScheduleConflictsPage } from './pages/hr/ScheduleConflictsPage';
import { ScheduleGapsPage } from './pages/hr/ScheduleGapsPage';
import { ScheduleTemplatesPage } from './pages/hr/ScheduleTemplatesPage';
import { AttendanceTodayPage } from './pages/hr/AttendanceTodayPage';
import { AttendanceDailyPage } from './pages/hr/AttendanceDailyPage';
import { AttendanceMonthlyPage } from './pages/hr/AttendanceMonthlyPage';
import { AttendanceAnomaliesPage } from './pages/hr/AttendanceAnomaliesPage';
import { AttendanceAdjustmentsPage } from './pages/hr/AttendanceAdjustmentsPage';
import { LeaveRequestsPage } from './pages/hr/LeaveRequestsPage';
import { LeaveDetailPage } from './pages/hr/LeaveDetailPage';
import { LeaveBalancesPage } from './pages/hr/LeaveBalancesPage';
import { LeaveApprovalBoardPage } from './pages/hr/LeaveApprovalBoardPage';
import { PerformanceScoresPage } from './pages/hr/PerformanceScoresPage';
import { PerformanceRankingsPage } from './pages/hr/PerformanceRankingsPage';
import { PerformanceHorseRacePage } from './pages/hr/PerformanceHorseRacePage';
import { PerformancePointsPage } from './pages/hr/PerformancePointsPage';
import { PerformancePointDetailPage } from './pages/hr/PerformancePointDetailPage';
import { PayrollLaborCostPage } from './pages/hr/PayrollLaborCostPage';
import { PayrollApprovalPage } from './pages/hr/PayrollApprovalPage';
import { PayrollSummaryPage } from './pages/hr/PayrollSummaryPage';
import { ComplianceDashboardPage } from './pages/hr/ComplianceDashboardPage';
import { ComplianceAlertsPage } from './pages/hr/ComplianceAlertsPage';
import { ComplianceDocExpiringPage } from './pages/hr/ComplianceDocExpiringPage';
import { ComplianceTasksPage } from './pages/hr/ComplianceTasksPage';
import { StoreOpsTodayPage } from './pages/hr/StoreOpsTodayPage';
import { StoreOpsFillGapsPage } from './pages/hr/StoreOpsFillGapsPage';
import { StoreOpsExceptionsPage } from './pages/hr/StoreOpsExceptionsPage';
import { GovernanceDashboardPage } from './pages/hr/GovernanceDashboardPage';
import { GovernanceBenchmarkPage } from './pages/hr/GovernanceBenchmarkPage';
import { GovernanceStaffingPage } from './pages/hr/GovernanceStaffingPage';
import { GovernanceRiskStoresPage } from './pages/hr/GovernanceRiskStoresPage';
import { AgentHubPage } from './pages/hr/AgentHubPage';
import { AgentComplianceAlertPage } from './pages/hr/AgentComplianceAlertPage';
import { AgentSalaryAdvisorPage } from './pages/hr/AgentSalaryAdvisorPage';
import { AgentWorkforcePlannerPage } from './pages/hr/AgentWorkforcePlannerPage';
import { AgentTurnoverRiskPage } from './pages/hr/AgentTurnoverRiskPage';
import { SettingsRolesPage } from './pages/hr/SettingsRolesPage';
import { SettingsApprovalWorkflowsPage } from './pages/hr/SettingsApprovalWorkflowsPage';
import { SettingsAuditLogsPage } from './pages/hr/SettingsAuditLogsPage';
// ─── P2: 人力分析三件套 ──────────────────────────────────────────────────────
import { LaborMarginDashboardPage } from './pages/hr/LaborMarginDashboardPage';
import { BudgetRecommendationPage } from './pages/hr/BudgetRecommendationPage';
import { MenuSkillMatchPage } from './pages/hr/MenuSkillMatchPage';
// ─── TC-P1-11: 试营业数据清除 ────────────────────────────────────────────────
import { TrialDataClearPage } from './pages/settings/TrialDataClearPage';
// ─── TC-P1-07: 移动端管理直通车 ─────────────────────────────────────────────
import { MobileDashboard } from './pages/mobile/MobileDashboard';
import { MobileAnomalyPage } from './pages/mobile/MobileAnomalyPage';
import { MobileTableStatusPage } from './pages/mobile/MobileTableStatusPage';
// ─── P3-04/P3-05: 菜品排名 + 企微SCRM ────────────────────────────────────────
import DishRankingPage from './pages/menu/DishRankingPage';
import SCRMAgentPage from './pages/growth/SCRMAgentPage';
// ─── Y-A12: 全渠道订单中心 ────────────────────────────────────────────────────
import OmniOrderCenterPage from './pages/trade/OmniOrderCenterPage';
// ─── OR-02: 员工培训管理 ───────────────────────────────────────────────────────
import EmployeeTrainingPage from './pages/org/EmployeeTrainingPage';
// ─── Y-H1/Y-H2: 多品牌管理统一 + 多区域管理 ────────────────────────────────────
import BrandRegionPage from './pages/org/BrandRegionPage';
// ─── Y-I2: 抖音团购管理 ───────────────────────────────────────────────────────
import DouyinVoucherPage from './pages/trade/DouyinVoucherPage';
// ─── Sprint 1: AI 中枢 ────────────────────────────────────────────────────────
import { AgentHubPage as HQAgentHubPage } from './pages/hq/agent/AgentHubPage';
import { AgentCommandCenterPage } from './pages/hq/agent/AgentCommandCenterPage';
// ─── Sprint 3: 经营分析师 + 收益优化师 ──────────────────────────────────────────
import { NLQueryPage } from './pages/hq/analytics/NLQueryPage';
import { AIDailyBriefPage } from './pages/hq/analytics/AIDailyBriefPage';
import { RevenueOptimizePage } from './pages/hq/analytics/RevenueOptimizePage';
import { CustomerBrainPage } from './pages/hq/growth/CustomerBrainPage';
// ─── Sprint 4: 供应链卫士 + Agent市场 + 异常检测 + 菜品智能体 ─────────────────
import { ProcurementSuggestionPage } from './pages/hq/supply/ProcurementSuggestionPage';
import { WastageAnalysisPage } from './pages/hq/supply/WastageAnalysisPage';
import { DemandForecastPage } from './pages/hq/supply/DemandForecastPage';
import { AgentMarketplacePage } from './pages/hq/agent/AgentMarketplacePage';
import { AgentSettingsPage } from './pages/hq/agent/AgentSettingsPage';
import { AnomalyDetectionPage } from './pages/hq/analytics/AnomalyDetectionPage';
import { TableTurnoverPage } from './pages/hq/analytics/TableTurnoverPage';
import { DishAgentDashboardPage } from './pages/hq/menu/DishAgentDashboardPage';
// ─── Y-C4: 多渠道菜单发布完善 + Y-D7: 付费会员卡产品化 ────────────────────────
import ChannelMenuPage from './pages/menu/ChannelMenuPage';
import PremiumCardPage from './pages/member/PremiumCardPage';
// ─── Y-M4: 外卖自营配送调度 + Y-A9: 企业客户管理 ──────────────────────────────
import DeliveryDispatchPage from './pages/trade/DeliveryDispatchPage';
import CorporateCustomerPage from './pages/trade/CorporateCustomerPage';
// ─── 人力中枢升级 Sprint 1: 编制+工单+预警 ────────────────────────────────────────
import StaffingTemplatePage from './pages/hr/StaffingTemplatePage';
import StaffingAnalysisPage from './pages/hr/StaffingAnalysisPage';
import DRIWorkOrderCenterPage from './pages/hr/DRIWorkOrderCenterPage';
// ─── 人力中枢升级 Sprint 2: 带教+训练+认证 ────────────────────────────────────────
import MentorshipSupervisePage from './pages/hr/MentorshipSupervisePage';
import OnboardingPathPage from './pages/hr/OnboardingPathPage';
import CertificationPage from './pages/hr/CertificationPage';
// ─── 人力中枢升级 Sprint 3: 就绪度+高峰保障 ────────────────────────────────────────
import StoreReadinessPage from './pages/hr/StoreReadinessPage';
import PeakGuardPage from './pages/hr/PeakGuardPage';
// ─── 人力中枢升级 Sprint 4: AI驱动层 ────────────────────────────────────────
import CoachSessionPage from './pages/hr/CoachSessionPage';
import AlertAggregationPage from './pages/hr/AlertAggregationPage';
import HRHubOverviewPage from './pages/hr/HRHubOverviewPage';
// ─── AI营销驾驶舱 ─────────────────────────────────────────────────────────────
import AiMarketingDashboardPage from './pages/marketing/AiMarketingDashboardPage';

function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(() => {
    const token = getToken();
    if (!token || isTokenExpired()) { clearAuth(); return false; }
    return true;
  });

  const handleLogout = () => {
    const token = getToken();
    if (token) {
      fetch('/api/v1/auth/logout', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
    }
    clearAuth();
    setIsLoggedIn(false);
  };

  if (!isLoggedIn) { return <LoginPage onLogin={() => setIsLoggedIn(true)} />; }

  return (
    <BrowserRouter>
      <ShellHQ onLogout={handleLogout}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/operations-dashboard" element={<OperationsDashboardPage />} />
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
          {/* 增长中枢V2新增路由 */}
          <Route path="/hq/growth/customers" element={<CustomerPoolPage />} />
          <Route path="/hq/growth/customers/:customerId" element={<Customer360Page />} />
          <Route path="/hq/growth/journey-templates" element={<GrowthJourneyTemplatePage />} />
          <Route path="/hq/growth/journey-runs" element={<GrowthJourneyRunsPage />} />
          <Route path="/hq/growth/agent-workbench" element={<AgentWorkbenchPage />} />
          <Route path="/hq/growth/settings" element={<GrowthSettingsPage />} />
          <Route path="/hq/growth/journey-attribution" element={<JourneyAttributionPage />} />
          <Route path="/hq/growth/segment-tags" element={<GrowthSegmentTagsPage />} />
          <Route path="/hq/growth/offer-packs" element={<GrowthOfferPacksPage />} />
          <Route path="/hq/growth/brand-comparison" element={<BrandComparisonPage />} />
          <Route path="/hq/growth/store-ranking" element={<StoreGrowthRankPage />} />
          <Route path="/hq/growth/cross-brand" element={<CrossBrandPage />} />
          <Route path="/hq/growth/external-signals" element={<ExternalSignalsPage />} />
          <Route path="/hq/trade/delivery" element={<DeliveryPage />} />
          <Route path="/hq/supply/inventory-intel" element={<InventoryIntelPage />} />
          <Route path="/hq/supply/chain" element={<SupplyChainPage />} />
          <Route path="/hq/org/hr" element={<HRDashboardPage />} />
          <Route path="/hq/banquet" element={<BanquetBoardPage />} />
          <Route path="/receipt-editor" element={<ReceiptEditorPage />} />
          <Route path="/receipt-editor/:templateId" element={<ReceiptEditorPage />} />
          <Route path="/hq/growth/member-cards" element={<MemberCardPage />} />
          <Route path="/hq/menu/live-seafood" element={<LiveSeafoodPage />} />
          <Route path="/hq/trade/banquet-menu" element={<BanquetMenuPage />} />
          <Route path="/trade/banquet" element={<BanquetManagePage />} />
          <Route path="/hq/kds/dish-dept-mapping" element={<DishDeptMappingPage />} />
          <Route path="/menu-templates" element={<MenuTemplatePage />} />
          <Route path="/central-kitchen" element={<CentralKitchenPage />} />
          <Route path="/supply/central-kitchen" element={<CentralKitchenPageV2 />} />
          <Route path="/supply/bom" element={<BomEditorPage />} />
          <Route path="/payroll" element={<PayrollPage />} />
          <Route path="/approval-templates" element={<ApprovalTemplatePage />} />
          <Route path="/approval-center" element={<ApprovalCenterPageNew />} />
          <Route path="/ops/approval-center" element={<ApprovalCenterPageNew />} />
          <Route path="/payroll-manage" element={<PayrollManagePage />} />
          <Route path="/franchise-dashboard" element={<FranchiseDashboardPage />} />
          <Route path="/franchise" element={<FranchisePage />} />
          <Route path="/franchise/contracts" element={<FranchiseContractPage />} />
          <Route path="/org/payroll-configs" element={<PayrollConfigPage />} />
          <Route path="/org/payroll-records" element={<PayrollRecordsPage />} />
          <Route path="/finance/audit" element={<FinanceAuditPage />} />
          <Route path="/finance/pnl-report" element={<PnLReportPage />} />
          <Route path="/finance/payroll" element={<PayrollPage />} />
          <Route path="/ops/patrol-inspection" element={<PatrolInspectionPage />} />
          <Route path="/ops/haccp" element={<HACCPPage />} />
          <Route path="/ops/energy-budget" element={<EnergyBudgetPage />} />
          <Route path="/analytics/dashboard" element={<AnalyticsDashboardPage />} />
          <Route path="/analytics/hq-dashboard" element={<HQDashboardPage />} />
          <Route path="/analytics/dishes" element={<DishAnalyticsPage />} />
          <Route path="/menu/optimize" element={<MenuOptimizePage />} />
          <Route path="/menu/specs" element={<DishSpecPage />} />
          <Route path="/menu/sort" element={<DishSortPage />} />
          <Route path="/menu/batch" element={<DishBatchPage />} />
          <Route path="/growth/crm-campaign" element={<CRMCampaignPage />} />
          <Route path="/growth/referral-distribution" element={<ReferralManagePage />} />  {/* v191 三级分销 */}
          <Route path="/growth/campaigns" element={<CampaignManagePage />} />
          <Route path="/org/attendance" element={<AttendancePage />} />
          <Route path="/org/performance" element={<PerformancePage />} />
          <Route path="/org/piecework" element={<PieceworkPage />} />  {/* v187 计件提成3.0 */}
          <Route path="/member/insight" element={<MemberInsightPage />} />
          <Route path="/member/customer-service" element={<CustomerServicePage />} />
          <Route path="/member/tiers" element={<MemberTierPage />} />
          <Route path="/supply/purchase-orders" element={<PurchaseOrderPage />} />
          <Route path="/supply/expiry-alerts" element={<ExpiryAlertPage />} />
          <Route path="/supply/dashboard" element={<SupplyDashboardPage />} />
          <Route path="/ops/reviews" element={<ReviewManagePage />} />
          <Route path="/ops/settlement-monitor" element={<SettlementMonitorPage />} />
          <Route path="/store/manage" element={<StoreManagePage />} />
          <Route path="/store/market-sessions" element={<MarketSessionPage />} />  {/* v186 营业市别 */}
          <Route path="/store/food-court" element={<FoodCourtManagePage />} />  {/* TC-P2-12 智慧商街档口管理 */}
          <Route path="/hq/trade/banquet-templates" element={<BanquetTemplatePage />} />
          <Route path="/hq/supply/suppliers" element={<SupplierPortalPage />} />
          <Route path="/agent/dashboard" element={<AgentDashboardPage />} />
          {/* ─── Phase1: 财务刚需 ─── */}
          <Route path="/finance/wine-storage" element={<WineStoragePage />} />
          <Route path="/finance/deposits" element={<DepositManagePage />} />
          <Route path="/finance/costs" element={<CostManagePage />} />
          <Route path="/finance/budgets" element={<BudgetManagePage />} />
          <Route path="/finance/agreement-units" element={<AgreementUnitPage />} />  {/* TC-P1-09 协议单位 */}
          {/* ─── Phase1: 交易配置 ─── */}
          <Route path="/trade/enterprise" element={<EnterprisePage />} />
          <Route path="/trade/service-charge" element={<ServiceChargeConfigPage />} />
          {/* ─── Phase2: KDS规则管理 ─── */}
          <Route path="/kds/dispatch-rules" element={<DispatchRuleConfigPage />} />
          <Route path="/kds/dispatch-codes" element={<DispatchCodePage />} />
          <Route path="/kds/call-settings" element={<KDSCallSettingsPage />} />
          {/* ─── Phase3: 管理直通车 + 专项报表 ─── */}
          <Route path="/analytics/manager-dashboard" element={<ManagerDashboardPage />} />
          <Route path="/analytics/wine-deposit-report" element={<WineDepositReportPage />} />
          {/* ─── TC-P2-15: 品牌自定义报表框架 ─── */}
          <Route path="/analytics/reports" element={<ReportCenterPage />} />
          {/* ─── Phase4: 菜谱方案 ─── */}
          <Route path="/menu/schemes" element={<MenuSchemePage />} />
          {/* ─── Sprint 0-8: 人力中枢 ─── */}
          <Route path="/hr" element={<HRHubPage />} />
          {/* 员工主数据 */}
          <Route path="/hr/employees" element={<EmployeeListPage />} />
          <Route path="/hr/employees/new" element={<EmployeeCreatePage />} />
          <Route path="/hr/employees/:employeeId" element={<EmployeeDetailPage />} />
          <Route path="/hr/org-structure" element={<OrgStructurePage />} />
          <Route path="/hr/job-grades" element={<JobGradesPage />} />
          {/* 排班中心 */}
          <Route path="/hr/schedules" element={<ScheduleCenterPage />} />
          <Route path="/hr/schedules/store/:storeId/week" element={<ScheduleStoreWeekPage />} />
          <Route path="/hr/schedules/batch" element={<ScheduleBatchPage />} />
          <Route path="/hr/schedules/adjustments" element={<ScheduleAdjustmentsPage />} />
          <Route path="/hr/schedules/conflicts" element={<ScheduleConflictsPage />} />
          <Route path="/hr/schedules/gaps" element={<ScheduleGapsPage />} />
          <Route path="/hr/schedules/templates" element={<ScheduleTemplatesPage />} />
          {/* 考勤中心 */}
          <Route path="/hr/attendance/today" element={<AttendanceTodayPage />} />
          <Route path="/hr/attendance/daily" element={<AttendanceDailyPage />} />
          <Route path="/hr/attendance/monthly" element={<AttendanceMonthlyPage />} />
          <Route path="/hr/attendance/anomalies" element={<AttendanceAnomaliesPage />} />
          <Route path="/hr/attendance/adjustments" element={<AttendanceAdjustmentsPage />} />
          {/* 请假中心 */}
          <Route path="/hr/leave-requests" element={<LeaveRequestsPage />} />
          <Route path="/hr/leave-requests/:leaveId" element={<LeaveDetailPage />} />
          <Route path="/hr/leave-balances" element={<LeaveBalancesPage />} />
          <Route path="/hr/leave-requests/approval-board" element={<LeaveApprovalBoardPage />} />
          {/* 绩效与激励 */}
          <Route path="/hr/performance/scores" element={<PerformanceScoresPage />} />
          <Route path="/hr/performance/rankings" element={<PerformanceRankingsPage />} />
          <Route path="/hr/performance/horse-race" element={<PerformanceHorseRacePage />} />
          <Route path="/hr/performance/points" element={<PerformancePointsPage />} />
          <Route path="/hr/performance/points/:employeeId" element={<PerformancePointDetailPage />} />
          {/* 薪资中心 */}
          <Route path="/hr/payroll/labor-cost" element={<PayrollLaborCostPage />} />
          <Route path="/hr/payroll/approval" element={<PayrollApprovalPage />} />
          <Route path="/hr/payroll/summary" element={<PayrollSummaryPage />} />
          {/* 合规中心 */}
          <Route path="/hr/compliance" element={<ComplianceDashboardPage />} />
          <Route path="/hr/compliance/alerts" element={<ComplianceAlertsPage />} />
          <Route path="/hr/compliance/documents/expiring" element={<ComplianceDocExpiringPage />} />
          <Route path="/hr/compliance/tasks" element={<ComplianceTasksPage />} />
          {/* 门店作战台 */}
          <Route path="/hr/store-ops/today" element={<StoreOpsTodayPage />} />
          <Route path="/hr/store-ops/fill-gaps" element={<StoreOpsFillGapsPage />} />
          <Route path="/hr/store-ops/exceptions" element={<StoreOpsExceptionsPage />} />
          {/* 总部治理台 */}
          <Route path="/hr/governance/dashboard" element={<GovernanceDashboardPage />} />
          <Route path="/hr/governance/benchmark" element={<GovernanceBenchmarkPage />} />
          <Route path="/hr/governance/staffing" element={<GovernanceStaffingPage />} />
          <Route path="/hr/governance/risk-stores" element={<GovernanceRiskStoresPage />} />
          {/* 人力中枢升级 Sprint 1 */}
          <Route path="/hr/staffing/templates" element={<StaffingTemplatePage />} />
          <Route path="/hr/staffing/analysis" element={<StaffingAnalysisPage />} />
          <Route path="/hr/dri-workorders" element={<DRIWorkOrderCenterPage />} />
          {/* 人力中枢升级 Sprint 2 */}
          <Route path="/hr/mentorship" element={<MentorshipSupervisePage />} />
          <Route path="/hr/onboarding" element={<OnboardingPathPage />} />
          <Route path="/hr/certifications" element={<CertificationPage />} />
          {/* 人力中枢升级 Sprint 3 */}
          <Route path="/hr/store-readiness" element={<StoreReadinessPage />} />
          <Route path="/hr/peak-guard" element={<PeakGuardPage />} />
          {/* 人力中枢升级 Sprint 4 */}
          <Route path="/hr/hub" element={<HRHubOverviewPage />} />
          <Route path="/hr/coach-sessions" element={<CoachSessionPage />} />
          <Route path="/hr/alert-center" element={<AlertAggregationPage />} />
          {/* Agent中枢 */}
          <Route path="/hr/agents" element={<AgentHubPage />} />
          <Route path="/hr/agents/compliance-alert" element={<AgentComplianceAlertPage />} />
          <Route path="/hr/agents/salary-advisor" element={<AgentSalaryAdvisorPage />} />
          <Route path="/hr/agents/workforce-planner" element={<AgentWorkforcePlannerPage />} />
          <Route path="/hr/agents/turnover-risk" element={<AgentTurnoverRiskPage />} />
          {/* P2: 人力分析 */}
          <Route path="/hr/analytics/labor-margin" element={<LaborMarginDashboardPage />} />
          <Route path="/hr/analytics/budget" element={<BudgetRecommendationPage />} />
          <Route path="/hr/analytics/menu-skill" element={<MenuSkillMatchPage />} />
          {/* 配置中心 */}
          <Route path="/hr/settings/roles" element={<SettingsRolesPage />} />
          <Route path="/hr/settings/approval-workflows" element={<SettingsApprovalWorkflowsPage />} />
          <Route path="/hr/settings/audit-logs" element={<SettingsAuditLogsPage />} />
          {/* ─── TC-P1-07: 移动端管理直通车（/m/* 前缀） ─── */}
          <Route path="/m/dashboard" element={<MobileDashboard />} />
          <Route path="/m/anomaly" element={<MobileAnomalyPage />} />
          <Route path="/m/tables" element={<MobileTableStatusPage />} />
          <Route path="/m" element={<Navigate to="/m/dashboard" replace />} />
          {/* ─── TC-P1-11: 试营业数据清除 ─── */}
          <Route path="/settings/trial-data-clear" element={<TrialDataClearPage />} />
          {/* ─── P3-04: 菜品5因子动态排名 ─── */}
          <Route path="/menu/ranking" element={<DishRankingPage />} />
          {/* ─── Sprint 1: AI 中枢 ─── */}
          <Route path="/hq/agent/hub"      element={<HQAgentHubPage />} />
          <Route path="/hq/agent/command"  element={<AgentCommandCenterPage />} />
          <Route path="/hq/agent/log"      element={<AgentCommandCenterPage />} />
          {/* ─── Sprint 4: 供应链卫士 + Agent市场 + 异常检测 + 菜品智能体 ─── */}
          <Route path="/hq/supply/procurement-ai"  element={<ProcurementSuggestionPage />} />
          <Route path="/hq/supply/wastage"         element={<WastageAnalysisPage />} />
          <Route path="/hq/supply/demand-forecast" element={<DemandForecastPage />} />
          <Route path="/hq/agent/market"           element={<AgentMarketplacePage />} />
          <Route path="/hq/agent/settings"         element={<AgentSettingsPage />} />
          <Route path="/hq/analytics/anomaly"      element={<AnomalyDetectionPage />} />
          <Route path="/hq/analytics/table-turnover" element={<TableTurnoverPage />} />
          <Route path="/hq/menu/dish-agent"        element={<DishAgentDashboardPage />} />
          <Route path="/hq/menu/kitchen-schedule"  element={<DishAgentDashboardPage />} />
          {/* ─── P3-05: 企微SCRM私域Agent ─── */}
          <Route path="/growth/scrm-agent" element={<SCRMAgentPage />} />
          {/* ─── Y-A12: 全渠道订单中心 ─── */}
          <Route path="/trade/omni-orders" element={<OmniOrderCenterPage />} />
          {/* ─── OR-02: 员工培训管理 ─── */}
          <Route path="/org/training" element={<EmployeeTrainingPage />} />
          {/* ─── Y-H1/Y-H2: 多品牌管理统一 + 多区域管理 ─── */}
          <Route path="/org/brands" element={<BrandRegionPage />} />
          {/* ─── Y-I2: 抖音团购管理 ─── */}
          <Route path="/trade/douyin-voucher" element={<DouyinVoucherPage />} />
          {/* ─── Sprint 3: 经营分析师 + 收益优化师 ─── */}
          <Route path="/hq/analytics/nlq"              element={<NLQueryPage />} />
          <Route path="/hq/analytics/daily-brief"      element={<AIDailyBriefPage />} />
          <Route path="/hq/analytics/revenue-optimize" element={<RevenueOptimizePage />} />
          {/* /hq/analytics/table-turnover handled in Sprint 4 routes above */}
          <Route path="/hq/growth/customer-brain"      element={<CustomerBrainPage />} />
          {/* ─── AI营销驾驶舱 ─── */}
          <Route path="/hq/growth/ai-marketing" element={<AiMarketingDashboardPage />} />
          {/* ─── Y-C4: 多渠道菜单发布完善 ─── */}
          <Route path="/menu/channels" element={<ChannelMenuPage />} />
          {/* ─── Y-D7: 付费会员卡产品化 ─── */}
          <Route path="/member/premium-cards" element={<PremiumCardPage />} />
          {/* ─── Y-M4: 外卖自营配送调度台 ─── */}
          <Route path="/trade/delivery" element={<DeliveryDispatchPage />} />
          {/* ─── Y-A9: 企业客户管理（团餐） ─── */}
          <Route path="/trade/corporate" element={<CorporateCustomerPage />} />
        </Routes>
      </ShellHQ>
    </BrowserRouter>
  );
}

export default App;
