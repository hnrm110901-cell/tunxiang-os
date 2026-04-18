/**
 * 门店配置路由 — /hq/store/*, /store/*
 */
import { Route } from 'react-router-dom';
import { StoreManagePage } from '../pages/store/StoreManagePage';
import { MarketSessionPage } from '../pages/store/MarketSessionPage';
import FoodCourtManagePage from '../pages/store/FoodCourtManagePage';
import { FloorTableConfigPage } from '../pages/store/FloorTableConfigPage';
import { BusinessDayConfigPage } from '../pages/store/BusinessDayConfigPage';
import { DispatchRuleConfigPage } from '../pages/kds/DispatchRuleConfigPage';
import { DispatchCodePage } from '../pages/kds/DispatchCodePage';
import { StoreHealthPage } from '../pages/StoreHealthPage';
import { WineStoragePage } from '../pages/store/WineStoragePage';

export const storeRoutes = (
  <>
    <Route path="/hq/org/stores" element={<StoreManagePage />} />
    <Route path="/hq/floor/tables" element={<FloorTableConfigPage />} />
    <Route path="/hq/business-day/config" element={<BusinessDayConfigPage />} />
    <Route path="/hq/store/business-day" element={<BusinessDayConfigPage />} />
    <Route path="/hq/kitchen/stations" element={<DispatchRuleConfigPage />} />
    <Route path="/hq/print/rules" element={<DispatchCodePage />} />
    <Route path="/hq/shifts/config" element={<MarketSessionPage />} />
    <Route path="/hq/payments/channels" element={<StoreManagePage />} />
    <Route path="/hq/billing/rules" element={<StoreManagePage />} />
    <Route path="/hq/invoice/rules" element={<StoreManagePage />} />
    {/* Legacy */}
    <Route path="/store/manage" element={<StoreManagePage />} />
    <Route path="/store/market-sessions" element={<MarketSessionPage />} />
    <Route path="/store/food-court" element={<FoodCourtManagePage />} />
    <Route path="/store-health" element={<StoreHealthPage />} />
    <Route path="/wine-storage" element={<WineStoragePage />} />
    <Route path="/hq/wine-storage" element={<WineStoragePage />} />
  </>
);
