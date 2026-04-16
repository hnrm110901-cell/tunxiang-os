/**
 * 人力行政路由 — /hr/*, /hq/org/*
 * 路径基于 pages/hr/ 实际文件结构
 */
import { Route } from 'react-router-dom';
// HR Hub
import HRHubPage from '../pages/hr/HRHub';
// 员工
import EmployeeListPage from '../pages/hr/employees/EmployeeList';
import EmployeeCreatePage from '../pages/hr/employees/EmployeeCreate';
import EmployeeDetailPage from '../pages/hr/employees/EmployeeDetail';
import OrgStructurePage from '../pages/hr/employees/OrgStructure';
import JobGradesPage from '../pages/hr/employees/JobGrades';
// 排班
import ScheduleCenterPage from '../pages/hr/schedules/ScheduleCenter';
import ScheduleStoreWeekPage from '../pages/hr/schedules/ScheduleStoreWeek';
import ScheduleBatchPage from '../pages/hr/schedules/ScheduleBatch';
import ScheduleAdjustmentsPage from '../pages/hr/schedules/ScheduleAdjustments';
import ScheduleConflictsPage from '../pages/hr/schedules/ScheduleConflicts';
import ScheduleGapsPage from '../pages/hr/schedules/ScheduleGaps';
import ScheduleTemplatesPage from '../pages/hr/schedules/ScheduleTemplates';
// 考勤
import AttendanceTodayPage from '../pages/hr/attendance/AttendanceToday';
import AttendanceDailyPage from '../pages/hr/attendance/AttendanceDaily';
import AttendanceMonthlyPage from '../pages/hr/attendance/AttendanceMonthly';
import AttendanceAnomaliesPage from '../pages/hr/attendance/AttendanceAnomalies';
import AttendanceAdjustmentsPage from '../pages/hr/attendance/AttendanceAdjustments';
import ComplianceAuditPage from '../pages/hr/attendance/ComplianceAuditPage';
// 请假
import LeaveRequestsPage from '../pages/hr/leave/LeaveRequests';
import LeaveDetailPage from '../pages/hr/leave/LeaveDetail';
import LeaveBalancesPage from '../pages/hr/leave/LeaveBalances';
import LeaveApprovalBoardPage from '../pages/hr/leave/LeaveApprovalBoard';
// 绩效
import PerformanceScoresPage from '../pages/hr/performance/PerformanceScores';
import PerformanceRankingsPage from '../pages/hr/performance/PerformanceRankings';
import PerformanceHorseRacePage from '../pages/hr/performance/PerformanceHorseRace';
import PerformancePointsPage from '../pages/hr/performance/PerformancePoints';
import PerformancePointDetailPage from '../pages/hr/performance/PerformancePointDetail';
import ReviewCyclesPage from '../pages/hr/performance/ReviewCyclesPage';
import OnlineScoringPage from '../pages/hr/performance/OnlineScoringPage';
import ReviewSummaryPage from '../pages/hr/performance/ReviewSummaryPage';
// 积分扩展（v253）
import PointsLeaderboardPage from '../pages/hr/performance/PointsLeaderboardPage';
import HorseRacePage from '../pages/hr/performance/HorseRacePage';
import PointsRewardsPage from '../pages/hr/performance/PointsRewardsPage';
// 薪资
import PayrollLaborCostPage from '../pages/hr/payroll/PayrollLaborCost';
import PayrollApprovalPage from '../pages/hr/payroll/PayrollApproval';
import PayrollSummaryPage from '../pages/hr/payroll/PayrollSummary';
import SalaryItemLibraryPage from '../pages/hr/payroll/SalaryItemLibraryPage';
import TaxFilingPage from '../pages/hr/payroll/TaxFilingPage';
// 合规
import ComplianceDashboardPage from '../pages/hr/compliance/ComplianceDashboard';
import ComplianceAlertsPage from '../pages/hr/compliance/ComplianceAlerts';
import ComplianceDocExpiringPage from '../pages/hr/compliance/ComplianceDocExpiring';
import ComplianceTasksPage from '../pages/hr/compliance/ComplianceTasks';
// 门店作战台
import StoreOpsTodayPage from '../pages/hr/store-ops/StoreOpsToday';
import StoreOpsFillGapsPage from '../pages/hr/store-ops/StoreOpsFillGaps';
import StoreOpsExceptionsPage from '../pages/hr/store-ops/StoreOpsExceptions';
// 治理
import GovernanceDashboardPage from '../pages/hr/governance/GovernanceDashboard';
import GovernanceBenchmarkPage from '../pages/hr/governance/GovernanceBenchmark';
import GovernanceStaffingPage from '../pages/hr/governance/GovernanceStaffing';
import GovernanceRiskStoresPage from '../pages/hr/governance/GovernanceRiskStores';
// Agent
import AgentHubPage from '../pages/hr/agents/AgentHub';
import AgentComplianceAlertPage from '../pages/hr/agents/AgentComplianceAlert';
import AgentSalaryAdvisorPage from '../pages/hr/agents/AgentSalaryAdvisor';
import AgentWorkforcePlannerPage from '../pages/hr/agents/AgentWorkforcePlanner';
import AgentTurnoverRiskPage from '../pages/hr/agents/AgentTurnoverRisk';
// 配置
import SettingsRolesPage from '../pages/hr/settings/SettingsRoles';
import SettingsApprovalWorkflowsPage from '../pages/hr/settings/SettingsApprovalWorkflows';
import SettingsAuditLogsPage from '../pages/hr/settings/SettingsAuditLogs';
import IMSyncSettingsPage from '../pages/hr/settings/IMSyncSettingsPage';
// 借调
import TransferListPage from '../pages/hr/transfers/TransferListPage';
import TransferCostReportPage from '../pages/hr/transfers/TransferCostReportPage';
// 电子签约
import ContractTemplatesPage from '../pages/hr/contracts/ContractTemplatesPage';
import ContractSigningPage from '../pages/hr/contracts/ContractSigningPage';
import ContractArchivePage from '../pages/hr/contracts/ContractArchivePage';
// 分析
import LaborMarginDashboardPage from '../pages/hr/analytics/LaborMarginDashboard';
import BudgetRecommendationPage from '../pages/hr/analytics/BudgetRecommendation';
import MenuSkillMatchPage from '../pages/hr/analytics/MenuSkillMatch';
// 外部页面
import { HRDashboardPage } from '../pages/hq/org/HRDashboardPage';
import { AttendancePage } from '../pages/org/AttendancePage';
import { PerformancePage } from '../pages/org/PerformancePage';
import { PieceworkPage } from '../pages/org/PieceworkPage';
import { PayrollManagePage } from '../pages/org/payroll/PayrollManagePage';
import { PayrollConfigPage } from '../pages/org/PayrollConfigPage';
import { PayrollRecordsPage } from '../pages/org/PayrollRecordsPage';
import { FranchiseDashboardPage } from '../pages/org/franchise/FranchiseDashboardPage';
import EmployeeTrainingPage from '../pages/org/EmployeeTrainingPage';
import BrandRegionPage from '../pages/org/BrandRegionPage';
import { FranchisePage } from '../pages/franchise/FranchisePage';
import FranchiseContractPage from '../pages/franchise/FranchiseContractPage';
import { OrgPage } from '../pages/OrgPage';

export const hrRoutes = (
  <>
    {/* 人力中枢 */}
    <Route path="/hr" element={<HRHubPage />} />
    <Route path="/hr/employees" element={<EmployeeListPage />} />
    <Route path="/hr/employees/new" element={<EmployeeCreatePage />} />
    <Route path="/hr/employees/:employeeId" element={<EmployeeDetailPage />} />
    <Route path="/hr/org-structure" element={<OrgStructurePage />} />
    <Route path="/hr/job-grades" element={<JobGradesPage />} />
    {/* 排班 */}
    <Route path="/hr/schedules" element={<ScheduleCenterPage />} />
    <Route path="/hr/schedules/store/:storeId/week" element={<ScheduleStoreWeekPage />} />
    <Route path="/hr/schedules/batch" element={<ScheduleBatchPage />} />
    <Route path="/hr/schedules/adjustments" element={<ScheduleAdjustmentsPage />} />
    <Route path="/hr/schedules/conflicts" element={<ScheduleConflictsPage />} />
    <Route path="/hr/schedules/gaps" element={<ScheduleGapsPage />} />
    <Route path="/hr/schedules/templates" element={<ScheduleTemplatesPage />} />
    {/* 考勤 */}
    <Route path="/hr/attendance/today" element={<AttendanceTodayPage />} />
    <Route path="/hr/attendance/daily" element={<AttendanceDailyPage />} />
    <Route path="/hr/attendance/monthly" element={<AttendanceMonthlyPage />} />
    <Route path="/hr/attendance/anomalies" element={<AttendanceAnomaliesPage />} />
    <Route path="/hr/attendance/adjustments" element={<AttendanceAdjustmentsPage />} />
    <Route path="/hr/attendance/compliance" element={<ComplianceAuditPage />} />
    {/* 请假 */}
    <Route path="/hr/leave-requests" element={<LeaveRequestsPage />} />
    <Route path="/hr/leave-requests/:leaveId" element={<LeaveDetailPage />} />
    <Route path="/hr/leave-balances" element={<LeaveBalancesPage />} />
    <Route path="/hr/leave-requests/approval-board" element={<LeaveApprovalBoardPage />} />
    {/* 绩效 */}
    <Route path="/hr/performance/scores" element={<PerformanceScoresPage />} />
    <Route path="/hr/performance/rankings" element={<PerformanceRankingsPage />} />
    <Route path="/hr/performance/horse-race" element={<PerformanceHorseRacePage />} />
    <Route path="/hr/performance/points" element={<PerformancePointsPage />} />
    <Route path="/hr/performance/points/:employeeId" element={<PerformancePointDetailPage />} />
    <Route path="/hr/performance/review-cycles" element={<ReviewCyclesPage />} />
    <Route path="/hr/performance/online-scoring" element={<OnlineScoringPage />} />
    <Route path="/hr/performance/review-summary" element={<ReviewSummaryPage />} />
    {/* 积分扩展（v253） */}
    <Route path="/hr/performance/points-leaderboard" element={<PointsLeaderboardPage />} />
    <Route path="/hr/performance/horse-race-seasons" element={<HorseRacePage />} />
    <Route path="/hr/performance/points-rewards" element={<PointsRewardsPage />} />
    {/* 薪资 */}
    <Route path="/hr/payroll/labor-cost" element={<PayrollLaborCostPage />} />
    <Route path="/hr/payroll/approval" element={<PayrollApprovalPage />} />
    <Route path="/hr/payroll/summary" element={<PayrollSummaryPage />} />
    <Route path="/hr/payroll/salary-items" element={<SalaryItemLibraryPage />} />
    <Route path="/hr/payroll/tax-filing" element={<TaxFilingPage />} />
    {/* 合规 */}
    <Route path="/hr/compliance" element={<ComplianceDashboardPage />} />
    <Route path="/hr/compliance/alerts" element={<ComplianceAlertsPage />} />
    <Route path="/hr/compliance/documents/expiring" element={<ComplianceDocExpiringPage />} />
    <Route path="/hr/compliance/tasks" element={<ComplianceTasksPage />} />
    {/* 门店作战台 */}
    <Route path="/hr/store-ops/today" element={<StoreOpsTodayPage />} />
    <Route path="/hr/store-ops/fill-gaps" element={<StoreOpsFillGapsPage />} />
    <Route path="/hr/store-ops/exceptions" element={<StoreOpsExceptionsPage />} />
    {/* 治理 */}
    <Route path="/hr/governance/dashboard" element={<GovernanceDashboardPage />} />
    <Route path="/hr/governance/benchmark" element={<GovernanceBenchmarkPage />} />
    <Route path="/hr/governance/staffing" element={<GovernanceStaffingPage />} />
    <Route path="/hr/governance/risk-stores" element={<GovernanceRiskStoresPage />} />
    {/* Agent */}
    <Route path="/hr/agents" element={<AgentHubPage />} />
    <Route path="/hr/agents/compliance-alert" element={<AgentComplianceAlertPage />} />
    <Route path="/hr/agents/salary-advisor" element={<AgentSalaryAdvisorPage />} />
    <Route path="/hr/agents/workforce-planner" element={<AgentWorkforcePlannerPage />} />
    <Route path="/hr/agents/turnover-risk" element={<AgentTurnoverRiskPage />} />
    {/* 分析 */}
    <Route path="/hr/analytics/labor-margin" element={<LaborMarginDashboardPage />} />
    <Route path="/hr/analytics/budget" element={<BudgetRecommendationPage />} />
    <Route path="/hr/analytics/menu-skill" element={<MenuSkillMatchPage />} />
    {/* 借调 */}
    <Route path="/hr/transfers" element={<TransferListPage />} />
    <Route path="/hr/transfers/cost-report" element={<TransferCostReportPage />} />
    {/* 电子签约 */}
    <Route path="/hr/contracts/templates" element={<ContractTemplatesPage />} />
    <Route path="/hr/contracts/signing" element={<ContractSigningPage />} />
    <Route path="/hr/contracts/archive" element={<ContractArchivePage />} />
    {/* 配置 */}
    <Route path="/hr/settings/roles" element={<SettingsRolesPage />} />
    <Route path="/hr/settings/approval-workflows" element={<SettingsApprovalWorkflowsPage />} />
    <Route path="/hr/settings/audit-logs" element={<SettingsAuditLogsPage />} />
    <Route path="/hr/settings/im-sync" element={<IMSyncSettingsPage />} />
    {/* /hq/org/* 别名 */}
    <Route path="/hq/org/hr" element={<HRDashboardPage />} />
    <Route path="/hq/org/franchise" element={<FranchiseDashboardPage />} />
    <Route path="/hq/org/payroll-configs" element={<PayrollConfigPage />} />
    <Route path="/hq/org/payroll-records" element={<PayrollRecordsPage />} />
    <Route path="/hq/org/payroll-manage" element={<PayrollManagePage />} />
    <Route path="/hq/org/attendance" element={<AttendancePage />} />
    <Route path="/hq/org/brands" element={<BrandRegionPage />} />
    <Route path="/hq/org/regions" element={<BrandRegionPage />} />
    <Route path="/hq/iam/roles" element={<SettingsRolesPage />} />
    <Route path="/hq/iam/staff" element={<EmployeeListPage />} />
    <Route path="/hq/audit/logs" element={<SettingsAuditLogsPage />} />
    {/* Legacy */}
    <Route path="/org" element={<OrgPage />} />
    <Route path="/org/attendance" element={<AttendancePage />} />
    <Route path="/org/performance" element={<PerformancePage />} />
    <Route path="/org/piecework" element={<PieceworkPage />} />
    <Route path="/org/payroll-configs" element={<PayrollConfigPage />} />
    <Route path="/org/payroll-records" element={<PayrollRecordsPage />} />
    <Route path="/org/training" element={<EmployeeTrainingPage />} />
    <Route path="/org/brands" element={<BrandRegionPage />} />
    <Route path="/payroll" element={<PayrollManagePage />} />
    <Route path="/payroll-manage" element={<PayrollManagePage />} />
    <Route path="/franchise-dashboard" element={<FranchiseDashboardPage />} />
    <Route path="/franchise" element={<FranchisePage />} />
    <Route path="/franchise/contracts" element={<FranchiseContractPage />} />
  </>
);
