/**
 * 经营分析路由 — /hq/analytics/*, /analytics/*
 */
import { Route } from 'react-router-dom';
import { FinanceAnalysisPage } from '../pages/hq/analytics/FinanceAnalysisPage';
import { PLReportPage } from '../pages/hq/analytics/PLReportPage';
import { MemberAnalysisPage } from '../pages/hq/analytics/MemberAnalysisPage';
import { MultiStoreComparePage } from '../pages/hq/analytics/MultiStoreComparePage';
import { TrendAnalysisPage } from '../pages/hq/analytics/TrendAnalysisPage';
import { BudgetTrackerPage } from '../pages/hq/analytics/BudgetTrackerPage';
import { NLQueryPage } from '../pages/hq/analytics/NLQueryPage';
import { AIDailyBriefPage } from '../pages/hq/analytics/AIDailyBriefPage';
import { RevenueOptimizePage } from '../pages/hq/analytics/RevenueOptimizePage';
import { AnomalyDetectionPage } from '../pages/hq/analytics/AnomalyDetectionPage';
import { TableTurnoverPage } from '../pages/hq/analytics/TableTurnoverPage';
import { AnalyticsDashboardPage } from '../pages/analytics/DashboardPage';
import { HQDashboardPage } from '../pages/analytics/HQDashboardPage';
import { DishAnalyticsPage } from '../pages/analytics/DishAnalyticsPage';
import { ManagerDashboardPage } from '../pages/analytics/ManagerDashboardPage';
import { WineDepositReportPage } from '../pages/analytics/WineDepositReportPage';
import ReportCenterPage from '../pages/analytics/ReportCenterPage';
import { StoreInsightsPage } from '../pages/hq/insights/StoreInsightsPage';
import { PeriodAnalysisPage } from '../pages/hq/insights/PeriodAnalysisPage';

export const analyticsRoutes = (
  <>
    <Route path="/hq/analytics/finance" element={<FinanceAnalysisPage />} />
    <Route path="/hq/analytics/pl-report" element={<PLReportPage />} />
    <Route path="/hq/analytics/member" element={<MemberAnalysisPage />} />
    <Route path="/hq/analytics/multi-store" element={<MultiStoreComparePage />} />
    <Route path="/hq/analytics/trend" element={<TrendAnalysisPage />} />
    <Route path="/hq/analytics/budget" element={<BudgetTrackerPage />} />
    <Route path="/hq/analytics/nlq" element={<NLQueryPage />} />
    <Route path="/hq/analytics/daily-brief" element={<AIDailyBriefPage />} />
    <Route path="/hq/analytics/revenue-optimize" element={<RevenueOptimizePage />} />
    <Route path="/hq/analytics/anomaly" element={<AnomalyDetectionPage />} />
    <Route path="/hq/analytics/table-turnover" element={<TableTurnoverPage />} />
    {/* P1: 经营洞察 */}
    <Route path="/hq/insights/stores" element={<StoreInsightsPage />} />
    <Route path="/hq/insights/periods" element={<PeriodAnalysisPage />} />
    {/* Legacy */}
    <Route path="/analytics/dashboard" element={<AnalyticsDashboardPage />} />
    <Route path="/analytics/hq-dashboard" element={<HQDashboardPage />} />
    <Route path="/analytics/dishes" element={<DishAnalyticsPage />} />
    <Route path="/analytics/manager-dashboard" element={<ManagerDashboardPage />} />
    <Route path="/analytics/wine-deposit-report" element={<WineDepositReportPage />} />
    <Route path="/analytics/reports" element={<ReportCenterPage />} />
  </>
);
