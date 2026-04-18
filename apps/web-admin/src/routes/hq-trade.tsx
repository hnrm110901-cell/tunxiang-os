/**
 * 交易管理路由 — /hq/trade/*, /trade/*, /finance/*
 */
import { Route } from 'react-router-dom';
import { TradePage } from '../pages/TradePage';
import { DeliveryPage } from '../pages/hq/trade/DeliveryPage';
import { BanquetTemplatePage } from '../pages/hq/trade/BanquetTemplatePage';
import { BanquetBoardPage } from '../pages/hq/BanquetBoardPage';
import { BanquetMenuPage } from '../pages/trade/banquet-menu/BanquetMenuPage';
import BanquetManagePage from '../pages/trade/BanquetManagePage';
import { DishDeptMappingPage } from '../pages/trade/kds-mapping/DishDeptMappingPage';
import { EnterprisePage } from '../pages/trade/EnterprisePage';
import { ServiceChargeConfigPage } from '../pages/trade/ServiceChargeConfigPage';
import OmniOrderCenterPage from '../pages/trade/OmniOrderCenterPage';
import DouyinVoucherPage from '../pages/trade/DouyinVoucherPage';
import DeliveryDispatchPage from '../pages/trade/DeliveryDispatchPage';
import CorporateCustomerPage from '../pages/trade/CorporateCustomerPage';
import { ReservationManagePage } from '../pages/trade/ReservationManagePage';
import { SettlementMonitorPage } from '../pages/ops/SettlementMonitorPage';
import { DispatchRuleConfigPage } from '../pages/kds/DispatchRuleConfigPage';
import { DispatchCodePage } from '../pages/kds/DispatchCodePage';
import { KDSCallSettingsPage } from '../pages/kds/KDSCallSettingsPage';
import { ReceiptEditorPage } from '../pages/ReceiptEditorPage';
import { FinanceAuditPage } from '../pages/finance/FinanceAuditPage';
import PnLReportPage from '../pages/finance/PnLReportPage';
import { WineStoragePage } from '../pages/finance/WineStoragePage';
import { DepositManagePage } from '../pages/finance/DepositManagePage';
import { CostManagePage } from '../pages/finance/CostManagePage';
import { BudgetManagePage } from '../pages/finance/BudgetManagePage';
import { AgreementUnitPage } from '../pages/finance/AgreementUnitPage';
import { CrmPage } from '../pages/CrmPage';
import { MemberInsightPage } from '../pages/member/MemberInsightPage';
import { CustomerServicePage } from '../pages/member/CustomerServicePage';
import { MemberTierPage } from '../pages/member/MemberTierPage';
import PremiumCardPage from '../pages/member/PremiumCardPage';
import { CRMCampaignPage } from '../pages/growth/CRMCampaignPage';
import { CampaignManagePage } from '../pages/growth/CampaignManagePage';

export const tradeRoutes = (
  <>
    {/* /hq/trade/* */}
    <Route path="/hq/trade/delivery" element={<DeliveryPage />} />
    <Route path="/hq/trade/orders" element={<TradePage />} />
    <Route path="/hq/trade/payments" element={<TradePage />} />
    <Route path="/hq/trade/settlements" element={<SettlementMonitorPage />} />
    <Route path="/hq/trade/refunds" element={<TradePage />} />
    <Route path="/hq/trade/banquets" element={<BanquetManagePage />} />
    <Route path="/hq/trade/banquet-menu" element={<BanquetMenuPage />} />
    <Route path="/hq/trade/banquet-templates" element={<BanquetTemplatePage />} />
    <Route path="/hq/reservations" element={<ReservationManagePage />} />
    <Route path="/hq/banquet" element={<BanquetBoardPage />} />
    <Route path="/hq/kds/dish-dept-mapping" element={<DishDeptMappingPage />} />
    <Route path="/hq/kds/dispatch" element={<DispatchRuleConfigPage />} />
    <Route path="/hq/corporate-accounts" element={<AgreementUnitPage />} />
    {/* 会员 */}
    <Route path="/hq/members" element={<MemberInsightPage />} />
    <Route path="/hq/members/tags" element={<MemberTierPage />} />
    <Route path="/hq/members/consumption" element={<MemberInsightPage />} />
    <Route path="/hq/members/coupons" element={<CRMCampaignPage />} />
    <Route path="/hq/members/campaigns" element={<CampaignManagePage />} />
    {/* Legacy trade */}
    <Route path="/trade" element={<TradePage />} />
    <Route path="/trade/banquet" element={<BanquetManagePage />} />
    <Route path="/trade/enterprise" element={<EnterprisePage />} />
    <Route path="/trade/service-charge" element={<ServiceChargeConfigPage />} />
    <Route path="/trade/omni-orders" element={<OmniOrderCenterPage />} />
    <Route path="/trade/douyin-voucher" element={<DouyinVoucherPage />} />
    <Route path="/trade/delivery" element={<DeliveryDispatchPage />} />
    <Route path="/trade/corporate" element={<CorporateCustomerPage />} />
    <Route path="/crm" element={<CrmPage />} />
    <Route path="/receipt-editor" element={<ReceiptEditorPage />} />
    <Route path="/receipt-editor/:templateId" element={<ReceiptEditorPage />} />
    {/* KDS */}
    <Route path="/kds/dispatch-rules" element={<DispatchRuleConfigPage />} />
    <Route path="/kds/dispatch-codes" element={<DispatchCodePage />} />
    <Route path="/kds/call-settings" element={<KDSCallSettingsPage />} />
    {/* 财务 */}
    <Route path="/finance/audit" element={<FinanceAuditPage />} />
    <Route path="/finance/pnl-report" element={<PnLReportPage />} />
    <Route path="/finance/wine-storage" element={<WineStoragePage />} />
    <Route path="/finance/deposits" element={<DepositManagePage />} />
    <Route path="/deposit-management" element={<DepositManagePage />} />
    <Route path="/finance/costs" element={<CostManagePage />} />
    <Route path="/finance/budgets" element={<BudgetManagePage />} />
    <Route path="/finance/agreement-units" element={<AgreementUnitPage />} />
    <Route path="/agreement-units" element={<AgreementUnitPage />} />
    <Route path="/finance/invoices" element={<CostManagePage />} />
    {/* 会员 legacy */}
    <Route path="/member/insight" element={<MemberInsightPage />} />
    <Route path="/member/customer-service" element={<CustomerServicePage />} />
    <Route path="/member/tiers" element={<MemberTierPage />} />
    <Route path="/member/premium-cards" element={<PremiumCardPage />} />
  </>
);
