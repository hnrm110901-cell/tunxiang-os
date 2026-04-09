/**
 * 人力行政路由 — /hr/*, /hq/org/*
 */
import { Route } from 'react-router-dom';
import HRHubPage from '../pages/hr/HRHub';
import { EmployeeListPage } from '../pages/hr/EmployeeListPage';
import { EmployeeCreatePage } from '../pages/hr/EmployeeCreatePage';
import { EmployeeDetailPage } from '../pages/hr/EmployeeDetailPage';
import { OrgStructurePage } from '../pages/hr/OrgStructurePage';
import { JobGradesPage } from '../pages/hr/JobGradesPage';
import { ScheduleCenterPage } from '../pages/hr/ScheduleCenterPage';
import { ScheduleStoreWeekPage } from '../pages/hr/ScheduleStoreWeekPage';
import { ScheduleBatchPage } from '../pages/hr/ScheduleBatchPage';
import { ScheduleAdjustmentsPage } from '../pages/hr/ScheduleAdjustmentsPage';
import { ScheduleConflictsPage } from '../pages/hr/ScheduleConflictsPage';
import { ScheduleGapsPage } from '../pages/hr/ScheduleGapsPage';
import { ScheduleTemplatesPage } from '../pages/hr/ScheduleTemplatesPage';
import { AttendanceTodayPage } from '../pages/hr/AttendanceTodayPage';
import { AttendanceDailyPage } from '../pages/hr/AttendanceDailyPage';
import { AttendanceMonthlyPage } from '../pages/hr/AttendanceMonthlyPage';
import { AttendanceAnomaliesPage } from '../pages/hr/AttendanceAnomaliesPage';
import { AttendanceAdjustmentsPage } from '../pages/hr/AttendanceAdjustmentsPage';
import { LeaveRequestsPage } from '../pages/hr/LeaveRequestsPage';
import { LeaveDetailPage } from '../pages/hr/LeaveDetailPage';
import { LeaveBalancesPage } from '../pages/hr/LeaveBalancesPage';
import { LeaveApprovalBoardPage } from '../pages/hr/LeaveApprovalBoardPage';
import { PerformanceScoresPage } from '../pages/hr/PerformanceScoresPage';
import { PerformanceRankingsPage } from '../pages/hr/PerformanceRankingsPage';
import { PerformanceHorseRacePage } from '../pages/hr/PerformanceHorseRacePage';
import { PerformancePointsPage } from '../pages/hr/PerformancePointsPage';
import { PerformancePointDetailPage } from '../pages/hr/PerformancePointDetailPage';
import { PayrollLaborCostPage } from '../pages/hr/PayrollLaborCostPage';
import { PayrollApprovalPage } from '../pages/hr/PayrollApprovalPage';
import { PayrollSummaryPage } from '../pages/hr/PayrollSummaryPage';
import { ComplianceDashboardPage } from '../pages/hr/ComplianceDashboardPage';
import { ComplianceAlertsPage } from '../pages/hr/ComplianceAlertsPage';
import { ComplianceDocExpiringPage } from '../pages/hr/ComplianceDocExpiringPage';
import { ComplianceTasksPage } from '../pages/hr/ComplianceTasksPage';
import { StoreOpsTodayPage } from '../pages/hr/StoreOpsTodayPage';
import { StoreOpsFillGapsPage } from '../pages/hr/StoreOpsFillGapsPage';
import { StoreOpsExceptionsPage } from '../pages/hr/StoreOpsExceptionsPage';
import { GovernanceDashboardPage } from '../pages/hr/GovernanceDashboardPage';
import { GovernanceBenchmarkPage } from '../pages/hr/GovernanceBenchmarkPage';
import { GovernanceStaffingPage } from '../pages/hr/GovernanceStaffingPage';
import { GovernanceRiskStoresPage } from '../pages/hr/GovernanceRiskStoresPage';
import { AgentHubPage } from '../pages/hr/AgentHubPage';
import { AgentComplianceAlertPage } from '../pages/hr/AgentComplianceAlertPage';
import { AgentSalaryAdvisorPage } from '../pages/hr/AgentSalaryAdvisorPage';
import { AgentWorkforcePlannerPage } from '../pages/hr/AgentWorkforcePlannerPage';
import { AgentTurnoverRiskPage } from '../pages/hr/AgentTurnoverRiskPage';
import { SettingsRolesPage } from '../pages/hr/SettingsRolesPage';
import { SettingsApprovalWorkflowsPage } from '../pages/hr/SettingsApprovalWorkflowsPage';
import { SettingsAuditLogsPage } from '../pages/hr/SettingsAuditLogsPage';
import { LaborMarginDashboardPage } from '../pages/hr/LaborMarginDashboardPage';
import { BudgetRecommendationPage } from '../pages/hr/BudgetRecommendationPage';
import { MenuSkillMatchPage } from '../pages/hr/MenuSkillMatchPage';
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
    {/* 薪资 */}
    <Route path="/hr/payroll/labor-cost" element={<PayrollLaborCostPage />} />
    <Route path="/hr/payroll/approval" element={<PayrollApprovalPage />} />
    <Route path="/hr/payroll/summary" element={<PayrollSummaryPage />} />
    {/* 合规 */}
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
    {/* Agent中枢 */}
    <Route path="/hr/agents" element={<AgentHubPage />} />
    <Route path="/hr/agents/compliance-alert" element={<AgentComplianceAlertPage />} />
    <Route path="/hr/agents/salary-advisor" element={<AgentSalaryAdvisorPage />} />
    <Route path="/hr/agents/workforce-planner" element={<AgentWorkforcePlannerPage />} />
    <Route path="/hr/agents/turnover-risk" element={<AgentTurnoverRiskPage />} />
    {/* 人力分析 */}
    <Route path="/hr/analytics/labor-margin" element={<LaborMarginDashboardPage />} />
    <Route path="/hr/analytics/budget" element={<BudgetRecommendationPage />} />
    <Route path="/hr/analytics/menu-skill" element={<MenuSkillMatchPage />} />
    {/* 配置 */}
    <Route path="/hr/settings/roles" element={<SettingsRolesPage />} />
    <Route path="/hr/settings/approval-workflows" element={<SettingsApprovalWorkflowsPage />} />
    <Route path="/hr/settings/audit-logs" element={<SettingsAuditLogsPage />} />
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
