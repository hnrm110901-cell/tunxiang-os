/**
 * web-admin — 总部管理后台
 * 路由已按产品域拆分到 src/routes/*.tsx
 */
import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from './store/authStore';
import { ShellHQ } from './shell/ShellHQ';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { DailyPlanPage } from './pages/DailyPlanPage';
import { SystemPage } from './pages/SystemPage';
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
import FinancePayrollPage from './pages/finance/PayrollPage';
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
import MenuPlanPage from './pages/menu/MenuPlanPage';  // 模块3.4 菜谱方案批量下发+门店差异化
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
// ─── 模块3.2: 加盟商管理闭环 ──────────────────────────────────────────────────
import FranchiseManagePage from './pages/org/FranchiseManagePage';
// ─── Y-H1/Y-H2: 多品牌管理统一 + 多区域管理 ────────────────────────────────────
import BrandRegionPage from './pages/org/BrandRegionPage';
// ─── Y-I2: 抖音团购管理 ───────────────────────────────────────────────────────
import DouyinVoucherPage from './pages/trade/DouyinVoucherPage';
// ─── AI经营合伙人 ─────────────────────────────────────────────────────────────
import { ChiefAgentPage } from './pages/agent/ChiefAgentPage';
// ─── 模块4.4: Agent KPI仪表盘 ────────────────────────────────────────────────
import AgentKPIDashboard from './pages/AgentKPIDashboard';
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
import { CommissionV3Page } from './pages/hr/CommissionV3Page';  // 计件提成3.0 模块2.6
// ─── AI营销驾驶舱 ─────────────────────────────────────────────────────────────
import AiMarketingDashboardPage from './pages/marketing/AiMarketingDashboardPage';
// ─── 促销规则引擎 V2（模块2.5）────────────────────────────────────────────────
import PromotionRulesV2Page from './pages/marketing/PromotionRulesV2Page';
// ─── P3: HQ总部管控看板 ────────────────────────────────────────────────────────
import { BrandOverview } from './pages/analytics/hq/BrandOverview';
import { StorePerformanceMatrix } from './pages/analytics/hq/StorePerformanceMatrix';
// ─── 模块4.4: Agent KPI 绑定仪表盘 ────────────────────────────────────────────
// (duplicate import removed - AgentKPIDashboard already imported above)

function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const restore = useAuthStore((s) => s.restore);
  const logout = useAuthStore((s) => s.logout);

  useEffect(() => { restore(); }, [restore]);

  if (!isAuthenticated) { return <LoginPage onLogin={() => {}} />; }

  return (
    <BrowserRouter>
      <ShellHQ onLogout={logout}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/daily-plan" element={<DailyPlanPage />} />
          <Route path="/system" element={<SystemPage />} />
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
          <Route path="/finance/payroll" element={<FinancePayrollPage />} />
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
          <Route path="/agent/chief" element={<ChiefAgentPage />} />
          {/* ─── 模块4.4: Agent KPI绑定仪表盘 ─── */}
          <Route path="/agent/kpi-dashboard" element={<AgentKPIDashboard />} />
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
          {/* ─── 模块3.4: 菜谱方案批量下发+门店差异化+版本管理 ─── */}
          <Route path="/menu/plans" element={<MenuPlanPage />} />
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
          <Route path="/hr/commission-v3" element={<CommissionV3Page />} />  {/* 计件提成3.0 模块2.6 */}
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
          {/* ─── 模块3.2: 加盟商管理闭环 ─── */}
          <Route path="/org/franchise" element={<FranchiseManagePage />} />
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
          {/* ─── 模块2.5: 促销规则引擎V2 ─── */}
          <Route path="/marketing/promotions-v2" element={<PromotionRulesV2Page />} />
          {/* ─── P3: HQ总部管控看板 ─── */}
          <Route path="/analytics/hq/overview" element={<BrandOverview />} />
          <Route path="/analytics/hq/stores"   element={<StorePerformanceMatrix />} />
          {/* ─── Y-C4: 多渠道菜单发布完善 ─── */}
          <Route path="/menu/channels" element={<ChannelMenuPage />} />
          {/* ─── Y-D7: 付费会员卡产品化 ─── */}
          <Route path="/member/premium-cards" element={<PremiumCardPage />} />
          {/* ─── Y-M4: 外卖自营配送调度台 ─── */}
          <Route path="/trade/delivery" element={<DeliveryDispatchPage />} />
          {/* ─── Y-A9: 企业客户管理（团餐） ─── */}
          <Route path="/trade/corporate" element={<CorporateCustomerPage />} />
          {/* ─── 模块4.4: Agent KPI 绑定仪表盘 ─── */}
          <Route path="/agent/kpi" element={<AgentKPIDashboard />} />
        </Routes>
      </ShellHQ>
    </BrowserRouter>
  );
}

export default App;
