/**
 * 运营管控路由 — /hq/ops/*
 */
import { Route } from 'react-router-dom';
import { OpsDashboardPage } from '../pages/hq/ops/OpsDashboardPage';
import { StoreAnalysisPage } from '../pages/hq/ops/StoreAnalysisPage';
import { DishAnalysisPage } from '../pages/hq/ops/DishAnalysisPage';
import { ApprovalCenterPage } from '../pages/hq/ops/ApprovalCenterPage';
import { ReviewCenterPage } from '../pages/hq/ops/ReviewCenterPage';
import { AlertCenterPage } from '../pages/hq/ops/AlertCenterPage';
import { SettingsPage } from '../pages/hq/ops/SettingsPage';
import { PeakMonitorPage } from '../pages/hq/ops/PeakMonitorPage';
import { RegionalPage } from '../pages/hq/ops/RegionalPage';
import { CruiseMonitorPage } from '../pages/hq/ops/CruiseMonitorPage';
import { OperationPlanPage } from '../pages/hq/ops/OperationPlanPage';
import { EventBusHealthPage } from '../pages/hq/ops/EventBusHealthPage';
import { StoreClonePage } from '../pages/hq/ops/StoreClonePage';
import { DailyReviewPage } from '../pages/hq/ops/DailyReviewPage';
import { SmartSpecialsPage } from '../pages/hq/ops/SmartSpecialsPage';
import { RectificationCenterPage } from '../pages/hq/ops/RectificationCenterPage';
import { StoreHealthRadarPage } from '../pages/hq/ops/StoreHealthRadarPage';
import { BriefingCenterPage } from '../pages/hq/ops/BriefingCenterPage';
import { AlertRuleConfigPage } from '../pages/hq/ops/AlertRuleConfigPage';
import { IntegrationHealthPage } from '../pages/hq/ops/IntegrationHealthPage';
import { OperationsPage } from '../pages/OperationsPage';
import { OperationsDashboardPage } from '../pages/OperationsDashboardPage';
import { ApprovalTemplatePage } from '../pages/ops/approval/ApprovalTemplatePage';
import { ApprovalCenterPage as ApprovalCenterPageNew } from '../pages/ops/approval/ApprovalCenterPage';
import { PatrolInspectionPage } from '../pages/ops/PatrolInspectionPage';
import { HACCPPage } from '../pages/ops/HACCPPage';
import { EnergyBudgetPage } from '../pages/ops/EnergyBudgetPage';
import { ReviewManagePage } from '../pages/ops/ReviewManagePage';
import { SettlementMonitorPage } from '../pages/ops/SettlementMonitorPage';
import { TaskCenterPage } from '../pages/ops/TaskCenterPage';

export const opsRoutes = (
  <>
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
    <Route path="/hq/ops/rectification" element={<RectificationCenterPage />} />
    <Route path="/hq/store-health" element={<StoreHealthRadarPage />} />
    <Route path="/hq/ops/briefings" element={<BriefingCenterPage />} />
    <Route path="/hq/ops/alert-rules" element={<AlertRuleConfigPage />} />
    <Route path="/hq/ops/integrations" element={<IntegrationHealthPage />} />
    <Route path="/hq/tasks" element={<TaskCenterPage />} />
    <Route path="/hq/events" element={<EventBusHealthPage />} />
    {/* Legacy */}
    <Route path="/operations" element={<OperationsPage />} />
    <Route path="/operations-dashboard" element={<OperationsDashboardPage />} />
    <Route path="/approval-templates" element={<ApprovalTemplatePage />} />
    <Route path="/approval-center" element={<ApprovalCenterPageNew />} />
    <Route path="/ops/approval-center" element={<ApprovalCenterPageNew />} />
    <Route path="/ops/patrol-inspection" element={<PatrolInspectionPage />} />
    <Route path="/ops/haccp" element={<HACCPPage />} />
    <Route path="/ops/energy-budget" element={<EnergyBudgetPage />} />
    <Route path="/ops/reviews" element={<ReviewManagePage />} />
    <Route path="/ops/settlement-monitor" element={<SettlementMonitorPage />} />
  </>
);
