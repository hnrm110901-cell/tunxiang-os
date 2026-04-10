/**
 * 增长营销路由 — /hq/growth/*, /growth/*
 */
import { Route } from 'react-router-dom';
import { GrowthDashboardPage } from '../pages/hq/growth/GrowthDashboardPage';
import { SegmentCenterPage } from '../pages/hq/growth/SegmentCenterPage';
import { JourneyListPage } from '../pages/hq/growth/JourneyListPage';
import { JourneyCanvasPage } from '../pages/hq/growth/JourneyCanvasPage';
import { ROIOverviewPage } from '../pages/hq/growth/ROIOverviewPage';
import { ContentCenterPage } from '../pages/hq/growth/ContentCenterPage';
import { OfferCenterPage } from '../pages/hq/growth/OfferCenterPage';
import { ChannelCenterPage } from '../pages/hq/growth/ChannelCenterPage';
import { ReferralCenterPage } from '../pages/hq/growth/ReferralCenterPage';
import { StoreExecutionPage } from '../pages/hq/growth/StoreExecutionPage';
import { JourneyDetailPage } from '../pages/hq/growth/JourneyDetailPage';
import { GroupBuyPage } from '../pages/hq/growth/GroupBuyPage';
import { StampCardPage } from '../pages/hq/growth/StampCardPage';
import { XHSIntegrationPage } from '../pages/hq/growth/XHSIntegrationPage';
import { RetailMallPage } from '../pages/hq/growth/RetailMallPage';
import { JourneyMonitorPage } from '../pages/hq/growth/JourneyMonitorPage';
import { MemberCardPage } from '../pages/hq/growth/MemberCardPage';
import { CustomerPoolPage } from '../pages/hq/growth/CustomerPoolPage';
import { Customer360Page } from '../pages/hq/growth/Customer360Page';
import { GrowthJourneyTemplatePage } from '../pages/hq/growth/GrowthJourneyTemplatePage';
import { GrowthJourneyRunsPage } from '../pages/hq/growth/GrowthJourneyRunsPage';
import { AgentWorkbenchPage } from '../pages/hq/growth/AgentWorkbenchPage';
import { GrowthSettingsPage } from '../pages/hq/growth/GrowthSettingsPage';
import { JourneyAttributionPage } from '../pages/hq/growth/JourneyAttributionPage';
import { StoreGrowthRankPage } from '../pages/hq/growth/StoreGrowthRankPage';
import { BrandComparisonPage } from '../pages/hq/growth/BrandComparisonPage';
import { CrossBrandPage } from '../pages/hq/growth/CrossBrandPage';
import { ExternalSignalsPage } from '../pages/hq/growth/ExternalSignalsPage';
import { GrowthSegmentTagsPage } from '../pages/hq/growth/GrowthSegmentTagsPage';
import { GrowthOfferPacksPage } from '../pages/hq/growth/GrowthOfferPacksPage';
import { CustomerBrainPage } from '../pages/hq/growth/CustomerBrainPage';
import { MemberDashboardPage } from '../pages/hq/growth/MemberDashboardPage';
import { MemberSegmentPage } from '../pages/hq/growth/MemberSegmentPage';
import CouponBenefitPage from '../pages/hq/growth/CouponBenefitPage';
import JourneyDesignerPage from '../pages/hq/growth/JourneyDesignerPage';
import { CRMCampaignPage } from '../pages/growth/CRMCampaignPage';
import { CampaignManagePage } from '../pages/growth/CampaignManagePage';
import ReferralManagePage from '../pages/growth/ReferralManagePage';
import SCRMAgentPage from '../pages/growth/SCRMAgentPage';
import { IntelDashboardPage } from '../pages/hq/market-intel/IntelDashboardPage';
import { NewProductListPage } from '../pages/hq/market-intel/NewProductListPage';
import { NewProductOpportunityPage } from '../pages/hq/market-intel/NewProductOpportunityPage';
import { CompetitorCenterPage } from '../pages/hq/market-intel/CompetitorCenterPage';
import { CompetitorDetailPage } from '../pages/hq/market-intel/CompetitorDetailPage';
import { ReviewTopicPage } from '../pages/hq/market-intel/ReviewTopicPage';
import { TrendReportPage } from '../pages/hq/market-intel/TrendReportPage';
import { TrendRadarPage } from '../pages/hq/market-intel/TrendRadarPage';
import { ReviewIntelPage } from '../pages/hq/market-intel/ReviewIntelPage';

export const growthRoutes = (
  <>
    {/* 增长中枢 */}
    <Route path="/hq/growth/dashboard" element={<GrowthDashboardPage />} />
    <Route path="/hq/growth/segments" element={<SegmentCenterPage />} />
    <Route path="/hq/growth/journeys" element={<JourneyListPage />} />
    <Route path="/hq/growth/journeys/:journeyId" element={<JourneyDetailPage />} />
    <Route path="/hq/growth/journeys/:journeyId/canvas" element={<JourneyCanvasPage />} />
    <Route path="/hq/growth/roi" element={<ROIOverviewPage />} />
    <Route path="/hq/growth/content" element={<ContentCenterPage />} />
    <Route path="/hq/growth/offers" element={<OfferCenterPage />} />
    <Route path="/hq/growth/channels" element={<ChannelCenterPage />} />
    <Route path="/hq/growth/referral" element={<ReferralCenterPage />} />
    <Route path="/hq/growth/execution" element={<StoreExecutionPage />} />
    <Route path="/hq/growth/group-buy" element={<GroupBuyPage />} />
    <Route path="/hq/growth/stamp-card" element={<StampCardPage />} />
    <Route path="/hq/growth/xhs" element={<XHSIntegrationPage />} />
    <Route path="/hq/growth/retail-mall" element={<RetailMallPage />} />
    <Route path="/hq/growth/journey-monitor" element={<JourneyMonitorPage />} />
    <Route path="/hq/growth/member-cards" element={<MemberCardPage />} />
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
    <Route path="/hq/growth/customer-brain" element={<CustomerBrainPage />} />
    {/* P1: 会员增长中枢 */}
    <Route path="/hq/growth/member-dashboard" element={<MemberDashboardPage />} />
    <Route path="/hq/growth/member-segments" element={<MemberSegmentPage />} />
    <Route path="/hq/growth/coupon-benefits" element={<CouponBenefitPage />} />
    <Route path="/hq/growth/journey-designer" element={<JourneyDesignerPage />} />
    {/* Legacy paths */}
    <Route path="/growth/crm-campaign" element={<CRMCampaignPage />} />
    <Route path="/growth/referral-distribution" element={<ReferralManagePage />} />
    <Route path="/growth/campaigns" element={<CampaignManagePage />} />
    <Route path="/growth/scrm-agent" element={<SCRMAgentPage />} />
    {/* 市场情报 */}
    <Route path="/hq/market-intel/dashboard" element={<IntelDashboardPage />} />
    <Route path="/hq/market-intel/new-products" element={<NewProductListPage />} />
    <Route path="/hq/market-intel/new-products/:id" element={<NewProductOpportunityPage />} />
    <Route path="/hq/market-intel/competitors" element={<CompetitorCenterPage />} />
    <Route path="/hq/market-intel/competitors/:competitorId" element={<CompetitorDetailPage />} />
    <Route path="/hq/market-intel/reviews" element={<ReviewTopicPage />} />
    <Route path="/hq/market-intel/reports" element={<TrendReportPage />} />
    <Route path="/hq/market-intel/trend-radar" element={<TrendRadarPage />} />
    <Route path="/hq/market-intel/review-intel" element={<ReviewIntelPage />} />
  </>
);
