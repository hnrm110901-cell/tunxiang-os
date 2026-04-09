/**
 * 人力行政路由 — /hr/*, /hq/org/*
 * 路径基于 pages/hr/ 实际文件结构
 */
import { Route } from 'react-router-dom';
// HR Hub
import HRHubPage from '../pages/hr/HRHub';
// 员工
import { EmployeeList as EmployeeListPage } from '../pages/hr/employees/EmployeeList';
import { EmployeeCreate as EmployeeCreatePage } from '../pages/hr/employees/EmployeeCreate';
import { EmployeeDetail as EmployeeDetailPage } from '../pages/hr/employees/EmployeeDetail';
import { OrgStructure as OrgStructurePage } from '../pages/hr/employees/OrgStructure';
import { JobGrades as JobGradesPage } from '../pages/hr/employees/JobGrades';
// 排班
import { ScheduleCenter as ScheduleCenterPage } from '../pages/hr/schedules/ScheduleCenter';
import { ScheduleStoreWeek as ScheduleStoreWeekPage } from '../pages/hr/schedules/ScheduleStoreWeek';
import { ScheduleBatch as ScheduleBatchPage } from '../pages/hr/schedules/ScheduleBatch';
import { ScheduleAdjustments as ScheduleAdjustmentsPage } from '../pages/hr/schedules/ScheduleAdjustments';
import { ScheduleConflicts as ScheduleConflictsPage } from '../pages/hr/schedules/ScheduleConflicts';
import { ScheduleGaps as ScheduleGapsPage } from '../pages/hr/schedules/ScheduleGaps';
import { ScheduleTemplates as ScheduleTemplatesPage } from '../pages/hr/schedules/ScheduleTemplates';
// 考勤
import { AttendanceToday as AttendanceTodayPage } from '../pages/hr/attendance/AttendanceToday';
import { AttendanceDaily as AttendanceDailyPage } from '../pages/hr/attendance/AttendanceDaily';
import { AttendanceMonthly as AttendanceMonthlyPage } from '../pages/hr/attendance/AttendanceMonthly';
import { AttendanceAnomalies as AttendanceAnomaliesPage } from '../pages/hr/attendance/AttendanceAnomalies';
import { AttendanceAdjustments as AttendanceAdjustmentsPage } from '../pages/hr/attendance/AttendanceAdjustments';
// 请假
import { LeaveRequests as LeaveRequestsPage } from '../pages/hr/leave/LeaveRequests';
import { LeaveDetail as LeaveDetailPage } from '../pages/hr/leave/LeaveDetail';
import { LeaveBalances as LeaveBalancesPage } from '../pages/hr/leave/LeaveBalances';
import { LeaveApprovalBoard as LeaveApprovalBoardPage } from '../pages/hr/leave/LeaveApprovalBoard';
// 绩效
import { PerformanceScores as PerformanceScoresPage } from '../pages/hr/performance/PerformanceScores';
import { PerformanceRankings as PerformanceRankingsPage } from '../pages/hr/performance/PerformanceRankings';
import { PerformanceHorseRace as PerformanceHorseRacePage } from '../pages/hr/performance/PerformanceHorseRace';
import { PerformancePoints as PerformancePointsPage } from '../pages/hr/performance/PerformancePoints';
import { PerformancePointDetail as PerformancePointDetailPage } from '../pages/hr/performance/PerformancePointDetail';
// 薪资
import { PayrollLaborCost as PayrollLaborCostPage } from '../pages/hr/payroll/PayrollLaborCost';
import { PayrollApproval as PayrollApprovalPage } from '../pages/hr/payroll/PayrollApproval';
import { PayrollSummary as PayrollSummaryPage } from '../pages/hr/payroll/PayrollSummary';
// 合规
import { ComplianceDashboard as ComplianceDashboardPage } from '../pages/hr/compliance/ComplianceDashboard';
import { ComplianceAlerts as ComplianceAlertsPage } from '../pages/hr/compliance/ComplianceAlerts';
import { ComplianceDocExpiring as ComplianceDocExpiringPage } from '../pages/hr/compliance/ComplianceDocExpiring';
import { ComplianceTasks as ComplianceTasksPage } from '../pages/hr/compliance/ComplianceTasks';
// 门店作战台
import { StoreOpsToday as StoreOpsTodayPage } from '../pages/hr/store-ops/StoreOpsToday';
import { StoreOpsFillGaps as StoreOpsFillGapsPage } from '../pages/hr/store-ops/StoreOpsFillGaps';
import { StoreOpsExceptions as StoreOpsExceptionsPage } from '../pages/hr/store-ops/StoreOpsExceptions';
// 治理
import { GovernanceDashboard as GovernanceDashboardPage } from '../pages/hr/governance/GovernanceDashboard';
import { GovernanceBenchmark as GovernanceBenchmarkPage } from '../pages/hr/governance/GovernanceBenchmark';
import { GovernanceStaffing as GovernanceStaffingPage } from '../pages/hr/governance/GovernanceStaffing';
import { GovernanceRiskStores as GovernanceRiskStoresPage } from '../pages/hr/governance/GovernanceRiskStores';
// Agent
import { AgentHub as AgentHubPage } from '../pages/hr/agents/AgentHub';
import { AgentComplianceAlert as AgentComplianceAlertPage } from '../pages/hr/agents/AgentComplianceAlert';
import { AgentSalaryAdvisor as AgentSalaryAdvisorPage } from '../pages/hr/agents/AgentSalaryAdvisor';
import { AgentWorkforcePlanner as AgentWorkforcePlannerPage } from '../pages/hr/agents/AgentWorkforcePlanner';
import { AgentTurnoverRisk as AgentTurnoverRiskPage } from '../pages/hr/agents/AgentTurnoverRisk';
// 配置
import { SettingsRoles as SettingsRolesPage } from '../pages/hr/settings/SettingsRoles';
import { SettingsApprovalWorkflows as SettingsApprovalWorkflowsPage } from '../pages/hr/settings/SettingsApprovalWorkflows';
import { SettingsAuditLogs as SettingsAuditLogsPage } from '../pages/hr/settings/SettingsAuditLogs';
// 分析
import { LaborMarginDashboard as LaborMarginDashboardPage } from '../pages/hr/analytics/LaborMarginDashboard';
import { BudgetRecommendation as BudgetRecommendationPage } from '../pages/hr/analytics/BudgetRecommendation';
import { MenuSkillMatch as MenuSkillMatchPage } from '../pages/hr/analytics/MenuSkillMatch';
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
